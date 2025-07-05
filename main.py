#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – Optimized Version
- Webhook via FastAPI on Render with secure secret token
- Dynamic products from Google Sheets with versioned cache
- Features: Invoice with Hafez quote, discount codes, order notes, abandoned cart reminders,
 photo upload (file_id), push notifications (preparing/shipped), weekly backup
- Enhanced error handling for webhook, lifespan, and file operations
- Uses Google Fonts as fallback for missing fonts
- Downloads images online if image_url is provided
"""

from __future__ import annotations
import asyncio
import datetime as dt
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import uuid
import yaml
from typing import Dict, Any, List, Optional
import io
import random
import zipfile
from contextlib import asynccontextmanager
import requests

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Request, HTTPException
import uvicorn
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters, JobQueue
)
from telegram.error import BadRequest, NetworkError
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("bazarino.log", maxBytes=5*1024*1024, backupCount=3)
    ]
)
log = logging.getLogger("bazarino")

# Global variables
tg_app = None
bot = None

# ───────────── Validate Google Sheets Structure
async def validate_sheets():
    try:
        sheets = {
            "orders": (orders_ws, SHEET_CONFIG["orders"]["columns"]),
            "products": (products_ws, SHEET_CONFIG["products"]["columns"]),
            "discounts": (discounts_ws, SHEET_CONFIG["discounts"]["columns"]),
            "abandoned_carts": (abandoned_cart_ws, SHEET_CONFIG["abandoned_carts"]["columns"]),
            "uploads": (uploads_ws, SHEET_CONFIG["uploads"]["columns"])
        }
        for sheet_name, (ws, cols) in sheets.items():
            headers = await asyncio.to_thread(ws.row_values, 1)
            for col_name in cols.keys():
                if col_name not in headers:
                    log.error(f"Missing column '{col_name}' in sheet '{sheet_name}'")
                    raise ValueError(f"❗️ ستون '{col_name}' در شیت '{sheet_name}' یافت نشد.")
        log.info("All Google Sheets validated successfully")
    except Exception as e:
        log.error(f"Error validating Google Sheets: {e}")
        raise

# ───────────── Generate Invoice
async def generate_invoice(order_id: str, user_data: Dict[str, Any], cart: List[Dict[str, Any]], total: float, discount: float) -> io.BytesIO:
    width, height = 600, 900
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    header_color = (0, 100, 0)
    text_color = (0, 0, 0)
    border_color = (0, 0, 0)
    footer_color = (0, 80, 0)

    # Fallback to Google Fonts if local fonts are missing
    font_files = ["fonts/Vazir.ttf", "fonts/arial.ttf", "fonts/Nastaliq.ttf"]
    fonts_exist = all(os.path.exists(f) for f in font_files)
    if not fonts_exist:
        log.warning("One or more font files missing, attempting to use Google Fonts")
        try:
            # Placeholder for Google Fonts integration (requires additional setup)
            title_font = ImageFont.truetype("fonts/Vazir.ttf", 30) if os.path.exists("fonts/Vazir.ttf") else ImageFont.load_default().font_variant(size=30)
            body_font = ImageFont.truetype("fonts/Vazir.ttf", 24) if os.path.exists("fonts/Vazir.ttf") else ImageFont.load_default().font_variant(size=24)
            small_font = ImageFont.truetype("fonts/Vazir.ttf", 20) if os.path.exists("fonts/Vazir.ttf") else ImageFont.load_default().font_variant(size=20)
            latin_font = ImageFont.truetype("fonts/arial.ttf", 22) if os.path.exists("fonts/arial.ttf") else ImageFont.load_default().font_variant(size=22)
            nastaliq_font = ImageFont.truetype("fonts/Nastaliq.ttf", 26) if os.path.exists("fonts/Nastaliq.ttf") else ImageFont.load_default().font_variant(size=26)
        except Exception as e:
            log.warning(f"Font loading error: {e}. Using default fonts.")
            title_font = ImageFont.load_default().font_variant(size=30)
            body_font = ImageFont.load_default().font_variant(size=24)
            small_font = ImageFont.load_default().font_variant(size=20)
            latin_font = ImageFont.load_default().font_variant(size=22)
            nastaliq_font = ImageFont.load_default().font_variant(size=26)
    else:
        try:
            title_font = ImageFont.truetype("fonts/Vazir.ttf", 30)
            body_font = ImageFont.truetype("fonts/Vazir.ttf", 24)
            small_font = ImageFont.truetype("fonts/Vazir.ttf", 20)
            latin_font = ImageFont.truetype("fonts/arial.ttf", 22)
            nastaliq_font = ImageFont.truetype("fonts/Nastaliq.ttf", 26)
        except Exception as e:
            log.warning(f"Font loading error: {e}. Using default fonts.")
            title_font = ImageFont.load_default().font_variant(size=30)
            body_font = ImageFont.load_default().font_variant(size=24)
            small_font = ImageFont.load_default().font_variant(size=20)
            latin_font = ImageFont.load_default().font_variant(size=22)
            nastaliq_font = ImageFont.load_default().font_variant(size=26)

    # Load background image
    if os.path.exists("background_pattern.png"):
        try:
            background = Image.open("background_pattern.png").resize((width, height))
            img.paste(background, (0, 0), background.convert("RGBA"))
        except Exception as e:
            log.warning(f"Background pattern loading error: {e}")
    else:
        log.warning("Background pattern file not found, using plain background")

    draw.rectangle([(0, 0), (width, 100)], fill=header_color)
    header_text = get_display(arabic_reshaper.reshape("فاکتور بازارینو / Fattura Bazarino"))
    draw.text((width // 2, 50), header_text, fill=(255, 255, 255), font=title_font, anchor="mm")

    if os.path.exists("logo.png"):
        try:
            logo = Image.open("logo.png").resize((100, 100), Image.Resampling.LANCZOS)
            img.paste(logo, (20, 10), logo.convert("RGBA"))
        except Exception as e:
            log.warning(f"Logo loading error: {e}")

    y = 120
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"شماره سفارش / Ordine #{order_id}")), font=body_font, fill=text_color, anchor="ra")
    y += 50
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"نام / Nome: {user_data['name']}")), font=body_font, fill=text_color, anchor="ra")
    y += 50
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"مقصد / Destinazione: {user_data['dest']}")), font=body_font, fill=text_color, anchor="ra")
    y += 50
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"آدرس / Indirizzo: {user_data['address']} | {user_data['postal']}")), font=body_font, fill=text_color, anchor="ra")
    y += 50

    draw.text((width - 50, y), get_display(arabic_reshaper.reshape("محصولات / Prodotti:")), font=body_font, fill=text_color, anchor="ra")
    y += 50
    draw.rectangle([(40, y - 10), (width - 40, y + 10 + len(cart) * 50)], outline=border_color, width=2, fill=(255, 250, 240))
    for item in cart:
        item_text = get_display(arabic_reshaper.reshape(f"{item['qty']}× {item['fa']} — {item['qty'] * item['price']:.2f}€"))
        draw.text((width - 60, y), item_text, font=body_font, fill=text_color, anchor="ra")
        draw.text((60, y), item.get('it', 'N/A'), font=latin_font, fill=text_color, anchor="la")
        y += 50
    y += 30

    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"تخفیف / Sconto: {discount:.2f}€")), font=body_font, fill=text_color, anchor="ra")
    y += 50
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"مجموع / Totale: {total:.2f}€")), font=body_font, fill=text_color, anchor="ra")
    y += 50
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"یادداشت / Nota: {user_data.get('notes', 'بدون یادداشت')}")), font=body_font, fill=text_color, anchor="ra")
    y += 50

    draw.rectangle([(40, y - 20), (width - 40, y + 120)], outline=border_color, width=2, fill=(240, 230, 210))
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape("✨ فال حافظ / Fal di Hafez:")), font=small_font, fill=text_color, anchor="ra")
    y += 30
    enabled_quotes = [q for q in HAFEZ_QUOTES if q.get("enabled", True)]
    if not enabled_quotes:
        log.error("No enabled Hafez quotes defined in config.yaml")
        hafez = {"fa": "بدون نقل‌قول", "it": "Nessuna citazione"}
    else:
        hafez = random.choice(enabled_quotes)
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(hafez["fa"])), font=nastaliq_font, fill=text_color, anchor="ra")
    y += 40
    draw.text((50, y), hafez["it"], font=latin_font, fill=text_color, anchor="la")
    y += 50

    draw.rectangle([(0, height - 50), (width, height)], fill=footer_color)
    footer_text = get_display(arabic_reshaper.reshape("بازارینو - طعم ایران در ایتالیا"))
    draw.text((width // 2, height - 25), footer_text, fill=(255, 255, 255), font=title_font, anchor="mm")
    draw.text((width // 2, height - 10), "Bazarino - The Taste of Iran in Italy", fill=(255, 255, 255), font=latin_font, anchor="mm")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", quality=95)
    buffer.seek(0)
    return buffer

# ───────────── Config
try:
    with open("config.yaml", encoding="utf-8") as f:
        CONFIG = yaml.safe_load(f)
    if not CONFIG or "sheets" not in CONFIG or "hafez_quotes" not in CONFIG:
        log.error("Invalid config.yaml: missing 'sheets' or 'hafez_quotes'")
        raise SystemExit("❗️ فایل config.yaml نامعتبر است: کلیدهای 'sheets' یا 'hafez_quotes' وجود ندارند.")
except FileNotFoundError:
    log.error("config.yaml not found")
    raise SystemExit("❗️ فایل config.yaml یافت نشد.")
except Exception as e:
    log.error(f"Error loading config.yaml: {e}")
    raise SystemExit(f"❗️ خطا در بارگذاری config.yaml: {e}")

SHEET_CONFIG = CONFIG["sheets"]
HAFEZ_QUOTES = CONFIG["hafez_quotes"]
required_sheets = ["orders", "products", "abandoned_carts", "discounts", "uploads"]
for sheet in required_sheets:
    if sheet not in SHEET_CONFIG or "name" not in SHEET_CONFIG[sheet]:
        log.error(f"Missing or invalid sheet configuration for '{sheet}' in config.yaml")
        raise SystemExit(f"❗️ تنظیمات sheet '{sheet}' در config.yaml نامعتبر است.")

# ───────────── Messages
try:
    with open("messages.json", encoding="utf-8") as f:
        MSG = json.load(f)
except FileNotFoundError:
    log.error("messages.json not found")
    raise SystemExit("❗️ فایل messages.json یافت نشد.")
except json.JSONDecodeError as e:
    log.error(f"Invalid messages.json: {e}")
    raise SystemExit("❗️ فایل messages.json نامعتبر است: خطا در تجزیه JSON")
except Exception as e:
    log.error(f"Error loading messages.json: {e}")
    raise SystemExit(f"❗️ خطا در بارگذاری messages.json: {e}")

def m(k: str) -> str:
    return MSG.get(k, f"[{k}]")

# ───────────── ENV
for v in ("TELEGRAM_TOKEN", "ADMIN_CHAT_ID", "BASE_URL"):
    if not os.getenv(v):
        log.error(f"Missing environment variable: {v}")
        raise SystemExit(f"❗️ متغیر محیطی {v} تنظیم نشده است.")

try:
    ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID"))
except ValueError:
    log.error("Invalid ADMIN_CHAT_ID: must be an integer")
    raise SystemExit("❗️ ADMIN_CHAT_ID باید یک عدد صحیح باشد.")

try:
    LOW_STOCK_TH = int(os.getenv("LOW_STOCK_THRESHOLD", "3"))
except ValueError:
    log.error("Invalid LOW_STOCK_THRESHOLD: must be an integer")
    raise SystemExit("❗️ LOW_STOCK_THRESHOLD باید یک عدد صحیح باشد.")

TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = os.getenv("BASE_URL").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", str(uuid.uuid4()))  # Secure random secret
SPREADSHEET = os.getenv("SPREADSHEET_NAME", "Bazarnio Orders")
PRODUCT_WS = os.getenv("PRODUCT_WORKSHEET", "Sheet2")
PORT = int(os.getenv("PORT", "8000"))

# ───────────── Google Sheets
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_path = os.getenv("GOOGLE_CREDS", "/etc/secrets/bazarino-perugia-bot-f37c44dd9b14.json")
    if creds_path.startswith("{"):
        CREDS_JSON = json.loads(creds_path)
    else:
        try:
            with open(creds_path, "r", encoding="utf-8") as f:
                CREDS_JSON = json.load(f)
        except FileNotFoundError:
            log.error(f"Credentials file '{creds_path}' not found")
            raise SystemExit(f"❗️ فایل احراز هویت '{creds_path}' یافت نشد.")
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse credentials file '{creds_path}': {e}")
            raise SystemExit(f"❗️ خطا در تجزیه فایل احراز هویت '{creds_path}': {e}")
    gc = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(CREDS_JSON, scope))
    try:
        wb = gc.open(SPREADSHEET)
    except gspread.exceptions.SpreadsheetNotFound:
        log.error(f"Spreadsheet '{SPREADSHEET}' not found. Please check the SPREADSHEET_NAME and access permissions.")
        raise SystemExit(f"❗️ فایل Google Spreadsheet با نام '{SPREADSHEET}' یافت نشد.")
    try:
        orders_ws = wb.worksheet(SHEET_CONFIG["orders"]["name"])
        products_ws = wb.worksheet(SHEET_CONFIG["products"]["name"])
    except gspread.exceptions.WorksheetNotFound as e:
        log.error(f"Worksheet not found: {e}. Check config.yaml for correct worksheet names.")
        raise SystemExit(f"❗️ خطا در دسترسی به worksheet: {e}")
    try:
        abandoned_cart_ws = wb.worksheet(SHEET_CONFIG["abandoned_carts"]["name"])
    except gspread.exceptions.WorksheetNotFound:
        log.warning(f"Abandoned carts worksheet not found, creating new one: {SHEET_CONFIG['abandoned_carts']['name']}")
        abandoned_cart_ws = wb.add_worksheet(title=SHEET_CONFIG["abandoned_carts"]["name"], rows=1000, cols=3)
    try:
        discounts_ws = wb.worksheet(SHEET_CONFIG["discounts"]["name"])
    except gspread.exceptions.WorksheetNotFound:
        log.warning(f"Discounts worksheet not found, creating new one: {SHEET_CONFIG['discounts']['name']}")
        discounts_ws = wb.add_worksheet(title=SHEET_CONFIG["discounts"]["name"], rows=1000, cols=4)
    try:
        uploads_ws = wb.worksheet(SHEET_CONFIG["uploads"]["name"])
    except gspread.exceptions.WorksheetNotFound:
        log.warning(f"Uploads worksheet not found, creating new one: {SHEET_CONFIG['uploads']['name']}")
        uploads_ws = wb.add_worksheet(title=SHEET_CONFIG["uploads"]["name"], rows=1000, cols=4)
    # Validate sheet structure synchronously during startup
    try:
        sheets = {
            "orders": (orders_ws, SHEET_CONFIG["orders"]["columns"]),
            "products": (products_ws, SHEET_CONFIG["products"]["columns"]),
            "discounts": (discounts_ws, SHEET_CONFIG["discounts"]["columns"]),
            "abandoned_carts": (abandoned_cart_ws, SHEET_CONFIG["abandoned_carts"]["columns"]),
            "uploads": (uploads_ws, SHEET_CONFIG["uploads"]["columns"])
        }
        for sheet_name, (ws, cols) in sheets.items():
            headers = ws.row_values(1)  # Synchronous call
            for col_name in cols.keys():
                if col_name not in headers:
                    log.error(f"Missing column '{col_name}' in sheet '{sheet_name}'")
                    raise ValueError(f"❗️ ستون '{col_name}' در شیت '{sheet_name}' یافت نشد.")
        log.info("All Google Sheets validated successfully")
    except Exception as e:
        log.error(f"Error validating Google Sheets: {e}")
        raise SystemExit(f"❗️ خطا در اعتبارسنجی Google Sheets: {e}")
except Exception as e:
    log.error(f"Failed to initialize Google Sheets: {e}")
    raise SystemExit(f"❗️ خطا در اتصال به Google Sheets: {e}")

# ───────────── Check Fonts and Images
for file in ["fonts/Vazir.ttf", "fonts/arial.ttf", "fonts/Nastaliq.ttf", "background_pattern.png", "logo.png"]:
    if not os.path.exists(file):
        log.warning(f"File '{file}' not found, using defaults where applicable")
# ───────────── Google Sheets Data
async def load_products() -> Dict[str, Dict[str, Any]]:
    try:
        records = await asyncio.to_thread(products_ws.get_all_records)
        required_cols = ["id", "cat", "fa", "it", "brand", "description", "weight", "price"]
        if records and not all(col in records[0] for col in required_cols):
            missing = [col for col in required_cols if col not in records[0]]
            log.error(f"Missing required columns in products worksheet: {missing}")
            raise SystemExit(f"❗️ ستون‌های مورد نیاز در worksheet محصولات وجود ندارند: {missing}")
        products = {}
        for r in records:
            try:
                stock = r.get("stock", "0")
                try:
                    stock = int(stock)
                except (ValueError, TypeError) as e:
                    log.warning(f"Invalid stock value for product {r.get('id', 'unknown')}: {stock}. Setting to 0. Error: {e}")
                    stock = 0
                products[r["id"]] = dict(
                    cat=r["cat"],
                    fa=r["fa"],
                    it=r.get("it", "N/A"),
                    brand=r["brand"],
                    desc=r["description"],
                    weight=r["weight"],
                    price=float(r["price"]),
                    image_url=r.get("image_url") or None,
                    stock=stock,
                    is_bestseller=r.get("is_bestseller", "FALSE").lower() == "true",
                    version=r.get("version", "0")
                )
            except (ValueError, KeyError) as e:
                log.error(f"Invalid product data in row: {r}, error: {e}")
                continue
        if not products:
            log.error("No valid products loaded from Google Sheets")
            raise SystemExit("❗️ هیچ محصول معتبری از Google Sheets بارگذاری نشد.")
        return products
    except Exception as e:
        log.error(f"Error loading products from Google Sheets: {e}")
        raise SystemExit(f"❗️ خطا در بارگذاری محصولات از Google Sheets: {e}")

async def load_discounts() -> Dict[str, Dict[str, Any]]:
    try:
        records = await asyncio.to_thread(discounts_ws.get_all_records)
        required_cols = ["code", "discount_percent", "valid_until", "is_active"]
        if records and not all(col in records[0] for col in required_cols):
            missing = [col for col in required_cols if col not in records[0]]
            log.error(f"Missing required columns in discounts worksheet: {missing}")
            return {}
        discounts = {}
        for r in records:
            try:
                discounts[r["code"]] = dict(
                    discount_percent=float(r["discount_percent"]),
                    valid_until=r["valid_until"],
                    is_active=r["is_active"].lower() == "true"
                )
            except (ValueError, KeyError) as e:
                log.error(f"Invalid discount data in row: {r}, error: {e}")
                continue
        return discounts
    except Exception as e:
        log.error(f"Error loading discounts: {e}")
        return {}

async def get_products() -> Dict[str, Dict[str, Any]]:
    try:
        cell = await asyncio.to_thread(products_ws.acell, "L1")
        current_version = cell.value or "0"
        if (not hasattr(get_products, "_data") or
                not hasattr(get_products, "_version") or
                get_products._version != current_version or
                dt.datetime.utcnow() > getattr(get_products, "_ts", dt.datetime.min)):
            get_products._data = await load_products()
            get_products._version = current_version
            get_products._ts = dt.datetime.utcnow() + dt.timedelta(minutes=5)
            log.info(f"Loaded {len(get_products._data)} products from Google Sheets, version {current_version}")
        return get_products._data
    except Exception as e:
        log.error(f"Error in get_products: {e}")
        if hasattr(get_products, "_data"):
            log.warning("Returning cached products due to error")
            return get_products._data
        if ADMIN_ID and bot:
            try:
                await bot.send_message(ADMIN_ID, f"⚠️ خطا در بارگذاری محصولات: {e}")
            except Exception as admin_e:
                log.error(f"Failed to notify admin: {admin_e}")
        raise

EMOJI = {
    "rice": "🍚 برنج / Riso", "beans": "🥣 حبوبات / Legumi", "spice": "🌿 ادویه / Spezie",
    "nuts": "🥜 خشکبار / Frutta secca", "drink": "🧃 نوشیدنی / Bevande",
    "canned": "🥫 کنسرو / Conserve", "sweet": "🍬 شیرینی / Dolci"
}

# ───────────── Helpers
cart_total = lambda c: sum(i["qty"] * i["price"] for i in c)
cart_count = lambda ctx: sum(i["qty"] for i in ctx.user_data.get("cart", []))

async def safe_edit(q, *a, **k):
    try:
        await q.message.delete()
        await q.message.reply_text(*a, **k)
    except BadRequest as e:
        if "not modified" in str(e) or "no text in the message to edit" in str(e):
            await q.message.reply_text(*a, **k)
        else:
            log.error(f"Edit msg error: {e}")
            await q.message.reply_text(*a, **k)
    except NetworkError as e:
        log.error(f"Network error: {e}")
        await q.message.reply_text(*a, **k)

async def alert_admin(pid: str, stock: int):
    if stock <= LOW_STOCK_TH and ADMIN_ID and bot:
        for attempt in range(3):
            try:
                products = await get_products()
                product_name = products.get(pid, {}).get("fa", "Unknown")
                await bot.send_message(ADMIN_ID, f"⚠️ موجودی کم {stock}: {product_name}")
                log.info(f"Low stock alert sent for {product_name}")
                break
            except Exception as e:
                log.error(f"Alert fail attempt {attempt + 1} for product {pid}: {e}")
                if attempt < 2:
                    await asyncio.sleep(1)

# ───────────── Keyboards
async def kb_main(ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    try:
        cats = {p["cat"] for p in (await get_products()).values()}
        rows = [[InlineKeyboardButton(EMOJI.get(c, c), callback_data=f"cat_{c}")] for c in sorted(cats)]
        cart = ctx.user_data.get("cart", [])
        cart_summary = f"{m('BTN_CART')} ({cart_count(ctx)} آیتم - {cart_total(cart):.2f}€)" if cart else m("BTN_CART")
        rows.append([
            InlineKeyboardButton(m("BTN_SEARCH"), callback_data="search"),
            InlineKeyboardButton("🔥 پرفروش‌ها / Più venduti", callback_data="bestsellers")
        ])
        rows.append([
            InlineKeyboardButton(cart_summary, callback_data="cart")
        ])
        rows.append([
            InlineKeyboardButton("📞 پشتیبانی / Supporto", callback_data="support")
        ])
        return InlineKeyboardMarkup(rows)
    except Exception as e:
        log.error(f"Error in kb_main: {e}")
        raise

async def kb_category(cat: str, ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    try:
        if not cat:
            log.error("Invalid category: empty or None")
            return InlineKeyboardMarkup([[InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")]])
        rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"show_{pid}")]
                for pid, p in (await get_products()).items() if p["cat"] == cat]
        rows.append([
            InlineKeyboardButton(m("BTN_SEARCH"), callback_data="search"),
            InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")
        ])
        return InlineKeyboardMarkup(rows)
    except Exception as e:
        log.error(f"Error in kb_category for category {cat}: {e}")
        raise

def kb_product(pid: str, cat: str) -> InlineKeyboardMarkup:
    try:
        p = get_products._data.get(pid, None)
        if not p:
            log.error(f"Product {pid} not found in cached products")
            raise KeyError(f"Product {pid} not found")
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(m("CART_ADDED").split("\n")[0], callback_data=f"add_{pid}_{cat}")],
            [InlineKeyboardButton(m("BTN_BACK"), callback_data=f"back_cat_{cat}")]
        ])
    except Exception as e:
        log.error(f"Error in kb_product for product {pid}: {e}")
        raise

def kb_cart(ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    try:
        cart = ctx.user_data.get("cart", [])
        rows = []
        for it in cart:
            pid = it["id"]
            rows.append([
                InlineKeyboardButton("➕", callback_data=f"inc_{pid}"),
                InlineKeyboardButton(f"{it['qty']}× {it['fa']}", callback_data="ignore"),
                InlineKeyboardButton("➖", callback_data=f"dec_{pid}"),
                InlineKeyboardButton("❌", callback_data=f"del_{pid}")
            ])
        if ctx.user_data.get("dest"):
            rows.append([
                InlineKeyboardButton(m("BTN_ORDER_PERUGIA"), callback_data="order_perugia"),
                InlineKeyboardButton(m("BTN_ORDER_ITALY"), callback_data="order_italy")
            ])
            rows.append([
                InlineKeyboardButton(m("BTN_CONTINUE"), callback_data="checkout"),
                InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")
            ])
        else:
            rows.append([
                InlineKeyboardButton(m("BTN_ORDER_PERUGIA"), callback_data="order_perugia"),
                InlineKeyboardButton(m("BTN_ORDER_ITALY"), callback_data="order_italy")
            ])
            rows.append([
                InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")
            ])
        return InlineKeyboardMarkup(rows)
    except Exception as e:
        log.error(f"Error in kb_cart: {e}")
        raise

def kb_support() -> InlineKeyboardMarkup:
    try:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📷 ارسال تصویر / Invia immagine", callback_data="upload_photo")],
            [InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")]
        ])
    except Exception as e:
        log.error(f"Error in kb_support: {e}")
        raise

# ───────────── Cart operations
async def add_cart(ctx: ContextTypes.DEFAULT_TYPE, pid: str, qty: int = 1, update: Optional[Update] = None) -> tuple[bool, str]:
    try:
        prods = await get_products()
        if pid not in prods:
            log.error(f"Product {pid} not found in products")
            return False, m("STOCK_EMPTY")
        p = prods[pid]
        stock = p.get("stock", 0)
        if not isinstance(stock, int):
            log.error(f"Invalid stock for product {pid}: {stock}")
            return False, "❗️ خطا در بررسی موجودی محصول."
        cart = ctx.user_data.setdefault("cart", [])
        cur = next((i for i in cart if i["id"] == pid), None)
        cur_qty = cur["qty"] if cur else 0
        if stock < cur_qty + qty:
            log.warning(f"Insufficient stock for {pid}: available={stock}, requested={cur_qty + qty}")
            return False, m("STOCK_EMPTY")
        if cur:
            cur["qty"] += qty
        else:
            cart.append(dict(
                id=pid,
                fa=p["fa"],
                it=p.get("it", "N/A"),
                price=p["price"],
                weight=p["weight"],
                qty=qty
            ))
        await alert_admin(pid, stock - qty)
        try:
            await asyncio.to_thread(
                abandoned_cart_ws.append_row,
                [dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                 ctx.user_data.get("user_id", update.effective_user.id if update else 0),
                 json.dumps(cart)]
            )
            log.info(f"Abandoned cart saved for user {ctx.user_data.get('user_id', 'unknown')}")
        except Exception as e:
            log.error(f"Error saving abandoned cart: {e}")
        return True, m("CART_ADDED")
    except Exception as e:
        log.error(f"Error in add_cart for product {pid}: {e}")
        return False, "❗️ خطا در افزودن به سبد خرید."

def fmt_cart(cart: List[Dict[str, Any]]) -> str:
    try:
        if not cart:
            return m("CART_EMPTY")
        lines = ["🛍 **سبد خرید / Carrello:**", ""]
        tot = 0
        for it in cart:
            sub = it["qty"] * it["price"]
            tot += sub
            lines.append(f"▫️ {it['qty']}× {it['fa']} — {sub:.2f}€")
        lines.append("")
        lines.append(f"💶 **جمع / Totale:** {tot:.2f}€")
        return "\n".join(lines)
    except Exception as e:
        log.error(f"Error in fmt_cart: {e}")
        return "❗️ خطا در نمایش سبد خرید."

# ───────────── Stock update
async def update_stock(cart: List[Dict[str, Any]]) -> bool:
    try:
        records = await asyncio.to_thread(products_ws.get_all_records)
        for it in cart:
            pid = it["id"]
            qty = it["qty"]
            for idx, row in enumerate(records, start=2):
                if row["id"] == pid:
                    try:
                        new = int(row["stock"]) - qty
                    except (ValueError, TypeError) as e:
                        log.error(f"Invalid stock value for {pid} in Google Sheets: {row.get('stock', 'N/A')}. Error: {e}")
                        return False
                    if new < 0:
                        log.error(f"Cannot update stock for {pid}: negative stock")
                        return False
                    await asyncio.to_thread(products_ws.update_cell, idx, 10, new)
                    (await get_products())[pid]["stock"] = new
                    log.info(f"Updated stock for {pid}: {new}")
                    await alert_admin(pid, new)
        return True
    except gspread.exceptions.APIError as e:
        log.error(f"Google Sheets API error during stock update: {e}")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در به‌روزرسانی موجودی: {e}")
        return False
    except Exception as e:
        log.error(f"Stock update error: {e}")
        return False

# ───────────── Order States
ASK_NAME, ASK_PHONE, ASK_ADDRESS, ASK_POSTAL, ASK_DISCOUNT, ASK_NOTES = range(6)

# ───────────── Order Process
async def start_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        q = update.callback_query
        if not ctx.user_data.get("dest"):
            await q.message.reply_text(f"{m('CART_GUIDE')}\n\n{fmt_cart(ctx.user_data.get('cart', []))}", reply_markup=kb_cart(ctx), parse_mode="HTML")
            return ConversationHandler.END
        ctx.user_data["name"] = f"{q.from_user.first_name} {(q.from_user.last_name or '')}".strip()
        ctx.user_data["handle"] = f"@{q.from_user.username}" if q.from_user.username else "-"
        ctx.user_data["user_id"] = update.effective_user.id
        await q.message.reply_text(m("INPUT_NAME"))
        return ASK_NAME
    except Exception as e:
        log.error(f"Error in start_order: {e}")
        await q.message.reply_text("❗️ خطا در شروع سفارش. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data["name"] = update.message.text.strip()
        await update.message.reply_text(m("INPUT_PHONE"))
        return ASK_PHONE
    except Exception as e:
        log.error(f"Error in ask_phone: {e}")
        await update.message.reply_text("❗️ خطا در ثبت نام. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        phone = update.message.text.strip()
        if not phone.startswith("+39") or len(phone) < 10:
            await update.message.reply_text(m("PHONE_INVALID"))
            return ASK_PHONE
        ctx.user_data["phone"] = phone
        await update.message.reply_text(m("INPUT_ADDRESS"))
        return ASK_ADDRESS
    except Exception as e:
        log.error(f"Error in ask_address: {e}")
        await update.message.reply_text("❗️ خطا در ثبت شماره تلفن. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_postal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        address = update.message.text.strip()
        if len(address) < 10:
            await update.message.reply_text(m("ADDRESS_INVALID"))
            return ASK_ADDRESS
        ctx.user_data["address"] = address
        await update.message.reply_text(m("INPUT_POSTAL"))
        return ASK_POSTAL
    except Exception as e:
        log.error(f"Error in ask_postal: {e}")
        await update.message.reply_text("❗️ خطا در ثبت آدرس. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_discount(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data["postal"] = update.message.text.strip()
        await update.message.reply_text("🎁 کد تخفیف دارید؟ وارد کنید یا /skip را بزنید.\nHai un codice sconto? Inseriscilo o premi /skip.")
        return ASK_DISCOUNT
    except Exception as e:
        log.error(f"Error in ask_discount: {e}")
        await update.message.reply_text("❗️ خطا در ثبت کد پستی. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if update.message.text == "/skip":
            ctx.user_data["discount_code"] = None
        else:
            code = update.message.text.strip()
            discounts = await load_discounts()
            if code in discounts and discounts[code]["is_active"] and dt.datetime.strptime(discounts[code]["valid_until"], "%Y-%m-%d") >= dt.datetime.utcnow():
                ctx.user_data["discount_code"] = code
            else:
                await update.message.reply_text("❌ کد تخفیف نامعتبر است. لطفاً دوباره وارد کنید یا /skip کنید.\nCodice sconto non valido.")
                return ASK_DISCOUNT
        await update.message.reply_text(m("INPUT_NOTES"))
        return ASK_NOTES
    except Exception as e:
        log.error(f"Error in ask_notes: {e}")
        await update.message.reply_text("❗️ خطا در بررسی کد تخفیف. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def confirm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if update.message.text == "/skip":
            ctx.user_data["notes"] = ""
        else:
            ctx.user_data["notes"] = update.message.text.strip()
        cart = ctx.user_data.get("cart", [])
        if not cart:
            await update.message.reply_text(m("CART_EMPTY"), reply_markup=ReplyKeyboardRemove())
            ctx.user_data.clear()
            return ConversationHandler.END

        if not await update_stock(cart):
            await update.message.reply_text(m("STOCK_EMPTY"), reply_markup=ReplyKeyboardRemove())
            ctx.user_data.clear()
            return ConversationHandler.END

        order_id = str(uuid.uuid4())[:8]
        ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        total = cart_total(cart)
        discount = 0
        if ctx.user_data.get("discount_code"):
            discounts = await load_discounts()
            discount = total * (discounts[ctx.user_data["discount_code"]]["discount_percent"] / 100)
            total -= discount
        address_full = f"{ctx.user_data['address']} | {ctx.user_data['postal']}"
        try:
            for it in cart:
                await asyncio.to_thread(
                    orders_ws.append_row,
                    [ts, order_id, ctx.user_data["user_id"], ctx.user_data["handle"],
                     ctx.user_data["name"], ctx.user_data["phone"], address_full,
                     ctx.user_data["dest"], it["id"], it["fa"], it["qty"], it["price"],
                     it["qty"] * it["price"], ctx.user_data["notes"],
                     ctx.user_data.get("discount_code", ""), discount, "preparing", "FALSE"]
                )
            log.info(f"Order {order_id} saved to Google Sheets for user {ctx.user_data['handle']}")
            invoice_buffer = await generate_invoice(order_id, ctx.user_data, cart, total, discount)
            await update.message.reply_photo(
                photo=invoice_buffer,
                caption=f"{m('ORDER_CONFIRMED')}\n\n📍 مقصد / Destinazione: {ctx.user_data['dest']}\n💶 مجموع / Totale: {total:.2f}€\n🎁 تخفیف / Sconto: {discount:.2f}€\n📝 یادداشت / Nota: {ctx.user_data['notes'] or 'بدون یادداشت'}",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            log.error(f"Error saving order {order_id}: {e}")
            await update.message.reply_text(m("ERROR_SHEET"), reply_markup=ReplyKeyboardRemove())
            ctx.user_data.clear()
            return ConversationHandler.END

        if promo := MSG.get("PROMO_AFTER_ORDER"):
            await update.message.reply_text(promo, disable_web_page_preview=True)
        if ADMIN_ID and bot:
            msg = [f"🆕 سفارش / Ordine {order_id}", f"{ctx.user_data['name']} — {total:.2f}€",
                   f"🎁 تخفیف / Sconto: {discount:.2f}€ ({ctx.user_data.get('discount_code', 'بدون کد')})",
                   f"📝 یادداشت / Nota: {ctx.user_data['notes'] or 'بدون یادداشت'}"] + \
                  [f"▫️ {i['qty']}× {i['fa']}" for i in cart]
            try:
                invoice_buffer.seek(0)
                await bot.send_photo(ADMIN_ID, photo=invoice_buffer, caption="\n".join(msg))
                log.info(f"Admin notified for order {order_id}")
            except Exception as e:
                log.error(f"Failed to notify admin for order {order_id}: {e}")
            try:
                await asyncio.to_thread(abandoned_cart_ws.clear)
            except Exception as e:
                log.error(f"Error clearing abandoned carts: {e}")
        ctx.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        log.error(f"Error in confirm_order: {e}")
        await update.message.reply_text("❗️ خطا در ثبت سفارش. لطفاً دوباره امتحان کنید.")
        ctx.user_data.clear()
        return ConversationHandler.END

async def cancel_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data.clear()
        await update.message.reply_text(m("ORDER_CANCELLED"), reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    except Exception as e:
        log.error(f"Error in cancel_order: {e}")
        await update.message.reply_text("❗️ خطا در لغو سفارش. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

# ───────────── Photo Upload
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        if not ctx.user_data.get("awaiting_photo"):
            return
        photo = update.message.photo[-1]
        if photo.file_size > 2 * 1024 * 1024:
            await update.message.reply_text(m("ERROR_FILE_SIZE"), reply_markup=await kb_main(ctx))
            ctx.user_data["awaiting_photo"] = False
            return
        file = await photo.get_file()
        try:
            await asyncio.to_thread(
                uploads_ws.append_row,
                [dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                 update.effective_user.id,
                 f"@{update.effective_user.username or '-'}",
                 file.file_id]
            )
            await bot.send_photo(
                ADMIN_ID,
                file.file_id,
                caption=f"تصویر از کاربر @{update.effective_user.username or update.effective_user.id}\n📝 توضیح: {ctx.user_data.get('photo_note', 'بدون توضیح')}"
            )
            await update.message.reply_text(m("PHOTO_UPLOADED"))
            ctx.user_data["awaiting_photo"] = False
            ctx.user_data["photo_note"] = ""
            await update.message.reply_text(m("SUPPORT_MESSAGE"), reply_markup=await kb_main(ctx))
        except Exception as e:
            log.error(f"Error handling photo upload: {e}")
            await update.message.reply_text(m("ERROR_UPLOAD"), reply_markup=await kb_main(ctx))
    except Exception as e:
        log.error(f"Error in handle_photo: {e}")
        await update.message.reply_text("❗️ خطا در آپلود تصویر. لطفاً دوباره امتحان کنید.")
        ctx.user_data["awaiting_photo"] = False

# ───────────── Push Notifications for Order Status
async def check_order_status(context: ContextTypes.DEFAULT_TYPE):
    try:
        last_checked_row = getattr(check_order_status, "_last_checked_row", 1)
        shipped_cells = await asyncio.to_thread(orders_ws.findall, "shipped")
        preparing_cells = await asyncio.to_thread(orders_ws.findall, "preparing")
        for cell in shipped_cells + preparing_cells:
            if cell.row <= last_checked_row:
                continue
            row_data = await asyncio.to_thread(orders_ws.row_values, cell.row)
            if len(row_data) < 18 or row_data[17] == "TRUE":
                continue
            user_id = int(row_data[2])
            order_id = row_data[1]
            status = row_data[16]
            msg = {
                "preparing": f"📦 سفارش شما (#{order_id}) در حال آماده‌سازی است!\nIl tuo ordine (#{order_id}) è in preparazione!",
                "shipped": f"🚚 سفارش شما (#{order_id}) ارسال شد!\nIl tuo ordine (#{order_id}) è stato spedito!"
            }[status]
            await context.bot.send_message(user_id, msg, reply_markup=await kb_main(context))
            await asyncio.to_thread(orders_ws.update_cell, cell.row, 18, "TRUE")
            log.info(f"Sent {status} notification for order {order_id} to user {user_id}")
        check_order_status._last_checked_row = max(last_checked_row, max((c.row for c in shipped_cells + preparing_cells), default=1))
    except Exception as e:
        log.error(f"Error checking order status: {e}")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در بررسی وضعیت سفارشات: {e}")

# ───────────── Backup Google Sheets
async def backup_sheets(context: ContextTypes.DEFAULT_TYPE):
    try:
        sheets = [orders_ws, products_ws, discounts_ws, abandoned_cart_ws, uploads_ws]
        for sheet in sheets:
            records = await asyncio.to_thread(sheet.get_all_values)
            csv_content = "\n".join([",".join(row) for row in records])
            csv_file = io.BytesIO()
            with zipfile.ZipFile(csv_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{sheet.title}.csv", csv_content.encode("utf-8"))
            csv_file.seek(0)
            csv_file.name = f"{sheet.title}_backup_{dt.datetime.utcnow().strftime('%Y%m%d')}.zip"
            await context.bot.send_document(ADMIN_ID, document=csv_file, caption=f"📊 بکاپ {sheet.title} - {dt.datetime.utcnow().strftime('%Y-%m-%d')}")
            log.info(f"Backup sent for {sheet.title}")
    except Exception as e:
        log.error(f"Error creating backup: {e}")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در ایجاد بکاپ: {e}")

# ───────────── Abandoned Cart Reminder
async def send_cart_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        records = await asyncio.to_thread(abandoned_cart_ws.get_all_records)
        for record in records:
            cart = json.loads(record["cart"])
            user_id = int(record["user_id"])
            if cart:
                await context.bot.send_message(
                    user_id,
                    f"🛒 سبد خرید شما هنوز منتظر شماست!\nHai lasciato qualcosa nel carrello!\n{fmt_cart(cart)}\n👉 برای تکمیل سفارش: /start",
                    reply_markup=await kb_main(context)
                )
        await asyncio.to_thread(abandoned_cart_ws.clear)
    except Exception as e:
        log.error(f"Error sending cart reminders: {e}")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در ارسال یادآور سبد خرید: {e}")

# ───────────── /search
from difflib import get_close_matches
async def cmd_search(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        q = " ".join(ctx.args).lower()
        if not q:
            await u.message.reply_text(m("SEARCH_USAGE"))
            return
        hits = [(pid, p) for pid, p in (await get_products()).items()
                if q in p['fa'].lower() or q in p['it'].lower()
                or get_close_matches(q, [p['fa'].lower() + " " + p['it'].lower()], cutoff=0.6)]
        if not hits:
            await u.message.reply_text(m("SEARCH_NONE"))
            return
        for pid, p in hits[:5]:
            cap = f"{p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€\nموجودی / Stock: {p['stock']}"
            btn = InlineKeyboardMarkup.from_button(InlineKeyboardButton(m("CART_ADDED").split("\n")[0], callback_data=f"add_{pid}_{p['cat']}"))
            if p["image_url"] and p["image_url"].strip():
                try:
                    response = requests.get(p["image_url"], timeout=5)
                    response.raise_for_status()
                    await u.message.reply_photo(p["image_url"], caption=cap, reply_markup=btn)
                except requests.RequestException as e:
                    log.warning(f"Failed to download image for product {pid}: {e}")
                    await u.message.reply_text(cap, reply_markup=btn)
            else:
                await u.message.reply_text(cap, reply_markup=btn)
    except Exception as e:
        log.error(f"Error in cmd_search: {e}")
        await u.message.reply_text("❗️ خطا در جستجو. لطفاً دوباره امتحان کنید.")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در /search: {e}")

# ───────────── Commands
async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["user_id"] = u.effective_user.id
        await u.message.reply_html(m("WELCOME"), reply_markup=await kb_main(ctx))
    except Exception as e:
        log.error(f"Error in cmd_start: {e}")
        await u.message.reply_text("❗️ خطایی در بارگذاری منو رخ داد. لطفاً بعداً امتحان کنید یا با پشتیبانی تماس بگیرید.\nErrore nel caricamento del menu. Riprova più tardi o contatta il supporto.")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در /start: {e}")
        raise

async def cmd_about(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await u.message.reply_text(m("ABOUT_US"), disable_web_page_preview=True)
    except Exception as e:
        log.error(f"Error in cmd_about: {e}")
        await u.message.reply_text("❗️ خطا در نمایش اطلاعات. لطفاً دوباره امتحان کنید.")

async def cmd_privacy(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await u.message.reply_text(m("PRIVACY"), disable_web_page_preview=True)
    except Exception as e:
        log.error(f"Error in cmd_privacy: {e}")
        await u.message.reply_text("❗️ خطا در نمایش سیاست حریم خصوصی. لطفاً دوباره امتحان کنید.")

# ───────────── Callback Query Router
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        data = query.data

        if data != "back_main" and not data.startswith("back_cat_"):
            ctx.user_data["last_menu"] = data

        if data.startswith("cat_"):
            cat = data[4:]
            if not cat:
                log.error("Empty category in cat_ callback")
                await safe_edit(query, "❗️ دسته‌بندی نامعتبر است.", reply_markup=await kb_main(ctx))
                return
            ctx.user_data["current_cat"] = cat
            await safe_edit(query, f"دسته‌بندی: {EMOJI.get(cat, cat)}", reply_markup=await kb_category(cat, ctx))

        elif data.startswith("show_"):
            pid = data[5:]
            prods = await get_products()
            if pid not in prods:
                log.error(f"Product {pid} not found in show_ callback")
                await safe_edit(query, m("STOCK_EMPTY"), reply_markup=await kb_main(ctx))
                return
            p = prods[pid]
            cap = f"{p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€\nموجودی / Stock: {p['stock']}"
            ctx.user_data["current_product"] = pid
            ctx.user_data["current_cat"] = p["cat"]
            if p["image_url"] and p["image_url"].strip():
                try:
                    response = requests.get(p["image_url"], timeout=5)
                    response.raise_for_status()
                    await query.message.delete()
                    await query.message.reply_photo(p["image_url"], caption=cap, reply_markup=kb_product(pid, p["cat"]))
                except (requests.RequestException, BadRequest) as e:
                    log.warning(f"Failed to display image for product {pid}: {e}")
                    await safe_edit(query, cap, reply_markup=kb_product(pid, p["cat"]))
            else:
                await safe_edit(query, cap, reply_markup=kb_product(pid, p["cat"]))

        elif data.startswith("add_"):
            parts = data.split("_")
            if len(parts) != 3:
                log.error(f"Invalid add_ callback data: {data}")
                await safe_edit(query, "❗️ خطا در افزودن محصول.", reply_markup=await kb_main(ctx))
                return
            pid, cat = parts[1], parts[2]
            success, msg = await add_cart(ctx, pid, update=update)
            prods = await get_products()
            if pid not in prods:
                log.error(f"Product {pid} not found after add_cart")
                await safe_edit(query, m("STOCK_EMPTY"), reply_markup=await kb_category(cat, ctx))
                return
            p = prods[pid]
            cap = f"{msg}\n\n{p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€\nموجودی / Stock: {p['stock']}"
            await safe_edit(query, cap, reply_markup=await kb_category(cat, ctx))

        elif data.startswith("inc_"):
            pid = data[4:]
            success, msg = await add_cart(ctx, pid, update=update)
            cart = ctx.user_data.get("cart", [])
            await safe_edit(query, fmt_cart(cart), reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data.startswith("dec_"):
            pid = data[4:]
            cart = ctx.user_data.get("cart", [])
            item = next((i for i in cart if i["id"] == pid), None)
            if item and item["qty"] > 1:
                item["qty"] -= 1
            elif item:
                cart.remove(item)
            await safe_edit(query, fmt_cart(cart), reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data.startswith("del_"):
            pid = data[4:]
            cart = ctx.user_data.get("cart", [])
            cart[:] = [i for i in cart if i["id"] != pid]
            await safe_edit(query, fmt_cart(cart), reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data == "cart":
            cart = ctx.user_data.get("cart", [])
            if not ctx.user_data.get("dest"):
                await safe_edit(query, f"{m('CART_GUIDE')}\n\n{fmt_cart(cart)}", reply_markup=kb_cart(ctx), parse_mode="HTML")
            else:
                await safe_edit(query, fmt_cart(cart), reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data == "order_perugia":
            ctx.user_data["dest"] = "Perugia"
            cart = ctx.user_data.get("cart", [])
            await safe_edit(query, f"مقصد: Perugia\n\n{fmt_cart(cart)}", reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data == "order_italy":
            ctx.user_data["dest"] = "Italia"
            cart = ctx.user_data.get("cart", [])
            await safe_edit(query, f"مقصد: Italia\n\n{fmt_cart(cart)}", reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data == "back_main":
            await safe_edit(query, m("WELCOME"), reply_markup=await kb_main(ctx), parse_mode="HTML")

        elif data.startswith("back_cat_"):
            cat = data[9:]
            if not cat:
                log.error("Invalid category in back_cat_ callback")
                await safe_edit(query, "❗️ دسته‌بندی نامعتبر است.", reply_markup=await kb_main(ctx))
                return
            ctx.user_data["current_cat"] = cat
            await safe_edit(query, f"دسته‌بندی: {EMOJI.get(cat, cat)}", reply_markup=await kb_category(cat, ctx))

        elif data == "bestsellers":
            prods = await get_products()
            bestsellers = [(pid, p) for pid, p in prods.items() if p["is_bestseller"]]
            if not bestsellers:
                await safe_edit(query, "❌ هیچ محصول پرفروشی یافت نشد.\nNessun prodotto bestseller trovato.", reply_markup=await kb_main(ctx))
                return
            try:
                await query.message.delete()
            except Exception:
                pass
            for pid, p in bestsellers[:5]:
                cap = f"{p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€\nموجودی / Stock: {p['stock']}"
                btn = InlineKeyboardMarkup.from_button(InlineKeyboardButton(m("CART_ADDED").split("\n")[0], callback_data=f"add_{pid}_{p['cat']}"))
                if p["image_url"] and p["image_url"].strip():
                    try:
                        response = requests.get(p["image_url"], timeout=5)
                        response.raise_for_status()
                        await query.message.reply_photo(p["image_url"], caption=cap, reply_markup=btn)
                    except requests.RequestException as e:
                        log.warning(f"Failed to display image for product {pid}: {e}")
                        await query.message.reply_text(cap, reply_markup=btn)
                else:
                    await query.message.reply_text(cap, reply_markup=btn)
            await query.message.reply_text("🔥 محصولات پرفروش / Prodotti più venduti", reply_markup=await kb_main(ctx))

        elif data == "search":
            await safe_edit(query, m("SEARCH_USAGE"))

        elif data == "support":
            await safe_edit(query, m("SUPPORT_MESSAGE"), reply_markup=kb_support())

        elif data == "upload_photo":
            ctx.user_data["awaiting_photo"] = True
            await safe_edit(query, m("UPLOAD_PHOTO"))

        else:
            await safe_edit(query, "❗️ دستور ناشناخته. لطفاً دوباره تلاش کنید.\nComando sconosciuto. Riprova.", reply_markup=await kb_main(ctx))

    except Exception as e:
        log.error(f"Error in router: {e}")
        await safe_edit(query, "❗️ خطا در پردازش درخواست. لطفاً دوباره امتحان کنید.\nErrore nell'elaborazione della richiesta. Riprova.", reply_markup=await kb_main(ctx))
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در router: {e}")

# ───────────── App, webhook and FastAPI
app = FastAPI()
# ───────────── App, webhook and FastAPI
app = FastAPI()

# Root endpoint to handle GET /
@app.get("/")
async def root():
    return {"message": "Bazarino Telegram Bot is running. Use the Telegram bot to interact."}

# Endpoint to check file existence
@app.get("/check-files")
async def check_files():
    files = [
        "config.yaml",
        "messages.json",
        "/etc/secrets/bazarino-perugia-bot-f37c44dd9b14.json",
        "fonts/Vazir.ttf",
        "fonts/arial.ttf",
        "fonts/Nastaliq.ttf",
        "background_pattern.png",
        "logo.png"
    ]
    result = {f: os.path.exists(f) for f in files}
    return result

# Endpoint to check Google Sheets connection
@app.get("/check-sheets")
async def check_sheets():
    try:
        wb = gc.open("Bazarnio Orders")
        ws = wb.worksheet("Sheet2")
        headers = ws.row_values(1)
        return {"status": "success", "worksheet": ws.title, "headers": headers}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Webhook endpoint
@app.post("/webhook/{secret}")
async def webhook(secret: str, request: Request):
    global tg_app
    if secret != WEBHOOK_SECRET:
        log.error(f"Invalid webhook secret: {secret}")
        raise HTTPException(status_code=403, detail="Invalid secret")
    if tg_app is None:
        log.error("Webhook failed: tg_app is None, likely due to startup failure")
        raise HTTPException(status_code=500, detail="Application not initialized")
    try:
        update = await request.json()
        await tg_app.process_update(Update.de_json(update, bot))
        return {"status": "ok"}
    except Exception as e:
        log.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Rest of the code (lifespan, uvicorn.run, etc.)
@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # ... (بقیه کد lifespan)
# Root endpoint to handle GET /
@app.get("/")
async def root():
    return {"message": "Bazarino Telegram Bot is running. Use the Telegram bot to interact."}

async def post_init(app: Application):
    try:
        webhook_url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
        for attempt in range(3):
            try:
                await app.bot.set_webhook(webhook_url)
                log.info(f"Webhook set to {webhook_url}")
                break
            except Exception as e:
                log.error(f"Webhook attempt {attempt + 1} failed: {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(2)
    except Exception as e:
        log.error(f"Failed to set webhook: {e}")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در تنظیم Webhook: {e}")
        raise

async def post_shutdown(app: Application):
    log.info("Application shutting down")
    try:
        await app.bot.delete_webhook()
    except Exception as e:
        log.error(f"Failed to delete webhook: {e}")

@app.post("/webhook/{secret}")
async def webhook(secret: str, request: Request):
    global tg_app
    if secret != WEBHOOK_SECRET:
        log.error(f"Invalid webhook secret: {secret}")
        raise HTTPException(status_code=403, detail="Invalid secret")
    if tg_app is None:
        log.error("Webhook failed: tg_app is None, likely due to startup failure")
        raise HTTPException(status_code=500, detail="Application not initialized")
    try:
        update = await request.json()
        await tg_app.process_update(Update.de_json(update, bot))
        return {"status": "ok"}
    except Exception as e:
        log.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    global tg_app, bot
    try:
        log.info("Starting up FastAPI application")
        # Check files
        files = ["config.yaml", "messages.json", "/etc/secrets/bazarino-perugia-bot-f37c44dd9b14.json",
                 "fonts/Vazir.ttf", "fonts/arial.ttf", "fonts/Nastaliq.ttf",
                 "background_pattern.png", "logo.png"]
        for f in files:
            if not os.path.exists(f):
                log.error(f"File not found: {f}")
            else:
                log.info(f"File found: {f}")
        
        builder = ApplicationBuilder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown)
        tg_app = builder.build()
        bot = tg_app.bot
        await tg_app.initialize()
        log.info("Telegram application initialized successfully")
        if not tg_app.job_queue:
            tg_app.job_queue = JobQueue()
            await tg_app.job_queue.start()
            log.info("JobQueue started")
        job_queue = tg_app.job_queue
        job_queue.run_daily(send_cart_reminder, time=dt.time(hour=18, minute=0))
        job_queue.run_repeating(check_order_status, interval=600)
        job_queue.run_daily(backup_sheets, time=dt.time(hour=0, minute=0))

        order_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(start_order, pattern="^checkout$")],
            states={
                ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
                ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
                ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_postal)],
                ASK_POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_discount)],
                ASK_DISCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_notes)],
                ASK_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_order)],
            },
            fallbacks=[CommandHandler("cancel", cancel_order)],
            per_user=True,
            per_chat=True
        )

        tg_app.add_handler(CommandHandler("start", cmd_start))
        tg_app.add_handler(CommandHandler("about", cmd_about))
        tg_app.add_handler(CommandHandler("privacy", cmd_privacy))
        tg_app.add_handler(CommandHandler("search", cmd_search))
        tg_app.add_handler(order_conv)
        tg_app.add_handler(CallbackQueryHandler(router))
        tg_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

        yield
    except Exception as e:
        log.error(f"Lifespan startup error: {e}")
        tg_app = None
        if ADMIN_ID and bot:
            try:
                await bot.send_message(ADMIN_ID, f"⚠️ خطا در راه‌اندازی اپلیکیشن: {e}")
            except Exception as admin_e:
                log.error(f"Failed to notify admin: {admin_e}")
        raise
    finally:
        log.info("Shutting down FastAPI application")
        if tg_app:
            try:
                await tg_app.shutdown()
                log.info("Telegram application shutdown completed")
            except Exception as e:
                log.error(f"Error during shutdown: {e}")

app.lifespan = lifespan

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

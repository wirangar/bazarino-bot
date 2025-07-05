#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – Optimized Version with Edit Option
- Webhook via FastAPI on Render with secret token
- Dynamic products from Google Sheets with versioned cache
- Features: Invoice with Hafez quote, discount codes, order notes, abandoned cart reminders,
           photo upload (file_id), push notifications (preparing/shipped), weekly backup
- Optimized for Render.com with Google Sheets
- Removed strict input validation
- Added order review and edit functionality
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
from typing import Dict, Any, List
import io
import random
import textwrap
import re

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

# ───────────── Generate Invoice
async def generate_invoice(order_id, user_data, cart, total, discount):
    width, height = 1000, 1200
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    header_color = (0, 128, 0)
    text_color = (0, 0, 0)
    border_color = (0, 0, 0)
    beige = (245, 245, 220)

    try:
        title_font_fa = ImageFont.truetype("fonts/Nastaliq.ttf", 36)
        body_font_fa = ImageFont.truetype("fonts/Vazir.ttf", 28)
        hafez_font_fa = ImageFont.truetype("fonts/Nastaliq.ttf", 24)
        body_font_it = ImageFont.truetype("fonts/Roboto.ttf", 26)
        small_font_it = ImageFont.truetype("fonts/Roboto.ttf", 22)
    except Exception as e:
        log.error(f"Font loading error: {e}")
        title_font_fa = ImageFont.load_default(size=36)
        body_font_fa = ImageFont.load_default(size=28)
        hafez_font_fa = ImageFont.load_default(size=24)
        body_font_it = ImageFont.load_default(size=26)
        small_font_it = ImageFont.load_default(size=22)

    draw.rectangle([(0, 0), (width, 100)], fill=header_color)
    header_text_fa = get_display(arabic_reshaper.reshape("فاکتور بازارینو"))
    header_text_it = "Fattura Bazarino"
    draw.text((width - 50, 50), header_text_fa, fill=(255, 255, 255), font=title_font_fa, anchor="ra")
    draw.text((50, 50), header_text_it, fill=(255, 255, 255), font=body_font_it, anchor="la")

    try:
        logo = Image.open("logo.png").resize((100, 100))
        img.paste(logo, (20, 10))
    except Exception as e:
        log.error(f"Logo loading error: {e}")
        draw.text((30, 50), get_display(arabic_reshaper.reshape("🍇 بازارینو")), fill=text_color, font=body_font_fa, anchor="lm")

    y = 120
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"شماره سفارش: #{order_id}")), font=body_font_fa, fill=text_color, anchor="ra")
    draw.text((50, y), f"Ordine #{order_id}", font=body_font_it, fill=text_color, anchor="la")
    y += 50
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"نام: {user_data['name']}")), font=body_font_fa, fill=text_color, anchor="ra")
    draw.text((50, y), f"Nome: {user_data['name']}", font=body_font_it, fill=text_color, anchor="la")
    y += 50
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"مقصد: {user_data['dest']}")), font=body_font_fa, fill=text_color, anchor="ra")
    draw.text((50, y), f"Destinazione: {user_data['dest']}", font=body_font_it, fill=text_color, anchor="la")
    y += 50
    address_fa = textwrap.wrap(f"آدرس: {user_data['address']} | {user_data['postal']}", width=50)
    address_it = textwrap.wrap(f"Indirizzo: {user_data['address']} | {user_data['postal']}", width=50)
    for fa_line, it_line in zip(address_fa, address_it):
        draw.text((width - 50, y), get_display(arabic_reshaper.reshape(fa_line)), font=body_font_fa, fill=text_color, anchor="ra")
        draw.text((50, y), it_line, font=body_font_it, fill=text_color, anchor="la")
        y += 50

    draw.text((width - 50, y), get_display(arabic_reshaper.reshape("محصولات:")), font=body_font_fa, fill=text_color, anchor="ra")
    draw.text((50, y), "Prodotti:", font=body_font_it, fill=text_color, anchor="la")
    y += 50
    draw.rectangle([(40, y - 10), (width - 40, y + 10 + len(cart) * 50)], outline=border_color, width=2)
    for item in cart:
        item_text_fa = get_display(arabic_reshaper.reshape(f"{item['qty']}× {item['fa']} — {item['qty'] * item['price']:.2f}€"))
        item_text_it = f"{item['qty']}× {item['it']} — {item['qty'] * item['price']:.2f}€"
        draw.text((width - 50, y), item_text_fa, font=body_font_fa, fill=text_color, anchor="ra")
        draw.text((50, y), item_text_it, font=body_font_it, fill=text_color, anchor="la")
        y += 50
    y += 30

    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"تخفیف: {discount:.2f}€")), font=body_font_fa, fill=text_color, anchor="ra")
    draw.text((50, y), f"Sconto: {discount:.2f}€", font=body_font_it, fill=text_color, anchor="la")
    y += 50
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape(f"مجموع: {total:.2f}€")), font=body_font_fa, fill=text_color, anchor="ra")
    draw.text((50, y), f"Totale: {total:.2f}€", font=body_font_it, fill=text_color, anchor="la")
    y += 50
    notes_fa = textwrap.wrap(f"یادداشت: {user_data.get('notes', 'بدون یادداشت')}", width=50)
    notes_it = textwrap.wrap(f"Nota: {user_data.get('notes', 'Nessuna nota')}", width=50)
    for fa_line, it_line in zip(notes_fa, notes_it):
        draw.text((width - 50, y), get_display(arabic_reshaper.reshape(fa_line)), font=body_font_fa, fill=text_color, anchor="ra")
        draw.text((50, y), it_line, font=body_font_it, fill=text_color, anchor="la")
        y += 50

    draw.rectangle([(40, y - 10), (width - 40, y + 150)], outline=border_color, width=2, fill=beige)
    draw.text((width - 50, y), get_display(arabic_reshaper.reshape("✨ فال حافظ:")), font=hafez_font_fa, fill=text_color, anchor="ra")
    draw.text((50, y), "Fal di Hafez:", font=small_font_it, fill=text_color, anchor="la")
    y += 30
    if not HAFEZ_QUOTES:
        log.error("No Hafez quotes defined in config.yaml")
        hafez = {"fa": "بدون نقل‌قول", "it": "Nessuna citazione"}
    else:
        hafez = random.choice(HAFEZ_QUOTES)
    fa_lines = textwrap.wrap(hafez["fa"], width=50)
    it_lines = textwrap.wrap(hafez["it"], width=50)
    for fa_line in fa_lines:
        draw.text((width - 50, y), get_display(arabic_reshaper.reshape(fa_line)), font=hafez_font_fa, fill=text_color, anchor="ra")
        y += 30
    for it_line in it_lines:
        draw.text((50, y), it_line, font=small_font_it, fill=text_color, anchor="la")
        y += 30

    draw.rectangle([(0, height - 50), (width, height)], fill=header_color)
    footer_text_fa = get_display(arabic_reshaper.reshape("بازارینو - طعم ایران در ایتالیا"))
    footer_text_it = "Bazarino - Il sapore dell'Iran in Italia"
    draw.text((width - 50, height - 25), footer_text_fa, fill=(255, 255, 255), font=body_font_fa, anchor="ra")
    draw.text((50, height - 25), footer_text_it, fill=(255, 255, 255), font=small_font_it, anchor="la")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
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
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "EhsaNegar1394")
SPREADSHEET = os.getenv("SPREADSHEET_NAME", "Bazarnio Orders")
PORT = int(os.getenv("PORT", "8000"))

# ───────────── Google Sheets
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_path = os.getenv("GOOGLE_CREDS", "/etc/secrets/bazarino-perugia-bot-f37c44dd9b14.json")
    try:
        if os.path.exists(creds_path):
            with open(creds_path, "r", encoding="utf-8") as f:
                CREDS_JSON = json.load(f)
        else:
            CREDS_JSON = json.loads(os.getenv("GOOGLE_CREDS"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error(f"Failed to load credentials: {e}")
        raise SystemExit(f"❗️ خطا در بارگذاری احراز هویت Google: {e}")
    gc = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(CREDS_JSON, scope))
    try:
        wb = gc.open(SPREADSHEET)
    except gspread.exceptions.SpreadsheetNotFound:
        log.error(f"Spreadsheet '{SPREADSHEET}' not found")
        raise SystemExit(f"❗️ فایل Google Spreadsheet با نام '{SPREADSHEET}' یافت نشد.")
    try:
        orders_ws = wb.worksheet(SHEET_CONFIG["orders"]["name"])
        products_ws = wb.worksheet(SHEET_CONFIG["products"]["name"])
    except gspread.exceptions.WorksheetNotFound as e:
        log.error(f"Worksheet not found: {e}")
        raise SystemExit(f"❗️ خطا در دسترسی به worksheet: {e}")
    try:
        abandoned_cart_ws = wb.worksheet(SHEET_CONFIG["abandoned_carts"]["name"])
    except gspread.exceptions.WorksheetNotFound:
        abandoned_cart_ws = wb.add_worksheet(title=SHEET_CONFIG["abandoned_carts"]["name"], rows=1000, cols=3)
    try:
        discounts_ws = wb.worksheet(SHEET_CONFIG["discounts"]["name"])
    except gspread.exceptions.WorksheetNotFound:
        discounts_ws = wb.add_worksheet(title=SHEET_CONFIG["discounts"]["name"], rows=1000, cols=4)
    try:
        uploads_ws = wb.worksheet(SHEET_CONFIG["uploads"]["name"])
    except gspread.exceptions.WorksheetNotFound:
        uploads_ws = wb.add_worksheet(title=SHEET_CONFIG["uploads"]["name"], rows=1000, cols=4)
except Exception as e:
    log.error(f"Failed to initialize Google Sheets: {e}")
    raise SystemExit(f"❗️ خطا در اتصال به Google Sheets: {e}")

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
                products[r["id"]] = dict(
                    cat=r["cat"],
                    fa=r["fa"],
                    it=r["it"],
                    brand=r["brand"],
                    desc=r["description"],
                    weight=r["weight"],
                    price=float(r["price"]),
                    image_url=r.get("image_url") or None,
                    stock=int(r.get("stock", 0)),
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

async def load_discounts():
    for attempt in range(3):
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
        except gspread.exceptions.APIError as e:
            log.warning(f"API error loading discounts, attempt {attempt + 1}: {e}")
            if attempt < 2:
                await asyncio.sleep(2)
            else:
                log.error(f"Failed to load discounts after 3 attempts: {e}")
                return {}
        except Exception as e:
            log.error(f"Error loading discounts: {e}")
            return {}

async def get_products():
    try:
        cell = await asyncio.to_thread(products_ws.acell, "L1")
        current_version = cell.value or "0"
        if (not hasattr(get_products, "_data") or
            not hasattr(get_products, "_version") or
            get_products._version != current_version or
            dt.datetime.utcnow() > getattr(get_products, "_ts", dt.datetime.min)):
            get_products._data = await load_products()
            get_products._version = current_version
            get_products._ts = dt.datetime.utcnow() + dt.timedelta(seconds=60)
            log.info(f"Loaded {len(get_products._data)} products from Google Sheets, version {current_version}")
        return get_products._data
    except Exception as e:
        log.error(f"Error in get_products: {e}")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در بارگذاری محصولات: {e}")
        raise

EMOJI = {
    "rice": "🍚 برنج / Riso",
    "beans": "🥣 حبوبات / Legumi",
    "spice": "🌿 ادویه / Spezie",
    "nuts": "🥜 خشکبار / Frutta secca",
    "drink": "🧃 نوشیدنی / Bevande",
    "canned": "🥫 کنسرو / Conserve",
    "sweet": "🍬 شیرینی / Dolci"
}

# ───────────── Helpers
cart_total = lambda c: sum(i["qty"] * i["price"] for i in c)
cart_count = lambda ctx: sum(i["qty"] for i in ctx.user_data.get("cart", []))

async def safe_edit(q, *a, **k):
    try:
        await q.edit_message_text(*a, **k)
    except BadRequest as e:
        if "not modified" in str(e) or "no text in the message to edit" in str(e):
            try:
                await q.message.delete()
            except Exception as del_e:
                log.error(f"Error deleting message: {del_e}")
            await q.message.reply_text(*a, **k)
        else:
            log.error(f"Edit msg error: {e}")
    except NetworkError as e:
        log.error(f"Network error: {e}")

async def alert_admin(pid, stock):
    if stock <= LOW_STOCK_TH and ADMIN_ID:
        for attempt in range(3):
            try:
                await bot.send_message(ADMIN_ID, f"⚠️ موجودی کم {stock}: {(await get_products())[pid]['fa']}")
                log.info(f"Low stock alert sent for {(await get_products())[pid]['fa']}")
                break
            except Exception as e:
                log.error(f"Alert fail attempt {attempt + 1}: {e}")
                if attempt < 2:
                    await asyncio.sleep(1)

# ───────────── Keyboards
async def kb_main(ctx):
    try:
        cats = sorted({p["cat"] for p in (await get_products()).values()})
        rows = [[InlineKeyboardButton(EMOJI.get(c, c), callback_data=f"cat_{c}")] for c in cats]
        cart = ctx.user_data.get("cart", [])
        cart_summary = f"{m('BTN_CART')} ({cart_count(ctx)} آیتم - {cart_total(cart):.2f}€)" if cart else m("BTN_CART")
        rows.append([
            InlineKeyboardButton(m("BTN_SEARCH"), callback_data="search"),
            InlineKeyboardButton("🔥 پرفروش‌ها", callback_data="bestsellers")
        ])
        rows.append([InlineKeyboardButton(cart_summary, callback_data="cart")])
        rows.append([InlineKeyboardButton("📞 پشتیبانی", callback_data="support")])
        return InlineKeyboardMarkup(rows)
    except Exception as e:
        log.error(f"Error in kb_main: {e}")
        raise

async def kb_category(cat, ctx):
    try:
        rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"show_{pid}")]
                for pid, p in sorted((await get_products()).items(), key=lambda x: x[1]["fa"]) if p["cat"] == cat]
        rows.append([
            InlineKeyboardButton(m("BTN_SEARCH"), callback_data="search"),
            InlineKeyboardButton(m("BTN_BACK"), callback_data="back")
        ])
        return InlineKeyboardMarkup(rows)
    except Exception as e:
        log.error(f"Error in kb_category: {e}")
        raise

async def kb_product(pid):
    try:
        p = (await get_products())[pid]
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(m("CART_ADDED").split("\n")[0], callback_data=f"add_{pid}")],
            [InlineKeyboardButton(m("BTN_BACK"), callback_data=f"back_cat_{p['cat']}")]
        ])
    except Exception as e:
        log.error(f"Error in kb_product: {e}")
        raise

async def kb_cart(cart):
    try:
        rows = []
        for it in cart:
            pid = it["id"]
            rows.append([
                InlineKeyboardButton("➕", callback_data=f"inc_{pid}"),
                InlineKeyboardButton(f"{it['qty']}× {it['fa']}", callback_data="ignore"),
                InlineKeyboardButton("➖", callback_data=f"dec_{pid}"),
                InlineKeyboardButton("❌", callback_data=f"del_{pid}")
            ])
        rows.append([
            InlineKeyboardButton(m("BTN_ORDER_PERUGIA"), callback_data="order_perugia"),
            InlineKeyboardButton(m("BTN_ORDER_ITALY"), callback_data="order_italy")
        ])
        rows.append([
            InlineKeyboardButton(m("BTN_CONTINUE"), callback_data="checkout"),
            InlineKeyboardButton(m("BTN_BACK"), callback_data="back")
        ])
        return InlineKeyboardMarkup(rows)
    except Exception as e:
        log.error(f"Error in kb_cart: {e}")
        raise

async def kb_support():
    try:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📷 ارسال تصویر", callback_data="upload_photo")],
            [InlineKeyboardButton(m("BTN_BACK"), callback_data="back")]
        ])
    except Exception as e:
        log.error(f"Error in kb_support: {e}")
        raise

async def kb_review_order():
    try:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأیید و ثبت سفارش", callback_data="confirm_order")],
            [InlineKeyboardButton("✏️ ویرایش نام", callback_data="edit_name")],
            [InlineKeyboardButton("✏️ ویرایش شماره تلفن", callback_data="edit_phone")],
            [InlineKeyboardButton("✏️ ویرایش آدرس", callback_data="edit_address")],
            [InlineKeyboardButton("✏️ ویرایش کد پستی", callback_data="edit_postal")],
            [InlineKeyboardButton("✏️ ویرایش یادداشت", callback_data="edit_notes")],
            [InlineKeyboardButton("❌ لغو سفارش", callback_data="cancel_order")]
        ])
    except Exception as e:
        log.error(f"Error in kb_review_order: {e}")
        raise

# ───────────── Cart operations
async def add_cart(ctx, pid, qty=1, update=None):
    try:
        prods = await get_products()
        if pid not in prods:
            return False, m("STOCK_EMPTY")
        p = prods[pid]
        stock = p["stock"]
        cart = ctx.user_data.setdefault("cart", [])
        cur = next((i for i in cart if i["id"] == pid), None)
        cur_qty = cur["qty"] if cur else 0
        if stock < cur_qty + qty:
            return False, m("STOCK_EMPTY")
        if cur:
            cur["qty"] += qty
        else:
            cart.append(dict(id=pid, fa=p["fa"], it=p["it"], price=p["price"], weight=p["weight"], qty=qty))
        await alert_admin(pid, stock - qty)
        try:
            await asyncio.to_thread(
                abandoned_cart_ws.append_row,
                [dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                 ctx.user_data.get("user_id", update.effective_user.id if update else 0),
                 json.dumps(cart)]
            )
        except Exception as e:
            log.error(f"Error saving abandoned cart: {e}")
        return True, m("CART_ADDED")
    except Exception as e:
        log.error(f"Error in add_cart: {e}")
        return False, "❗️ خطا در افزودن به سبد خرید."

def fmt_cart(cart):
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
async def update_stock(cart):
    try:
        records = await asyncio.to_thread(products_ws.get_all_records)
        prods = await get_products()
        for it in cart:
            pid = it["id"]
            qty = it["qty"]
            for idx, row in enumerate(records, start=2):
                if row["id"] == pid:
                    new = int(row["stock"]) - qty
                    if new < 0:
                        log.error(f"Cannot update stock for {pid}: negative stock")
                        return False, f"❌ موجودی {prods[pid]['fa']} کافی نیست."
                    await asyncio.to_thread(products_ws.update_cell, idx, 10, new)
                    prods[pid]["stock"] = new
                    log.info(f"Updated stock for {pid}: {new}")
        return True, None
    except gspread.exceptions.APIError as e:
        log.error(f"Google Sheets API error during stock update: {e}")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در به‌روزرسانی موجودی: {e}")
        return False, "❗️ خطا در به‌روزرسانی موجودی. لطفاً دوباره تلاش کنید."
    except Exception as e:
        log.error(f"Stock update error: {e}")
        return False, "❗️ خطا در به‌روزرسانی موجودی."

# ───────────── Order States
ASK_NAME, ASK_PHONE, ASK_ADDRESS, ASK_POSTAL, ASK_DISCOUNT, ASK_NOTES, REVIEW_ORDER = range(7)

# ───────────── Order Process
async def skip_discount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["discount_code"] = None
        await update.message.reply_text(m("INPUT_NOTES"), reply_markup=ReplyKeyboardRemove())
        return ASK_NOTES
    except Exception as e:
        log.error(f"Error in skip_discount: {e}")
        await update.message.reply_text("❗️ خطا در پرش کد تخفیف. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def skip_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["notes"] = ""
        return await review_order(update, ctx)
    except Exception as e:
        log.error(f"Error in skip_notes: {e}")
        await update.message.reply_text("❗️ خطا در پرش یادداشت. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def start_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.callback_query
        if not ctx.user_data.get("dest"):
            await safe_edit(q, m("CART_GUIDE") + "\n\n" + fmt_cart(ctx.user_data.get("cart", [])), reply_markup=await kb_cart(ctx.user_data.get("cart", [])), parse_mode="HTML")
            return
        ctx.user_data["name"] = f"{q.from_user.first_name} {(q.from_user.last_name or '')}".strip()
        ctx.user_data["handle"] = f"@{q.from_user.username}" if q.from_user.username else "-"
        ctx.user_data["user_id"] = update.effective_user.id
        try:
            await q.message.delete()
        except Exception as e:
            log.error(f"Error deleting previous message in start_order: {e}")
        await ctx.bot.send_message(
            chat_id=q.message.chat.id,
            text=m("INPUT_NAME"),
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_NAME
    except Exception as e:
        log.error(f"Error in start_order: {e}")
        await q.message.reply_text("❗️ خطا در شروع سفارش. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        name = update.message.text.strip()
        if not name:
            await update.message.reply_text("❗️ لطفاً نام و نام خانوادگی خود را وارد کنید.\nInserisci nome e cognome.")
            return ASK_NAME
        ctx.user_data["name"] = name
        await update.message.reply_text(m("INPUT_PHONE"), reply_markup=ReplyKeyboardRemove())
        return ASK_PHONE
    except Exception as e:
        log.error(f"Error in ask_phone: {e}")
        await update.message.reply_text("❗️ خطا در ثبت نام. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def ask_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        phone = update.message.text.strip()
        if not phone:
            await update.message.reply_text("❗️ لطفاً شماره تلفن خود را وارد کنید.\nInserisci il numero di telefono.")
            return ASK_PHONE
        ctx.user_data["phone"] = phone
        await update.message.reply_text(m("INPUT_ADDRESS"), reply_markup=ReplyKeyboardRemove())
        return ASK_ADDRESS
    except Exception as e:
        log.error(f"Error in ask_address: {e}")
        await update.message.reply_text("❗️ خطا در ثبت شماره تلفن. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def ask_postal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        address = update.message.text.strip()
        if not address:
            await update.message.reply_text("❗️ لطفاً آدرس کامل خود را وارد کنید.\nInserisci l'indirizzo completo.")
            return ASK_ADDRESS
        ctx.user_data["address"] = address
        await update.message.reply_text(m("INPUT_POSTAL"), reply_markup=ReplyKeyboardRemove())
        return ASK_POSTAL
    except Exception as e:
        log.error(f"Error in ask_postal: {e}")
        await update.message.reply_text("❗️ خطا در ثبت آدرس. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def ask_discount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        postal = update.message.text.strip()
        if not postal:
            await update.message.reply_text("❗️ لطفاً کد پستی خود را وارد کنید.\nInserisci il CAP.")
            return ASK_POSTAL
        ctx.user_data["postal"] = postal
        await update.message.reply_text("🎁 کد تخفیف دارید؟ وارد کنید یا /skip را بزنید.\nHai un codice sconto? Inseriscilo o premi /skip.", reply_markup=ReplyKeyboardRemove())
        return ASK_DISCOUNT
    except Exception as e:
        log.error(f"Error in ask_discount: {e}")
        await update.message.reply_text("❗️ خطا در ثبت کد پستی. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def ask_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        code = update.message.text.strip()
        discounts = await load_discounts()
        if code in discounts and discounts[code]["is_active"] and dt.datetime.strptime(discounts[code]["valid_until"], "%Y-%m-%d") >= dt.datetime.utcnow():
            ctx.user_data["discount_code"] = code
        else:
            await update.message.reply_text("❌ کد تخفیف نامعتبر است. لطفاً دوباره وارد کنید یا /skip کنید.\nCodice sconto non valido.", reply_markup=ReplyKeyboardRemove())
            return ASK_DISCOUNT
        await update.message.reply_text(m("INPUT_NOTES"), reply_markup=ReplyKeyboardRemove())
        return ASK_NOTES
    except Exception as e:
        log.error(f"Error in ask_notes: {e}")
        await update.message.reply_text("❗️ خطا در بررسی کد تخفیف. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def review_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.text != "/skip":
            ctx.user_data["notes"] = update.message.text.strip()
        cart = ctx.user_data.get("cart", [])
        if not cart:
            await update.message.reply_text(m("CART_EMPTY"), reply_markup=ReplyKeyboardRemove())
            ctx.user_data.clear()
            return ConversationHandler.END
        summary = [
            "📝 **خلاصه سفارش / Riepilogo ordine:**",
            f"👤 نام / Nome: {ctx.user_data['name']}",
            f"📞 تلفن / Telefono: {ctx.user_data['phone']}",
            f"📍 آدرس / Indirizzo: {ctx.user_data['address']}",
            f"🏷 کد پستی / CAP: {ctx.user_data['postal']}",
            f"📍 مقصد / Destinazione: {ctx.user_data['dest']}",
            f"🎁 کد تخفیف / Codice sconto: {ctx.user_data.get('discount_code', 'بدون کد / Nessun codice')}",
            f"📝 یادداشت / Nota: {ctx.user_data.get('notes', 'بدون یادداشت / Nessuna nota')}",
            "",
            fmt_cart(cart)
        ]
        await update.message.reply_text("\n".join(summary), reply_markup=await kb_review_order(), parse_mode="HTML")
        return REVIEW_ORDER
    except Exception as e:
        log.error(f"Error in review_order: {e}")
        await update.message.reply_text("❗️ خطا در نمایش خلاصه سفارش. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE, field: str, prompt: str, next_state):
    try:
        q = update.callback_query
        await q.message.delete()
        await ctx.bot.send_message(
            chat_id=q.message.chat.id,
            text=prompt,
            reply_markup=ReplyKeyboardRemove()
        )
        ctx.user_data["edit_field"] = field
        return next_state
    except Exception as e:
        log.error(f"Error in edit_field: {e}")
        await q.message.reply_text("❗️ خطا در ویرایش اطلاعات. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def edit_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await edit_field(update, ctx, "name", m("INPUT_NAME"), ASK_NAME)

async def edit_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await edit_field(update, ctx, "phone", m("INPUT_PHONE"), ASK_PHONE)

async def edit_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await edit_field(update, ctx, "address", m("INPUT_ADDRESS"), ASK_ADDRESS)

async def edit_postal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await edit_field(update, ctx, "postal", m("INPUT_POSTAL"), ASK_POSTAL)

async def edit_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await edit_field(update, ctx, "notes", m("INPUT_NOTES"), ASK_NOTES)

async def save_edited_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        field = ctx.user_data.get("edit_field")
        value = update.message.text.strip()
        if not value and field != "notes":
            await update.message.reply_text(f"❗️ لطفاً مقدار معتبر وارد کنید.\nInserisci un valore valido.")
            return ctx.user_data.get("state", REVIEW_ORDER)
        ctx.user_data[field] = value if field != "notes" or value else ""
        cart = ctx.user_data.get("cart", [])
        summary = [
            "📝 **خلاصه سفارش / Riepilogo ordine:**",
            f"👤 نام / Nome: {ctx.user_data['name']}",
            f"📞 تلفن / Telefono: {ctx.user_data['phone']}",
            f"📍 آدرس / Indirizzo: {ctx.user_data['address']}",
            f"🏷 کد پستی / CAP: {ctx.user_data['postal']}",
            f"📍 مقصد / Destinazione: {ctx.user_data['dest']}",
            f"🎁 کد تخفیف / Codice sconto: {ctx.user_data.get('discount_code', 'بدون کد / Nessun codice')}",
            f"📝 یادداشت / Nota: {ctx.user_data.get('notes', 'بدون یادداشت / Nessuna nota')}",
            "",
            fmt_cart(cart)
        ]
        await update.message.reply_text("\n".join(summary), reply_markup=await kb_review_order(), parse_mode="HTML")
        return REVIEW_ORDER
    except Exception as e:
        log.error(f"Error in save_edited_field: {e}")
        await update.message.reply_text("❗️ خطا در ذخیره اطلاعات ویرایش‌شده. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def confirm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.callback_query
        cart = ctx.user_data.get("cart", [])
        if not cart:
            await q.message.reply_text(m("CART_EMPTY"), reply_markup=ReplyKeyboardRemove())
            ctx.user_data.clear()
            return ConversationHandler.END

        success, error = await update_stock(cart)
        if not success:
            await q.message.reply_text(error, reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END

        total = cart_total(cart)
        discount = 0
        if ctx.user_data.get("discount_code"):
            discounts = await load_discounts()
            code = ctx.user_data["discount_code"]
            if code in discounts and discounts[code]["is_active"]:
                discount = total * (discounts[code]["discount_percent"] / 100)
                total -= discount

        order_id = str(uuid.uuid4())[:8]
        invoice = await generate_invoice(order_id, ctx.user_data, cart, total, discount)
        order_data = [
            order_id,
            dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            ctx.user_data["user_id"],
            ctx.user_data["handle"],
            ctx.user_data["name"],
            ctx.user_data["phone"],
            ctx.user_data["address"],
            ctx.user_data["postal"],
            ctx.user_data["dest"],
            json.dumps(cart),
            total,
            ctx.user_data.get("discount_code", ""),
            discount,
            ctx.user_data.get("notes", ""),
            "pending"
        ]

        try:
            await asyncio.to_thread(orders_ws.append_row, order_data)
            log.info(f"Order {order_id} saved to Google Sheets")
        except Exception as e:
            log.error(f"Error saving order {order_id}: {e}")
            await q.message.reply_text("❗️ خطا در ثبت سفارش. لطفاً دوباره امتحان کنید.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END

        try:
            await q.message.delete()
            await ctx.bot.send_photo(
                chat_id=q.message.chat.id,
                photo=invoice,
                caption=m("ORDER_CONFIRMED").format(order_id=order_id),
                parse_mode="HTML"
            )
            await ctx.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🆕 سفارش جدید #{order_id}\nنام: {ctx.user_data['name']}\nمقصد: {ctx.user_data['dest']}\nجمع: {total:.2f}€",
                parse_mode="HTML"
            )
            ctx.user_data.clear()
            return ConversationHandler.END
        except Exception as e:
            log.error(f"Error sending invoice: {e}")
            await q.message.reply_text("❗️ خطا در ارسال فاکتور. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
    except Exception as e:
        log.error(f"Error in confirm_order: {e}")
        await q.message.reply_text("❗️ خطا در تأیید سفارش. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def cancel_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.callback_query
        await q.message.reply_text(m("ORDER_CANCELLED"), reply_markup=ReplyKeyboardRemove())
        ctx.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        log.error(f"Error in cancel_order: {e}")
        await q.message.reply_text("❗️ خطا در لغو سفارش. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

# ───────────── Main Handlers
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(m("WELCOME"), reply_markup=await kb_main(ctx), parse_mode="HTML")
    except Exception as e:
        log.error(f"Error in start: {e}")
        await update.message.reply_text("❗️ خطا در شروع. لطفاً دوباره امتحان کنید.")

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.callback_query
        data = q.data
        if data == "back":
            await safe_edit(q, m("WELCOME"), reply_markup=await kb_main(ctx), parse_mode="HTML")
        elif data.startswith("cat_"):
            cat = data[4:]
            await safe_edit(q, m("CATEGORY").format(cat=EMOJI.get(cat, cat)), reply_markup=await kb_category(cat, ctx), parse_mode="HTML")
        elif data.startswith("show_"):
            pid = data[5:]
            prods = await get_products()
            if pid not in prods:
                await safe_edit(q, m("STOCK_EMPTY"), reply_markup=await kb_main(ctx), parse_mode="HTML")
                return
            p = prods[pid]
            text = m("PRODUCT").format(
                fa=p["fa"], it=p["it"], brand=p["brand"], desc=p["description"],
                weight=p["weight"], price=p["price"], stock=p["stock"]
            )
            if p["image_url"]:
                await q.message.delete()
                await ctx.bot.send_photo(
                    chat_id=q.message.chat.id,
                    photo=p["image_url"],
                    caption=text,
                    reply_markup=await kb_product(pid),
                    parse_mode="HTML"
                )
            else:
                await safe_edit(q, text, reply_markup=await kb_product(pid), parse_mode="HTML")
        elif data.startswith("add_"):
            pid = data[4:]
            success, msg = await add_cart(ctx, pid, update=update)
            await safe_edit(q, msg, reply_markup=await kb_product(pid), parse_mode="HTML")
        elif data.startswith("inc_"):
            pid = data[4:]
            success, msg = await add_cart(ctx, pid, update=update)
            await safe_edit(q, m("CART_GUIDE") + "\n\n" + fmt_cart(ctx.user_data.get("cart", [])), reply_markup=await kb_cart(ctx.user_data.get("cart", [])), parse_mode="HTML")
        elif data.startswith("dec_"):
            pid = data[4:]
            cart = ctx.user_data.get("cart", [])
            item = next((i for i in cart if i["id"] == pid), None)
            if item:
                item["qty"] -= 1
                if item["qty"] <= 0:
                    cart.remove(item)
                await asyncio.to_thread(
                    abandoned_cart_ws.append_row,
                    [dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), ctx.user_data.get("user_id", update.effective_user.id), json.dumps(cart)]
                )
            await safe_edit(q, m("CART_GUIDE") + "\n\n" + fmt_cart(cart), reply_markup=await kb_cart(cart), parse_mode="HTML")
        elif data.startswith("del_"):
            pid = data[4:]
            cart = ctx.user_data.get("cart", [])
            cart[:] = [i for i in cart if i["id"] != pid]
            await asyncio.to_thread(
                abandoned_cart_ws.append_row,
                [dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), ctx.user_data.get("user_id", update.effective_user.id), json.dumps(cart)]
            )
            await safe_edit(q, m("CART_GUIDE") + "\n\n" + fmt_cart(cart), reply_markup=await kb_cart(cart), parse_mode="HTML")
        elif data == "cart":
            await safe_edit(q, m("CART_GUIDE") + "\n\n" + fmt_cart(ctx.user_data.get("cart", [])), reply_markup=await kb_cart(ctx.user_data.get("cart", [])), parse_mode="HTML")
        elif data == "support":
            await safe_edit(q, m("SUPPORT"), reply_markup=await kb_support(), parse_mode="HTML")
        elif data == "upload_photo":
            await q.message.reply_text(m("SEND_PHOTO"), reply_markup=ReplyKeyboardRemove())
        elif data == "bestsellers":
            prods = await get_products()
            best = [p for p in prods.values() if p["is_bestseller"]]
            if not best:
                await safe_edit(q, m("NO_BESTSELLERS"), reply_markup=await kb_main(ctx), parse_mode="HTML")
                return
            rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"show_{pid}")]
                    for pid, p in sorted(prods.items(), key=lambda x: x[1]["fa"]) if p["is_bestseller"]]
            rows.append([InlineKeyboardButton(m("BTN_BACK"), callback_data="back")])
            await safe_edit(q, m("BESTSELLERS"), reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
        elif data == "search":
            await q.message.reply_text(m("SEARCH"), reply_markup=ReplyKeyboardRemove())
        elif data == "order_perugia":
            ctx.user_data["dest"] = "Perugia"
            await safe_edit(q, m("CART_GUIDE") + "\n\n" + fmt_cart(ctx.user_data.get("cart", [])), reply_markup=await kb_cart(ctx.user_data.get("cart", [])), parse_mode="HTML")
        elif data == "order_italy":
            ctx.user_data["dest"] = "Italy"
            await safe_edit(q, m("CART_GUIDE") + "\n\n" + fmt_cart(ctx.user_data.get("cart", [])), reply_markup=await kb_cart(ctx.user_data.get("cart", [])), parse_mode="HTML")
        elif data == "checkout":
            if not ctx.user_data.get("cart"):
                await safe_edit(q, m("CART_EMPTY"), reply_markup=await kb_main(ctx), parse_mode="HTML")
                return
            if not ctx.user_data.get("dest"):
                await safe_edit(q, m("CART_GUIDE") + "\n\n" + fmt_cart(ctx.user_data.get("cart", [])), reply_markup=await kb_cart(ctx.user_data.get("cart", [])), parse_mode="HTML")
                return
            await start_order(update, ctx)
        elif data == "confirm_order":
            await confirm_order(update, ctx)
        elif data == "edit_name":
            await edit_name(update, ctx)
        elif data == "edit_phone":
            await edit_phone(update, ctx)
        elif data == "edit_address":
            await edit_address(update, ctx)
        elif data == "edit_postal":
            await edit_postal(update, ctx)
        elif data == "edit_notes":
            await edit_notes(update, ctx)
        elif data == "cancel_order":
            await cancel_order(update, ctx)
    except Exception as e:
        log.error(f"Error in callback_handler: {e}")
        await q.message.reply_text("❗️ خطا در پردازش درخواست. لطفاً دوباره امتحان کنید.")

async def search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.message.text.strip().lower()
        prods = await get_products()
        matches = [p for p in prods.values() if query in p["fa"].lower() or query in p["it"].lower()]
        if not matches:
            await update.message.reply_text(m("NO_RESULTS"), reply_markup=await kb_main(ctx), parse_mode="HTML")
            return
        rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"show_{pid}")]
                for pid, p in prods.items() if p in matches]
        rows.append([InlineKeyboardButton(m("BTN_BACK"), callback_data="back")])
        await update.message.reply_text(m("SEARCH_RESULTS"), reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    except Exception as e:
        log.error(f"Error in search: {e}")
        await update.message.reply_text("❗️ خطا در جستجو. لطفاً دوباره امتحان کنید.")

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        photo = update.message.photo[-1]
        file_id = photo.file_id
        await asyncio.to_thread(
            uploads_ws.append_row,
            [dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
             update.effective_user.id,
             f"@{update.effective_user.username or '-'}",
             file_id]
        )
        await ctx.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=f"📷 تصویر جدید از @{update.effective_user.username or update.effective_user.id}"
        )
        await update.message.reply_text(m("PHOTO_RECEIVED"), reply_markup=await kb_main(ctx), parse_mode="HTML")
    except Exception as e:
        log.error(f"Error in handle_photo: {e}")
        await update.message.reply_text("❗️ خطا در دریافت تصویر. لطفاً دوباره امتحان کنید.")

async def abandoned_cart_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        records = await asyncio.to_thread(abandoned_cart_ws.get_all_records)
        threshold = dt.datetime.utcnow() - dt.timedelta(hours=24)
        for r in records:
            ts = dt.datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S")
            if ts < threshold:
                user_id = int(r["user_id"])
                cart = json.loads(r["cart"])
                if cart:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=m("ABANDONED_CART").format(cart=fmt_cart(cart)),
                        reply_markup=await kb_main(context),
                        parse_mode="HTML"
                    )
        await asyncio.to_thread(abandoned_cart_ws.clear)
        await asyncio.to_thread(abandoned_cart_ws.append_row, ["timestamp", "user_id", "cart"])
    except Exception as e:
        log.error(f"Error in abandoned_cart_reminder: {e}")

async def weekly_backup(context: ContextTypes.DEFAULT_TYPE):
    try:
        backup_name = f"Bazarino_Backup_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        await asyncio.to_thread(gc.copy, SPREADSHEET, backup_name)
        log.info(f"Backup created: {backup_name}")
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID, f"📥 نسخه پشتیبان جدید ایجاد شد: {backup_name}")
    except Exception as e:
        log.error(f"Error in weekly_backup: {e}")
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID, f"⚠️ خطا در ایجاد نسخه پشتیبان: {e}")

# ───────────── Webhook
app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    try:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid secret token")
        update = await request.json()
        await tg_app.process_update(Update.de_json(update, bot))
        return {"status": "ok"}
    except Exception as e:
        log.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ───────────── Main
async def main():
    global tg_app, bot
    try:
        tg_app = ApplicationBuilder().token(TOKEN).build()
        bot = tg_app.bot
        await bot.set_webhook(f"{BASE_URL}/webhook", secret_token=WEBHOOK_SECRET)
        log.info(f"Webhook set to {BASE_URL}/webhook")

        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(start_order, pattern="^(order_perugia|order_italy|checkout)$")
            ],
            states={
                ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
                ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
                ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_postal)],
                ASK_POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_discount)],
                ASK_DISCOUNT: [
                    MessageHandler(filters.Regex("^/skip$"), skip_discount),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, ask_notes)
                ],
                ASK_NOTES: [
                    MessageHandler(filters.Regex("^/skip$"), skip_notes),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, review_order)
                ],
                REVIEW_ORDER: [
                    CallbackQueryHandler(edit_name, pattern="^edit_name$"),
                    CallbackQueryHandler(edit_phone, pattern="^edit_phone$"),
                    CallbackQueryHandler(edit_address, pattern="^edit_address$"),
                    CallbackQueryHandler(edit_postal, pattern="^edit_postal$"),
                    CallbackQueryHandler(edit_notes, pattern="^edit_notes$"),
                    CallbackQueryHandler(confirm_order, pattern="^confirm_order$"),
                    CallbackQueryHandler(cancel_order, pattern="^cancel_order$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_field)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel_order)]
        )

        tg_app.add_handler(CommandHandler("start", start))
        tg_app.add_handler(CallbackQueryHandler(callback_handler))
        tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))
        tg_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        tg_app.job_queue.run_repeating(abandoned_cart_reminder, interval=24*3600, first=10)
        tg_app.job_queue.run_repeating(weekly_backup, interval=7*24*3600, first=60)

        log.info("Starting webhook server...")
        await uvicorn.run(app, host="0.0.0.0", port=PORT)
    except Exception as e:
        log.error(f"Startup error: {e}")
        raise SystemExit(f"❗️ خطا در راه‌اندازی بات: {e}")

if __name__ == "__main__":
    asyncio.run(main())
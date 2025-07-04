#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – Optimized Version
- Webhook via FastAPI on Render with secret token
- Dynamic products from Google Sheets with versioned cache
- Features: Invoice with Hafez quote, discount codes, order notes, abandoned cart reminders,
           photo upload (file_id), push notifications (preparing/shipped), weekly backup
- Optimized for Render.com with Google Sheets
"""

from __future__ import annotations
import asyncio
import datetime as dt
import json
import logging
import os
import uuid
import yaml
from typing import Dict, Any, List
import io
import random

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

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bazarino.log")
    ]
)
log = logging.getLogger("bazarino")

# Global variables
tg_app = None
bot = None

# ───────────── Lazy-import Pillow
async def generate_invoice(order_id, user_data, cart, total, discount):
    from PIL import Image, ImageDraw, ImageFont
    width, height = 600, 900
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    header_color = (0, 128, 0)
    text_color = (0, 0, 0)
    accent_color = (255, 215, 0)
    border_color = (0, 0, 0)
    beige = (245, 245, 220)

    try:
        title_font = ImageFont.truetype("fonts/Vazir.ttf", 24)
        body_font = ImageFont.truetype("fonts/arial.ttf", 18)
        small_font = ImageFont.truetype("fonts/Vazir.ttf", 16)
    except Exception as e:
        log.error(f"Font loading error: {e}")
        title_font = body_font = small_font = ImageFont.load_default(18)

    draw.rectangle([(0, 0), (width, 80)], fill=header_color)
    draw.text((width // 2, 40), "فاکتور بازارینو / Fattura Bazarino", fill=(255, 255, 255), font=title_font, anchor="mm")
    try:
        logo = Image.open("logo.png").resize((60, 60))
        img.paste(logo, (20, 10))
    except Exception as e:
        log.error(f"Logo loading error: {e}")

    y = 100
    draw.text((50, y), f"شماره سفارش / Ordine #{order_id}", font=body_font, fill=text_color)
    y += 30
    draw.text((50, y), f"نام / Nome: {user_data['name']}", font=body_font, fill=text_color)
    y += 30
    draw.text((50, y), f"مقصد / Destinazione: {user_data['dest']}", font=body_font, fill=text_color)
    y += 30
    draw.text((50, y), f"آدرس / Indirizzo: {user_data['address']} | {user_data['postal']}", font=body_font, fill=text_color)
    y += 40

    draw.text((50, y), "محصولات / Prodotti:", font=body_font, fill=text_color)
    y += 30
    draw.rectangle([(40, y - 10), (width - 40, y + 10 + len(cart) * 30)], outline=border_color, width=1)
    for item in cart:
        draw.text((50, y), f"{item['qty']}× {item['fa']} — {item['qty'] * item['price']:.2f}€", font=body_font, fill=text_color)
        y += 30
    y += 20

    draw.text((50, y), f"تخفیف / Sconto: {discount:.2f}€", font=body_font, fill=text_color)
    y += 30
    draw.text((50, y), f"مجموع / Totale: {total:.2f}€", font=body_font, fill=text_color)
    y += 30
    draw.text((50, y), f"یادداشت / Nota: {user_data.get('notes', 'بدون یادداشت')}", font=body_font, fill=text_color)
    y += 40

    draw.rectangle([(40, y - 10), (width - 40, y + 80)], outline=border_color, width=1, fill=beige)
    hafez = random.choice(HAFEZ_QUOTES)
    draw.text((50, y), "✨ فال حافظ / Fal di Hafez:", font=small_font, fill=text_color)
    y += 20
    draw.text((50, y), hafez["fa"], font=small_font, fill=text_color)
    y += 20
    draw.text((50, y), hafez["it"], font=small_font, fill=text_color)
    y += 30

    draw.rectangle([(0, height - 40), (width, height)], fill=header_color)
    draw.text((width // 2, height - 20), "بازارینو - طعم ایران در ایتالیا", fill=(255, 255, 255), font=small_font, anchor="mm")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

# ───────────── Config
try:
    with open("config.yaml", encoding="utf-8") as f:
        CONFIG = yaml.safe_load(f)
except FileNotFoundError:
    log.error("config.yaml not found")
    raise SystemExit("❗️ فایل config.yaml یافت نشد.")

SHEET_CONFIG = CONFIG["sheets"]
HAFEZ_QUOTES = CONFIG["hafez_quotes"]

# ───────────── Messages
try:
    with open("messages.json", encoding="utf-8") as f:
        MSG = json.load(f)
except FileNotFoundError:
    log.error("messages.json not found")
    raise SystemExit("❗️ فایل messages.json یافت نشد.")

def m(k: str) -> str:
    return MSG.get(k, f"[{k}]")

# ───────────── ENV
for v in ("TELEGRAM_TOKEN", "ADMIN_CHAT_ID", "BASE_URL"):
    if not os.getenv(v):
        log.error(f"Missing environment variable: {v}")
        raise SystemExit(f"❗️ متغیر محیطی {v} تنظیم نشده است.")

TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = os.getenv("BASE_URL").rstrip("/")
WEBHOOK_SECRET = "EhsaNegar1394"
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID"))
SPREADSHEET = os.getenv("SPREADSHEET_NAME", "Bazarnio Orders")
PRODUCT_WS = os.getenv("PRODUCT_WORKSHEET", "Sheet2")
LOW_STOCK_TH = int(os.getenv("LOW_STOCK_THRESHOLD", "3"))
PORT = int(os.getenv("PORT", "8000"))

# ───────────── Google Sheets
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_path = os.getenv("GOOGLE_CREDS", "/etc/secrets/bazarino-perugia-bot-f37c44dd9b14.json")
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
        abandoned_cart_ws = wb.add_worksheet(title=SHEET_CONFIG["abandoned_carts"]["name"], rows=100, cols=3)
    try:
        discounts_ws = wb.worksheet(SHEET_CONFIG["discounts"]["name"])
    except gspread.exceptions.WorksheetNotFound:
        discounts_ws = wb.add_worksheet(title=SHEET_CONFIG["discounts"]["name"], rows=100, cols=4)
    try:
        uploads_ws = wb.worksheet(SHEET_CONFIG["uploads"]["name"])
    except gspread.exceptions.WorksheetNotFound:
        uploads_ws = wb.add_worksheet(title=SHEET_CONFIG["uploads"]["name"], rows=100, cols=4)
except Exception as e:
    log.error(f"Failed to initialize Google Sheets: {e}")
    raise SystemExit(f"❗️ خطا در اتصال به Google Sheets: {e}")

# ───────────── Google Sheets Data
async def load_products() -> Dict[str, Dict[str, Any]]:
    try:
        records = await asyncio.to_thread(products_ws.get_all_records)
        return {
            r["id"]: dict(
                cat=r["cat"], fa=r["fa"], it=r["it"], brand=r["brand"],
                desc=r["description"], weight=r["weight"],
                price=float(r["price"]), image_url=r["image_url"] or None,
                stock=int(r.get("stock", 0)), is_bestseller=r.get("is_bestseller", "FALSE").lower() == "true",
                version=r.get("version", "0")
            ) for r in records
        }
    except Exception as e:
        log.error(f"Error loading products from Google Sheets: {e}")
        raise SystemExit(f"❗️ خطا در بارگذاری محصولات از Google Sheets: {e}")

async def load_discounts():
    try:
        records = await asyncio.to_thread(discounts_ws.get_all_records)
        return {
            r["code"]: dict(
                discount_percent=float(r["discount_percent"]),
                valid_until=r["valid_until"],
                is_active=r["is_active"].lower() == "true"
            ) for r in records
        }
    except Exception as e:
        log.error(f"Error loading discounts: {e}")
        return {}

# Versioned cache for products
async def get_products():
    current_version = await asyncio.to_thread(products_ws.acell, "L1").value or "0"
    if (not hasattr(get_products, "_data") or
        not hasattr(get_products, "_version") or
        get_products._version != current_version or
        dt.datetime.utcnow() > getattr(get_products, "_ts", dt.datetime.min)):
        get_products._data = await load_products()
        get_products._version = current_version
        get_products._ts = dt.datetime.utcnow() + dt.timedelta(seconds=60)
        log.info(f"Loaded {len(get_products._data)} products from Google Sheets, version {current_version}")
    return get_products._data

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
        await q.edit_message_text(*a, **k)
    except BadRequest as e:
        if "not modified" in str(e):
            return
        log.error(f"Edit msg error: {e}")
    except NetworkError as e:
        log.error(f"Network error: {e}")

async def alert_admin(pid, stock):
    if stock <= LOW_STOCK_TH and ADMIN_ID:
        for _ in range(3):
            try:
                await bot.send_message(ADMIN_ID, f"⚠️ موجودی کم {stock}: {(await get_products())[pid]['fa']}")
                log.info(f"Low stock alert sent for {(await get_products())[pid]['fa']}")
                break
            except Exception as e:
                log.error(f"Alert fail attempt: {e}")
                await asyncio.sleep(1)

# ───────────── Keyboards
async def kb_main(ctx):
    cats = {p["cat"] for p in (await get_products()).values()}
    rows = [[InlineKeyboardButton(EMOJI.get(c, c), callback_data=f"cat_{c}")] for c in cats]
    cart = ctx.user_data.get("cart", [])
    cart_summary = f"{m('BTN_CART')} ({cart_count(ctx)} آیتم - {cart_total(cart):.2f}€)" if cart else m("BTN_CART")
    rows.append([
        InlineKeyboardButton(m("BTN_SEARCH"), callback_data="search"),
        InlineKeyboardButton(cart_summary, callback_data="cart"),
        InlineKeyboardButton("🔥 پرفروش‌ها / Più venduti", callback_data="bestsellers")
    ])
    rows.append([
        InlineKeyboardButton("📞 پشتیبانی / Supporto", callback_data="support")
    ])
    return InlineKeyboardMarkup(rows)

async def kb_category(cat, ctx):
    rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"show_{pid}")]
            for pid, p in (await get_products()).items() if p["cat"] == cat]
    rows.append([
        InlineKeyboardButton(m("BTN_SEARCH"), callback_data="search"),
        InlineKeyboardButton(m("BTN_BACK"), callback_data="back")
    ])
    return InlineKeyboardMarkup(rows)

def kb_product(pid):
    p = get_products._data[pid] if hasattr(get_products, "_data") else (asyncio.run(get_products()))[pid]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(m("CART_ADDED").split("\n")[0], callback_data=f"add_{pid}")],
        [InlineKeyboardButton(m("BTN_BACK"), callback_data=f"back_cat_{p['cat']}")]
    ])

def kb_cart(cart):
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

def kb_support():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📷 ارسال تصویر / Invia immagine", callback_data="upload_photo")],
        [InlineKeyboardButton(m("BTN_BACK"), callback_data="back")]
    ])

# ───────────── Cart operations
async def add_cart(ctx, pid, qty=1, update=None):
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
        cart.append(dict(id=pid, fa=p["fa"], price=p["price"], weight=p["weight"], qty=qty))
    await alert_admin(pid, stock)
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

def fmt_cart(cart):
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

# ───────────── Stock update
async def update_stock(cart):
    try:
        records = await asyncio.to_thread(products_ws.get_all_records)
        for it in cart:
            pid = it["id"]
            qty = it["qty"]
            for idx, row in enumerate(records, start=2):
                if row["id"] == pid:
                    new = row["stock"] - qty
                    if new < 0:
                        log.error(f"Cannot update stock for {pid}: negative stock")
                        return False
                    await asyncio.to_thread(products_ws.update_cell, idx, 10, new)
                    (await get_products())[pid]["stock"] = new
                    log.info(f"Updated stock for {pid}: {new}")
        return True
    except Exception as e:
        log.error(f"Stock update error: {e}")
        return False

# ───────────── Order States
ASK_NAME, ASK_PHONE, ASK_ADDRESS, ASK_POSTAL, ASK_DISCOUNT, ASK_NOTES = range(6)

# ───────────── Order Process
async def start_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not ctx.user_data.get("dest"):
        await q.message.reply_text("لطفاً مقصد (پروجا/ایتالیا) را انتخاب کنید.\nScegli la destinazione (Perugia/Italia).", reply_markup=kb_cart(ctx.user_data.get("cart", [])))
        return
    ctx.user_data["name"] = f"{q.from_user.first_name} {(q.from_user.last_name or '')}".strip()
    ctx.user_data["handle"] = f"@{q.from_user.username}" if q.from_user.username else "-"
    ctx.user_data["user_id"] = update.effective_user.id
    await q.message.reply_text(m("INPUT_NAME"))
    return ASK_NAME

async def ask_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(m("INPUT_PHONE"))
    return ASK_PHONE

async def ask_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text(m("INPUT_ADDRESS"))
    return ASK_ADDRESS

async def ask_postal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["address"] = update.message.text.strip()
    await update.message.reply_text(m("INPUT_POSTAL"))
    return ASK_POSTAL

async def ask_discount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["postal"] = update.message.text.strip()
    await update.message.reply_text("🎁 کد تخفیف دارید؟ وارد کنید یا /skip را بزنید.\nHai un codice sconto? Inseriscilo o premi /skip.")
    return ASK_DISCOUNT

async def ask_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

async def confirm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    if ADMIN_ID:
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

async def cancel_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(m("ORDER_CANCELLED"), reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ───────────── Photo Upload
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("awaiting_photo"):
        return
    photo = update.message.photo[-1]
    if photo.file_size > 2 * 1024 * 1024:  # حداکثر 2 مگابایت
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
            if row_data[17] == "TRUE":  # notified
                continue
            user_id = int(row_data[2])  # user_id
            order_id = row_data[1]  # order_id
            status = row_data[16]  # status
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

# ───────────── Backup Google Sheets
async def backup_sheets(context: ContextTypes.DEFAULT_TYPE):
    try:
        sheets = [orders_ws, products_ws, discounts_ws, abandoned_cart_ws, uploads_ws]
        for sheet in sheets:
            records = await asyncio.to_thread(sheet.get_all_values)
            csv_content = "\n".join([",".join(row) for row in records])
            csv_file = io.BytesIO(csv_content.encode("utf-8"))
            csv_file.name = f"{sheet.title}_backup_{dt.datetime.utcnow().strftime('%Y%m%d')}.csv"
            await context.bot.send_document(ADMIN_ID, document=csv_file, caption=f"📊 بکاپ {sheet.title} - {dt.datetime.utcnow().strftime('%Y-%m-%d')}")
            log.info(f"Backup sent for {sheet.title}")
    except Exception as e:
        log.error(f"Error creating backup: {e}")

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

# ───────────── /search
from difflib import get_close_matches
async def cmd_search(u, ctx: ContextTypes.DEFAULT_TYPE):
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
        btn = InlineKeyboardMarkup.from_button(InlineKeyboardButton(m("CART_ADDED").split("\n")[0], callback_data=f"add_{pid}"))
        if p["image_url"] and p["image_url"].strip():
            await u.message.reply_photo(p["image_url"], caption=cap, reply_markup=btn)
        else:
            await u.message.reply_text(cap, reply_markup=btn)

# ───────────── Commands
async def cmd_start(u, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["user_id"] = u.effective_user.id
    await u.message.reply_html(m("WELCOME"), reply_markup=await kb_main(ctx))

async def cmd_about(u, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(m("ABOUT_US"), disable_web_page_preview=True)

async def cmd_privacy(u, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(m("PRIVACY"), disable_web_page_preview=True)

# ───────────── App, webhook and FastAPI
async def post_init(app: Application):
    log.info("Application initialized")
    webhook_url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
    await app.bot.set_webhook(webhook_url)
    log.info(f"Webhook set to {webhook_url}")

async def post_shutdown(app: Application):
    log.info("Application shutting down")
    await app.bot.delete_webhook()

async def lifespan(app: FastAPI):
    global tg_app, bot
    builder = ApplicationBuilder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown)
    tg_app = builder.build()
    bot = tg_app.bot
    await tg_app.initialize()
    if not tg_app.job_queue:
        tg_app.job_queue = JobQueue()
        await tg_app.job_queue.start()
    job_queue = tg_app.job_queue
    job_queue.run_daily(send_cart_reminder, time=dt.time(hour=18, minute=0))
    job_queue.run_repeating(check_order_status, interval=600)
    job_queue.run_daily(backup_sheets, time=dt.time(hour=0, minute=0))
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("search", cmd_search))
    tg_app.add_handler(CommandHandler("about", cmd_about))
    tg_app.add_handler(CommandHandler("privacy", cmd_privacy))
    tg_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    tg_app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_order, pattern="^checkout$")],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_postal)],
            ASK_POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_discount)],
            ASK_DISCOUNT: [MessageHandler(filters.TEXT | filters.COMMAND, ask_notes)],
            ASK_NOTES: [MessageHandler(filters.TEXT | filters.COMMAND, confirm_order)],
        },
        fallbacks=[CommandHandler("cancel", cancel_order)]
    ))
    tg_app.add_handler(CallbackQueryHandler(router))
    yield
    await tg_app.shutdown()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook/{secret}")
async def wh(req: Request, secret: str):
    if secret != WEBHOOK_SECRET:
        log.error("Invalid webhook secret")
        raise HTTPException(status_code=403, detail="Invalid secret")
    try:
        data = await req.json()
        update = Update.de_json(data, bot)
        if not update:
            log.error("Invalid webhook update received")
            raise HTTPException(status_code=400, detail="Invalid update")
        await tg_app.process_update(update)
        return {"ok": True}
    except Exception as e:
        log.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    await q.answer()

    if d == "back":
        await safe_edit(q, m("WELCOME"), reply_markup=await kb_main(ctx), parse_mode="HTML")
        return

    if d == "support":
        await safe_edit(q, m("SUPPORT_MESSAGE"), reply_markup=kb_support(), parse_mode="HTML")
        return

    if d == "upload_photo":
        ctx.user_data["awaiting_photo"] = True
        await safe_edit(q, m("UPLOAD_PHOTO"), reply_markup=kb_support())
        return

    if d == "bestsellers":
        bestsellers = [(pid, p) for pid, p in (await get_products()).items() if p.get("is_bestseller", False)]
        if not bestsellers:
            await safe_edit(q, "🔥 در حال حاضر محصول پرفروشی وجود ندارد.\nNessun prodotto più venduto al momento.", reply_markup=await kb_main(ctx), parse_mode="HTML")
            return
        rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"show_{pid}")] for pid, p in bestsellers]
        rows.append([InlineKeyboardButton(m("BTN_BACK"), callback_data="back")])
        await safe_edit(q, "🔥 محصولات پرفروش / Più venduti", reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
        return

    if d == "search":
        await safe_edit(q, m("SEARCH_USAGE"), reply_markup=await kb_main(ctx))
        return

    if d.startswith("cat_"):
        cat = d[4:]
        await safe_edit(q, EMOJI.get(cat, cat), reply_markup=await kb_category(cat, ctx), parse_mode="HTML")
        return

    if d.startswith("show_"):
        pid = d[5:]
        p = (await get_products())[pid]
        cap = f"<b>{p['fa']} / {p['it']}</b>\n{p['desc']}\n{p['price']}€ / {p['weight']}\n||موجودی / Stock:|| {p['stock']}"
        try:
            await q.message.delete()
        except Exception as e:
            log.error(f"Error deleting previous message: {e}")
        if p["image_url"] and p["image_url"].strip():
            await ctx.bot.send_photo(
                chat_id=q.message.chat.id,
                photo=p["image_url"],
                caption=cap,
                reply_markup=kb_product(pid),
                parse_mode="HTML"
            )
        else:
            await ctx.bot.send_message(
                chat_id=q.message.chat.id,
                text=cap,
                reply_markup=kb_product(pid),
                parse_mode="HTML"
            )
        return

    if d.startswith("add_"):
        pid = d[4:]
        ok, msg = await add_cart(ctx, pid, qty=1, update=update)
        await q.answer(msg, show_alert=not ok)
        cat = (await get_products())[pid]["cat"]
        await safe_edit(q, EMOJI.get(cat, cat), reply_markup=await kb_category(cat, ctx), parse_mode="HTML")
        return

    if d.startswith("back_cat_"):
        cat = d.split("_")[2]
        await safe_edit(q, EMOJI.get(cat, cat), reply_markup=await kb_category(cat, ctx), parse_mode="HTML")
        return

    if d == "cart":
        await safe_edit(q, fmt_cart(ctx.user_data.get("cart", [])), reply_markup=kb_cart(ctx.user_data.get("cart", [])), parse_mode="HTML")
        return

    if d.startswith(("inc_", "dec_", "del_")):
        pid = d.split("_")[1]
        cart = ctx.user_data.get("cart", [])
        it = next((i for i in cart if i["id"] == pid), None)
        if not it:
            return
        if d.startswith("inc_"):
            await add_cart(ctx, pid, 1, update=update)
        elif d.startswith("dec_"):
            it["qty"] = max(1, it["qty"] - 1)
        else:
            cart.remove(it)
        try:
            await asyncio.to_thread(
                abandoned_cart_ws.append_row,
                [dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                 ctx.user_data.get("user_id", update.effective_user.id),
                 json.dumps(cart)]
            )
        except Exception as e:
            log.error(f"Error saving abandoned cart: {e}")
        await safe_edit(q, fmt_cart(cart), reply_markup=kb_cart(cart), parse_mode="HTML")
        return

    if d in ["order_perugia", "order_italy"]:
        ctx.user_data["dest"] = "Perugia" if d == "order_perugia" else "Italy"
        await safe_edit(q, fmt_cart(ctx.user_data.get("cart", [])), reply_markup=kb_cart(ctx.user_data.get("cart", [])), parse_mode="HTML")
        return

    if d == "checkout":
        return await start_order(update, ctx)

def main():
    uvicorn.run(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
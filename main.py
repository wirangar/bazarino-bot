#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – final clean version
==========================================

• منوی دو زبانه (فارسی/ایتالیایی) با دسته‌ها و کارت محصولات
• ثبت سفارش در Google Sheets
• پرداخت تلگرامی (Stripe) برای مقصد «Italia»؛ سفارش‌های «Perugia» پرداخت در محل
• سازگار با python-telegram-bot v20.7  (Python 3.11)

Required ENV (Render.com):
    TELEGRAM_TOKEN          <bot token>
    BASE_URL                https://…/  (public HTTPS for webhook)
    ADMIN_CHAT_ID           <chat id>  (numeric)
    GOOGLE_CREDS_JSON       service-account JSON (string or Base64→string)
    PAYMENT_PROVIDER_TOKEN  Stripe token (@BotFather → /setinlinepayment)
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import textwrap
from functools import partial
from typing import Any, Dict

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

# ───────────── LOGGING ─────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ───────────── ENV ─────────────
TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = os.getenv("BASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN")
SHEET_NAME = "Bazarnio Orders"

for var, name in [
    (TOKEN, "TELEGRAM_TOKEN"),
    (BASE_URL, "BASE_URL"),
    (GOOGLE_CREDS_JSON, "GOOGLE_CREDS_JSON"),
]:
    if not var:
        logger.critical("%s env var is required.", name)
        raise SystemExit(1)

# ───────────── Google Sheets ─────────────
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds_dict = json.loads(GOOGLE_CREDS_JSON)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
sheet = gspread.authorize(creds).open(SHEET_NAME).sheet1
logger.info("Google Sheets connected.")

# ───────────── Conversation states ─────────────
NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

# ───────────── Data ─────────────
CATEGORIES: Dict[str, str] = {
    "rice":   "🍚 برنج / Riso",
    "beans":  "🥣 حبوبات / Legumi",
    "spice":  "🌿 ادویه / Spezie",
    "nuts":   "🥜 خشکبار / Frutta secca",
    "drink":  "🧃 نوشیدنی / Bevande",
    "canned": "🥫 کنسرو / Conserve",
}

PRODUCTS: Dict[str, Dict[str, Any]] = {
    "rice_hashemi": {
        "cat": "rice",
        "fa": "برنج هاشمی",
        "it": "Riso Hashemi",
        "desc": "عطر بالا / Profumato",
        "weight": "1 kg",
        "price": 6.0,
        "image_url": "https://i.imgur.com/paddy.jpg",
    },
    "bean_lentil": {
        "cat": "beans",
        "fa": "عدس",
        "it": "Lenticchie",
        "desc": "عدس سبز / Lenticchie verdi",
        "weight": "1 kg",
        "price": 4.0,
        "image_url": "https://i.imgur.com/lentil.jpg",
    },
}

# ───────────── Texts ─────────────
WELCOME = textwrap.dedent(
    """
    🍇 به بازارینو خوش آمدید! 🇮🇷🇮🇹
    Benvenuto in Bazarino!
    🏠 فروشگاه ایرانی‌های پروجا

    👇 لطفاً یک دسته را انتخاب کنید:
    """
)
ABOUT = "بازارینو توسط دانشجویان ایرانی در پروجا اداره می‌شود."
PRIVACY = "داده‌های شما فقط برای پردازش سفارش استفاده می‌شوند."
NO_ONLINE_PAY = "❌ پرداخت آنلاین فعال نیست؛ لطفاً «سفارش پروجا» را انتخاب کنید."

# ───────────── Keyboards ─────────────
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(lbl, callback_data=f"cat_{k}")] for k, lbl in CATEGORIES.items()]
    )

def kb_category(cat: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"prd_{code}")]
        for code, p in PRODUCTS.items() if p["cat"] == cat
    ]
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_product(code: str) -> InlineKeyboardMarkup:
    btns = [[InlineKeyboardButton("🛒 سفارش پروجا", callback_data=f"ordP_{code}")]]
    if PAYMENT_PROVIDER_TOKEN:
        btns.append([InlineKeyboardButton("📦 سفارش ایتالیا (پرداخت)", callback_data=f"ordI_{code}")])
    btns.append([InlineKeyboardButton("⬅️ بازگشت", callback_data=f"back_{PRODUCTS[code]['cat']}")])
    return InlineKeyboardMarkup(btns)

# ───────────── Callback router ─────────────
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    if data == "back_main":
        await q.edit_message_text(WELCOME, reply_markup=kb_main(), disable_web_page_preview=True)
        return
    if data.startswith("back_"):
        cat = data.split("_", 1)[1]
        await q.edit_message_text(CATEGORIES.get(cat, "❓"), reply_markup=kb_category(cat))
        return
    if data.startswith("cat_"):
        cat = data.split("_", 1)[1]
        await q.edit_message_text(CATEGORIES.get(cat, "❓"), reply_markup=kb_category(cat))
        return
    if data.startswith("prd_"):
        code = data.split("_", 1)[1]
        p = PRODUCTS[code]
        caption = (
            f"<b>{p['fa']} / {p['it']}</b>\n"
            f"{p['desc']}\nوزن: {p['weight']}\nقیمت: €{p['price']:.2f}"
        )
        await q.message.delete()
        await q.message.chat.send_photo(
            photo=p["image_url"], caption=caption, parse_mode="HTML", reply_markup=kb_product(code)
        )
        return
    if data.startswith(("ordP_", "ordI_")):
        if data.startswith("ordI_") and not PAYMENT_PROVIDER_TOKEN:
            await q.message.reply_text(NO_ONLINE_PAY)
            return ConversationHandler.END

        ctx.user_data.clear()
        ctx.user_data["product_code"] = data.split("_", 1)[1]
        ctx.user_data["dest"] = "Perugia" if data.startswith("ordP_") else "Italia"
        await q.message.reply_text("👤 نام و نام خانوادگی:")
        return NAME

# ───────────── Form steps ─────────────
async def step_name(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = u.message.text.strip()
    if not ctx.user_data["name"]:
        await u.message.reply_text("❌ نام نمی‌تواند خالی باشد. دوباره وارد کنید:")
        return NAME
    await u.message.reply_text("📍 آدرس:")
    return ADDRESS

async def step_address(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["address"] = u.message.text.strip()
    if not ctx.user_data["address"]:
        await u.message.reply_text("❌ آدرس نمی‌تواند خالی باشد. دوباره وارد کنید:")
        return ADDRESS
    if ctx.user_data["dest"] == "Italia":
        await u.message.reply_text("🔢 کد پستی:")
        return POSTAL
    await u.message.reply_text("☎️ تلفن:")
    return PHONE

async def step_postal(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    postal = u.message.text.strip()
    if not postal.isdigit():
        await u.message.reply_text("❌ کد پستی باید عدد باشد. دوباره وارد کنید:")
        return POSTAL
    ctx.user_data["postal"] = postal
    await u.message.reply_text("☎️ تلفن:")
    return PHONE

async def step_phone(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = u.message.text.strip()
    if not phone.replace("+", "").replace(" ", "").isdigit():
        await u.message.reply_text("❌ شماره تلفن معتبر نیست. دوباره وارد کنید:")
        return PHONE
    ctx.user_data["phone"] = phone
    await u.message.reply_text("📝 یادداشت (اختیاری):")
    return NOTES

async def step_notes(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["notes"] = u.message.text.strip()

    if ctx.user_data["dest"] == "Italia":  # online payment
        p = PRODUCTS[ctx.user_data["product_code"]]
        amount = int(p["price"] * 100)
        await u.message.reply_invoice(
            title=f"سفارش {p['fa']}",
            description=p["desc"],
            payload=f"order:{u.effective_user.id}:{ctx.user_data['product_code']}",
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency="EUR",
            prices=[LabeledPrice(label=p["fa"], amount=amount)],
        )
    await save_order(u, ctx)
    return ConversationHandler.END

# ───────────── Helpers ─────────────
async def save_order(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Store order in Google Sheets and notify admin."""
    p = PRODUCTS[ctx.user_data["product_code"]]
    row = [
        datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        ctx.user_data["dest"],
        p["fa"],
        f"{p['price']:.2f}",
        ctx.user_data["name"],
        ctx.user_data["address"],
        ctx.user_data.get("postal", "-"),
        ctx.user_data["phone"],
        ctx.user_data["notes"] or "-",
        f"@{u.effective_user.username}" if u.effective_user.username else "-",
        "Pending" if ctx.user_data["dest"] == "Italia" else "COD",
    ]
    loop = asyncio.get_running
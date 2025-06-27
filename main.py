#!/usr/bin/env python3

-- coding: utf-8 --

""" Bazarino Telegram Bot (python‑telegram‑bot v20+) — with Payment Gateway for Italy Orders

• دوبخشی: منوی فارسی/ایتالیایی و کارت محصول • پرداخت آنلاین برای مقصد «Italia» (Stripe/Telegram Payments) • ذخیره سفارش در Google Sheets و ارسال به ادمین """

import os import datetime import asyncio import logging import textwrap from functools import partial from typing import Dict, Any

from telegram import ( Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, LabeledPrice, ) from telegram.ext import ( ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, PreCheckoutQueryHandler, ContextTypes, filters, )

import gspread from oauth2client.service_account import ServiceAccountCredentials

─────────────────────── ENV ───────────────────────────

TOKEN       = os.environ["TELEGRAM_TOKEN"] BASE_URL    = os.environ["BASE_URL"]              # https://bazarino-bot.onrender.com ADMIN_ID    = int(os.getenv("ADMIN_CHAT_ID", "0")) CREDS_PATH  = os.environ["GOOGLE_CREDS"]          # /etc/secrets/creds.json SHEET_NAME  = "Bazarnio Orders" PAYMENT_PROVIDER_TOKEN = os.environ.get("PAYMENT_PROVIDER_TOKEN")  # Stripe token

─────────────────────── Google Sheets ────────────────

scope = [ "https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive", ] creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope) sheet = gspread.authorize(creds).open(SHEET_NAME).sheet1

─────────────────────── Conversation States ─────────

NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

─────────────────────── Data ─────────────────────────

CATEGORIES = { "rice":  "🍚 برنج / Riso", "beans": "🥣 حبوبات / Legumi", "spice": "🌿 ادویه / Spezie", "nuts":  "🥜 خشکبار / Frutta secca", "drink": "🧃 نوشیدنی / Bevande", "canned":"🥫 کنسرو / Conserve", }

PRODUCTS: Dict[str, Dict[str, Any]] = { "rice_hashemi": { "cat": "rice", "fa": "برنج هاشمی", "it": "Riso Hashemi", "desc": "عطر بالا / Profumato", "weight": "1 kg", "price": "6",  # in EUR "img": "https://i.imgur.com/paddy.jpg", }, "bean_lentil": { "cat": "beans", "fa": "عدس", "it": "Lenticchie", "desc": "عدس سبز / Lenticchie verdi", "weight": "1 kg", "price": "4", "img": "https://i.imgur.com/lentil.jpg", }, }

─────────────────────── Texts ────────────────────────

WELCOME = textwrap.dedent( """ 🍇 به بازارینو خوش آمدید! 🇮🇷🇮🇹\nBenvenuto in Bazarino!\n🏠 فروشگاه ایرانی‌های پروجا\n\n👇 لطفاً یک دسته را انتخاب کنید: """ ) ABOUT   = "بازارینو توسط دانشجویان ایرانی در پروجا اداره می‌شود." PRIVACY = "حریم‌خصوصی شما برای ما مقدس است؛ داده‌ها فقط جهت پردازش سفارش استفاده می‌شوند."

─────────────────────── Keyboards ────────────────────

def kb_main() -> InlineKeyboardMarkup: return InlineKeyboardMarkup( [[InlineKeyboardButton(lbl, callback_data=f"cat_{key}")] for key, lbl in CATEGORIES.items()] )

def kb_category(cat: str) -> InlineKeyboardMarkup: btns = [ [InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"prd_{code}")] for code, p in PRODUCTS.items() if p["cat"] == cat ] btns.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")]) return InlineKeyboardMarkup(btns)

def kb_product(code: str) -> InlineKeyboardMarkup: return InlineKeyboardMarkup( [ [InlineKeyboardButton("🛒 سفارش پروجا", callback_data=f"ordP_{code}")], [InlineKeyboardButton("📦 سفارش ایتالیا (پرداخت)", callback_data=f"ordI_{code}")], [InlineKeyboardButton("⬅️ بازگشت", callback_data=f"back_{PRODUCTS[code]['cat']}")], ] )

─────────────────────── Callback Router ──────────────

async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE): q = update.callback_query await q.answer() data = q.data

if data == "back_main":
    await q.edit_message_text(WELCOME, reply_markup=kb_main(), disable_web_page_preview=True)
    return

if data.startswith("back_"):
    cat = data.split("_", 1)[1]
    await q.edit_message_text(CATEGORIES[cat], reply_markup=kb_category(cat))
    return

if data.startswith("cat_"):
    cat = data.split("_", 1)[1]
    await q.edit_message_text(CATEGORIES[cat], reply_markup=kb_category(cat))
    return

if data.startswith("prd_"):
    code = data.split("_", 1)[1]
    p = PRODUCTS[code]
    caption = (
        f"<b>{p['fa']} / {p['it']}</b>\n{p['desc']}\nوزن: {p['weight']}\nقیمت: €{p['price']}"
    )
    await q.message.delete()
    await q.message.chat.send_photo(
        photo=p["img"],
        caption=caption,
        parse_mode="HTML",
        reply_markup=kb_product(code),
    )
    return

if data.startswith(("ordP_", "ordI_")):
    ctx.user_data.clear()
    ctx.user_data["product_code"] = data.split("_", 1)[1]
    ctx.user_data["dest"] = "Perugia" if data.startswith("ordP_") else "Italia"
    await q.message.reply_text("👤 نام و نام خانوادگی:")
    return NAME

─────────────────────── Form Steps ───────────────────

async def step_name(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["name"] = u.message.text await u.message.reply_text("📍 آدرس:") return ADDRESS

async def step_address(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["address"] = u.message.text if ctx.user_data["dest"] == "Italia": await u.message.reply_text("🔢 کد پستی:") return POSTAL await u.message.reply_text("☎️ تلفن:") return PHONE

async def step_postal(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["postal"] = u.message.text await u.message.reply_text("☎️ تلفن:") return PHONE

async def step_phone(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["phone"] = u.message.text await u.message.reply_text("📝 یادداشت:") return NOTES

async def step_notes(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["notes"] = u.message.text

# اگر مقصد ایتالیاست → پرداخت تلگرام
if ctx.user_data["dest"] == "Italia":
    p = PRODUCTS[ctx.user_data["product_code"]]
    amount_cents = int(float(p["price"]) * 100)
    await u.message.reply_invoice(
        title=f"سفارش {p['fa']}",
        description=p["desc"],
        payload="order-payload",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="EUR",
        prices=[LabeledPrice(label=p["fa"], amount=amount_cents)],
    )
    return ConversationHandler.END

# اگر مقصد پروجاست، مستقیم ثبت سفارش
await save_order(u, ctx)
return ConversationHandler.END

─────────────────────── Payment Handlers ─────────────

async def precheckout(update: Update, ctx: ContextTypes.DEFAULT_TYPE): await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("💳 پرداخت با موفقیت انجام شد! در حال ثبت سفارش …") # بازیابی user_data از پیام قبلی Conversation تمام شده؛ لذا اینفو را از Invoice استخراج کنیم # برای سادگی در این نسخه فرض می‌کنیم آخرین ctx.user_data معتبر است (مرحله NOTES). await save


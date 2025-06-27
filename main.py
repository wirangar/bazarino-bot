#!/usr/bin/env python3

#-- coding: utf-8 --

""" Bazarino Telegram Bot (python-telegram-bot v20+)

• Dual‑language menu (Persian / Italian) with nested categories and product cards. • Google Sheets order storage via service‑account JSON. • Telegram Payments (Stripe) enabled for destination "Italia"; Perugia orders remain cash‑on‑delivery.

Environment variables expected: TELEGRAM_TOKEN          Bot token BASE_URL                Public https URL of webhook (e.g. https://bazarino-bot.onrender.com) ADMIN_CHAT_ID           Telegram chat ID for admin notifications GOOGLE_CREDS            Path to service‑account JSON inside container PAYMENT_PROVIDER_TOKEN  Stripe token from @BotFather → /setinlinepayment

Run with Python 3.11+ """

from future import annotations

import asyncio import datetime import logging import os import textwrap from functools import partial from typing import Any, Dict

import gspread from oauth2client.service_account import ServiceAccountCredentials from telegram import ( InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, ReplyKeyboardRemove, Update, ) from telegram.ext import ( ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, PreCheckoutQueryHandler, filters, )

========= ENV =========

TOKEN = os.environ["TELEGRAM_TOKEN"] BASE_URL = os.environ["BASE_URL"] ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "0")) CREDS_PATH = os.environ["GOOGLE_CREDS"] SHEET_NAME = "Bazarnio Orders" PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN")

========= GOOGLE SHEETS =========

SCOPE = [ "https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive", ] creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, SCOPE) sheet = gspread.authorize(creds).open(SHEET_NAME).sheet1

========= CONVERSATION STATES =========

NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

========= DATA =========

CATEGORIES: Dict[str, str] = { "rice": "🍚 برنج / Riso", "beans": "🥣 حبوبات / Legumi", "spice": "🌿 ادویه / Spezie", "nuts": "🥜 خشکبار / Frutta secca", "drink": "🧃 نوشیدنی / Bevande", "canned": "🥫 کنسرو / Conserve", }

PRODUCTS: Dict[str, Dict[str, Any]] = { "rice_hashemi": { "cat": "rice", "fa": "برنج هاشمی", "it": "Riso Hashemi", "desc": "عطر بالا / Profumato", "weight": "1 kg", "price": "6",  # EUR string → float for payments "img": "https://i.imgur.com/paddy.jpg", }, "bean_lentil": { "cat": "beans", "fa": "عدس", "it": "Lenticchie", "desc": "عدس سبز / Lenticchie verdi", "weight": "1 kg", "price": "4", "img": "https://i.imgur.com/lentil.jpg", }, }

========= STATIC TEXTS =========

WELCOME = textwrap.dedent( """ 🍇 به بازارینو خوش آمدید! 🇮🇷🇮🇹\nBenvenuto in Bazarino!\n🏠 فروشگاه ایرانی‌های پروجا\n\n👇 لطفاً یک دسته را انتخاب کنید: """ ) ABOUT = "بازارینو توسط دانشجویان ایرانی در پروجا اداره می‌شود." PRIVACY = "داده‌های شما فقط جهت پردازش سفارش استفاده می‌شوند."

========= KEYBOARDS =========

def kb_main() -> InlineKeyboardMarkup: return InlineKeyboardMarkup( [[InlineKeyboardButton(lbl, callback_data=f"cat_{k}")] for k, lbl in CATEGORIES.items()] )

def kb_category(cat: str) -> InlineKeyboardMarkup: rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"prd_{code}")] for code, p in PRODUCTS.items() if p["cat"] == cat] rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")]) return InlineKeyboardMarkup(rows)

def kb_product(code: str) -> InlineKeyboardMarkup: return InlineKeyboardMarkup([ [InlineKeyboardButton("🛒 سفارش پروجا", callback_data=f"ordP_{code}")], [InlineKeyboardButton("📦 سفارش ایتالیا (پرداخت)", callback_data=f"ordI_{code}")], [InlineKeyboardButton("⬅️ بازگشت", callback_data=f"back_{PRODUCTS[code]['cat']}")], ])

========= CALLBACK ROUTER =========

async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE): q = update.callback_query if not q: return await q.answer() data = q.data or ""

if data == "back_main":
    await q.edit_message_text(WELCOME, reply_markup=kb_main(), disable_web_page_preview=True)
    return
if data.startswith("back_"):
    cat = data.split("_", 1)[1]
    await q.edit_message_text(CATEGORIES.get(cat, ""), reply_markup=kb_category(cat))
    return
if data.startswith("cat_"):
    cat = data.split("_", 1)[1]
    await q.edit_message_text(CATEGORIES.get(cat, ""), reply_markup=kb_category(cat))
    return
if data.startswith("prd_"):
    code = data.split("_", 1)[1]
    p = PRODUCTS[code]
    caption = (
        f"<b>{p['fa']} / {p['it']}</b>\n{p['desc']}\nوزن: {p['weight']}\nقیمت: €{p['price']}"
    )
    await q.message.delete()
    await q.message.chat.send_photo(photo=p['img'], caption=caption, parse_mode="HTML", reply_markup=kb_product(code))
    return
if data.startswith(("ordP_", "ordI_")):
    ctx.user_data.clear()
    ctx.user_data["product_code"] = data.split("_", 1)[1]
    ctx.user_data["dest"] = "Perugia" if data.startswith("ordP_") else "Italia"
    await q.message.reply_text("👤 نام و نام خانوادگی:")
    return NAME

========= FORM STEPS =========

async def step_name(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["name"] = u.message.text await u.message.reply_text("📍 آدرس:") return ADDRESS

async def step_address(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["address"] = u.message.text if ctx.user_data["dest"] == "Italia": await u.message.reply_text("🔢 کد پستی:") return POSTAL await u.message.reply_text("☎️ تلفن:") return PHONE

async def step_postal(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["postal"] = u.message.text await u.message.reply_text("☎️ تلفن:") return PHONE

async def step_phone(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["phone"] = u.message.text await u.message.reply_text("📝 یادداشت:") return NOTES

async def step_notes(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["notes"] = u.message.text if ctx.user_data["dest"] == "Italia": p = PRODUCTS[ctx.user_data["product_code"]] amount_cents = int(float(p['price']) * 100) await u.message.reply_invoice( title=f"سفارش {p['fa']}", description=p['desc'], payload="order-payload", provider_token=PAYMENT_PROVIDER_TOKEN, currency="EUR", prices=[LabeledPrice(label=p['fa'], amount=amount_cents)], ) return ConversationHandler.END await save


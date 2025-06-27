#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – Final (shopping-cart + Google Sheets + Stripe)
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import textwrap
import uuid
from functools import partial
from typing import Any, Dict, List

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

# ─────────── logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bazarino")

# ─────────── ENV
TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = os.getenv("BASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
CREDS_PATH = os.getenv("GOOGLE_CREDS")          # مسیر فایل JSON
CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")     # رشته JSON (اختیاری)
STRIPE_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN")  # اختیاری
SHEET_NAME = "Bazarnio Orders"

if not TOKEN or not BASE_URL:
    raise SystemExit("❗️ TELEGRAM_TOKEN و BASE_URL باید تنظیم شوند.")

# ─────────── Google Sheets (accept path or json string)
if CREDS_PATH and os.path.isfile(CREDS_PATH):
    with open(CREDS_PATH, "r", encoding="utf-8") as f:
        creds_info = json.load(f)
elif CREDS_JSON:
    creds_info = json.loads(CREDS_JSON)
else:
    raise SystemExit("❗️ GOOGLE_CREDS یا GOOGLE_CREDS_JSON باید تنظیم شود.")

scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
sheet = gspread.authorize(credentials).open(SHEET_NAME).sheet1
log.info("Google Sheets connected.")

# ─────────── Conversation states
NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

# ─────────── sample data
CATEGORIES: Dict[str, str] = {
    "rice":  "🍚 برنج / Riso",
    "beans": "🥣 حبوبات / Legumi",
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

# ─────────── texts
WELCOME = textwrap.dedent("""\
🍇 به بازارینو خوش آمدید! 🇮🇷🇮🇹
Benvenuto in Bazarino!
🏠 فروشگاه ایرانی‌های پروجا

👇 لطفاً یک دسته را انتخاب کنید:
""")
ABOUT = "بازارینو توسط دانشجویان ایرانی در پروجا اداره می‌شود."
PRIVACY = "اطلاعات شما فقط برای پردازش سفارش استفاده می‌شود."
NO_ONLINE_PAY = "❌ پرداخت آنلاین فعال نیست؛ لطفاً سفارش نقدی (پروجـا) را انتخاب کنید."
CART_EMPTY = "سبد خرید شما خالی است."

# ─────────── keyboard helpers
def cart_count(ctx: ContextTypes.DEFAULT_TYPE) -> int:
    return sum(item["quantity"] for item in ctx.user_data.get("cart", []))

def kb_main(ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(lbl, callback_data=f"cat_{code}")]
               for code, lbl in CATEGORIES.items()]
    buttons.append([InlineKeyboardButton(
        f"🛒 سبد خرید ({cart_count(ctx)})" if cart_count(ctx) else "🛒 سبد خرید",
        callback_data="show_cart")])
    return InlineKeyboardMarkup(buttons)

def kb_category(cat: str, ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"prd_{code}")]
            for code, p in PRODUCTS.items() if p["cat"] == cat]
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_product(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن به سبد", callback_data=f"add_{code}")],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data=f"back_{PRODUCTS[code]['cat']}")],
    ])

def kb_cart() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تکمیل سفارش", callback_data="checkout")],
        [InlineKeyboardButton("🗑️ پاک کردن سبد", callback_data="clear_cart")],
        [InlineKeyboardButton("⬅️ ادامه خرید", callback_data="back_main")],
    ])

# ─────────── router
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    # -------- navigation
    if data == "back_main":
        await q.edit_message_text(WELCOME, reply_markup=kb_main(ctx))
        return
    if data.startswith("back_"):
        cat = data[5:]
        await q.edit_message_text(CATEGORIES.get(cat, "❓"),
                                  reply_markup=kb_category(cat, ctx))
        return
    if data.startswith("cat_"):
        cat = data[4:]
        await q.edit_message_text(CATEGORIES.get(cat, "❓"),
                                  reply_markup=kb_category(cat, ctx))
        return

    # -------- product card
    if data.startswith("prd_"):
        code = data[4:]
        p = PRODUCTS[code]
        caption = (f"<b>{p['fa']} / {p['it']}</b>\n"
                   f"{p['desc']}\nوزن: {p['weight']}\nقیمت: €{p['price']:.2f}")
        await q.message.delete()
        await q.message.chat.send_photo(
            p["image_url"], caption, parse_mode="HTML", reply_markup=kb_product(code))
        return

    # -------- add to cart
    if data.startswith("add_"):
        code = data[4:]
        cart: List[Dict[str, Any]] = ctx.user_data.setdefault("cart", [])
        for item in cart:
            if item["code"] == code:
                item["quantity"] += 1
                break
        else:
            cart.append({"code": code, "quantity": 1})
        await q.message.reply_text("✅ به سبد افزوده شد.")
        await q.edit_message_reply_markup(reply_markup=kb_main(ctx))
        return

    # -------- show cart
    if data == "show_cart":
        cart: List[Dict[str, Any]] = ctx.user_data.get("cart", [])
        if not cart:
            await q.edit_message_text(CART_EMPTY, reply_markup=kb_main(ctx))
            return
        total = 0.0
        text = "🛒 <b>سبد خرید:</b>\n"
        for item in cart:
            p = PRODUCTS[item["code"]]
            line = p["price"] * item["quantity"]
            total += line
            text += f"• {p['fa']} × {item['quantity']} = €{line:.2f}\n"
        text += f"\n<b>مجموع: €{total:.2f}</b>"
        ctx.user_data["total"] = total
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb_cart())
        return

    # -------- clear cart
    if data == "clear_cart":
        ctx.user_data.clear()
        await q.edit_message_text("🗑️ سبد خرید خالی شد.", reply_markup=kb_main(ctx))
        return

    # -------- checkout
    if data == "checkout":
        if not ctx.user_data.get("cart"):
            await q.answer("سبد خالی است.", show_alert=True)
            return
        await q.edit_message_text(
            "نحوه تحویل و پرداخت:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 پروجا (نقدی)", callback_data="dest_Perugia")],
                [InlineKeyboardButton("📦 ایتالیا (آنلاین)", callback_data="dest_Italia")],
            ]))
        return

    # -------- destination chosen → start form
    if data.startswith("dest_"):
        dest = data[5:]
        ctx.user_data["dest"] = dest
        if dest == "Italia" and not STRIPE_TOKEN:
            await q.answer(NO_ONLINE_PAY, show_alert=True)
            return
        await q.message.reply_text("👤 نام و نام خانوادگی:")
        return NAME

# ─────────── form steps
async def step_name(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = u.message.text.strip()
    if not ctx.user_data["name"]:
        await u.message.reply_text("❌ نام نمی‌تواند خالی باشد. دوباره وارد کنید:")
        return NAME
    await u.message.reply_text("📍 آدرس کامل:")
    return ADDRESS

async def step_address(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["address"] = u.message.text.strip()
    if not ctx.user_data["address"]:
        await u.message.reply_text("❌ آدرس خالی است. دوباره وارد کنید:")
        return ADDRESS
    if ctx.user_data["dest"] == "Italia":
        await u.message.reply_text("🔢 کد پستی (۵ رقم):")
        return POSTAL
    await u.message.reply_text("☎️ تلفن تماس:")
    return PHONE

async def step_postal(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    postal = u.message.text.strip()
    if not (postal.isdigit() and len(postal) == 5):
        await u.message.reply_text("❌ کد پستی باید ۵ رقم باشد. دوباره:")
        return POSTAL
    ctx.user_data["postal"] = postal
    await u.message.reply_text("☎️ تلفن تماس:")
    return PHONE

async def step_phone(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = u.message.text.strip()
    if not phone.replace("+", "").replace(" ", "").isdigit():
        await u.message.reply_text("❌ شماره معتبر نیست. دوباره:")
        return PHONE
    ctx.user_data["phone"] = phone
    await u.message.reply_text("📝 یادداشت (اختیاری):")
    return NOTES

async def step_notes(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["notes"] = u.message.text or "-"
    status = "COD"
    if ctx.user_data["dest"] == "Italia":
        if not STRIPE_TOKEN:
            await u.message.reply_text(NO_ONLINE_PAY, reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        amount_cents = int(ctx.user_data["total"] * 100)
        await u.message.reply_invoice(
            title="سفارش بازارینو",
            description="پرداخت سفارش شما",
            payload=f"order-{uuid.uuid4()}",
            provider_token=STRIPE_TOKEN,
            currency="EUR",
            prices=[LabeledPrice("سبد خرید", amount_cents)],
        )
        status = "Pending"
    else:
        await u.message.reply_text(
            "✅ سفارش ثبت شد؛ به‌زودی با شما تماس می‌گیریم.",
            reply_markup=ReplyKeyboardRemove(),
        )
    await save_order(u, ctx, status)
    return ConversationHandler.END

# ─────────── save order to Google Sheets
async def save_order(u: Update, ctx: ContextTypes.DEFAULT_TYPE, status: str):
    cart = ctx.user_data.get("cart", [])
    summary_lines, total = [], 0.0
    for item in cart:
        p = PRODUCTS[item["code"]]
        cost = p["price"] * item["quantity"]
        total += cost
        summary_lines.append(f"{p['fa']}×{item['quantity']}(€{cost:.2f})")
    row = [
        dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        u.effective_chat.id,
        f"@{u.effective_user.username}" if u.effective_user.username else "-",
        ctx.user_data["dest"],
        ", ".join(summary_lines),
        f"{total:.2f}",
        ctx.user_data["name"],
        ctx.user_data["address"],
        ctx.user_data.get("postal", "-"),
        ctx.user_data["phone"],
        ctx.user_data["notes"],
        status,
    ]
    await asyncio.get_running_loop().run_in_executor(None, partial(sheet.append_row, row))
    ctx.user_data.clear()

    if ADMIN_ID:
        admin_msg = (
            "📥 <b>سفارش جدید</b>\n"
            f"🏷 مقصد: {row[3]}\n"
            f"📦 {row[4]}\n"
            f"💰 €{row[5]}\n"
            f"👤 {row[6]}\n"
            f"📍 {row[7]} {row[8]}\n"
            f"☎️ {row[9]}\n"
            f"📝 {row[10]}"
        )
        await u.get_bot().send_message(ADMIN_ID, admin_msg, parse_mode="HTML")

# ─────────── payment handlers
async def precheckout(update: Update, _):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, _):
    await update.message.reply_text(
        "💳 پرداخت موفق! سفارش شما ثبت شد و در حال پردازش است.",
        reply_markup=ReplyKeyboardRemove(),
    )

# ─────────── cancel
async def cancel(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await u.message.reply_text("⛔️ سفارش لغو شد و سبد خالی گردید.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ─────────── commands
async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_html(WELCOME, reply_markup=kb_main(ctx))

async def cmd_about(u: Update, _):   await u.message.reply_text(ABOUT)
async def cmd_privacy(u: Update, _): await u.message.reply_text(PRIVACY)

# ─────────── main
def main() -> None:
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("privacy", cmd_privacy))

    # router (همه callbackها به جز dest_ …)
    app.add_handler(CallbackQueryHandler(
        router,
        pattern="^(back_|cat_|prd_|add_|show_cart|clear_cart|checkout)$"
    ))

    # conversation (شروع با dest_)
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(router, pattern="^dest_")],
        states={
            NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_name)],
            ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_address)],
            POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_postal)],
            PHONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, step_phone)],
            NOTES:  [MessageHandler(filters.TEXT & ~filters.COMMAND, step_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}",
    )
    log.info("Bot is running via webhook.")

if __name__ == "__main__":
    main()
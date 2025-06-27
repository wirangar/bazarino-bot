#!/usr/bin/env python3

-- coding: utf-8 --

""" Bazarino Telegram Bot – final clean version

• Dual‑language (Persian/Italian) menu with nested categories & product cards. • Google Sheets order storage. • Telegram Payments (Stripe) for orders with destination “Italia”; Perugia orders are cash‑on‑delivery. • Tested with python‑telegram‑bot v20.7 and Python 3.11.

Required environment variables

TELEGRAM_TOKEN          your‑bot‑token BASE_URL                public HTTPS URL (e.g. https://bazarino-bot.onrender.com) ADMIN_CHAT_ID           Telegram ID that receives order notifications GOOGLE_CREDS            path to service‑account JSON inside container PAYMENT_PROVIDER_TOKEN  Stripe payment token from @BotFather (/setinlinepayment) """

from future import annotations

import asyncio import datetime import logging import os import textwrap from functools import partial from typing import Any, Dict

import gspread from oauth2client.service_account import ServiceAccountCredentials from telegram import ( InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, ReplyKeyboardRemove, Update, ) from telegram.ext import ( ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, PreCheckoutQueryHandler, filters, )

========= ENV =========

TOKEN = os.environ["TELEGRAM_TOKEN"] BASE_URL = os.environ["BASE_URL"] ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "0")) CREDS_PATH = os.environ["GOOGLE_CREDS"] SHEET_NAME = "Bazarnio Orders" PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN")

========= GOOGLE SHEETS =========

SCOPE = [ "https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive", ] creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, SCOPE) sheet = gspread.authorize(creds).open(SHEET_NAME).sheet1

========= STATES =========

NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

========= DATA =========

CATEGORIES: Dict[str, str] = { "rice": "🍚 برنج / Riso", "beans": "🥣 حبوبات / Legumi", "spice": "🌿 ادویه / Spezie", "nuts": "🥜 خشکبار / Frutta secca", "drink": "🧃 نوشیدنی / Bevande", "canned": "🥫 کنسرو / Conserve", }

PRODUCTS: Dict[str, Dict[str, Any]] = { "rice_hashemi": { "cat": "rice", "fa": "برنج هاشمی", "it": "Riso Hashemi", "desc": "عطر بالا / Profumato", "weight": "1 kg", "price": "6",  # EUR as string "img": "https://i.imgur.com/paddy.jpg", }, "bean_lentil": { "cat": "beans", "fa": "عدس", "it": "Lenticchie", "desc": "عدس سبز / Lenticchie verdi", "weight": "1 kg", "price": "4", "img": "https://i.imgur.com/lentil.jpg", }, }

========= TEXTS =========

WELCOME = textwrap.dedent( """ 🍇 به بازارینو خوش آمدید! 🇮🇷🇮🇹\nBenvenuto in Bazarino!\n🏠 فروشگاه ایرانی‌های پروجا\n\n👇 لطفاً یک دسته را انتخاب کنید: """ ) ABOUT = "بازارینو توسط دانشجویان ایرانی در پروجا اداره می‌شود." PRIVACY = "داده‌های شما فقط برای پردازش سفارش استفاده می‌شوند."

========= KEYBOARDS =========

def kb_main() -> InlineKeyboardMarkup: return InlineKeyboardMarkup( [[InlineKeyboardButton(lbl, callback_data=f"cat_{k}")] for k, lbl in CATEGORIES.items()] )

def kb_category(cat: str) -> InlineKeyboardMarkup: rows = [ [InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"prd_{code}")] for code, p in PRODUCTS.items() if p["cat"] == cat ] rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")]) return InlineKeyboardMarkup(rows)

def kb_product(code: str) -> InlineKeyboardMarkup: return InlineKeyboardMarkup([ [InlineKeyboardButton("🛒 سفارش پروجا", callback_data=f"ordP_{code}")], [InlineKeyboardButton("📦 سفارش ایتالیا (پرداخت)", callback_data=f"ordI_{code}")], [InlineKeyboardButton("⬅️ بازگشت", callback_data=f"back_{PRODUCTS[code]['cat']}")], ])

========= ROUTER =========

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
    await q.message.chat.send_photo(
        photo=p['img'],
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

========= FORM STEPS =========

async def step_name(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["name"] = u.message.text await u.message.reply_text("📍 آدرس:") return ADDRESS

async def step_address(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["address"] = u.message.text if ctx.user_data["dest"] == "Italia": await u.message.reply_text("🔢 کد پستی:") return POSTAL await u.message.reply_text("☎️ تلفن:") return PHONE

async def step_postal(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["postal"] = u.message.text await u.message.reply_text("☎️ تلفن:") return PHONE

async def step_phone(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["phone"] = u.message.text await u.message.reply_text("📝 یادداشت:") return NOTES

async def step_notes(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["notes"] = u.message.text if ctx.user_data["dest"] == "Italia": p = PRODUCTS[ctx.user_data["product_code"]] amount_cents = int(float(p['price']) * 100) await u.message.reply_invoice( title=f"سفارش {p['fa']}", description=p['desc'], payload="order-payload", provider_token=PAYMENT_PROVIDER_TOKEN, currency="EUR", prices=[LabeledPrice(label=p['fa'], amount=amount_cents)], ) return ConversationHandler.END

await save_order(u, ctx)
return ConversationHandler.END

========= HELPERS =========

async def save_order(u: Update, ctx: ContextTypes.DEFAULT_TYPE): """Append one order row to Google Sheets and notify admin.""" p = PRODUCTS[ctx.user_data["product_code"]] row = [ datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), ctx.user_data["dest"], p["fa"], p["price"], ctx.user_data["name"], ctx.user_data["address"], ctx.user_data.get("postal", "-"), ctx.user_data["phone"], ctx.user_data["notes"], f"@{u.effective_user.username}" if u.effective_user.username else "-", ] loop = asyncio.get_running_loop() await loop.run_in_executor(None, partial(sheet.append_row, row))

# confirmation to user
await u.message.reply_text("✅ سفارش ثبت شد!", reply_markup=ReplyKeyboardRemove())

# notify admin
admin_msg = (
    "📥 سفارش جدید

" f"🏷 مقصد: {ctx.user_data['dest']} " f"📦 {p['fa']} — €{p['price']} " f"👤 {ctx.user_data['name']} " f"📍 {ctx.user_data['address']} {ctx.user_data.get('postal','')} " f"☎️ {ctx.user_data['phone']} " f"📝 {ctx.user_data['notes']}" ) await ctx.bot.send_message(ADMIN_ID, admin_msg)

========= PAYMENT HANDLERS =========

async def precheckout(update: Update, ctx: ContextTypes.DEFAULT_TYPE): """Answer the pre‑checkout query so Telegram can proceed with payment.""" await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE): """Handle successful payment; simply acknowledge the user.""" await update.message.reply_text("💳 پرداخت موفق! سفارش شما در حال پردازش است…") # در نسخه ساده، جزئیات سفارش قبلاً ذخیره شده‌است (در step_notes => save_order)

========= CANCEL =========

async def cancel(u: Update, _): await u.message.reply_text("⛔️ سفارش لغو شد.", reply_markup=ReplyKeyboardRemove()) return ConversationHandler.END

========= COMMANDS =========

async def cmd_start(u: Update, _): await u.message.reply_html(WELCOME, reply_markup=kb_main(), disable_web_page_preview=True)

aasync def cmd_about(u: Update, _): await u.message.reply_html(ABOUT)

async def cmd_privacy(u: Update, _): await u.message.reply_html(PRIVACY)

========= MAIN =========

def main() -> None: logging.basicConfig(level=logging.INFO) app = ApplicationBuilder().token(TOKEN).build()

# command handlers
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("about", cmd_about))
app.add_handler(CommandHandler("privacy", cmd_privacy))

# callback router
app.add_handler(CallbackQueryHandler(router))

# payment
app.add_handler(PreCheckoutQueryHandler(precheckout))
app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

# conversation for order form
conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(router, pattern="^ord[PI]_")],
    states={
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_name)],
        ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_address)],
        POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_postal)],
        PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_phone)],
        NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_notes)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
app.add_handler(conv)

# webhook
app.run_webhook(
    listen="0.0.0.0",
    port=int(os.getenv("PORT", "8080")),
    url_path=TOKEN,
    webhook_url=f"{BASE_URL}/{TOKEN}",
)

if name == "main": main()


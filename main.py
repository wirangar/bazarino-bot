# main.py – Bazarnio Bot (PTB-20 + Webhook, Python 3.11)

import os
import datetime
from functools import partial

# ────────── Telegram  &  PTB ──────────
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# ────────── Google Sheets ──────────
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ────────────────────────── پیکربندی محیط ──────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")       # الزامی
ADMIN_CHAT_ID   = int(os.getenv("ADMIN_CHAT_ID", "0"))
SHEET_NAME      = os.getenv("SHEET_NAME", "Bazarnio Orders")

# نشانی بیرونی سرویس؛ در Render پیشنهاد ⇐ متغیّر BASE_URL را دستی ست کنید
BASE_URL = os.getenv("BASE_URL") or f'https://{os.getenv("RENDER_EXTERNAL_HOSTNAME")}'

# فایل JSON سرویس‌اکانت را به‌صورت Secret File در مسیر دلخواه آپلود کن
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS", "/etc/secrets/creds.json")

# ────────── اتصال به شیت گوگل ──────────
scope  = ["https://spreadsheets.google.com/feeds",
          "https://www.googleapis.com/auth/drive"]
creds  = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS, scope)
gc     = gspread.authorize(creds)
sheet  = gc.open(SHEET_NAME).sheet1                 # تب اوّل

# ────────── State numbers برای فرم سفارش ──────────
NAME, ADDRESS, PHONE, PRODUCT, QTY, NOTES = range(6)

# ────────────────────────── هندلرهای دستورها ──────────────────────────
async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    kb = [["🛍 مشاهده منو"],
          ["📝 ثبت سفارش"],
          ["ℹ️ درباره ما", "📞 تماس"]]
    await update.message.reply_html(
        "🍊 خوش آمدی به <b>Bazarnio</b> – طعم ایران در قلب پروجا 🇮🇷🇮🇹\n\n"
        "برای شروع یکی از گزینه‌ها را بزن:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def cmd_about(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("بازارینو – مواد غذایی ایرانی در پروجا 🇮🇷🇮🇹")

async def cmd_contact(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📞 واتساپ: +39 XXXXXXXX\nاینستاگرام: @bazarnio")

async def cmd_menu(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 منو:\n"
        "🍚 برنج و حبوبات\n🌿 ادویه و خشکبار\n🍬 تنقلات\n🥖 نان و کنسرو\n🧃 نوشیدنی‌ها"
    )

# ────────────────────────── گفت‌وگوی سفارش ──────────────────────────
async def ask(update: Update, _: ContextTypes.DEFAULT_TYPE, text: str):
    await update.message.reply_text(text)

async def order_start(u, c):   return await ask(u, c, "👤 نام و نام خانوادگی؟")      or NAME
async def order_name(u, c):    c.user_data["name"]=u.message.text; \
                               return await ask(u, c, "🏠 آدرس دقیق در پروجا؟")      or ADDRESS
async def order_addr(u, c):    c.user_data["addr"]=u.message.text; \
                               return await ask(u, c, "📞 شماره تماس؟")             or PHONE
async def order_phone(u, c):   c.user_data["phone"]=u.message.text; \
                               return await ask(u, c, "📦 نام محصول؟")              or PRODUCT
async def order_prod(u, c):    c.user_data["prod"]=u.message.text; \
                               return await ask(u, c, "🔢 تعداد؟")                  or QTY
async def order_qty(u, c):     c.user_data["qty"]=u.message.text;  \
                               return await ask(u, c, "📝 توضیح (ندارم)؟")          or NOTES

async def order_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["notes"] = update.message.text
    user = update.effective_user

    # ردیفی که در شیت ذخیره می‌کنیم
    row = [
        datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        context.user_data["name"],
        context.user_data["addr"],
        context.user_data["phone"],
        context.user_data["prod"],
        context.user_data["qty"],
        context.user_data["notes"],
        f"@{user.username}" if user.username else "-"
    ]
    sheet.append_row(row)

    await update.message.reply_text("✅ سفارش ثبت شد! به‌زودی تماس می‌گیریم.")

    if ADMIN_CHAT_ID:
        msg = (
            "📥 سفارش جدید:\n\n"
            f"👤 {row[1]}\n📍 {row[2]}\n📞 {row[3]}\n"
            f"📦 {row[4]} × {row[5]}\n📝 {row[6]}\n🔗 {row[7]}"
        )
        await context.bot.send_message(ADMIN_CHAT_ID, msg)

    return ConversationHandler.END

async def order_cancel(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⛔️ سفارش لغو شد.")
    return ConversationHandler.END

# ────────────────────────── fallback برای پیام‌های متنیِ نامشخّص ──────────────────────────
async def echo_unknown(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("متوجه نشدم. یکی از دکمه‌ها را بزن یا /start را ارسال کن.")

# ────────────────────────── اجرای برنامه ──────────────────────────
def main() -> None:
    if not TELEGRAM_TOKEN or not BASE_URL:
        raise RuntimeError("TELEGRAM_TOKEN یا BASE_URL تنظیم نشده‌اند!")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # فرمان‌های ثابت
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(MessageHandler(filters.Regex("^🛍"), cmd_menu))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️"), cmd_about))
    app.add_handler(MessageHandler(filters.Regex("^📞"), cmd_contact))

    # مکالمهٔ سفارش
    order_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝"), order_start)],
        states={
            NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, order_name)],
            ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND, order_addr)],
            PHONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            PRODUCT:[MessageHandler(filters.TEXT & ~filters.COMMAND, order_prod)],
            QTY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, order_qty)],
            NOTES:  [MessageHandler(filters.TEXT & ~filters.COMMAND, order_notes)],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
    )
    app.add_handler(order_conv)

    # پیام‌های متنیِ بی‌هدف
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_unknown))

    # ───── Webhook
    port = int(os.getenv("PORT", "8080"))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TELEGRAM_TOKEN,                # همان مسیری که تلگرام POST می‌کند
        webhook_url=f"{BASE_URL}/{TELEGRAM_TOKEN}",
        allowed_updates=Update.ALL_TYPES,
    )

# ──────────────────────────
if __name__ == "__main__":
    main()

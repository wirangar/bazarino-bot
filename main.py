import os
import json
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ───── تنظیمات پایه و لاگ‌ها ─────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ───── محیط ─────
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_NAME = "Bazarnio Orders"  # ← اسم Google Sheet شما

# ───── Google Sheets ─────
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    "/etc/secrets/bazarino-perugia-bot-f37c44dd9b14.json",  # ← دقیقاً اسم Secret File
    scope,
)
sheet = gspread.authorize(creds).open(SHEET_NAME).sheet1


# ───── دستور /start ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"سلام {user.first_name} 👋\n"
        f"به ربات خرید محصولات ایرانی در پروجا خوش اومدی!\n"
        f"برای ثبت سفارش، لطفاً محصول مورد نظرت رو تایپ کن."
    )


# ───── دستور /order ─────
async def order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = " ".join(context.args)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    if not msg:
        await update.message.reply_text("❗ لطفاً بعد از /order متن سفارشت رو بنویس.")
        return

    # ذخیره در Google Sheets
    sheet.append_row([timestamp, user.username, user.id, msg])

    await update.message.reply_text("✅ سفارشت ثبت شد. به زودی باهات تماس می‌گیریم.")
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"🛒 سفارش جدید:\n{msg}")


# ───── اجرا ─────
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("order", order))
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        webhook_url=f"https://bazarino-bot.onrender.com/{TELEGRAM_TOKEN}"
    )

import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 📌 فعال‌سازی لاگ‌ها
logging.basicConfig(level=logging.INFO)

# 📌 مقادیر محیطی
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# 📌 تنظیمات Google Sheet
SHEET_NAME = "Bazarnio Orders"
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    "/etc/secrets/bazarino-perugia-bot-f37c44dd9b14.json", scope
)
client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1

# 🔸 دستور شروع
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! برای سفارش، لطفاً پیام خود را به این صورت وارد کنید:\n\nنام، آدرس، شماره تماس، محصول، تعداد، توضیحات")

# 🔸 ثبت سفارش از هر پیام معمولی
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.message.from_user

    try:
        data = text.split("،")
        if len(data) < 6:
            await update.message.reply_text("فرمت درست نیست. لطفاً ۶ بخش را با ویرگول فارسی جدا کنید.")
            return

        name, address, phone, product, quantity, notes = [x.strip() for x in data]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        username = user.username if user.username else "بدون یوزرنیم"

        row = [timestamp, name, address, phone, product, quantity, notes, username]
        sheet.append_row(row)
        await update.message.reply_text("✅ سفارش با موفقیت ثبت شد!")

        # به ادمین هم پیام بده
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"📥 سفارش جدید:\n\n{text}")

    except Exception as e:
        await update.message.reply_text("⛔ مشکلی در ثبت سفارش پیش آمد.")
        logging.error(f"Error: {e}")

# 🔧 اجرای برنامه
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

if __name__ == "__main__":
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        webhook_url=f"https://bazarino-bot.onrender.com/{TELEGRAM_TOKEN}"
    )

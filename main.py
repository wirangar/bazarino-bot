# main.py – Bazarnio Bot (PTB-20, Render Webhook)

import os
import random
import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    CommandHandler, MessageHandler, ConversationHandler, filters,
)

import gspread
from oauth2client.service_account import ServiceAccountCredentials


# ────── متغیرهای محیطی ──────
TOKEN           = os.environ["TELEGRAM_TOKEN"]
ADMIN_CHAT_ID   = int(os.getenv("ADMIN_CHAT_ID", "0"))
BASE_URL        = os.environ["BASE_URL"]                    # https://bazarino-bot.onrender.com
CREDS_PATH      = os.environ["GOOGLE_CREDS"]               # ‎/etc/secrets/…‎
SHEET_NAME      = os.getenv("SHEET_NAME", "Bazarnio Orders")
PORT            = int(os.getenv("PORT", 10000))

# ────── اتصال به Google Sheets ──────
scope  = ["https://spreadsheets.google.com/feeds",
          "https://www.googleapis.com/auth/drive"]
creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
sheet  = gspread.authorize(creds).open(SHEET_NAME).sheet1

# ────── استیت‌های فرم سفارش ──────
NAME, ADDRESS, PHONE, PRODUCT, QTY, NOTES = range(6)

# ────── شعارها (چرخشی) ──────
TAGLINES = [
    "Bazarnio – طعم ایران در قلب پروجا",
    "بازار ایرانی‌ها، همین‌جا!",
    "Everyday Persia. Delivered.",
    "طعم خونه، با یک کلیک",
    "Iranian Taste, Italian Life",
    "Tradizione Persiana, ogni giorno",
    "Dall’Iran a casa tua",
    "Iran. A portata di click.",
    "Un piccolo Iran, nel cuore d’Italia",
]

# ───────── پیام شروع ─────────
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    tagline = random.choice(TAGLINES)
    kb = [["🛍 مشاهده منو"], ["📝 ثبت سفارش"], ["ℹ️ درباره ما", "📞 تماس"]]

    welcome = (
        f"🍊 <b>{tagline}</b>\n\n"
        "خوش آمدی! این‌جا می‌تونی محصولات اصیل ایرانی رو سفارش بدی و درب منزل تحویل بگیری.\n"
        "برای شروع یکی از گزینه‌ها رو انتخاب کن:"
    )
    await u.message.reply_html(welcome, reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

# ───────── سایر هندلرها ─────────
async def about(u, _):    await u.message.reply_text("بازارینو – پلی بین ایران و ایتالیا 🇮🇷🇮🇹")
async def contact(u, _):  await u.message.reply_text("📞 واتساپ: +39 …\nاینستاگرام: @bazarnio")
async def menu(u, _):     await u.message.reply_text(
    "📋 دسته‌بندی محصولات:\n"
    "🍚 برنج و حبوبات\n🌿 ادویه و خشکبار\n🍬 تنقلات\n🥖 نان و کنسرو\n🧃 نوشیدنی‌ها"
)

async def start_order(u, _):              await u.message.reply_text("👤 نام و نام خانوادگی:");           return NAME
async def get_name(u, c):    c.user_data["name"]=u.message.text;     await u.message.reply_text("🏠 آدرس دقیق در پروجا:"); return ADDRESS
async def get_address(u, c): c.user_data["address"]=u.message.text;  await u.message.reply_text("📞 شماره تماس:");       return PHONE
async def get_phone(u, c):   c.user_data["phone"]=u.message.text;    await u.message.reply_text("📦 نام محصول:");        return PRODUCT
async def get_product(u, c): c.user_data["product"]=u.message.text;  await u.message.reply_text("🔢 تعداد:");             return QTY
async def get_qty(u, c):     c.user_data["quantity"]=u.message.text; await u.message.reply_text("📝 توضیح (یا «ندارم»):"); return NOTES

async def get_notes(u, c):
    c.user_data["notes"]=u.message.text
    row = [
        datetime.datetime.utcnow().isoformat(timespec="seconds"),
        c.user_data["name"], c.user_data["address"], c.user_data["phone"],
        c.user_data["product"], c.user_data["quantity"], c.user_data["notes"],
        f"@{u.effective_user.username}" if u.effective_user.username else "-"
    ]
    try: sheet.append_row(row)
    except Exception as e: print("Google Sheets error:", e)

    await u.message.reply_text("✅ سفارش ثبت شد! به‌زودی تماس می‌گیریم.")

    if ADMIN_CHAT_ID:
        admin_msg = (
            "📥 سفارش جدید:\n\n"
            f"👤 {row[1]}\n📍 {row[2]}\n📞 {row[3]}\n"
            f"📦 {row[4]} × {row[5]}\n📝 {row[6]}\n🔗 {row[7]}"
        )
        await c.bot.send_message(ADMIN_CHAT_ID, admin_msg)

    return ConversationHandler.END

async def cancel(u,_): await u.message.reply_text("⛔️ سفارش لغو شد."); return ConversationHandler.END

# ───────── اجرا با وبهوک ─────────
def main() -> None:
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🛍"), menu))
    app.add_handler(MessageHandler(filters.Regex("^ℹ"), about))
    app.add_handler(MessageHandler(filters.Regex("^📞"), contact))

    order_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝"), start_order)],
        states={
            NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ADDRESS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            PHONE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            PRODUCT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product)],
            QTY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_qty)],
            NOTES:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(order_conv)

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}",
        allowed_updates=Update.ALL_TYPES,
    )

if __name__ == "__main__":
    main()

# main.py  –  Bazarnio Telegram Bot  (PTB-20 + webhook)   Python 3.11
import os, datetime, random, asyncio
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes,
    CommandHandler, MessageHandler, ConversationHandler, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ─────────────── متغیرهای محیطی ────────────────
TOKEN       = os.environ["TELEGRAM_TOKEN"]
BASE_URL    = os.environ["BASE_URL"]                 # https://bazarino-bot.onrender.com
ADMIN_ID    = int(os.environ["ADMIN_CHAT_ID"])
CREDS_PATH  = os.environ["GOOGLE_CREDS"]             # /etc/secrets/....json
SHEET_NAME  = "Bazarnio Orders"

# ─────────────── Google Sheets ────────────────
scope  = ["https://spreadsheets.google.com/feeds",
          "https://www.googleapis.com/auth/drive"]
creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
sheet  = gspread.authorize(creds).open(SHEET_NAME).sheet1

# ─────────────── استیت‌های فرم سفارش ───────────
NAME, ADDRESS, PHONE, PRODUCT, QTY, NOTES = range(6)

# ─────────────── پیام خوش‌آمد ───────────────
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

async def start(u: Update, _: ContextTypes.DEFAULT_TYPE):
    welcome = (
    f"🍇 <b>به بازارینو خوش آمدید!</b> 🇮🇷🇮🇹\n\n"
    "🏠 فروشگاه آنلاین محصولات ایرانی در قلب پروجا – با طعم اصیل ایران، هر روز!\n\n"
    "📦 <b>چی کار می‌کنیم؟</b>\n"
    "• ارسال خشکبار، برنج، ادویه و نوشیدنی‌های ایرانی 🍚🌿🧃\n"
    "• ثبت سفارش آسان با چند کلیک 📝\n"
    "• تحویل سریع درب منزل 🚚\n\n"
    "🌟 <i>شعار ما:</i>\n"
    "«Bazarnio – طعم ایران در قلب پروجا»\n"
    "«بازار ایرانی‌ها، همین‌جا!»\n"
    "«Everyday Persia. Delivered.»\n"
    "«طعم خونه، با یک کلیک»\n"
    "«Un piccolo Iran, nel cuore d’Italia»\n\n"
    "👇 یکی از گزینه‌ها رو انتخاب کن:"
)

    kb = [["🛍 مشاهده منو"],
          ["📝 ثبت سفارش"],
          ["ℹ️ درباره‌ ما", "📞 تماس"]]
    await u.message.reply_html(welcome, reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

# ─────────────── صفحات ثابت ────────────────
async def about(u, _):   await u.message.reply_text("بازارینو – طعم خونه با کیفیت اصیل 🇮🇷🇮🇹")
async def contact(u, _): await u.message.reply_text("📞 واتساپ: +39 …  |  اینستاگرام: @bazarnio")
async def menu(u, _):    await u.message.reply_text("🍚 برنج و حبوبات\n🌿 ادویه و خشکبار\n🍬 تنقلات\n🥖 نان و کنسرو\n🧃 نوشیدنی‌ها")

# ─────────────── فرم سفارش ────────────────
async def start_order(u, _):
    await u.message.reply_text("👤 نام و نام خانوادگی:")
    return NAME

async def get_name(u, c):
    c.user_data["name"] = u.message.text
    await u.message.reply_text("🏠 آدرس دقیق در پروجا:")
    return ADDRESS

async def get_address(u, c):
    c.user_data["address"] = u.message.text
    await u.message.reply_text("📞 شماره تماس:")
    return PHONE

async def get_phone(u, c):
    c.user_data["phone"] = u.message.text
    await u.message.reply_text("📦 نام محصول:")
    return PRODUCT

async def get_product(u, c):
    c.user_data["product"] = u.message.text
    await u.message.reply_text("🔢 تعداد:")
    return QTY

async def get_qty(u, c):
    c.user_data["qty"] = u.message.text
    await u.message.reply_text("📝 توضیح (یا بنویسید «ندارم»):")
    return NOTES

async def get_notes(u, c):
    c.user_data["notes"] = u.message.text
    row = [
        datetime.datetime.utcnow().isoformat(sep=" ", timespec="seconds"),
        *(c.user_data.get(k) for k in ("name", "address", "phone", "product", "qty", "notes")),
        f"@{u.effective_user.username}" if u.effective_user.username else "-"
    ]
    # ذخیره در شیت
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sheet.append_row, row)

    await u.message.reply_text("✅ سفارش ثبت شد! در اسرع وقت با شما تماس می‌گیریم.")

    admin_msg = (
        "📥 <b>سفارش جدید</b>\n\n"
        f"👤 {row[1]}\n📍 {row[2]}\n📞 {row[3]}\n"
        f"📦 {row[4]} × {row[5]}\n📝 {row[6]}\n🔗 {row[7]}"
    )
    await c.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
    return ConversationHandler.END

async def cancel(u, _):
    await u.message.reply_text("⛔️ سفارش لغو شد.")
    return ConversationHandler.END

# ─────────────── اجرا با وبهوک ────────────────
def build_app() -> Application:
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
    return app

if __name__ == "__main__":
    build_app().run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}",
        allowed_updates=Update.ALL_TYPES,
    )

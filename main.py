# main.py  –  Bazarino Telegram Bot (PTB-20 + webhook) – Render Deployment
import os, datetime, asyncio
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes,
    CommandHandler, MessageHandler, ConversationHandler, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ─────────────── ENVIRONMENT CONFIG ───────────────
TOKEN       = os.environ["TELEGRAM_TOKEN"]
BASE_URL    = os.environ["BASE_URL"]                 # Example: https://bazarino-bot.onrender.com
ADMIN_ID    = int(os.environ["ADMIN_CHAT_ID"])
CREDS_PATH  = os.environ["CREDS_PATH"]               # Example: /etc/secrets/creds.json
SHEET_NAME  = "Bazarnio Orders"

# ─────────────── GOOGLE SHEETS INIT ───────────────
scope  = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
sheet  = gspread.authorize(creds).open(SHEET_NAME).sheet1

# ─────────────── ORDER FORM STATES ───────────────
NAME, ADDRESS, PHONE, PRODUCT, QTY, NOTES = range(6)

# ─────────────── WELCOME MESSAGE ───────────────
WELCOME_TXT = (
    "🍇 <b>به بازارینو خوش آمدید!</b> 🇮🇷🇮🇹\n\n"
    "🏠 فروشگاه آنلاین محصولات ایرانی در قلب پروجا – با طعم اصیل ایران، هر روز!\n\n"
    "📦 <b>چی کار می‌کنیم؟</b>\n"
    "• ارسال خشکبار، برنج، ادویه و نوشیدنی‌های ایرانی 🍚🌿🧃\n"
    "• ثبت سفارش آسان با چند کلیک 📝\n"
    "• تحویل سریع درب منزل 🚚\n\n"
    "🌟 <i>شعار ما:</i>\n"
    "«Bazarnio – طعم ایران در قلب پروجا»\n"
    "«بازار ایرانی‌ها، همین‌جا!»\n"
    "«Everyday Persia. Delivered.»\n"
    "«Un piccolo Iran, nel cuore d’Italia»\n\n"
    "👇 یکی از گزینه‌ها را انتخاب کنید:"
)

# ─────────────── ABOUT MESSAGE ───────────────
ABOUT_TXT = (
    "📜 خط‌مشی حریم خصوصی – بازارینو\n"
    "Privacy Policy – Bazarino\n\n"
    "🔍 چه داده‌هایی جمع‌آوری می‌کنیم؟ / Quali dati raccogliamo?\n"
    "• 👤 نام و نام خانوادگی / Nome e cognome\n"
    "• 📍 آدرس و ☎️ شماره تماس در ایتالیا / Indirizzo e telefono in Italia\n"
    "• 🛒 جزئیات سفارش (محصول، تعداد، یادداشت) / Dettagli ordine (prodotto, quantità, note)\n\n"
    "🎯 فقط برای پردازش و ارسال سفارش استفاده می‌شود.\n"
    "Usati solo per elaborare e consegnare l’ordine.\n\n"
    "🤝 اطلاعات با هیچ شخص یا شرکت ثالثی به اشتراک گذاشته نمی‌شود.\n"
    "Nessuna condivisione con terze parti.\n\n"
    "🗑 هر زمان خواستید با @BazarinoSupport تماس بگیرید تا در ≤۴۸ساعت حذف شود.\n"
    "Per la cancellazione dei dati → @BazarinoSupport (entro 48h).\n\n"
    "🛡 بازارینو متعهد به حفظ امنیت داده‌هاست.\n"
    "Bazarino protegge i tuoi dati con la massima sicurezza."
)

# ─────────────── HANDLERS ───────────────
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    kb = [["🛍 منو"], ["📝 ثبت سفارش"], ["ℹ️ درباره‌ ما / Info"]]
    await update.message.reply_html(WELCOME_TXT, reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def about(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_TXT)

async def menu(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛒 دسته‌بندی محصولات:\n" "• برنج و غلات\n• ادویه و خشکبار\n• نوشیدنی و تنقلات\n• نان و کنسرو")

# ─────────────── ORDER FLOW ───────────────
async def start_order(update: Update, _):
    await update.message.reply_text("👤 لطفاً نام و نام خانوادگی خود را وارد کنید:")
    return NAME

async def get_name(update: Update, context):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("🏠 آدرس کامل خود در پروجا را وارد کنید:")
    return ADDRESS

async def get_address(update: Update, context):
    context.user_data["address"] = update.message.text
    await update.message.reply_text("📞 شماره تماس:")
    return PHONE

async def get_phone(update: Update, context):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("📦 نام محصول مورد نظر:")
    return PRODUCT

async def get_product(update: Update, context):
    context.user_data["product"] = update.message.text
    await update.message.reply_text("🔢 تعداد:")
    return QTY

async def get_qty(update: Update, context):
    context.user_data["qty"] = update.message.text
    await update.message.reply_text("📝 یادداشت یا توضیح خاصی دارید؟ (اگر ندارید بنویسید 'ندارم')")
    return NOTES

async def get_notes(update: Update, context):
    context.user_data["notes"] = update.message.text
    row = [
        datetime.datetime.utcnow().isoformat(sep=" ", timespec="seconds"),
        *(context.user_data.get(k) for k in ("name", "address", "phone", "product", "qty", "notes")),
        f"@{update.effective_user.username}" if update.effective_user.username else "-"
    ]
    # Write to Google Sheet
    await asyncio.get_running_loop().run_in_executor(None, sheet.append_row, row)

    await update.message.reply_text("✅ سفارش شما ثبت شد. در اسرع وقت تماس می‌گیریم.")

    admin_msg = (
        "📥 <b>سفارش جدید ثبت شد</b>\n\n"
        f"👤 {row[1]}\n📍 {row[2]}\n📞 {row[3]}\n"
        f"📦 {row[4]} × {row[5]}\n📝 {row[6]}\n🔗 {row[7]}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
    except Exception as e:
        print("Admin notify failed:", e)

    return ConversationHandler.END

async def cancel(update: Update, _):
    await update.message.reply_text("⛔️ سفارش لغو شد.")
    return ConversationHandler.END

# ─────────────── RUN APP ───────────────
def build_app() -> Application:
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🛍"), menu))
    app.add_handler(MessageHandler(filters.Regex("^ℹ"), about))

    conv = ConversationHandler(
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
    app.add_handler(conv)
    return app

if __name__ == "__main__":
    build_app().run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}",
        allowed_updates=Update.ALL_TYPES,
    )

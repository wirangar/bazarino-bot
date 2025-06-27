# main.py – Bazarnio Telegram Bot (Render-ready)
# Python 3.11 – python-telegram-bot 20.x
# -------------------------------------------------
"""
ویژگی‌های کلیدی
--------------
• می‌خوانَد از GOOGLE_CREDS (بدون خطای CREDS_PATH)
• پیام‌های دوزبانه (فارسی 🇮🇷 + ایتالیایی 🇮🇹)
• منوی نمایشی دو-سطحی (دسته → لیست کالا)
• ثبت سفارش در Google Sheets + اعلان به مدیر
• سازگار با Render (وبهوک روی پورت 8080)
"""

import os, datetime, asyncio, random
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, Application, ContextTypes,
    CommandHandler, MessageHandler, ConversationHandler, filters,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# ─────────────── ENV ───────────────
TOKEN      = os.environ["TELEGRAM_TOKEN"]
BASE_URL   = os.environ["BASE_URL"]                # ex: https://bazarino-bot.onrender.com
ADMIN_ID   = int(os.environ["ADMIN_CHAT_ID"])
CREDS_PATH = os.environ["GOOGLE_CREDS"]            # secret-file path in Render
SHEET_NAME = "Bazarnio Orders"


# ─────────────── Google Sheets ───────────────
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
sheet = gspread.authorize(creds).open(SHEET_NAME).sheet1


# ─────────────── Conversation states ───────────────
NAME, ADDRESS, PHONE, PRODUCT, QTY, NOTES = range(6)


# ─────────────── ثابت‌های متنی (FA | IT) ───────────────
TAGLINES = [
    "Bazarnio – طعم ایران در قلب پروجا",
    "بازار ایرانی‌ها، همین‌جا!",
    "Everyday Persia. Delivered.",
    "طعم خونه، با یک کلیک",
]

ABOUT_TXT = (
    "بازارینو – طعم اصیل ایران، در قلب ایتالیا 🇮🇷🇮🇹\n"
    "Bazarino – Il gusto autentico dell’Iran, nel cuore dell’Italia 🇮🇹🇮🇷"
)

CONTACT_TXT = (
    "📞 واتساپ: +39 …  |  اینستاگرام: @bazarino\n"
    "WhatsApp: +39 …  |  Instagram: @bazarino"
)

# فقط برای نمایش لیست دسته‌ها – سفارش همچنان دستی است
CATEGORIES = {
    "🍚 برنج":      ["برنج هاشمی", "برنج طارم", "برنج دودی"],
    "🌿 ادویه":     ["زعفران", "زردچوبه", "دارچین"],
    "🍬 تنقلات":    ["گز", "سوهان", "پسته شور"],
    "🥖 نان":       ["نان بربری", "نان لواش"],
    "🧃 نوشیدنی":   ["دوغ", "دلستر", "شربت زعفران"],
}


# ─────────────── Handlers ───────────────
async def start(update: Update, _):
    tag = random.choice(TAGLINES)
    msg = (
        "🍇 <b>به بازارینو خوش آمدید!</b> 🇮🇷🇮🇹\n"
        "Benvenuto/a su <b>Bazarino</b>! 🇮🇹🇮🇷\n\n"
        "🏠 فروشگاه آنلاین محصولات ایرانی در پروجا\n"
        "Negozio online di prodotti persiani a Perugia\n\n"
        "📦 ارسال سریع | پرداخت هنگام تحویل\n"
        "Consegna veloce | Pagamento alla consegna\n\n"
        f"<i>{tag}</i>\n\n"
        "👇 یکی از گزینه‌ها / Scegli un’opzione:"
    )
    kb = [
        ["🛍 منو / Menu"],
        ["📝 ثبت سفارش / Ordina"],
        ["ℹ️ درباره‌ ما / Info", "📞 تماس / Contatto"],
    ]
    await update.message.reply_html(msg, reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))


async def about(update: Update, _):
    await update.message.reply_text(ABOUT_TXT)


async def contact(update: Update, _):
    await update.message.reply_text(CONTACT_TXT)


# منوی دسته‌ها (فقط نمایش)
async def menu_handler(update: Update, _):
    fa_lines = "\n".join(CATEGORIES.keys())
    it_lines = "\n".join([k.split()[1] for k in CATEGORIES])
    await update.message.reply_text(
        f"{fa_lines}\n\n{it_lines}\n\n"
        "برای سفارش / Per ordinare → دکمهٔ «📝»"
    )


# ─────────────── Order flow ───────────────
async def start_order(update: Update, _):
    await update.message.reply_text("👤 نام و نام خانوادگی / Nome e cognome:")
    return NAME


async def get_name(update, context):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("🏠 آدرس کامل / Indirizzo:")
    return ADDRESS


async def get_address(update, context):
    context.user_data["address"] = update.message.text
    await update.message.reply_text("📞 شماره تماس / Telefono:")
    return PHONE


async def get_phone(update, context):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("📦 نام محصول / Prodotto:")
    return PRODUCT


async def get_product(update, context):
    context.user_data["product"] = update.message.text
    await update.message.reply_text("🔢 تعداد / Quantità:")
    return QTY


async def get_qty(update, context):
    context.user_data["qty"] = update.message.text
    await update.message.reply_text("📝 توضیح (یا «ندارم») / Note (o 'nessuna'):")
    return NOTES


async def get_notes(update, context):
    context.user_data["notes"] = update.message.text

    # ذخیره در Sheet
    row = [
        datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        context.user_data["name"],
        context.user_data["address"],
        context.user_data["phone"],
        context.user_data["product"],
        context.user_data["qty"],
        context.user_data["notes"],
        f"@{update.effective_user.username}" if update.effective_user.username else "-",
    ]
    await asyncio.get_running_loop().run_in_executor(None, sheet.append_row, row)

    await update.message.reply_text("✅ سفارش ثبت شد! / Ordine ricevuto! Grazie.")

    # اعلان مدیر
    admin_msg = (
        "📥 <b>سفارش جدید / Nuovo ordine</b>\n\n"
        f"👤 {row[1]}\n📍 {row[2]}\n📞 {row[3]}\n"
        f"📦 {row[4]} × {row[5]}\n📝 {row[6]}\n🔗 {row[7]}"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
    return ConversationHandler.END


async def cancel(update, _):
    await update.message.reply_text(
        "⛔️ سفارش لغو شد / Operazione annullata",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ─────────────── Build & Run ───────────────
def build_app() -> Application:
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🛍"), menu_handler))
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

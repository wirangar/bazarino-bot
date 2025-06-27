# main.py – Bazarnio Bot  (Python-Telegram-Bot 20.x)   Python 3.11
import os, json, datetime, asyncio, random, tempfile
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, Application, ContextTypes,
    CommandHandler, MessageHandler, ConversationHandler, filters
)

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ────────────── ENV ──────────────
TOKEN      = os.environ["TELEGRAM_TOKEN"]
BASE_URL   = os.environ["BASE_URL"]                 # e.g. https://bazarino-bot.onrender.com
ADMIN_ID   = int(os.environ["ADMIN_CHAT_ID"])
CREDS_PATH = os.environ["CREDS_PATH"]               # /etc/secrets/creds.json
SHEET_NAME = "Bazarnio Orders"

# ────────────── Google Sheets ──────────────
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
sheet = gspread.authorize(creds).open(SHEET_NAME).sheet1

# ────────────── States ──────────────
(DELIVERY_ZONE, NAME, ADDRESS, ZIP, PHONE,
 PRODUCT, QTY, NOTES) = range(8)
(MainMenu, CatChoice, SubChoice) = range(8, 11)   # برای منو

# ────────────── ثابت‌ها ──────────────
TAGLINES = [
    "Bazarnio – طعم ایران در قلب پروجا",
    "Everyday Persia. Delivered.",
    "بازار ایرانی‌ها، همین‌جا!",
    "Un piccolo Iran, nel cuore d’Italia",
]

MAIN_KB = [["🛍 منو / Menu"], ["📝 سفارش / Ordina"], ["ℹ️ درباره / Info", "📞 تماس / Contatto"]]

CATEGORIES = {
    "برنج / Riso": ["هاشمی", "طارم", "دودی", "↩️ بازگشت"],
    "حبوبات / Legumi": ["لوبیا", "عدس", "نخود", "↩️ بازگشت"],
    "ادویه / Spezie": ["زعفران", "زرچوبه", "زیره", "↩️ بازگشت"],
    "خشکبار / Frutta secca": ["پسته", "بادام", "کشمش", "↩️ بازگشت"],
    "نوشیدنی / Bevande": ["دلستر", "دوغ", "↩️ بازگشت"],
}

# ────────────── Handlers ──────────────
async def start(u: Update, _):
    welcome = (
        f"🍊 <b>{random.choice(TAGLINES)}</b> 🇮🇷🇮🇹\n"
        "🛍 فروشگاه آنلاین محصولات ایرانی در پروجا – تحویل سریع درب منزل.\n\n"
        "👇 یکی از گزینه‌ها را انتخاب کنید:"
    )
    await u.message.reply_html(welcome, reply_markup=ReplyKeyboardMarkup(MAIN_KB, resize_keyboard=True))

async def about(u: Update, _):
    txt = (
        "⚡️ ما چند دانشجوی ایرانی در پروجا هستیم که مزهٔ خونه را به شما می‌رسانیم؛ "
        "کیفیت اصیل، قیمت منصفانه و تحویل سریع!\n\n"
        "Giovani studenti persiani a Perugia che portano i sapori di casa direttamente a te. "
        "Qualità autentica, prezzi onesti e consegna rapida!"
    )
    await u.message.reply_text(txt)

async def contact(u: Update, _):
    await u.message.reply_text("📞 WhatsApp: +39 …  |  Instagram: @bazarino")

# ────────────── ① منوی دسته‌ها و زیرمنو ──────────────
async def menu_entry(u: Update, _):
    cats = [[k] for k in CATEGORIES]
    cats.append(["↩️ بازگشت / Back"])
    await u.message.reply_text("🍱 دسته را انتخاب کنید:", reply_markup=ReplyKeyboardMarkup(cats, resize_keyboard=True))
    return CatChoice

async def category_chosen(u: Update, c: ContextTypes.DEFAULT_TYPE):
    choice = u.message.text
    if choice.startswith("↩️"):
        await u.message.reply_text("بازگشت به منوی اصلی.", reply_markup=ReplyKeyboardMarkup(MAIN_KB, resize_keyboard=True))
        return ConversationHandler.END

    if choice in CATEGORIES:
        c.user_data["category"] = choice
        items = [[i] for i in CATEGORIES[choice]]
        await u.message.reply_text("🛒 محصول را انتخاب کنید:", reply_markup=ReplyKeyboardMarkup(items, resize_keyboard=True))
        return SubChoice
    await u.message.reply_text("گزینه نامعتبر؛ دوباره انتخاب کنید.")
    return CatChoice

async def product_from_menu(u: Update, c: ContextTypes.DEFAULT_TYPE):
    item = u.message.text
    if item.startswith("↩️"):
        return await menu_entry(u, c)
    c.user_data["product"] = item
    await u.message.reply_text("🔢 تعداد:", reply_markup=ReplyKeyboardRemove())
    return QTY

# ────────────── ② فرم سفارش ──────────────
async def order_entry(u: Update, _):
    kb = [["📍 داخل پروجا", "🚚 سایر شهرها"]]
    await u.message.reply_text("محل تحویل را انتخاب کنید:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return DELIVERY_ZONE

async def zone_chosen(u, c):
    c.user_data["zone"] = u.message.text
    await u.message.reply_text("👤 نام و نام خانوادگی:", reply_markup=ReplyKeyboardRemove())
    return NAME

async def get_name(u, c):
    c.user_data["name"] = u.message.text
    await u.message.reply_text("🏠 آدرس کامل:")
    return ADDRESS

async def get_address(u, c):
    c.user_data["address"] = u.message.text
    if c.user_data["zone"].startswith("🚚"):
        await u.message.reply_text("🔢 کد پستی (CAP):")
        return ZIP
    await u.message.reply_text("📞 شماره تماس:")
    return PHONE

async def get_zip(u, c):
    c.user_data["zip"] = u.message.text
    await u.message.reply_text("📞 شماره تماس:")
    return PHONE

async def get_phone(u, c):
    c.user_data["phone"] = u.message.text
    await u.message.reply_text("🛒 نام محصول یا «/menu» برای لیست:")
    return PRODUCT

async def direct_product(u, c):
    c.user_data["product"] = u.message.text
    await u.message.reply_text("🔢 تعداد:")
    return QTY

async def qty_receive(u, c):
    c.user_data["qty"] = u.message.text
    await u.message.reply_text("📝 توضیح (یا «ندارم»):")
    return NOTES

async def finish_order(u, c):
    c.user_data["notes"] = u.message.text
    user = u.effective_user
    row = [
        datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        c.user_data.get("zone"),
        c.user_data.get("name"),
        c.user_data.get("address"),
        c.user_data.get("zip", "-"),
        c.user_data.get("phone"),
        c.user_data.get("product"),
        c.user_data.get("qty"),
        c.user_data.get("notes"),
        f"@{user.username}" if user.username else "-",
    ]
    await asyncio.get_running_loop().run_in_executor(None, sheet.append_row, row)
    order_id = sheet.row_count
    await u.message.reply_text(f"✅ سفارش شما ثبت شد!\nکد سفارش: #{order_id}")

    admin_msg = (
        f"📥 <b>سفارش #{order_id}</b>\n\n"
        f"{row[2]}  |  {row[5]}\n"
        f"{row[3]} ({row[4]})\n"
        f"📦 {row[6]} × {row[7]}\n"
        f"📝 {row[8]}\n{row[9]}"
    )
    try:
        await c.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
    except Exception as e:
        print("Admin notify failed:", e)
    return ConversationHandler.END

async def cancel(u, _):
    await u.message.reply_text("⛔️ سفارش لغو شد.", reply_markup=ReplyKeyboardMarkup(MAIN_KB, resize_keyboard=True))
    return ConversationHandler.END

# ────────────── Build App ──────────────
def build_app() -> Application:
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^ℹ"), about))
    app.add_handler(MessageHandler(filters.Regex("^📞"), contact))

    # منو و زیرمنو
    menu_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛍"), menu_entry)],
        states={
            CatChoice: [MessageHandler(filters.TEXT & ~filters.COMMAND, category_chosen)],
            SubChoice: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_from_menu)],
            QTY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, qty_receive)],
            NOTES:     [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_order)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        map_to_parent={ConversationHandler.END: ConversationHandler.END},
    )
    app.add_handler(menu_conv)

    # سفارش مستقیم
    order_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝"), order_entry)],
        states={
            DELIVERY_ZONE: [MessageHandler(filters.TEXT, zone_chosen)],
            NAME:          [MessageHandler(filters.TEXT, get_name)],
            ADDRESS:       [MessageHandler(filters.TEXT, get_address)],
            ZIP:           [MessageHandler(filters.TEXT, get_zip)],
            PHONE:         [MessageHandler(filters.TEXT, get_phone)],
            PRODUCT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, direct_product)],
            QTY:           [MessageHandler(filters.TEXT & ~filters.COMMAND, qty_receive)],
            NOTES:         [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_order)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(order_conv)

    return app

# ────────────── Webhook for Render ──────────────
if __name__ == "__main__":
    build_app().run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}",
        allowed_updates=Update.ALL_TYPES,
    )

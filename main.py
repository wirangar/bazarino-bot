# main.py  –  Bazarnio Telegram Bot  (PTB-20 + webhook)   Python 3.11
import os, datetime, asyncio, random
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, Application, ContextTypes,
    CommandHandler, MessageHandler, ConversationHandler, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ──────────────── تنظیمات محیط ─────────────────
TOKEN      = os.environ["TELEGRAM_TOKEN"]
BASE_URL   = os.environ["BASE_URL"]
ADMIN_ID   = int(os.environ["ADMIN_CHAT_ID"])
CREDS_PATH = os.environ["CREDS_PATH"]
SHEET_NAME = "Bazarnio Orders"

# ──────────────── Google Sheets ────────────────
scope  = ["https://spreadsheets.google.com/feeds",
          "https://www.googleapis.com/auth/drive"]
creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
sheet  = gspread.authorize(creds).open(SHEET_NAME).sheet1

# ─────────────── استیت‌ها ───────────────
(
    CHOICE,          # انتخاب منو اصلی
    CATEGORY, ITEM,  # منو و زیرمنو
    MARKET,          # انتخاب نوع سفارش
    NAME, ADDRESS, CAP, PHONE, PRODUCT, QTY, NOTES
) = range(11)

# ─────────────── داده‌های منو ───────────────
MENU = {
    "RISO": {
        "برنج هاشمی / Hashemi": "Riso Hashemi",
        "برنج طارم / Tarom":    "Riso Tarom",
        "برنج دودی / Affumicato": "Riso Affumicato",
    },
    "LEGUMI": {
        "لوبیا / Fagioli": "Fagioli",
        "عدس / Lenticchie": "Lenticchie",
        "نخود / Ceci":     "Ceci",
    },
    "SPEZIE": {
        "زعفران / Zafferano": "Zafferano",
        "زرچوبه / Curcuma":   "Curcuma",
        "نعناع خشک / Menta secca": "Menta secca",
        "سبزی خشک آش / Mix erbe secche": "Mix erbe",
    },
    "SNACK": {
        "خرما / Datteri": "Datteri",
        "بادام / Mandorle": "Mandorle",
        "گردو / Noci":      "Noci",
    },
    "BIBITE": {
        "دوغ معمولی / Doogh": "Doogh",
        "دوغ محلی / Doogh artig.": "Doogh art.",
        "نوشابه ایرانی / Cola IR": "Cola IR",
    },
    "PANE": {
        "نان لواش / Lavash": "Lavash",
        "نان تافتون / Taftoon": "Taftoon",
        "کنسرو قورمه / Ghorme can": "Ghorme can",
    },
}

CAT_BUTTONS = {
    "RISO":   "🍚 برنج و غلات / Riso e Cereali",
    "LEGUMI": "🥦 حبوبات / Legumi",
    "SPEZIE": "🌿 ادویه و خشکبار / Spezie & Frutta secca",
    "SNACK":  "🍬 تنقلات / Snack",
    "BIBITE": "🧃 نوشیدنی‌ها / Bibite",
    "PANE":   "🥖 نان و کنسرو / Pane & Conserve",
}

TAGLINES = [
    "Bazarnio – طعم ایران در قلب پروجا",
    "بازار ایرانی‌ها، همین‌جا!",
    "Everyday Persia. Delivered.",
    "طعم خونه، با یک کلیک",
    "Un piccolo Iran, nel cuore d’Italia",
]

# ─────────────── helper keyboards ─────────────
def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["🛍 مشاهده منو / Mostra menu"],
            ["📝 ثبت سفارش / Ordina"],
            ["ℹ️ درباره‌ ما / Info", "📞 تماس / Contatto"],
        ], resize_keyboard=True
    )

def category_keyboard() -> ReplyKeyboardMarkup:
    rows = [[CAT_BUTTONS[k]] for k in CAT_BUTTONS]
    rows.append(["🔙 بازگشت / Indietro"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def items_keyboard(cat_key: str) -> ReplyKeyboardMarkup:
    rows = [[item] for item in MENU[cat_key]]
    rows.append(["🔙 بازگشت / Indietro"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def order_type_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["📝 سفارش پروجا / Ordina a Perugia"],
            ["📦 سفارش سایر شهرها / Ordina in Italia"],
            ["🔙 بازگشت / Indietro"],
        ], resize_keyboard=True
    )

# ─────────────── handlers ───────────────
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    msg = (
        f"🍊 <b>{random.choice(TAGLINES)}</b>\n\n"
        "🇮🇷 محصولات ایرانی، 🇮🇹 به خانه شما!\n"
        "👇 یکی از گزینه‌ها را انتخاب کنید / Scegli un’opzione:"
    )
    await update.message.reply_html(msg, reply_markup=main_keyboard())
    return CHOICE

# ---------- ثابت‌ها ----------
async def about(update: Update, _):
    txt = (
        "بازارینو – فروشگاه آنلاین ایرانیان پروجا 🇮🇷🇮🇹\n"
        "Bazarino – Emporio persiano a Perugia 🇮🇷🇮🇹"
    )
    await update.message.reply_text(txt)

async def contact(update: Update, _):
    await update.message.reply_text(
        "واتساپ/WhatsApp: +39 …\nاینستاگرام/Instagram: @bazarino"
    )

# ---------- منوی اصلی ----------
async def choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t.startswith("🛍"):
        await update.message.reply_text(
            "🔻 دسته‌بندی را انتخاب کنید / Scegli la categoria:",
            reply_markup=category_keyboard())
        return CATEGORY
    elif t.startswith("📝"):
        await update.message.reply_text(
            "📍 نوع سفارش را مشخص کنید / Scegli il tipo di ordine:",
            reply_markup=order_type_keyboard())
        return MARKET
    else:
        return CHOICE

# ---------- دسته‌بندی ----------
async def category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if txt.startswith("🔙"):
        await update.message.reply_text("↩️", reply_markup=main_keyboard())
        return CHOICE
    # پیدا کردن کلید
    for key, label in CAT_BUTTONS.items():
        if txt == label:
            context.user_data["cat"] = key
            await update.message.reply_text(
                "🔻 محصول را انتخاب کنید / Scegli il prodotto:",
                reply_markup=items_keyboard(key))
            return ITEM
    return CATEGORY

# ---------- آیتم ----------
async def item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if txt.startswith("🔙"):
        return await category(update, context)
    cat = context.user_data["cat"]
    if txt in MENU[cat]:
        context.user_data["product"] = txt
        await update.message.reply_text(
            "❗ برای ثبت سفارش به منوی «📝» بروید / Vai su «📝» per ordinare.",
            reply_markup=main_keyboard())
        return CHOICE
    return ITEM

# ---------- انتخاب نوع سفارش ----------
async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t.startswith("🔙"):
        await update.message.reply_text("↩️", reply_markup=main_keyboard())
        return CHOICE
    if "پروجا" in t or "Perugia" in t:
        context.user_data["scope"] = "PERUGIA"
    else:
        context.user_data["scope"] = "ITALY"
    await update.message.reply_text("👤 نام و نام خانوادگی / Nome e cognome:")
    return NAME

# ---------- فرم سفارش ----------
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("🏠 آدرس / Indirizzo:")
    return ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text
    if context.user_data["scope"] == "ITALY":
        await update.message.reply_text("🔢 کد پستی / CAP:")
        return CAP
    await update.message.reply_text("☎️ شماره تماس / Telefono:")
    return PHONE

async def get_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cap"] = update.message.text
    await update.message.reply_text("☎️ شماره تماس / Telefono:")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    prod = context.user_data.get("product", "—")
    await update.message.reply_text(
        f"📦 محصول (الان: {prod}) / Prodotto (corrente: {prod}):")
    return PRODUCT

async def get_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["product"] = update.message.text
    await update.message.reply_text("🔢 تعداد / Quantità:")
    return QTY

async def get_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["qty"] = update.message.text
    await update.message.reply_text("📝 یادداشت / Note (یا «ندارم»):")
    return NOTES

async def get_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["notes"] = update.message.text
    user = update.effective_user
    data = context.user_data
    row = [
        datetime.datetime.utcnow().isoformat(" ", "seconds"),
        data["name"], data["address"],
        data.get("cap", "-"),
        data["phone"], data["product"],
        data["qty"], data["notes"],
        f"@{user.username}" if user.username else "-"
    ]
    # ذخیره در شیت
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sheet.append_row, row)

    # پیام کاربر
    await update.message.reply_text(
        "✅ سفارش ثبت شد / Ordine registrato!",
        reply_markup=main_keyboard())

    # پیام مدیر
    admin_msg = (
        "📥 <b>سفارش جدید / Nuovo ordine</b>\n\n"
        f"👤 {row[1]}\n📍 {row[2]} {row[3]}\n☎️ {row[4]}\n"
        f"📦 {row[5]} × {row[6]}\n📝 {row[7]}\n🔗 {row[8]}"
    )
    await context.bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML")
    return CHOICE

async def cancel(update: Update, _):
    await update.message.reply_text("⛔️ لغو شد / Annullato.",
                                    reply_markup=main_keyboard())
    return CHOICE

# ─────────────── main ───────────────
def build_app() -> Application:
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.ALL, start)],
        states={
            CHOICE:    [MessageHandler(filters.TEXT, choice)],
            CATEGORY:  [MessageHandler(filters.TEXT, category)],
            ITEM:      [MessageHandler(filters.TEXT, item)],
            MARKET:    [MessageHandler(filters.TEXT, market)],
            NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ADDRESS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            CAP:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_cap)],
            PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            PRODUCT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product)],
            QTY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_qty)],
            NOTES:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
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

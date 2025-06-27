# main.py – Bazarino Telegram Bot  (PTB-20)  Python 3.11
"""
نسخهٔ کامل با ویژگی‌های:
• منوی دو سطحی (دسته → کالا) + توضیح، تصویر و دکمهٔ سفارش (پروجا / بقیهٔ ایتالیا)
• فرم سفارش کامل (نام، آدرس، CAP اگر خارج پروجا، تلفن، یادداشت) + پیام خلاصه به کاربر و مدیر
• منوی همیشگی Bot Commands
• گوگل‌شیت + متغیّر محیطی GOOGLE_CREDS
• دو زبانه فارسی 🇮🇷 / ایتالیایی 🇮🇹
"""
import os, datetime, asyncio, logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove,
    BotCommand, InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder, Application, ContextTypes,
    CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, filters,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

TOKEN       = os.environ["TELEGRAM_TOKEN"]
BASE_URL    = os.environ["BASE_URL"]
ADMIN_ID    = int(os.environ["ADMIN_CHAT_ID"])
CREDS_PATH  = os.environ["GOOGLE_CREDS"]
SHEET_NAME  = "Bazarnio Orders"

scope  = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
sheet  = gspread.authorize(creds).open(SHEET_NAME).sheet1

# ───── states
NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

# ───── product data (code ➜ dict)
PRODUCTS = {
    "rice_hashemi": {
        "label": "برنج هاشمی / Riso Hashemi",
        "desc":  "برنج ممتاز گیلان، عطر بالا • Riso aromatico della Gilan",
        "weight": "10 kg",
        "price":  "€38",
        "img":    "https://i.imgur.com/6k2nqf8.jpg",
    },
    "rice_tarem": {
        "label": "برنج طارم / Riso Tarom",
        "desc":  "محصول مازندران، قدبلند • Chicchi lunghi, Mazandaran",
        "weight": "10 kg", "price": "€34", "img": "https://i.imgur.com/7hX5z1C.jpg",
    },
    "bean_lentil": {"label": "عدس / Lenticchie", "desc": "عدس سبز ایرانی", "weight": "1 kg", "price": "€4", "img": "https://i.imgur.com/IbWhVtI.jpg"},
    # … بقیهٔ محصولات مشابه
}

CATEGORIES = {
    "rice":  ("🍚 برنج و غلات / Riso & Cereali", ["rice_hashemi", "rice_tarem"]),
    "beans": ("🥣 حبوبات / Legumi",             ["bean_lentil"]),
    # ادامهٔ دسته‌ها مطابق قبلی
}

# ───── keyboards

def main_menu():
    rows = [[InlineKeyboardButton(title, callback_data=f"cat_{key}")] for key, (title, _) in CATEGORIES.items()]
    rows.append([InlineKeyboardButton("ℹ️ درباره ما / Info", callback_data="about")])
    rows.append([InlineKeyboardButton("📞 پشتیبانی / Support", url="https://t.me/BazarinoSupport")])
    return InlineKeyboardMarkup(rows)

def items_kb(cat_key):
    codes = CATEGORIES[cat_key][1]
    rows = [
        [InlineKeyboardButton(PRODUCTS[c]["label"], callback_data=f"prd_{c}")]
        for c in codes
    ]
    rows.append([InlineKeyboardButton("⬅️ بازگشت / Indietro", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def order_kb(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 سفارش پروجا / Ordina a Perugia", callback_data=f"ordP_{code}")],
        [InlineKeyboardButton("📦 سفارش ایتالیا / Ordina in Italia",  callback_data=f"ordI_{code}")],
        [InlineKeyboardButton("⬅️ بازگشت / Indietro", callback_data="back_cat")],
    ])

# ───── command menu once
BOT_CMDS = [
    BotCommand("start", "منو / Menu"),
    BotCommand("privacy", "سیاست حریم خصوصی / Privacy"),
]

# ───── handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.set_my_commands(BOT_CMDS)
    text = (
        "🍇 <b>به بازارینو خوش آمدید!</b> / Benvenuto su <b>Bazarino</b>!\n"
        "🇮🇷 طعم خانه در 🇮🇹 ایتالیا\n\n"
        "👇 دسته‌بندی را انتخاب کنید / Scegli una categoria:"
    )
    if update.message:
        await update.message.reply_html(text, reply_markup=main_menu())
    else:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu(), parse_mode="HTML")

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = q.data

    if data == "about":
        await q.edit_message_text("بازارینو – فروشگاه ایرانیان پروجا 🇮🇷🇮🇹\nBazarino – Emporio persiano a Perugia")
        return
    if data == "back_main":
        await start(update, context); return

    if data.startswith("cat_"):
        key = data[4:]
        await q.edit_message_text(CATEGORIES[key][0], reply_markup=items_kb(key))
        context.user_data["cat"] = key
        return

    if data == "back_cat":
        key = context.user_data.get("cat")
        await q.edit_message_text(CATEGORIES[key][0], reply_markup=items_kb(key)); return

    if data.startswith("prd_"):
        code = data[4:]
        p = PRODUCTS[code]
        cap = f"<b>{p['label']}</b>\n{p['desc']}\nوزن/Peso: {p['weight']}\n💶 قیمت/Prezzo: {p['price']}"
        await q.message.delete()
        await context.bot.send_photo(q.message.chat_id, p["img"], caption=cap, parse_mode="HTML", reply_markup=order_kb(code))
        return

    # شروع سفارش
    if data.startswith("ordP_") or data.startswith("ordI_"):
        dest = "PERUGIA" if data.startswith("ordP_") else "ITALY"
        code = data[5:]
        context.user_data.update({"dest": dest, "code": code})
        await q.message.reply_text("👤 نام و نام خانوادگی / Nome e cognome:")
        return NAME

# ───── order flow
async def name_h(update: Update, context):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("🏠 آدرس / Indirizzo:")
    return ADDRESS

async def addr_h(update: Update, context):
    context.user_data["addr"] = update.message.text
    if context.user_data["dest"] == "ITALY":
        await update.message.reply_text("🔢 کد پستی / CAP:")
        return POSTAL
    await update.message.reply_text("☎️ تلفن / Telefono:")
    return PHONE

async def cap_h(update: Update, context):
    context.user_data["cap"] = update.message.text
    await update.message.reply_text("☎️ تلفن / Telefono:")
    return PHONE

async def phone_h(update: Update, context):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("📝 یادداشت / Note (یا بنویسید «ندارم»):")
    return NOTES

async def notes_h(update: Update, context):
    context.user_data["notes"] = update.message.text
    u = update.effective_user
    p = PRODUCTS[context.user_data["code"]]
    row = [
        datetime.datetime.utcnow().isoformat(" ", "seconds"),
        context.user_data["name"], context.user_data["addr"], context.user_data.get("cap", "-"),
        context.user_data["phone"], p["label"], p["price"], context.user_data["notes"],
        f"@{u.username}" if u.username else "-",
    ]
    await asyncio.get_running_loop().run_in_executor(None, sheet.append_row, row)

    summary = (
        "✅ سفارش ثبت شد!\n"
        f"👤 {row[1]}\n📍 {row[2]} {row[3]}\n☎️ {row[4]}\n"
        f"📦 {row[5]} – {p['price']}\n📝 {row[7]}"
    )
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت به منو / Menu", callback_data="back_main")]]))

    admin_msg = (
        "📥 <b>سفارش جدید</b>\n\n" + summary.replace("✅ سفارش ثبت شد!\n", ""))
    await context.bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML")
    return ConversationHandler.END

async def cancel(update: Update, _):
    await update.message.reply_text("⛔️ لغو شد / Annullato", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ───── main ─────
logging.basicConfig(level=logging.INFO)
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("privacy", lambda u, c: u.message.reply_html("<pre>privacy…</pre>")))
app.add_handler(CallbackQueryHandler(menu_router))
order_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(menu_router, pattern=r"^ord[PI]_")],
    states={
        NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, name_h)],
        ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND, addr_h)],
        POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, cap_h)],
        PHONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_h)],
        NOTES:  [MessageHandler(filters.TEXT & ~filters.COMMAND, notes_h)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
app.add_handler(order_conv)

app.run_webhook(
    listen="0.0.0.0", port=int(os.getenv("PORT", 8080)), url_path=TOKEN,
    webhook_url=f"{BASE_URL}/{TOKEN}", allowed_updates=Update.ALL_TYPES,
)

# main.py – Bazarino Telegram Bot (python‑telegram‑bot v20)  Python 3.11
"""
نسخهٔ تکمیل‌‎شده مطابق درخواست نهایی
────────────────────────────────────────
● منوی اصلی → دسته‌ ها → کالا ها (عکس + توضیح + وزن + قیمت)
● دکمه‌های «🛒 سفارش پروجا» و «📦 سفارش ایتالیا» در صفحهٔ کالا
● فرم سفارش کامل (نام، آدرس، CAP اگر لازم، تلفن، یادداشت)
● خلاصهٔ سفارش برای کاربر و مدیر + ذخیره در Google Sheets
●_COMMAND Menu همیشگی: /start (menu) /about /privacy
● دو زبانهٔ کامل فارسی 🇮🇷 و ایتالیایی 🇮🇹
● استفاده از متغیّر محیطی GOOGLE_CREDS (بدون ارور)
"""
import os, datetime, asyncio, logging, textwrap
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, InputMediaPhoto, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, Application, ContextTypes,
    CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ─────────────── تنظیمات محیط ───────────────
TOKEN       = os.environ["TELEGRAM_TOKEN"]
BASE_URL    = os.environ["BASE_URL"]            # ‎https://bazarino-bot.onrender.com
ADMIN_ID    = int(os.environ["ADMIN_CHAT_ID"])
CREDS_PATH  = os.environ["GOOGLE_CREDS"]        # ‎/etc/secrets/…json
SHEET_NAME  = "Bazarnio Orders"

# ─────────────── Google Sheets ───────────────
scope  = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
sheet  = gspread.authorize(creds).open(SHEET_NAME).sheet1

# ─────────────── فرم سفارش ───────────────
NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

# ─────────────── دیتای کالاها ───────────────
PRODUCTS = {
    "rice_hashemi": dict(
        label="برنج هاشمی / Riso Hashemi",
        desc ="برنج ممتاز گیلان، عطر زیاد • Riso aromatico della Gilan",
        weight="10 kg", price="€38", img="https://i.imgur.com/6k2nqf8.jpg"),
    "rice_tarem": dict(
        label="برنج طارم / Riso Tarom",
        desc ="قد بلند مازندران • Chicchi lunghi, Mazandaran",
        weight="10 kg", price="€34", img="https://i.imgur.com/7hX5z1C.jpg"),
    "rice_smoke": dict(
        label="برنج دودی / Riso Affumicato",
        desc ="دودی سنتی • Affumicatura tradizionale",
        weight="10 kg", price="€40", img="https://i.imgur.com/2Slx1Ab.jpg"),
    "bean_lentil": dict(label="عدس / Lenticchie", desc="عدس سبز ایرانی", weight="1 kg", price="€4", img="https://i.imgur.com/IbWhVtI.jpg"),
    "bean_lobio": dict(label="لوبیا / Fagioli",   desc="لوبیای قرمز", weight="1 kg", price="€4", img="https://i.imgur.com/P5B2aOQ.jpg"),
    "bean_chick": dict(label="نخود / Ceci",        desc="نخود درشت کرمانشاه", weight="1 kg", price="€4", img="https://i.imgur.com/8a4hPH2.jpg"),
    # … بقیهٔ محصولات را می‌توان مانند بالا افزود
}

CATEGORIES = {
    "rice":  ("🍚 برنج و غلات / Riso & Cereali",  ["rice_hashemi", "rice_tarem", "rice_smoke"]),
    "beans": ("🥣 حبوبات / Legumi",               ["bean_lentil", "bean_lobio", "bean_chick"]),
    # spice / nuts / drink / canned به‌دلخواه همانند بالا اضافه شود
}

# ─────────────── پیام‌های ثابت ───────────────
WELCOME = textwrap.dedent("""
    🍇 <b>به بازارینو خوش آمدید!</b> 🇮🇷🇮🇹
    Benvenuto in <b>Bazarino</b>!

    🏠 فروشگاه آنلاین محصولات ایرانی در پروجا – طعم اصیل ایران هر روز!
    Il mini‑market persiano nel cuore di Perugia.

    👇 دسته‌بندی را انتخاب کنید / Scegli una categoria:
""")
ABOUT = "بازارینو – طعم خانه در قلب ایتالیا 🇮🇷🇮🇹\nBazarino – Sapori persiani a Perugia"

# ─────────────── ساخت کیبوردها ───────────────

def kb_main() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(title, callback_data=f"cat_{key}")] for key, (title, _) in CATEGORIES.items()]
    rows.append([InlineKeyboardButton("ℹ️ درباره ما / Info", callback_data="about")])
    rows.append([InlineKeyboardButton("📞 پشتیبانی / Support", url="https://t.me/BazarinoSupport")])
    return InlineKeyboardMarkup(rows)

def kb_items(cat_key: str) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(PRODUCTS[c]["label"], callback_data=f"prd_{c}")]
               for c in CATEGORIES[cat_key][1]]
    buttons.append([InlineKeyboardButton("⬅️ بازگشت / Indietro", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

def kb_buy(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 سفارش پروجا / Ordina a Perugia", callback_data=f"buyP_{code}")],
        [InlineKeyboardButton("📦 سفارش ایتالیا / Ordina in Italia",  callback_data=f"buyI_{code}")],
        [InlineKeyboardButton("⬅️ بازگشت / Indietro", callback_data="back_cat")],
    ])

# ─────────────── handlers ───────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.set_my_commands([
        BotCommand("start", "منو / Menu"),
        BotCommand("about", "درباره ما / Info"),
        BotCommand("privacy", "حریم خصوصی / Privacy"),
    ])
    await update.message.reply_html(WELCOME, reply_markup=kb_main())

async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    d = q.data

    if d == "about":
        await q.answer(); await q.message.reply_html(ABOUT); return
    if d == "back_main":
        await q.edit_message_text("↩️", reply_markup=kb_main()); return

    # نمایش کالاهای دسته
    if d.startswith("cat_"):
        key = d[4:]
        await q.edit_message_text(CATEGORIES[key][0], reply_markup=kb_items(key))
        context.user_data["cat"] = key
        return

    if d == "back_cat":
        key = context.user_data.get("cat")
        await q.edit_message_text(CATEGORIES[key][0], reply_markup=kb_items(key)); return

    # صفحهٔ کالا
    if d.startswith("prd_"):
        code = d[4:]
        p = PRODUCTS[code]
        cap = f"<b>{p['label']}</b>\n{p['desc']}\nوزن/Peso: {p['weight']}\n💶 قیمت/Prezzo: {p['price']}"
        await q.message.delete()
        await context.bot.send_photo(q.message.chat_id, p["img"], caption=cap, parse_mode="HTML", reply_markup=kb_buy(code))
        context.user_data["sel_code"] = code
        return

    # شروع فرم سفارش
    if d.startswith("buyP_") or d.startswith("buyI_"):
        context.user_data["dest"] = "PERUGIA" if d.startswith("buyP_") else "ITALY"
        context.user_data["sel_code"] = d[5:]
        await q.message.reply_text("👤 نام و نام خانوادگی / Nome e cognome:")
        return NAME

# ───── گفتگو سفارش
async def h_name(update: Update, context):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("🏠 آدرس / Indirizzo:")
    return ADDRESS

async def h_address(update: Update, context):
    context.user_data["addr"] = update.message.text
    if context.user_data["dest"] == "ITALY":
        await update.message.reply_text("🔢 کد پستی / CAP:")
        return POSTAL
    await update.message.reply_text("☎️ تلفن / Telefono:")
    return PHONE

async def h_cap(update: Update, context):
    context.user_data["cap"] = update.message.text
    await update.message.reply_text("☎️ تلفن / Telefono:")
    return PHONE

async def h_phone(update: Update, context):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("📝 یادداشت / Note (یا 'ندارم'):")
    return NOTES

async def h_notes(update: Update, context):
    context.user_data["notes"] = update.message.text
    p = PRODUCTS[context.user_data["sel_code"]]
    u = update.effective_user
    row = [
        datetime.datetime.utcnow().isoformat(" ", "seconds"),
        context.user_data["dest"], context.user_data["name"], context.user_data["addr"],
        context.user_data.get("cap", "-"), context.user_data["phone"],
        p["label"], p["price"], context.user_data["notes"],
        f"@{u.username}" if u.username else "-",
    ]
    await asyncio.get_running_loop().run_in_executor(None, sheet.append_row, row)

    summary = (
        "✅ سفارش ثبت شد! / Ordine ricevuto!\n\n"
        f"👤 {row[2]}\n📍 {row[3]} {row[4]}\n☎️ {row[5]}\n" +
        f"📦 {row[6]} – {row[7]}\n📝 {row[8]}"
    )
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو / Menu", callback_data="back_main")]]))

    admin = "📥 <b>سفارش جدید</b>\n\n" + summary.replace("✅ سفارش ثبت شد! / Ordine ricevuto!\n\n", "")
    await context.bot.send_message(ADMIN_ID, admin, parse_mode="HTML")
    return ConversationHandler.END

async def cancel(update: Update, _):
    await update.message.reply_text("⛔️ لغو شد / Annullato", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ───── main ─────
logging.basicConfig(level=logging.INFO)
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("about", lambda u, c: u.message.reply_text(ABOUT)))
app.add_handler(CommandHandler("privacy", lambda u, c: u.message.reply_html("<pre>Privacy…</pre>")))
app.add_handler(CallbackQueryHandler(cb_router))

conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(cb_router, pattern=r"^buy[PI]_")],
    states={
        NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, h_name)],
        ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND, h_address)],
        POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_cap)],
        PHONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, h_phone)],
        NOTES:  [MessageHandler(filters.TEXT & ~filters.COMMAND, h_notes)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
app.add_handler(conv)

app.run_webhook(
    listen="0.0.0.0", port=int(os.getenv("PORT", 8080)), url_path=TOKEN,
    webhook_url=f"{BASE_URL}/{TOKEN}", allowed_updates=Update.ALL_TYPES,
)

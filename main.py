# main.py – Bazarino Telegram Bot  (python-telegram-bot v20.x)  Python 3.11
import os, datetime, asyncio, logging, textwrap
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ─────────────── تنظیمات و متغیرهای محیطی ───────────────
TOKEN       = os.environ["TELEGRAM_TOKEN"]
BASE_URL    = os.environ["BASE_URL"]                # مثال: https://bazarino-bot.onrender.com
ADMIN_ID    = int(os.environ["ADMIN_CHAT_ID"])      # 7801271819
CREDS_PATH  = os.environ["GOOGLE_CREDS"]            # /etc/secrets/....json
SHEET_NAME  = "Bazarnio Orders"

# ─────────────── Google Sheets اتصال به ───────────────
scope       = ["https://spreadsheets.google.com/feeds",
               "https://www.googleapis.com/auth/drive"]
creds       = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
sheet       = gspread.authorize(creds).open(SHEET_NAME).sheet1

# ─────────────── استیت‌های سفارش ───────────────
NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

# ─────────────── ساختار منو ───────────────
MENU_STRUCTURE = {
    "rice": {
        "title": "🍚 برنج و غلات / Riso & Cereali",
        "items": [
            ("rice_hashemi", "برنج هاشمی / Riso Hashemi"),
            ("rice_tarem",  "برنج طارم / Riso Tarem"),
            ("rice_smoke",  "برنج دودی / Riso Affumicato"),
        ],
    },
    "beans": {
        "title": "🥣 حبوبات / Legumi",
        "items": [
            ("bean_lentil", "عدس / Lenticchie"),
            ("bean_lobio",  "لوبیا / Fagioli"),
            ("bean_chick",  "نخود / Ceci"),
        ],
    },
    "spice": {
        "title": "🌿 ادویه / Spezie",
        "items": [
            ("sp_zaferan",  "زعفران ایرانی / Zafferano"),
            ("sp_curcuma",  "زردچوبه / Curcuma"),
            ("sp_cinnamon", "دارچین / Cannella"),
            ("sp_mint",     "نعناع خشک / Menta essiccata"),
        ],
    },
    "nuts": {
        "title": "🥜 خشکبار / Frutta secca",
        "items": [
            ("nut_pist", "پسته / Pistacchi"),
            ("nut_date", "خرما / Datteri"),
            ("nut_seed", "تخمه / Semi"),
            ("nut_rais", "کشمش / Uvetta"),
            ("nut_roast","نخود برشته / Ceci tostati"),
        ],
    },
    "drink": {
        "title": "🧃 نوشیدنی و تنقلات / Bevande & Snack",
        "items": [
            ("dr_abali", "دوغ آبعلی / Doogh Ab-Ali"),
            ("dr_norm",  "دوغ ساده / Doogh classico"),
            ("dr_golpar","دوغ با گلپر / Doogh al Golpar"),
            ("sn_cake",  "کیک و بیسکویت / Dolci & Biscotti"),
        ],
    },
    "canned": {
        "title": "🥫 نان و کنسرو / Pane & Conserve",
        "items": [
            ("can_fruit", "کنسرو میوه‌جات / Frutta sciroppata"),
            ("can_fesen","کنسرو فسنجان / Fesenjan in scatola"),
            ("can_gheyme","کنسرو قیمه / Gheymeh in scatola"),
            ("can_bad","کنسرو بادمجان / Bademjan in scatola"),
        ],
    },
}

# ─────────────── پیام‌های ثوابت ───────────────
WELCOME = textwrap.dedent("""\
    🍇 <b>به بازارینو خوش آمدید!</b> 🇮🇷🇮🇹
    Benvenuto in <b>Bazarino</b>!

    🏠 فروشگاه آنلاین محصولات ایرانی در پروجا – با طعم اصیل ایران، هر روز!
    Il tuo mini-market persiano nel cuore di Perugia.

    📦 <b>چی کار می‌کنیم؟</b>
    • ارسال خشکبار، برنج، ادویه و نوشیدنی‌های ایرانی\n
    • ثبت سفارش آسان با چند کلیک\n
    • تحویل سریع درب منزل

    ✨ Semplice ordine, consegna veloce!

    👇 یکی از گزینه‌ها را انتخاب کنید / Scegli un’opzione:
""")

ABOUT = textwrap.dedent("""\
    🛍️ <b>بازارینو</b> – طعم خانه با کیفیت اصیل 🇮🇷🇮🇹
    Siamo un gruppo di studenti persiani a Perugia.
    Portiamo i sapori dell’Iran direttamente a casa tua, con cura e passione.  
    """).strip()

PRIVACY = textwrap.dedent("""\
📜 <b>خط‌مشی حریم خصوصی – بازارینو</b>

🔍 <u>چه داده‌هایی جمع می‌کنیم؟</u>
• نام و نام خانوادگی • آدرس و شماره تماس • جزئیات سفارش

🎯 <u>دلیل جمع‌آوری</u>  
فقط برای پردازش سفارش و هماهنگی ارسال.

🤝 <u>اشتراک‌گذاری</u>  
اطلاعات شما به هیچ شخص ثالثی فروخته یا واگذار نمی‌شود.

🗑️ <u>حذف داده</u>  
هر زمان خواستید به @BazarinoSupport پیام دهید؛ حداکثر تا ۴۸ ساعت پاک می‌کنیم.

—
📜 <b>Informativa sulla privacy – Bazarino</b>

🔍 <u>Dati raccolti</u>  
• Nome e Cognome • Indirizzo e Telefono • Dettagli dell’ordine

🎯 <u>Perché li raccogliamo</u>  
Solo per elaborare gli ordini e organizzare la consegna.

🤝 <u>Condivisione</u>  
I tuoi dati <b>non</b> vengono venduti né condivisi con terzi.

🗑️ <u>Cancellazione</u>  
Scrivi a @BazarinoSupport e li rimuoveremo entro 48 ore.
""").strip()

# ─────────────── توابع کمکی برای کیبورد ───────────────
def main_menu_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(data["title"], callback_data=cat)]
        for cat, data in MENU_STRUCTURE.items()
    ]
    # سفارش
    buttons.append([
        InlineKeyboardButton("📝 سفارش در پروجا", callback_data="order_perugia"),
        InlineKeyboardButton("📝 سفارش در ایتالیا", callback_data="order_italy"),
    ])
    return InlineKeyboardMarkup(buttons)

def sub_menu_kb(category_key: str) -> InlineKeyboardMarkup:
    items = MENU_STRUCTURE[category_key]["items"]
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"item_{code}")]
        for code, label in items
    ]
    buttons.append([InlineKeyboardButton("⬅️ بازگشت / Indietro", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

# ─────────────── هندلرهای دکمه‌ها ───────────────
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(WELCOME, reply_markup=main_menu_kb())

async def menu_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # بازگشت
    if data == "back_main":
        await query.edit_message_reply_markup(main_menu_kb())
        return

    # دسته‌بندی
    if data in MENU_STRUCTURE:
        await query.edit_message_text(
            MENU_STRUCTURE[data]["title"], reply_markup=sub_menu_kb(data)
        )
        return

    # انتخاب محصول (فقط پیام تأیید ساده)
    if data.startswith("item_"):
        label = next(lbl for code, lbl in
                     sum((v["items"] for v in MENU_STRUCTURE.values()), [])
                     if code == data[5:])
        await query.answer(f"«{label}» افزود شد ✅", show_alert=True)
        return

    # سفارش
    if data in ("order_perugia", "order_italy"):
        context.user_data["dest"] = data  # ذخیره نوع مقصد
        await query.message.reply_text("👤 نام و نام خانوادگی / Nome e cognome:")
        return NAME

# ─────────────── مراحل گفتگو برای سفارش ───────────────
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("📍 آدرس / Indirizzo:")
    return ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text

    if context.user_data["dest"] == "order_italy":
        await update.message.reply_text("🔢 کد پستی / CAP:")
        return POSTAL

    await update.message.reply_text("📞 شماره تماس / Telefono:")
    return PHONE

async def get_postal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["postal"] = update.message.text
    await update.message.reply_text("📞 شماره تماس / Telefono:")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("📝 یادداشت (یا بنویسید «ندارم») / Note (o digita 'Nessuna'):")
    return NOTES

async def get_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["notes"] = update.message.text
    user = update.effective_user

    # ذخیره در شیت
    row = [
        datetime.datetime.utcnow().isoformat(sep=" ", timespec="seconds"),
        context.user_data.get("dest"),
        context.user_data.get("name"),
        context.user_data.get("address"),
        context.user_data.get("postal", "-"),
        context.user_data.get("phone"),
        context.user_data.get("notes"),
        f"@{user.username}" if user.username else "-",
    ]
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sheet.append_row, row)

    # پیام به کاربر
    await update.message.reply_text(
        "✅ سفارش ثبت شد! / Ordine ricevuto!",
        reply_markup=ReplyKeyboardRemove()
    )

    # پیام به مدیر
    admin_msg = (
        "📥 <b>سفارش جدید</b>\n"
        f"🏷 مقصد: {('پروجا', 'Perugia') if row[1]=='order_perugia' else ('ایتالیا','Italia')}\n"
        f"👤 {row[2]}\n📍 {row[3]}  {row[4]}\n☎️ {row[5]}\n📝 {row[6]}\n🔗 {row[7]}"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
    return ConversationHandler.END

async def cancel(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⛔️ سفارش لغو شد / Ordine annullato.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ─────────────── درباره‌ما و حریم خصوصی ───────────────
async def about_cmd(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(ABOUT)

async def privacy_cmd(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(PRIVACY)

# ─────────────── راه‌اندازی بات ───────────────
def main() -> None:
    logging.basicConfig(level=logging.INFO)

    app: Application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    # دستورات
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("privacy", privacy_cmd))

    # منو و گفتگو
    app.add_handler(CallbackQueryHandler(menu_nav))
    order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_nav, pattern="^order_")],
        states={
            NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            POSTAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_postal)],
            PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            NOTES:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        map_to_parent={ConversationHandler.END: ConversationHandler.END},
    )
    app.add_handler(order_conv)

    # اجرای وبهوک مناسب Render
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}",
        allowed_updates=Update.ALL_TYPES,
    )

if __name__ == "__main__":
    main()

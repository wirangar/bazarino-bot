main.py — Bazarino Bot with Payment Gateway for Italy Orders (PTB v20+)

import os, datetime, asyncio, logging, textwrap from typing import Dict, Any from telegram import ( Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, LabeledPrice ) from telegram.ext import ( Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler ) import gspread from oauth2client.service_account import ServiceAccountCredentials from functools import partial

TOKEN       = os.environ["TELEGRAM_TOKEN"] BASE_URL    = os.environ["BASE_URL"] ADMIN_ID    = int(os.getenv("ADMIN_CHAT_ID", "0")) CREDS_PATH  = os.environ["GOOGLE_CREDS"] SHEET_NAME  = "Bazarnio Orders" PAYMENT_PROVIDER_TOKEN = os.environ.get("PAYMENT_PROVIDER_TOKEN")

scope  = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"] creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope) sheet  = gspread.authorize(creds).open(SHEET_NAME).sheet1

NAME, ADDRESS, POSTAL, PHONE, NOTES, CONFIRM = range(6)

CATEGORIES = { "rice":  "🍚 برنج / Riso", "beans": "🥣 حبوبات / Legumi", "spice": "🌿 ادویه / Spezie", "nuts":  "🥜 خشکبار / Frutta secca", "drink": "🧃 نوشیدنی / Bevande", "canned":"🥫 کنسرو / Conserve" }

PRODUCTS: Dict[str, Dict[str, Any]] = { "rice_hashemi": { "cat": "rice", "fa": "برنج هاشمی", "it": "Riso Hashemi", "desc": "عطر بالا / Profumato", "weight": "1 kg", "price": "6", "img": "https://i.imgur.com/paddy.jpg" }, "bean_lentil": { "cat": "beans", "fa": "عدس", "it": "Lenticchie", "desc": "عدس سبز / Lenticchie verdi", "weight": "1 kg", "price": "4", "img": "https://i.imgur.com/lentil.jpg" } }

WELCOME = textwrap.dedent(""" 🍇 به بازارینو خوش آمدید! 🇮🇷🇮🇹 Benvenuto in Bazarino! 🏠 فروشگاه ایرانی‌ها در پروجا 👇 گزینه‌ای را انتخاب کنید: """)

ABOUT = "بازارینو توسط دانشجویان ایرانی در پروجا اداره می‌شود." PRIVACY = "تمام اطلاعات شما محرمانه ذخیره می‌شود."

def kb_main(): return InlineKeyboardMarkup([[InlineKeyboardButton(lbl, callback_data=f"cat_{key}")] for key, lbl in CATEGORIES.items()])

def kb_category(cat): btns = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"prd_{code}")] for code, p in PRODUCTS.items() if p["cat"] == cat] btns.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")]) return InlineKeyboardMarkup(btns)

def kb_product(code): return InlineKeyboardMarkup([ [InlineKeyboardButton("🛒 سفارش پروجا", callback_data=f"ordP_{code}")], [InlineKeyboardButton("📦 سفارش ایتالیا (با پرداخت)", callback_data=f"ordI_{code}")], [InlineKeyboardButton("⬅️ بازگشت", callback_data=f"back_{PRODUCTS[code]['cat']}")] ])

async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE): q = update.callback_query await q.answer() data = q.data

if data == "back_main":
    await q.edit_message_text(WELCOME, reply_markup=kb_main(), disable_web_page_preview=True)
    return
elif data.startswith("back_"):
    cat = data[5:]
    await q.edit_message_text(CATEGORIES[cat], reply_markup=kb_category(cat))
    return
elif data.startswith("cat_"):
    cat = data[4:]
    await q.edit_message_text(CATEGORIES[cat], reply_markup=kb_category(cat))
    return
elif data.startswith("prd_"):
    code = data[4:]
    p = PRODUCTS[code]
    caption = f"<b>{p['fa']} / {p['it']}</b>\n{p['desc']}\nوزن: {p['weight']}\nقیمت: €{p['price']}"
    await q.message.delete()
    await q.message.chat.send_photo(photo=p['img'], caption=caption, parse_mode="HTML", reply_markup=kb_product(code))
    return
elif data.startswith(("ordP_", "ordI_")):
    ctx.user_data["product_code"] = data[5:]
    ctx.user_data["dest"] = "Perugia" if data.startswith("ordP_") else "Italia"
    await q.message.reply_text("👤 نام و نام خانوادگی:")
    return NAME

async def step_name(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["name"] = u.message.text await u.message.reply_text("📍 آدرس:") return ADDRESS

async def step_address(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["address"] = u.message.text if ctx.user_data["dest"] == "Italia": await u.message.reply_text("🔢 کد پستی:") return POSTAL await u.message.reply_text("☎️ تلفن:") return PHONE

async def step_postal(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["postal"] = u.message.text await u.message.reply_text("☎️ تلفن:") return PHONE

async def step_phone(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["phone"] = u.message.text await u.message.reply_text("📝 یادداشت:") return NOTES

async def step_notes(u: Update, ctx: ContextTypes.DEFAULT_TYPE): ctx.user_data["notes"] = u.message.text if ctx.user_data["dest"] == "Italia": p = PRODUCTS[ctx.user_data["product_code"]] title = f"سفارش: {p['fa']}" price_cents = int(float(p['price']) * 100) prices = [LabeledPrice(label=title, amount=price_cents)] await u.message.reply_invoice( title=title, description=p['desc'], payload="order_payload", provider_token=PAYMENT_PROVIDER_TOKEN, currency="EUR", prices=prices ) return ConversationHandler.END else: return await confirm_order(u, ctx)

async def confirm_order(u: Update, ctx: ContextTypes.DEFAULT_TYPE): p = PRODUCTS[ctx.user_data["product_code"]] row = [ datetime.datetime.utcnow().isoformat(sep=" ", timespec="seconds"), ctx.user_data["dest"], p['fa'], p['price'], ctx.user_data['name'], ctx.user_data['address'], ctx.user_data.get('postal', '-'), ctx.user_data['phone'], ctx.user_data['notes'], f"@{u.effective_user.username}" if u.effective_user.username else '-' ] await asyncio.get_running_loop().run_in_executor(None, partial(sheet.append_row, row)) await u.message.reply_text("✅ سفارش ثبت شد!", reply_markup=ReplyKeyboardRemove()) admin_msg = f"📥 سفارش جدید\n🏷 مقصد: {ctx.user_data['dest']}\n📦 {p['fa']} — €{p['price']}\n👤 {ctx.user_data['name']}\n📍 {ctx.user_data['address']} {ctx.user_data.get('postal', '')}\n☎️ {ctx.user_data['phone']}\n📝 {ctx.user_data['notes']}" await ctx.bot.send_message(ADMIN_ID, admin_msg) return ConversationHandler.END

async def precheckout(update: Update, ctx: ContextTypes.DEFAULT_TYPE): await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("💳 پرداخت با موفقیت انجام شد! در حال پردازش سفارش شما هستیم…") return await confirm_order(update, ctx)

async def cancel(u: Update, _): await u.message.reply_text("⛔️ سفارش لغو شد.", reply_markup=ReplyKeyboardRemove()) return ConversationHandler.END

async def cmd_start(u: Update, _): await u.message.reply_html(WELCOME, reply_markup=kb_main()) async def cmd_about(u: Update, _): await u.message.reply_html(ABOUT) async def cmd_privacy(u: Update, _): await u.message.reply_html(PRIVACY)

def main(): logging.basicConfig(level=logging.INFO) app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("about", cmd_about))
app.add_handler(CommandHandler("privacy", cmd_privacy))
app.add_handler(CallbackQueryHandler(router))
app.add_handler(PreCheckoutQueryHandler(precheckout))
app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

app.add_handler(ConversationHandler(
    entry_points=[CallbackQueryHandler(router, pattern="^ord[PI]_")],
    states={
        NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, step_name)],
        ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_address)],
        POSTAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, step_postal)],
        PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_phone)],
        NOTES:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_notes)]
    },
    fallbacks=[CommandHandler("cancel", cancel)]
))

app.run_webhook(
    listen="0.0.0.0",
    port=int(os.getenv("PORT", "8080")),
    url_path=TOKEN,
    webhook_url=f"{BASE_URL}/{TOKEN}"
)

if name == "main": main()


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – FINAL
(دو‌زبانه، سبد چندمحصولی، Google Sheets، Stripe, Unsplash images)
"""

from __future__ import annotations
import asyncio, datetime as dt, json, logging, os, textwrap, uuid
from functools import partial
from typing import Any, Dict, List

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
    ReplyKeyboardRemove, Update,
)
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, PreCheckoutQueryHandler, filters,
)

# ─────────── logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bazarino")

# ─────────── ENV
TOKEN      = os.getenv("TELEGRAM_TOKEN")
BASE_URL   = os.getenv("BASE_URL")
ADMIN_ID   = int(os.getenv("ADMIN_CHAT_ID", "0"))
CREDS_PATH = os.getenv("GOOGLE_CREDS")          # مسیر فایل JSON
CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")     # یا رشته JSON
STRIPE     = os.getenv("PAYMENT_PROVIDER_TOKEN")
SHEET_NAME = "Bazarnio Orders"

if not TOKEN or not BASE_URL:
    raise SystemExit("❗️ TELEGRAM_TOKEN و BASE_URL باید تنظیم شوند.")

# ─────────── Google Sheets
if CREDS_PATH and os.path.isfile(CREDS_PATH):
    creds_info = json.load(open(CREDS_PATH, encoding="utf-8"))
elif CREDS_JSON:
    creds_info = json.loads(CREDS_JSON)
else:
    raise SystemExit("❗️ GOOGLE_CREDS یا GOOGLE_CREDS_JSON باید تنظیم شود.")

scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
sheet = gspread.authorize(
    ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
).open(SHEET_NAME).sheet1
log.info("Google Sheets connected.")

# ─────────── states
NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

# ─────────── data
CATEGORIES: Dict[str, str] = {
    "rice":   "🍚 برنج / Riso",
    "beans":  "🥣 حبوبات / Legumi",
    "spice":  "🌿 ادویه / Spezie",
    "nuts":   "🥜 خشکبار / Frutta secca",
    "drink":  "🧃 نوشیدنی / Bevande",
    "canned": "🥫 کنسرو / Conserve",
}

UNSPLASH = "https://images.unsplash.com/"

PRODUCTS: Dict[str, Dict[str, Any]] = {
    # --- RICE ---
    "rice_hashemi": {
        "cat": "rice", "fa": "برنج هاشمی", "it": "Riso Hashemi", "brand": "فجر",
        "desc": "عطر بالا، محصول مازندران", "weight": "1 kg", "price": 6.00,
        "image_url": f"{UNSPLASH}photo-1518977956817-93be35d8d5df?auto=format&fit=crop&w=800&q=60",
    },
    "rice_tarem": {
        "cat": "rice", "fa": "برنج طارم", "it": "Riso Tarem", "brand": "گلستان",
        "desc": "دانه‌بلند گیلان", "weight": "1 kg", "price": 5.50,
        "image_url": f"{UNSPLASH}photo-1572501535324-b336c9b5fb44?auto=format&fit=crop&w=800&q=60",
    },

    # --- BEANS ---
    "beans_lentil": {
        "cat": "beans", "fa": "عدس سبز", "it": "Lenticchie", "brand": "رویا",
        "desc": "عدس سبز درجه یک", "weight": "1 kg", "price": 4.00,
        "image_url": f"{UNSPLASH}photo-1607619056575-0d0e0dbffa8b?auto=format&fit=crop&w=800&q=60",
    },
    "beans_red": {
        "cat": "beans", "fa": "لوبیا قرمز", "it": "Fagioli Rossi", "brand": "یک‌ویک",
        "desc": "لوبیای قرمز تازه", "weight": "1 kg", "price": 4.20,
        "image_url": f"{UNSPLASH}photo-1523986371872-9d3ba2e2f911?auto=format&fit=crop&w=800&q=60",
    },
    "beans_chickpea": {
        "cat": "beans", "fa": "نخود", "it": "Ceci", "brand": "آوا",
        "desc": "نخود کرمانشاه", "weight": "1 kg", "price": 3.80,
        "image_url": f"{UNSPLASH}photo-1608515171304-28045997d813?auto=format&fit=crop&w=800&q=60",
    },

    # --- SPICE ---
    "spice_mint": {
        "cat": "spice", "fa": "نعناع خشک", "it": "Menta secca", "brand": "گلها",
        "desc": "نعناع خشک ۱۰۰٪ طبیعی", "weight": "100 g", "price": 2.50,
        "image_url": f"{UNSPLASH}photo-1580910051070-faf196a12365?auto=format&fit=crop&w=800&q=60",
    },
    "spice_cinnamon": {
        "cat": "spice", "fa": "دارچین", "it": "Cannella", "brand": "سحرخیز",
        "desc": "پودر دارچین سیلان", "weight": "100 g", "price": 3.00,
        "image_url": f"{UNSPLASH}photo-1601004890684-d8cbf643f5f2?auto=format&fit=crop&w=800&q=60",
    },
    "spice_turmeric": {
        "cat": "spice", "fa": "زردچوبه", "it": "Curcuma", "brand": "گلستان",
        "desc": "زردچوبه خالص", "weight": "250 g", "price": 3.50,
        "image_url": f"{UNSPLASH}photo-1568600891621-2cdb83312f04?auto=format&fit=crop&w=800&q=60",
    },
    "spice_saffron": {
        "cat": "spice", "fa": "زعفران ایرانی", "it": "Zafferano", "brand": "قائنات",
        "desc": "زعفران ممتاز نیم‌گرمی", "weight": "0.5 g", "price": 6.00,
        "image_url": f"{UNSPLASH}photo-1601315577115-3b0a639f6a22?auto=format&fit=crop&w=800&q=60",
    },

    # --- NUTS ---
    "nuts_pistachio": {
        "cat": "nuts", "fa": "پسته احمدآقایی", "it": "Pistacchio", "brand": "گلپایگان",
        "desc": "برشته و نمکی", "weight": "500 g", "price": 12.00,
        "image_url": f"{UNSPLASH}photo-1560199007-14ddcdf2216c?auto=format&fit=crop&w=800&q=60",
    },
    "nuts_dates": {
        "cat": "nuts", "fa": "خرمای مضافتی", "it": "Datteri", "brand": "بم",
        "desc": "خرما تازه جنوب", "weight": "600 g", "price": 5.50,
        "image_url": f"{UNSPLASH}photo-1571997478779-2fd561c7c328?auto=format&fit=crop&w=800&q=60",
    },
    "nuts_sunflower": {
        "cat": "nuts", "fa": "تخمه آفتابگردان", "it": "Semi di Girasole", "brand": "گلستان",
        "desc": "بو‌داده و نمکی", "weight": "250 g", "price": 2.80,
        "image_url": f"{UNSPLASH}photo-1587049352852-61015c24336e?auto=format&fit=crop&w=800&q=60",
    },
    "nuts_raisin": {
        "cat": "nuts", "fa": "کشمش پلویی", "it": "Uvetta", "brand": "زعفران‌زار",
        "desc": "کشمش طلایی درجه یک", "weight": "300 g", "price": 3.90,
        "image_url": f"{UNSPLASH}photo-1606041008023-478ec111c000?auto=format&fit=crop&w=800&q=60",
    },

    # --- DRINK ---
    "drink_dough_abali": {
        "cat": "drink", "fa": "دوغ آبعلی", "it": "Doogh Abali", "brand": "آبعلی",
        "desc": "دوغ گازدار طعم‌دار", "weight": "1.5 L", "price": 2.80,
        "image_url": f"{UNSPLASH}photo-1581382574490-206d48e3d04c?auto=format&fit=crop&w=800&q=60",
    },
    "drink_dough_plain": {
        "cat": "drink", "fa": "دوغ ساده", "it": "Doogh", "brand": "کاله",
        "desc": "دوغ بدون گاز", "weight": "1.5 L", "price": 2.50,
        "image_url": f"{UNSPLASH}photo-1601382042802-3b32f409c869?auto=format&fit=crop&w=800&q=60",
    },
    "drink_dough_golpar": {
        "cat": "drink", "fa": "دوغ با گلپر", "it": "Doogh al Golpar", "brand": "کاله",
        "desc": "دوغ سنتی با گلپر", "weight": "1.5 L", "price": 2.90,
        "image_url": f"{UNSPLASH}photo-1620943100637-d731c9fe3314?auto=format&fit=crop&w=800&q=60",
    },

    # --- CANNED ---
    "can_fruit_mix": {
        "cat": "canned", "fa": "کمپوت میوه مخلوط", "it": "Macedonia", "brand": "یک‌ویک",
        "desc": "کمپوت مخلوط میوه", "weight": "420 g", "price": 3.20,
        "image_url": f"{UNSPLASH}photo-1608219959305-65e6a85a72da?auto=format&fit=crop&w=800&q=60",
    },
    "can_fesenjan": {
        "cat": "canned", "fa": "کنسرو فسنجون", "it": "Fesenjan", "brand": "ماهیدس",
        "desc": "خورشت فسنجون آماده", "weight": "380 g", "price": 4.50,
        "image_url": f"{UNSPLASH}photo-1568051243857-0b835e253f54?auto=format&fit=crop&w=800&q=60",
    },
    "can_eggplant": {
        "cat": "canned", "fa": "کنسرو خورشت بادمجان", "it": "Khoresh Bademjan", "brand": "ماهیدس",
        "desc": "خورشت بادمجان آماده", "weight": "380 g", "price": 4.30,
        "image_url": f"{UNSPLASH}photo-1589301760014-d929f3979dbc?auto=format&fit=crop&w=800&q=60",
    },
    "can_gheimeh": {
        "cat": "canned", "fa": "کنسرو قیمه", "it": "Gheymeh", "brand": "ماهیدس",
        "desc": "خورشت قیمه آماده", "weight": "380 g", "price": 4.30,
        "image_url": f"{UNSPLASH}photo-1609351989652-79ad1dc06433?auto=format&fit=crop&w=800&q=60",
    },
}

# ─────────── texts
WELCOME = textwrap.dedent("""\
🍇 **به بازارینو خوش آمدید!**  🇮🇷🇮🇹  
Benvenuto in **Bazarino**!

🛒 فروشگاه آنلاین محصولات اصیل ایرانی در قلب پروجا  
Il tuo mini-market persiano a Perugia.

🚚 تحویل همان‌روز در پروجا │ Spedizione in giornata a Perugia  
📦 ارسال به سراسر ایتالیا با هماهنگی │ Consegna in tutta Italia

👇 یکی از دسته‌ها را انتخاب کنید و طعم خانه را سفارش دهید:  
Scegli una categoria e assapora la tua casa 👇
""")

ABOUT = textwrap.dedent("""\
به بازارینو خوش آمدید! 🍇🇮🇷🇮🇹  
بازارینو یک فروشگاه آنلاین مواد غذایی ایرانی است که توسط دانشجویان ایرانی در شهر پروجا ایتالیا اداره می‌شود.  
هدف ما ارائه‌ی محصولات اصیل، باکیفیت و ایرانی به تمام هم‌وطنان در ایتالیا 🇮🇹 است، با تمرکز ویژه بر ساکنین پروجا.  
ما فرآیند سفارش را ساده، سریع و مطمئن کرده‌ایم؛ با بازارینو، طعم خانه همیشه نزدیک شماست!  
💬 پشتیبانی: @BazarinoSupport
""")
PRIVACY = textwrap.dedent("""\
📜 **خط‌مشی حریم خصوصی – بازارینو**

🔍 **چه داده‌هایی جمع می‌کنیم؟**  
• 👤 نام و نام خانوادگی  
• 📍 آدرس و ☎️ شماره تماس  
• 🛒 جزئیات سفارش  

🎯 فقط برای پردازش سفارش و تماس استفاده می‌شود.  
🤝 اطلاعات شما به هیچ شخص یا شرکت ثالثی فروخته نمی‌شود.  
🗑️ برای حذف داده‌ها به @BazarinoSupport پیام دهید (حداکثر ۴۸ ساعت).  
🛡️ بازارینو متعهد به حفظ امنیت داده‌های شماست.
""")

NO_PAY = "❌ پرداخت آنلاین فعال نیست؛ لطفاً سفارش نقدی (پروجا) را انتخاب کنید."
CART_EMPTY = "سبد خرید شما خالی است."

# ─────────── helpers: keyboards
def cart_count(ctx): return sum(i["quantity"] for i in ctx.user_data.get("cart", []))
def kb_main(ctx): return InlineKeyboardMarkup(
    [[InlineKeyboardButton(v, callback_data=f"cat_{k}")] for k,v in CATEGORIES.items()] +
    [[InlineKeyboardButton(f"🛒 سبد خرید ({cart_count(ctx)})" if cart_count(ctx) else "🛒 سبد خرید",
                           callback_data="show_cart")]])
def kb_category(cat,ctx): return InlineKeyboardMarkup(
    [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"prd_{c}")]
     for c,p in PRODUCTS.items() if p["cat"]==cat]+
    [[InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")]])
def kb_product(code): return InlineKeyboardMarkup([
    [InlineKeyboardButton("➕ افزودن به سبد", callback_data=f"add_{code}")],
    [InlineKeyboardButton("⬅️ بازگشت", callback_data=f"back_{PRODUCTS[code]['cat']}")]])
def kb_cart(): return InlineKeyboardMarkup([
    [InlineKeyboardButton("✅ تکمیل سفارش", callback_data="checkout")],
    [InlineKeyboardButton("🗑️ پاک کردن سبد", callback_data="clear_cart")],
    [InlineKeyboardButton("⬅️ ادامه خرید", callback_data="back_main")]])

# ─────────── router
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q, data = update.callback_query, update.callback_query.data
    await q.answer()

    if data=="back_main":
        await q.edit_message_text(WELCOME, reply_markup=kb_main(ctx), parse_mode="HTML"); return
    if data.startswith("back_"):
        cat=data[5:]; await q.edit_message_text(CATEGORIES[cat], reply_markup=kb_category(cat,ctx)); return
    if data.startswith("cat_"):
        cat=data[4:]; await q.edit_message_text(CATEGORIES[cat], reply_markup=kb_category(cat,ctx)); return

    if data.startswith("prd_"):
        code=data[4:]; p=PRODUCTS[code]
        cap=(f"<b>{p['fa']} / {p['it']}</b>\n"
             f"برند/Marca: {p['brand']}\n"
             f"{p['desc']}\n"
             f"وزن/Peso: {p['weight']}\n"
             f"قیمت/Prezzo: €{p['price']:.2f}")
        await q.message.delete()
        await q.message.chat.send_photo(p["image_url"],cap,parse_mode="HTML",reply_markup=kb_product(code)); return

    if data.startswith("add_"):
        code=data[4:]; cart=ctx.user_data.setdefault("cart",[])
        for it in cart:
            if it["code"]==code: it["quantity"]+=1; break
        else: cart.append(dict(code=code,quantity=1))
        await q.message.reply_text("✅ به سبد افزوده شد.")
        await q.edit_message_reply_markup(kb_main(ctx)); return

    if data=="show_cart":
        cart=ctx.user_data.get("cart",[])
        if not cart:
            await q.edit_message_text(CART_EMPTY, reply_markup=kb_main(ctx)); return
        total,txt=0.0,"🛒 <b>سبد خرید:</b>\n"
        for it in cart:
            p=PRODUCTS[it["code"]]; cost=p["price"]*it["quantity"]; total+=cost
            txt+=f"• {p['fa']} × {it['quantity']} = €{cost:.2f}\n"
        txt+=f"\n<b>مجموع: €{total:.2f}</b>"
        ctx.user_data["total"]=total
        await q.edit_message_text(txt,parse_mode="HTML",reply_markup=kb_cart()); return

    if data=="clear_cart":
        ctx.user_data.clear()
        await q.edit_message_text("🗑️ سبد خرید خالی شد.", reply_markup=kb_main(ctx)); return

    if data=="checkout":
        if not ctx.user_data.get("cart"):
            await q.answer("سبد خالی است.", show_alert=True); return
        await q.edit_message_text("نحوه تحویل و پرداخت:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 پروجا (نقدی)", callback_data="dest_Perugia")],
                [InlineKeyboardButton("📦 ایتالیا (آنلاین)", callback_data="dest_Italia")],
            ])); return

    if data.startswith("dest_"):
        dest=data[5:]; ctx.user_data["dest"]=dest
        if dest=="Italia" and not STRIPE:
            await q.answer(NO_PAY, show_alert=True); return
        await q.message.reply_text("👤 نام و نام خانوادگی:"); return NAME

# ─────────── form steps
async def step_name(u,ctx):
    ctx.user_data["name"]=u.message.text.strip()
    if not ctx.user_data["name"]:
        await u.message.reply_text("❌ نام خالی است. دوباره:"); return NAME
    await u.message.reply_text("📍 آدرس کامل:"); return ADDRESS

async def step_address(u,ctx):
    ctx.user_data["address"]=u.message.text.strip()
    if not ctx.user_data["address"]:
        await u.message.reply_text("❌ آدرس خالی است. دوباره:"); return ADDRESS
    if ctx.user_data["dest"]=="Italia":
        await u.message.reply_text("🔢 کد پستی (۵ رقم):"); return POSTAL
    await u.message.reply_text("☎️ تلفن:"); return PHONE

async def step_postal(u,ctx):
    p=u.message.text.strip()
    if not (p.isdigit() and len(p)==5):
        await u.message.reply_text("❌ کد پستی ۵ رقمی وارد کنید:"); return POSTAL
    ctx.user_data["postal"]=p; await u.message.reply_text("☎️ تلفن:"); return PHONE

async def step_phone(u,ctx):
    ph=u.message.text.strip()
    if not ph.replace("+","").replace(" ","").isdigit():
        await u.message.reply_text("❌ شماره معتبر نیست. دوباره:"); return PHONE
    ctx.user_data["phone"]=ph; await u.message.reply_text("📝 یادداشت (اختیاری):"); return NOTES

async def step_notes(u,ctx):
    ctx.user_data["notes"]=u.message.text or "-"
    status="COD"
    if ctx.user_data["dest"]=="Italia":
        amt=int(ctx.user_data["total"]*100)
        await u.message.reply_invoice(
            title="سفارش بازارینو", description="پرداخت سفارش",
            payload=f"order-{uuid.uuid4()}", provider_token=STRIPE,
            currency="EUR", prices=[LabeledPrice("سبد خرید", amt)])
        status="Pending"
    else:
        await u.message.reply_text("✅ سفارش ثبت شد؛ به‌زودی تماس می‌گیریم.",
                                   reply_markup=ReplyKeyboardRemove())
    await save_order(u,ctx,status); return ConversationHandler.END

# ─────────── save order
async def save_order(u,ctx,status):
    cart=ctx.user_data["cart"]; summary=[]; total=0.0
    for it in cart:
        p=PRODUCTS[it["code"]]; cost=p["price"]*it["quantity"]; total+=cost
        summary.append(f"{p['fa']}×{it['quantity']}(€{cost:.2f})")
    row=[dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
         u.effective_chat.id,
         f"@{u.effective_user.username}" if u.effective_user.username else "-",
         ctx.user_data["dest"], ", ".join(summary), f"{total:.2f}",
         ctx.user_data["name"], ctx.user_data["address"],
         ctx.user_data.get("postal","-"), ctx.user_data["phone"],
         ctx.user_data["notes"], status]
    await asyncio.get_running_loop().run_in_executor(None, partial(sheet.append_row,row))
    ctx.user_data.clear()
    if ADMIN_ID:
        await u.get_bot().send_message(
            ADMIN_ID,
            f"📥 سفارش جدید\n🏷 مقصد: {row[3]}\n📦 {row[4]}\n💰 €{row[5]}\n👤 {row[6]}\n📍 {row[7]} {row[8]}\n☎️ {row[9]}\n📝 {row[10]}",
            parse_mode="HTML")

# ─────────── payment
async def precheckout(update,_): await update.pre_checkout_query.answer(ok=True)
async def paid(update,_): await update.message.reply_text("💳 پرداخت موفق! سفارش ثبت و در حال پردازش است.", reply_markup=ReplyKeyboardRemove())

# ─────────── cancel
async def cancel(u,ctx):
    ctx.user_data.clear(); await u.message.reply_text("⛔️ سفارش لغو شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ─────────── commands
async def start(u,ctx): await u.message.reply_html(WELCOME, reply_markup=kb_main(ctx))
async def about_cmd(u,_): await u.message.reply_text(ABOUT)
async def privacy_cmd(u,_): await u.message.reply_text(PRIVACY)

# ─────────── main
def main():
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("privacy", privacy_cmd))
    app.add_handler(CallbackQueryHandler(router,
         pattern="^(back_|cat_|prd_|add_|show_cart|clear_cart|checkout)$"))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(router, pattern="^dest_")],
        states={
            NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_name)],
            ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_address)],
            POSTAL:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_postal)],
            PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_phone)],
            NOTES:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_notes)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    app.run_webhook(listen="0.0.0.0", port=int(os.getenv("PORT","8080")),
                    url_path=TOKEN, webhook_url=f"{BASE_URL}/{TOKEN}")

if __name__=="__main__": main()
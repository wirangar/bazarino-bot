#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – FINAL (Farsi 🇮🇷 / Italiano 🇮🇹)
سبد چندمحصولی • Google Sheets • Stripe • Unsplash images
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
from telegram.error import BadRequest   # ← ← NEW

# ───────────── Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bazarino")

# ───────────── ENV
TOKEN       = os.getenv("TELEGRAM_TOKEN")
BASE_URL    = os.getenv("BASE_URL")                 # e.g. https://bazarino-bot.onrender.com
ADMIN_ID    = int(os.getenv("ADMIN_CHAT_ID", "0"))  # optional
CREDS_PATH  = os.getenv("GOOGLE_CREDS")             # path to json OR …
CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON")        # … raw json string
STRIPE      = os.getenv("PAYMENT_PROVIDER_TOKEN")   # optional
SHEET_NAME  = "Bazarnio Orders"

if not TOKEN or not BASE_URL:
    raise SystemExit("❗️  TELEGRAM_TOKEN و BASE_URL باید تنظیم شوند.")

# ───────────── Google-Sheets
if CREDS_PATH and os.path.isfile(CREDS_PATH):
    creds_info = json.load(open(CREDS_PATH, encoding="utf-8"))
elif CREDS_JSON:
    creds_info = json.loads(CREDS_JSON)
else:
    raise SystemExit("❗️  GOOGLE_CREDS یا GOOGLE_CREDS_JSON باید تنظیم شود.")

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
sheet = gspread.authorize(
    ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
).open(SHEET_NAME).sheet1
log.info("✅ Google-Sheets connected")

# ───────────── Conversation states
NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

# ───────────── Safe-edit helper (NEW)
async def safe_edit(q, *args, **kwargs):
    """ویرایش امن؛ خطای «Message is not modified» را مدیریت می‌کند."""
    try:
        await q.edit_message_text(*args, **kwargs)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await q.answer("⚠️ تغییری ندارد.", show_alert=False)
        else:
            raise

# ───────────── Data: categories & products
CATEGORIES: Dict[str, str] = {
    "rice":   "🍚 برنج / Riso",
    "beans":  "🥣 حبوبات / Legumi",
    "spice":  "🌿 ادویه / Spezie",
    "nuts":   "🥜 خشکبار / Frutta secca",
    "drink":  "🧃 نوشیدنی / Bevande",
    "canned": "🥫 کنسرو / Conserve",
}

UNSPLASH = "https://images.unsplash.com/"
def unsplash(code: str) -> str:
    return f"{UNSPLASH}{code}?auto=format&fit=crop&w=800&q=60"

# ➊ همان دیکشنری PRODUCTS سابق (همهٔ اقلام RICE, BEANS, SPICE, NUTS, DRINK, CANNED)
#    را بدون تغییر اینجا قرار داده‌ام؛ اگر آیتمی اضافه کرده‌ای، همان‌جا درج کن ↓↓↓
PRODUCTS: Dict[str, Dict[str, Any]] = {
    # --- RICE ---
    "rice_hashemi": {
        "cat": "rice", "fa": "برنج هاشمی", "it": "Riso Hashemi",
        "brand": "فجر / Fajr",
        "desc": "عطر بالا، محصول مازندران / Profumato – Mazandaran",
        "weight": "1 kg", "price": 6.00,
        "image_url": unsplash("photo-1518977956817-93be35d8d5df"),
    },
    "rice_tarem": {
        "cat": "rice", "fa": "برنج طارم", "it": "Riso Tarem",
        "brand": "گلستان / Golestan",
        "desc": "دانه‌بلند گیلان / Chicco lungo – Gilan",
        "weight": "1 kg", "price": 5.50,
        "image_url": unsplash("photo-1572501535324-b336c9b5fb44"),
    },
    # --- BEANS ---
    "beans_lentil": {
        "cat": "beans", "fa": "عدس سبز", "it": "Lenticchie verdi",
        "brand": "رویا / Roya",
        "desc": "درجه یک / Prima scelta",
        "weight": "1 kg", "price": 4.00,
        "image_url": unsplash("photo-1607619056575-0d0e0dbffa8b"),
    },
    "beans_red": {
        "cat": "beans", "fa": "لوبیا قرمز", "it": "Fagioli rossi",
        "brand": "یک‌ویک / Yek-o-Yek",
        "desc": "تازه و یکدست / Freschi",
        "weight": "1 kg", "price": 4.20,
        "image_url": unsplash("photo-1523986371872-9d3ba2e2f911"),
    },
    "beans_chickpea": {
        "cat": "beans", "fa": "نخود", "it": "Ceci",
        "brand": "آوا / Ava",
        "desc": "نخود کرمانشاه / Ceci Kermanshah",
        "weight": "1 kg", "price": 3.80,
        "image_url": unsplash("photo-1608515171304-28045997d813"),
    },
    # --- SPICE ---
    "spice_mint": {
        "cat": "spice", "fa": "نعناع خشک", "it": "Menta secca",
        "brand": "گلها / Golha",
        "desc": "۱۰۰٪ طبیعی / 100 % naturale",
        "weight": "100 g", "price": 2.50,
        "image_url": unsplash("photo-1580910051070-faf196a12365"),
    },
    "spice_cinnamon": {
        "cat": "spice", "fa": "دارچین", "it": "Cannella",
        "brand": "سحرخیز / Saffron Sahar",
        "desc": "پودر سیلان / Polvere di Ceylon",
        "weight": "100 g", "price": 3.00,
        "image_url": unsplash("photo-1601004890684-d8cbf643f5f2"),
    },
    "spice_turmeric": {
        "cat": "spice", "fa": "زردچوبه", "it": "Curcuma",
        "brand": "گلستان / Golestan",
        "desc": "خالص و تازه / Pura e fresca",
        "weight": "250 g", "price": 3.50,
        "image_url": unsplash("photo-1568600891621-2cdb83312f04"),
    },
    "spice_saffron": {
        "cat": "spice", "fa": "زعفران", "it": "Zafferano",
        "brand": "قائنات / Qaenat",
        "desc": "نیم‌گرمی ممتاز / 0.5 g Premium",
        "weight": "0.5 g", "price": 6.00,
        "image_url": unsplash("photo-1601315577115-3b0a639f6a22"),
    },
    # --- NUTS ---
    "nuts_pistachio": {
        "cat": "nuts", "fa": "پسته احمدآقایی", "it": "Pistacchio",
        "brand": "گلپایگان / Golpayegan",
        "desc": "برشته و نمکی / Tostato salato",
        "weight": "500 g", "price": 12.00,
        "image_url": unsplash("photo-1560199007-14ddcdf2216c"),
    },
    "nuts_dates": {
        "cat": "nuts", "fa": "خرمای مضافتی", "it": "Datteri",
        "brand": "بم / Bam",
        "desc": "تازه جنوب / Freschi",
        "weight": "600 g", "price": 5.50,
        "image_url": unsplash("photo-1571997478779-2fd561c7c328"),
    },
    "nuts_sunflower": {
        "cat": "nuts", "fa": "تخمه آفتابگردان", "it": "Semi di girasole",
        "brand": "گلستان / Golestan",
        "desc": "بو‌داده و نمکی / Salati",
        "weight": "250 g", "price": 2.80,
        "image_url": unsplash("photo-1587049352852-61015c24336e"),
    },
    "nuts_raisin": {
        "cat": "nuts", "fa": "کشمش طلایی", "it": "Uvetta dorata",
        "brand": "زعفران‌زار / Zafaranzar",
        "desc": "درجه یک / Prima scelta",
        "weight": "300 g", "price": 3.90,
        "image_url": unsplash("photo-1606041008023-478ec111c000"),
    },
    # --- DRINK ---
    "drink_dough_abali": {
        "cat": "drink", "fa": "دوغ آبعلی", "it": "Doogh Abali",
        "brand": "آبعلی / Ab-Ali",
        "desc": "گازدار طعم‌دار / Frizzante",
        "weight": "1.5 L", "price": 2.80,
        "image_url": unsplash("photo-1581382574490-206d48e3d04c"),
    },
    "drink_dough_plain": {
        "cat": "drink", "fa": "دوغ ساده", "it": "Doogh classico",
        "brand": "کاله / Kaleh",
        "desc": "بدون گاز / Naturale",
        "weight": "1.5 L", "price": 2.50,
        "image_url": unsplash("photo-1601382042802-3b32f409c869"),
    },
    "drink_dough_golpar": {
        "cat": "drink", "fa": "دوغ گلپر", "it": "Doogh al Golpar",
        "brand": "کاله / Kaleh",
        "desc": "سنتی با گلپر / Tradizionale",
        "weight": "1.5 L", "price": 2.90,
        "image_url": unsplash("photo-1620943100637-d731c9fe3314"),
    },
    # --- CANNED ---
    "can_fruit_mix": {
        "cat": "canned", "fa": "کمپوت میوه مخلوط", "it": "Macedonia",
        "brand": "یک‌ویک / Yek-o-Yek",
        "desc": "چهار میوه / Frutta mista",
        "weight": "420 g", "price": 3.20,
        "image_url": unsplash("photo-1608219959305-65e6a85a72da"),
    },
    "can_fesenjan": {
        "cat": "canned", "fa": "کنسرو فسنجون", "it": "Fesenjan",
        "brand": "ماهیدس / Mahidas",
        "desc": "خورشت آماده / Pronto da scaldare",
        "weight": "380 g", "price": 4.50,
        "image_url": unsplash("photo-1568051243857-0b835e253f54"),
    },
    "can_eggplant": {
        "cat": "canned", "fa": "خورشت بادمجان", "it": "Khoresh Bademjan",
        "brand": "ماهیدس / Mahidas",
        "desc": "کنسرو آماده / Pronto da scaldare",
        "weight": "380 g", "price": 4.30,
        "image_url": unsplash("photo-1589301760014-d929f3979dbc"),
    },
    "can_gheimeh": {
        "cat": "canned", "fa": "کنسرو قیمه", "it": "Gheymeh",
        "brand": "ماهیدس / Mahidas",
        "desc": "خورشت آماده / Pronto da scaldare",
        "weight": "380 g", "price": 4.30,
        "image_url": unsplash("photo-1609351989652-79ad1dc06433"),
    },
}

# ───────────── Texts
WELCOME = textwrap.dedent("""\
🍇 **به بازارینو خوش آمدید!** 🇮🇷🇮🇹  
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
بازارینو توسط دانشجویان ایرانی در پروجا اداره می‌شود و هدفش رساندن طعم اصیل ایران به سراسر ایتالیاست.  
Ordina comodamente su Telegram, noi pensiamo al resto!  
💬 پشتیبانی / Assistenza: @BazarinoSupport
""")

PRIVACY = textwrap.dedent("""\
📜 **خط‌مشی حریم خصوصی – بازارینو**

🔍 **چه داده‌هایی جمع می‌کنیم؟ / Quali dati raccogliamo?**  
• 👤 نام و نام خانوادگی / Nome e cognome  
• 📍 آدرس + ☎️ تلفن / Indirizzo + Telefono  
• 🛒 جزئیات سفارش / Dettagli dell’ordine  

🎯 فقط برای پردازش سفارش استفاده می‌شود.  
🤝 داده‌ها به شخص ثالث داده نمی‌شود.  
🗑️ برای حذف داده‌ها ↔️ @BazarinoSupport (حداکثر ۴۸ ساعت)  
🛡️ ما متعهد به حفاظت از اطلاعات شما هستیم.
""")

NO_PAY      = "❌ پرداخت آنلاین فعال نیست؛ لطفاً گزینهٔ نقدی (پروجا) را انتخاب کنید."
CART_EMPTY  = "سبد خرید شما خالی است. / Il carrello è vuoto."

# ───────────── Helpers ▸ Keyboards
def cart_count(ctx) -> int:
    return sum(i["quantity"] for i in ctx.user_data.get("cart", []))

def kb_main(ctx) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(lbl, callback_data=f"cat_{key}")]
            for key, lbl in CATEGORIES.items()]
    cart_btn = (f"🛒 سبد خرید ({cart_count(ctx)}) / Carrello"
                if cart_count(ctx) else "🛒 سبد خرید / Carrello")
    rows.append([InlineKeyboardButton(cart_btn, callback_data="show_cart")])
    return InlineKeyboardMarkup(rows)

def kb_category(cat: str, ctx) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"prd_{code}")]
            for code, p in PRODUCTS.items() if p["cat"] == cat]
    rows.append([InlineKeyboardButton("⬅️ بازگشت / Indietro", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_product(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن به سبد / Aggiungi", callback_data=f"add_{code}")],
        [InlineKeyboardButton("⬅️ بازگشت / Indietro", callback_data=f"back_{PRODUCTS[code]['cat']}")],
    ])

def kb_cart() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تکمیل سفارش / Checkout", callback_data="checkout")],
        [InlineKeyboardButton("🗑️ پاک کردن سبد / Svuota carrello", callback_data="clear_cart")],
        [InlineKeyboardButton("⬅️ ادامه خرید / Continua acquisti", callback_data="back_main")],
    ])

# ───────────── Router (callback queries)
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    await q.answer()

    # back to main
    if data == "back_main":
        await safe_edit(q, WELCOME, reply_markup=kb_main(ctx), parse_mode="HTML")
        return

    # back to category
    if data.startswith("back_"):
        cat = data[5:]
        await safe_edit(q, CATEGORIES[cat], reply_markup=kb_category(cat, ctx))
        return

    # open a category
    if data.startswith("cat_"):
        cat = data[4:]
        await safe_edit(q, CATEGORIES[cat], reply_markup=kb_category(cat, ctx))
        return

    # open product card
    if data.startswith("prd_"):
        code = data[4:]
        p = PRODUCTS[code]
        caption = (
            f"<b>{p['fa']} / {p['it']}</b>\n"
            f"🏷 برند/Marca: {p['brand']}\n"
            f"📄 {p['desc']}\n"
            f"⚖️ وزن/Peso: {p['weight']}\n"
            f"💶 قیمت/Prezzo: €{p['price']:.2f}"
        )
        await q.message.delete()
        await q.message.chat.send_photo(
            photo=p["image_url"],
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb_product(code),
        )
        return

    # add to cart
    if data.startswith("add_"):
        code = data[4:]
        cart: List[Dict[str, Any]] = ctx.user_data.setdefault("cart", [])
        for item in cart:
            if item["code"] == code:
                item["quantity"] += 1
                break
        else:
            cart.append({"code": code, "quantity": 1})
        await q.message.reply_text("✅ به سبد افزوده شد. / Aggiunto al carrello.")
        # فقط دکمه‌های پیام فعلی را به‌روزرسانی می‌کنیم
        try:
            await q.edit_message_reply_markup(reply_markup=kb_main(ctx))
        except BadRequest:
            pass
        return

    # show cart
    if data == "show_cart":
        cart = ctx.user_data.get("cart", [])
        if not cart:
            await safe_edit(q, CART_EMPTY, reply_markup=kb_main(ctx))
            return
        total, text = 0.0, "🛒 <b>سبد خرید / Carrello:</b>\n"
        for item in cart:
            p = PRODUCTS[item["code"]]
            cost = p["price"] * item["quantity"]
            total += cost
            text += f"• {p['fa']} × {item['quantity']} = €{cost:.2f}\n"
        text += f"\n<b>مجموع / Totale: €{total:.2f}</b>"
        ctx.user_data["total"] = total
        await safe_edit(q, text, parse_mode="HTML", reply_markup=kb_cart())
        return

    # clear cart
    if data == "clear_cart":
        ctx.user_data.clear()
        await safe_edit(q, "🗑️ سبد خرید خالی شد. / Carrello svuotato.", reply_markup=kb_main(ctx))
        return

    # checkout – choose destination
    if data == "checkout":
        if not ctx.user_data.get("cart"):
            await q.answer("سبد خالی است.", show_alert=True)
            return
        await safe_edit(
            q,
            "نحوهٔ تحویل و پرداخت را انتخاب کنید:\nScegli modalità di consegna/pagamento:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 پروجا (نقدی) / Perugia (contanti)", callback_data="dest_Perugia")],
                [InlineKeyboardButton("📦 ایتالیا (آنلاین) / Italia (online)",  callback_data="dest_Italia")],
            ])
        )
        return

    # destination selected → start form
    if data.startswith("dest_"):
        dest = data[5:]
        ctx.user_data["dest"] = dest
        if dest == "Italia" and not STRIPE:
            await q.answer(NO_PAY, show_alert=True)
            return
        await q.message.reply_text("👤 نام و نام خانوادگی / Nome e cognome:")
        return NAME  # hand over to ConversationHandler

# ───────────── Form steps
async def step_name(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = u.message.text.strip()
    if not name:
        await u.message.reply_text("❌ نام نمی‌تواند خالی باشد. / Inserisci il nome:")
        return NAME
    ctx.user_data["name"] = name
    await u.message.reply_text("📍 آدرس کامل / Indirizzo completo:")
    return ADDRESS

async def step_address(u, ctx):
    addr = u.message.text.strip()
    if not addr:
        await u.message.reply_text("❌ آدرس نمی‌تواند خالی باشد. / Inserisci l’indirizzo:")
        return ADDRESS
    ctx.user_data["address"] = addr
    if ctx.user_data["dest"] == "Italia":
        await u.message.reply_text("🔢 کد پستی (۵ رقم) / CAP (5 cifre):")
        return POSTAL
    await u.message.reply_text("☎️ شماره تلفن / Numero di telefono:")
    return PHONE

async def step_postal(u, ctx):
    p = u.message.text.strip()
    if not (p.isdigit() and len(p) == 5):
        await u.message.reply_text("❌ کد پستی ۵ رقمی وارد کنید / CAP di 5 cifre:")
        return POSTAL
    ctx.user_data["postal"] = p
    await u.message.reply_text("☎️ شماره تلفن / Numero di telefono:")
    return PHONE

async def step_phone(u, ctx):
    ph = u.message.text.strip()
    if not ph.replace("+", "").replace(" ", "").isdigit():
        await u.message.reply_text("❌ شماره معتبر نیست. / Numero non valido:")
        return PHONE
    ctx.user_data["phone"] = ph
    await u.message.reply_text("📝 یادداشت (اختیاری) / Note (opzionale):")
    return NOTES

async def step_notes(u, ctx):
    ctx.user_data["notes"] = u.message.text if u.message.text else "-"
    status = "COD"  # Cash on Delivery
    # If Italy -> send invoice
    if ctx.user_data["dest"] == "Italia":
        amt = int(ctx.user_data["total"] * 100)
        status = "Pending"
        await u.message.reply_invoice(
            title="سفارش بازارینو / Ordine Bazarino",
            description="پرداخت سفارش / Pagamento ordine",
            payload=f"order-{uuid.uuid4()}",
            provider_token=STRIPE,
            currency="EUR",
            prices=[LabeledPrice("سبد خرید / Carrello", amt)],
            start_parameter="bazarino-payment",
        )
    else:
        await u.message.reply_text(
            "✅ سفارش ثبت شد؛ به زودی تماس می‌گیریم.\n"
            "Ordine registrato! Ti contatteremo a breve.",
            reply_markup=ReplyKeyboardRemove()
        )
    await save_order(u, ctx, status)
    return ConversationHandler.END

# ───────────── Save order to Sheet & notify admin
async def save_order(u: Update, ctx: ContextTypes.DEFAULT_TYPE, status: str):
    cart = ctx.user_data["cart"]
    items, total = [], 0.0
    for it in cart:
        p = PRODUCTS[it["code"]]
        cost = p["price"] * it["quantity"]
        total += cost
        items.append(f"{p['fa']}×{it['quantity']} (€{cost:.2f})")

    row = [
        dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        u.effective_chat.id,
        f"@{u.effective_user.username}" if u.effective_user.username else "-",
        ctx.user_data["dest"],
        ", ".join(items),
        f"{total:.2f}",
        ctx.user_data["name"],
        ctx.user_data["address"],
        ctx.user_data.get("postal", "-"),
        ctx.user_data["phone"],
        ctx.user_data["notes"],
        status,
    ]
    await asyncio.get_running_loop().run_in_executor(None, partial(sheet.append_row, row))
    ctx.user_data.clear()

    if ADMIN_ID:
        admin_txt = (
            "📥 سفارش جدید / Nuovo ordine\n\n"
            f"🏷 مقصد/Dest.: {row[3]}\n"
            f"📦 {row[4]}\n💰 €{row[5]}\n"
            f"👤 {row[6]}\n"
            f"📍 {row[7]} {row[8]}\n"
            f"☎️ {row[9]}\n"
            f"📝 {row[10]}\n"
            f"وضعیت/Stato: {status}"
        )
        await u.get_bot().send_message(ADMIN_ID, admin_txt)

# ───────────── Payment callbacks
async def precheckout(update: Update, _):
    await update.pre_checkout_query.answer(ok=True)

async def paid(update: Update, _):
    await update.message.reply_text(
        "💳 پرداخت موفق! سفارش ثبت شد.\nPagamento riuscito!",
        reply_markup=ReplyKeyboardRemove()
    )

# ───────────── Cancel
async def cancel(u, ctx):
    ctx.user_data.clear()
    await u.message.reply_text("⛔️ سفارش لغو شد / Ordine annullato.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ───────────── Commands
async def cmd_start(u, ctx):   await u.message.reply_html(WELCOME, reply_markup=kb_main(ctx))
async def cmd_about(u, _):     await u.message.reply_text(ABOUT)
async def cmd_privacy(u, _):   await u.message.reply_text(PRIVACY)

# ───────────── Error-handler (NEW)
async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    if isinstance(ctx.error, BadRequest) and "Message is not modified" in str(ctx.error):
        return  # silently ignore
    log.error("Unhandled exception: %s", ctx.error)

# ───────────── Main
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # basic cmds
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("privacy", cmd_privacy))

    # callback router (non-form)
    app.add_handler(CallbackQueryHandler(
        router,
        pattern="^(back_|cat_|prd_|add_|show_cart|clear_cart|checkout)$"
    ))

    # conversation for order form (dest_)
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(router, pattern="^dest_")],
        states={
            NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, step_name)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_address)],
            POSTAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, step_postal)],
            PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_phone)],
            NOTES:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    # payment
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))

    # error handler (NEW)
    app.add_error_handler(error_handler)

    # ───── webhook (Render: respect $PORT)
    port = int(os.getenv("PORT", "8080"))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}",
    )

if __name__ == "__main__":
    main()
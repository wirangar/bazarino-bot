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
from telegram.error import BadRequest

# ───────────── Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bazarino")

# ───────────── ENV
TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = os.getenv("BASE_URL")  # e.g. https://bazarino-bot.onrender.com
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))  # optional
CREDS_PATH = os.getenv("GOOGLE_CREDS")  # path to json OR …
CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")  # … raw json string
STRIPE = os.getenv("PAYMENT_PROVIDER_TOKEN")  # optional
SHEET_NAME = "Bazarnio Orders"

# Validate essential environment variables
if not TOKEN or not BASE_URL:
    raise SystemExit("❗️ TELEGRAM_TOKEN و BASE_URL باید تنظیم شوند.")

# ───────────── Google-Sheets
if CREDS_PATH and os.path.isfile(CREDS_PATH):
    try:
        with open(CREDS_PATH, encoding="utf-8") as f:
            creds_info = json.load(f)
    except Exception as e:
        raise SystemExit(f"❗️ Error loading Google credentials from file: {e}")
elif CREDS_JSON:
    try:
        creds_info = json.loads(CREDS_JSON)
    except json.JSONDecodeError as e:
        raise SystemExit(f"❗️ Error parsing GOOGLE_CREDS_JSON: {e}")
else:
    raise SystemExit("❗️ GOOGLE_CREDS یا GOOGLE_CREDS_JSON باید تنظیم شود.")

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
try:
    sheet = gspread.authorize(
        ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
    ).open(SHEET_NAME).sheet1
    log.info("✅ Google-Sheets connected")
except Exception as e:
    raise SystemExit(f"❗️ Error connecting to Google Sheets: {e}")

# ───────────── Conversation states
NAME, ADDRESS, POSTAL, PHONE, NOTES = range(5)

# ───────────── Safe-edit helper
async def safe_edit(q, *args, **kwargs):
    """ویرایش امن پیام CallbackQuery؛ خطای «Message is not modified» را مدیریت می‌کند."""
    try:
        await q.edit_message_text(*args, **kwargs)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await q.answer("⚠️ تغییری ندارد.", show_alert=False)
        else:
            log.error(f"Error editing message for user {q.from_user.id}: {e}", exc_info=True)
            await q.answer("❌ خطایی در ویرایش پیام رخ داد.", show_alert=True)
            try:
                await q.message.chat.send_message(*args, **kwargs)
            except Exception as e:
                log.error(f"Failed to send fallback message for user {q.from_user.id}: {e}")

# ───────────── Data: categories & products
CATEGORIES: Dict[str, str] = {
    "rice": "🍚 برنج / Riso",
    "beans": "🥣 حبوبات / Legumi",
    "spice": "🌿 ادویه / Spezie",
    "nuts": "🥜 خشکبار / Frutta secca",
    "drink": "🧃 نوشیدنی / Bevande",
    "canned": "🥫 کنسرو / Conserve",
}

UNSPLASH = "https://images.unsplash.com/"
def unsplash(code: str) -> str:
    return f"{UNSPLASH}{code}?auto=format&fit=crop&w=800&q=60"

PRODUCTS: Dict[str, Dict[str, Any]] = {
    # --- RICE ---
    "rice_hashemi": {
        "cat": "rice", "fa": "برنج هاشمی", "it": "Riso Hashemi", "brand": "فجر / Fajr",
        "desc": "عطر بالا، محصول مازندران / Profumato – Mazandaran", "weight": "1 kg", "price": 6.00,
        "image_url": unsplash("photo-1518977956817-93be35d8d5df"),
    },
    "rice_tarem": {
        "cat": "rice", "fa": "برنج طارم", "it": "Riso Tarem", "brand": "گلستان / Golestan",
        "desc": "دانه‌بلند گیلان / Chicco lungo – Gilan", "weight": "1 kg", "price": 5.50,
        "image_url": unsplash("photo-1572501535324-b336c9b5fb44"),
    },
    # --- BEANS ---
    "beans_lentil": {
        "cat": "beans", "fa": "عدس سبز", "it": "Lenticchie verdi", "brand": "رویا / Roya",
        "desc": "درجه یک / Prima scelta", "weight": "1 kg", "price": 4.00,
        "image_url": unsplash("photo-1607619056575-0d0e0dbffa8b"),
    },
    "beans_red": {
        "cat": "beans", "fa": "لوبیا قرمز", "it": "Fagioli rossi", "brand": "یک‌ویک / Yek-o-Yek",
        "desc": "تازه و یکدست / Freschi", "weight": "1 kg", "price": 4.20,
        "image_url": unsplash("photo-1523986371872-9d3ba2e2f911"),
    },
    "beans_chickpea": {
        "cat": "beans", "fa": "نخود", "it": "Ceci", "brand": "آوا / Ava",
        "desc": "نخود کرمانشاه / Ceci Kermanshah", "weight": "1 kg", "price": 3.80,
        "image_url": unsplash("photo-1608515171304-28045997d813"),
    },
    # --- SPICE ---
    "spice_mint": {
        "cat": "spice", "fa": "نعناع خشک", "it": "Menta secca", "brand": "گلها / Golha",
        "desc": "۱۰۰٪ طبیعی / 100 % naturale", "weight": "100 g", "price": 2.50,
        "image_url": unsplash("photo-1580910051070-14ddcdf2216c"),
    },
    "spice_cinnamon": {
        "cat": "spice", "fa": "دارچین", "it": "Cannella", "brand": "سحرخیز / Saffron Sahar",
        "desc": "پودر دارچین سیلان / Polvere di Ceylon", "weight": "100 g", "price": 3.00,
        "image_url": unsplash("photo-1601004890684-d8cbf643f5f2"),
    },
    "spice_turmeric": {
        "cat": "spice", "fa": "زردچوبه", "it": "Curcuma", "brand": "گلستان / Golestan",
        "desc": "زردچوبه خالص / Pura e fresca", "weight": "250 g", "price": 3.50,
        "image_url": unsplash("photo-1568600891621-2cdb83312f04"),
    },
    "spice_saffron": {
        "cat": "spice", "fa": "زعفران ایرانی", "it": "Zafferano", "brand": "قائنات / Qaenat",
        "desc": "زعفران ممتاز نیم‌گرمی / 0.5 g Premium", "weight": "0.5 g", "price": 6.00,
        "image_url": unsplash("photo-1601315577115-3b0a639f6a22"),
    },
    # --- NUTS ---
    "nuts_pistachio": {
        "cat": "nuts", "fa": "پسته احمدآقایی", "it": "Pistacchio", "brand": "گلپایگان / Golpayegan",
        "desc": "برشته و نمکی / Tostato salato", "weight": "500 g", "price": 12.00,
        "image_url": unsplash("photo-1560199007-14ddcdf2216c"),
    },
    "nuts_dates": {
        "cat": "nuts", "fa": "خرمای مضافتی", "it": "Datteri", "brand": "بم / Bam",
        "desc": "خرما تازه جنوب / Freschi", "weight": "600 g", "price": 5.50,
        "image_url": unsplash("photo-1571997478779-2fd561c7c328"),
    },
    "nuts_sunflower": {
        "cat": "nuts", "fa": "تخمه آفتابگردان", "it": "Semi di girasole", "brand": "گلستان / Golestan",
        "desc": "بو‌داده و نمکی / Salati", "weight": "250 g", "price": 2.80,
        "image_url": unsplash("photo-1587049352852-61015c24336e"),
    },
    "nuts_raisin": {
        "cat": "nuts", "fa": "کشمش پلویی", "it": "Uvetta", "brand": "زعفران‌زار / Zafaranzar",
        "desc": "کشمش طلایی درجه یک / Prima scelta", "weight": "300 g", "price": 3.90,
        "image_url": unsplash("photo-1606041008023-65e6a85a72da"),
    },
    # --- DRINK ---
    "drink_dough_abali": {
        "cat": "drink", "fa": "دوغ آبعلی", "it": "Doogh Abali", "brand": "آبعلی / Ab-Ali",
        "desc": "دوغ گازدار طعم‌دار / Frizzante", "weight": "1.5 L", "price": 2.80,
        "image_url": unsplash("photo-1581382574490-206d48e3d04c"),
    },
    "drink_dough_plain": {
        "cat": "drink", "fa": "دوغ ساده", "it": "Doogh classico", "brand": "کاله / Kaleh",
        "desc": "دوغ بدون گاز / Naturale", "weight": "1.5 L", "price": 2.50,
        "image_url": unsplash("photo-1601382042802-3b32f409c869"),
    },
    "drink_dough_golpar": {
        "cat": "drink", "fa": "دوغ با گلپر", "it": "Doogh al Golpar", "brand": "کاله / Kaleh",
        "desc": "دوغ سنتی با گلپر / Tradizionale", "weight": "1.5 L", "price": 2.90,
        "image_url": unsplash("photo-1620943100637-d731c9fe3314"),
    },
    # --- CANNED ---
    "can_fruit_mix": {
        "cat": "canned", "fa": "کمپوت میوه مخلوط", "it": "Macedonia", "brand": "یک‌ویک / Yek-o-Yek",
        "desc": "کمپوت مخلوط میوه / Frutta mista", "weight": "420 g", "price": 3.20,
        "image_url": unsplash("photo-1608219959305-65e6a85a72da"),
    },
    "can_fesenjan": {
        "cat": "canned", "fa": "کنسرو فسنجون", "it": "Fesenjan", "brand": "ماهیدس / Mahidas",
        "desc": "خورشت فسنجون آماده / Pronto da scaldare", "weight": "380 g", "price": 4.50,
        "image_url": unsplash("photo-1568051243857-0b835e253f54"),
    },
    "can_eggplant": {
        "cat": "canned", "fa": "کنسرو خورشت بادمجان", "it": "Khoresh Bademjan", "brand": "ماهیدس / Mahidas",
        "desc": "خورشت بادمجان آماده / Pronto da scaldare", "weight": "380 g", "price": 4.30,
        "image_url": unsplash("photo-1589301760014-d929f3979dbc"),
    },
    "can_gheimeh": {
        "cat": "canned", "fa": "کنسرو قیمه", "it": "Gheymeh", "brand": "ماهیدس / Mahidas",
        "desc": "خورشت قیمه آماده / Pronto da scaldare", "weight": "380 g", "price": 4.30,
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

NO_PAY = "❌ پرداخت آنلاین فعال نیست؛ لطفاً گزینهٔ نقدی (پروجا) را انتخاب کنید."
CART_EMPTY = "سبد خرید شما خالی است. / Il carrello è vuoto."

# ───────────── Helpers ▸ Keyboards
def cart_count(ctx) -> int:
    return sum(item["quantity"] for item in ctx.user_data.get("cart", []))

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
    user_id = q.from_user.id
    log.info(f"Router received callback: {data} from user {user_id}")
    await q.answer()

    if data == "back_main":
        await safe_edit(q, WELCOME, reply_markup=kb_main(ctx), parse_mode="HTML")
        return

    if data.startswith("back_"):
        cat = data[5:]
        if cat not in CATEGORIES:
            log.warning(f"Invalid category '{cat}' in back_ callback from user {user_id}")
            await q.message.reply_text("❌ دسته‌بندی نامعتبر است.")
            return
        await safe_edit(q, CATEGORIES[cat], reply_markup=kb_category(cat, ctx))
        return

    if data.startswith("cat_"):
        cat = data[4:]
        if cat not in CATEGORIES:
            log.warning(f"Invalid category '{cat}' in cat_ callback from user {user_id}")
            await q.message.reply_text("❌ دسته‌بندی نامعتبر است.")
            return
        await safe_edit(q, CATEGORIES[cat], reply_markup=kb_category(cat, ctx))
        return

    if data.startswith("prd_"):
        code = data[4:]
        if code not in PRODUCTS:
            log.warning(f"Invalid product code '{code}' in prd_ callback from user {user_id}")
            await q.message.reply_text("❌ محصول مورد نظر یافت نشد.")
            return

        p = PRODUCTS[code]
        caption = (
            f"<b>{p['fa']} / {p['it']}</b>\n"
            f"🏷 برند/Marca: {p['brand']}\n"
            f"📄 {p['desc']}\n"
            f"⚖️ وزن/Peso: {p['weight']}\n"
            f"💶 قیمت/Prezzo: €{p['price']:.2f}"
        )

        try:
            if q.message.photo:
                await q.edit_message_caption(caption=caption, parse_mode="HTML", reply_markup=kb_product(code))
            else:
                await q.message.delete()
                await q.message.chat.send_photo(
                    photo=p["image_url"], caption=caption, parse_mode="HTML", reply_markup=kb_product(code)
                )
        except BadRequest as e:
            log.error(f"Error handling product display for {code} by user {user_id}: {e}")
            await q.message.reply_text("❌ خطایی در نمایش محصول رخ داد.")
        return

    if data.startswith("add_"):
        code = data[4:]
        cart: List[Dict[str, Any]] = ctx.user_data.setdefault("cart", [])

        if code not in PRODUCTS:
            log.warning(f"Attempted to add non-existent product '{code}' to cart by user {user_id}")
            await q.answer("❌ محصول مورد نظر یافت نشد.", show_alert=True)
            return

        for item in cart:
            if item["code"] == code:
                item["quantity"] += 1
                break
        else:
            cart.append({"code": code, "quantity": 1})

        await q.message.reply_text("✅ به سبد افزوده شد. / Aggiunto al carrello.")
        await safe_edit(q, WELCOME, reply_markup=kb_main(ctx), parse_mode="HTML")
        return

    if data == "show_cart":
        cart = ctx.user_data.get("cart", [])
        if not cart:
            await safe_edit(q, CART_EMPTY, reply_markup=kb_main(ctx))
            return

        total, text = 0.0, "🛒 <b>سبد خرید / Carrello:</b>\n"
        for item in cart:
            p = PRODUCTS.get(item["code"])
            if p:
                cost = p["price"] * item["quantity"]
                total += cost
                text += f"• {p['fa']} × {item['quantity']} = €{cost:.2f}\n"
            else:
                log.warning(f"Product '{item['code']}' in cart but not found in PRODUCTS data for user {user_id}")
                cart.remove(item)

        text += f"\n<b>مجموع / Totale: €{total:.2f}</b>"
        ctx.user_data["total"] = total
        await safe_edit(q, text, parse_mode="HTML", reply_markup=kb_cart())
        return

    if data == "clear_cart":
        ctx.user_data.clear()
        await safe_edit(q, "🗑️ سبد خرید خالی شد. / Carrello svuotato.", reply_markup=kb_main(ctx))
        return

    if data == "checkout":
        if not ctx.user_data.get("cart"):
            await q.answer("سبد خالی است.", show_alert=True)
            return
        await safe_edit(
            q,
            "نحوهٔ تحویل و پرداخت را انتخاب کنید:\nScegli modalità di consegna/pagamento:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 پروجا (نقدی) / Perugia (contanti)", callback_data="dest_Perugia")],
                [InlineKeyboardButton("📦 ایتالیا (آنلاین) / Italia (online)", callback_data="dest_Italia")],
            ])
        )
        return

# ───────────── Form steps (ConversationHandler states)
async def start_form(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    data = q.data
    user_id = q.from_user.id
    log.info(f"start_form initiated for user {user_id} with data: {data}")
    await q.answer()

    dest = data[5:]
    ctx.user_data["dest"] = dest

    if dest == "Italia" and not STRIPE:
        await q.message.reply_text(NO_PAY)
        return ConversationHandler.END

    await q.message.reply_text("👤 نام و نام خانوادگی / Nome e cognome:", reply_markup=ReplyKeyboardRemove())
    return NAME

async def step_name(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = u.message.text.strip()
    if not name:
        await u.message.reply_text("❌ نام نمی‌تواند خالی باشد. / Inserisci il nome:")
        return NAME
    ctx.user_data["name"] = name
    await u.message.reply_text("📍 آدرس کامل / Indirizzo completo:")
    return ADDRESS

async def step_address(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

async def step_postal(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    p = u.message.text.strip()
    if not (p.isdigit() and len(p) == 5):
        await u.message.reply_text("❌ کد پستی ۵ رقمی وارد کنید / CAP di 5 cifre:")
        return POSTAL
    ctx.user_data["postal"] = p
    await u.message.reply_text("☎️ شماره تلفن / Numero di telefono:")
    return PHONE

async def step_phone(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ph = u.message.text.strip()
    if not all(char.isdigit() or char == '+' or char == ' ' for char in ph) or not any(char.isdigit() for char in ph):
        await u.message.reply_text("❌ شماره معتبر نیست. / Numero non valido:")
        return PHONE
    ctx.user_data["phone"] = ph
    await u.message.reply_text("📝 یادداشت (اختیاری) / Note (opzionale):")
    return NOTES

async def step_notes(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["notes"] = u.message.text if u.message.text else "-"

    if not ctx.user_data.get("cart"):
        log.error(f"Cart empty during step_notes for user {u.effective_user.id}")
        await u.message.reply_text("❌ سبد خرید شما خالی است.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    status = "COD"
    if ctx.user_data["dest"] == "Italia":
        if not STRIPE:
            await u.message.reply_text(NO_PAY, reply_markup=ReplyKeyboardRemove())
            ctx.user_data.clear()
            return ConversationHandler.END

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
            "✅ سفارش ثبت شد؛ به زودی تماس می‌گیریم.\nOrdine registrato!",
            reply_markup=ReplyKeyboardRemove()
        )

    await save_order(u, ctx, status)
    return ConversationHandler.END

# ───────────── Save order to Sheet & notify admin
async def save_order(u: Update, ctx: ContextTypes.DEFAULT_TYPE, status: str):
    cart = ctx.user_data.get("cart", [])
    if not cart:
        log.error(f"Attempted to save empty cart for user {u.effective_chat.id}")
        return

    items_summary, total = [], 0.0
    for item in cart:
        p = PRODUCTS.get(item["code"])
        if p:
            cost = p["price"] * item["quantity"]
            total += cost
            items_summary.append(f"{p['fa']}×{item['quantity']} (€{cost:.2f})")
        else:
            log.warning(f"Product '{item['code']}' not found for user {u.effective_chat.id}")

    order_id = str(uuid.uuid4())
    row = [
        dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        order_id,
        u.effective_chat.id,
        f"@{u.effective_user.username}" if u.effective_user.username else "-",
        ctx.user_data.get("dest", "N/A"),
        ", ".join(items_summary),
        f"{total:.2f}",
        ctx.user_data.get("name", "N/A"),
        ctx.user_data.get("address", "N/A"),
        ctx.user_data.get("postal", "-"),
        ctx.user_data.get("phone", "N/A"),
        ctx.user_data.get("notes", "-"),
        status,
    ]

    log.info(f"Saving order {order_id} for user {u.effective_chat.id}")
    try:
        await asyncio.get_running_loop().run_in_executor(None, partial(sheet.append_row, row))
        log.info(f"Order {order_id} saved")
        ctx.user_data.clear()
    except Exception as e:
        log.error(f"Failed to save order {order_id}: {e}")
        if status == "COD":
            await u.message.reply_text("❌ خطایی در ثبت سفارش رخ داد.", reply_markup=ReplyKeyboardRemove())
        return

    if ADMIN_ID:
        admin_txt = (
            f"📥 سفارش جدید / Nuovo ordine\n\n"
            f"ID سفارش/Order ID: `{order_id}`\n"
            f"🏷 مقصد/Dest.: {row[4]}\n"
            f"📦 {row[5]}\n💰 €{row[6]}\n"
            f"👤 {row[7]}\n"
            f"📍 {row[8]} {row[9]}\n"
            f"☎️ {row[10]}\n"
            f"📝 {row[11]}\n"
            f"وضعیت/Stato: {status}\n"
            f"User: @{u.effective_user.username or u.effective_user.id}"
        )
        try:
            await u.get_bot().send_message(ADMIN_ID, admin_txt, parse_mode="MarkdownV2")
            log.info(f"Admin notified for order {order_id}")
        except Exception as e:
            log.error(f"Failed to notify admin for order {order_id}: {e}")

# ───────────── Payment callbacks
async def precheckout(update: Update, _: ContextTypes.DEFAULT_TYPE):
    log.info(f"Pre-checkout query from user {update.pre_checkout_query.from_user.id}")
    if STRIPE:
        await update.pre_checkout_query.answer(ok=True)
    else:
        await update.pre_checkout_query.answer(ok=False, error_message=NO_PAY)

async def paid(update: Update, _: ContextTypes.DEFAULT_TYPE):
    order_payload = update.message.successful_payment.invoice_payload
    order_uuid = order_payload.replace("order-", "")
    log.info(f"Payment successful for order {order_uuid} from user {update.message.from_user.id}")
    await update.message.reply_text(
        "💳 پرداخت موفق! سفارش در حال پردازش است.\nPagamento riuscito!",
        reply_markup=ReplyKeyboardRemove()
    )
    if ADMIN_ID:
        try:
            admin_msg = (
                f"✅ پرداخت موفقیت‌آمیز برای سفارش `{order_uuid}` از طرف "
                f"@{update.message.from_user.username or update.message.from_user.id}"
            )
            await update.get_bot().send_message(ADMIN_ID, admin_msg, parse_mode="MarkdownV2")
        except Exception as e:
            log.error(f"Failed to notify admin about payment: {e}")

# ───────────── Cancel
async def cancel(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await u.message.reply_text("⛔️ سفارش لغو شد / Ordine annullato.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ───────────── Commands
async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log.info(f"Start command received from user {u.effective_user.id}")
    await u.message.reply_html(WELCOME, reply_markup=kb_main(ctx))

async def cmd_about(u: Update, _: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(ABOUT)

async def cmd_privacy(u: Update, _: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(PRIVACY)

# ───────────── Error-handler
async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Exception while handling update:", exc_info=ctx.error)
    if isinstance(ctx.error, BadRequest) and "Message is not modified" in str(ctx.error):
        return
    if update and hasattr(update, "effective_chat") and update.effective_chat:
        try:
            await update.effective_chat.send_message(
                "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید."
            )
        except Exception as e:
            log.error(f"Failed to send error message to user {update.effective_chat.id}: {e}")

# ───────────── Main application setup
def main():
    log.info("Starting Bazarino Telegram Bot...")
    app = ApplicationBuilder().token(TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("privacy", cmd_privacy))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_form, pattern="^dest_")],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_name)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_address)],
            POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_postal)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_phone)],
            NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,  # Changed to False to avoid PTBUserWarning
    )
    app.add_handler(conv)

    app.add_handler(CallbackQueryHandler(
        router,
        pattern="^(back_|cat_|prd_|add_|show_cart|clear_cart|checkout)$"
    ))

    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))

    # Register error handler correctly
    app.add_error_handler(error_handler)

    port = int(os.getenv("PORT", "8080"))
    webhook_url = f"{BASE_URL}/{TOKEN}"
    log.info(f"Setting webhook: listen=0.0.0.0:{port}, url_path=/{TOKEN}, webhook_url={webhook_url}")

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=webhook_url,
    )
    log.info("Bazarino Telegram Bot started successfully.")

if __name__ == "__main__":
    main()
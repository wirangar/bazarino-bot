#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – FINAL (multi-product cart, Google Sheets, Stripe)
"""

from __future__ import annotations
import asyncio, datetime as dt, html, json, logging, os, textwrap, uuid
from functools import partial
from typing import Dict, Any

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
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bazarino")

# ─────────── ENV
TOKEN      = os.getenv("TELEGRAM_TOKEN")
BASE_URL   = os.getenv("BASE_URL")
ADMIN_ID   = int(os.getenv("ADMIN_CHAT_ID", "0"))
CREDS_PATH = os.getenv("GOOGLE_CREDS")
CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
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

PRODUCTS: Dict[str, Dict[str, Any]] = {
    # --- RICE ---
    "rice_hashemi": {
        "cat": "rice",
        "fa": "برنج هاشمی",
        "it": "Riso Hashemi",
        "desc": "برنج عطری ایرانی مناسب پخت روزانه.",
        "brand": "گلستان",
        "weight": "1 kg",
        "price": 6.00,
        "image_url": "",  # لینک Imgur را اینجا بگذار
    },
    "rice_tarem": {
        "cat": "rice",
        "fa": "برنج طارم",
        "it": "Riso Tarem",
        "desc": "دانه بلند محصول گیلان.",
        "brand": "فجر",
        "weight": "1 kg",
        "price": 5.50,
        "image_url": "",
    },

    # --- BEANS ---
    "beans_lentil": {
        "cat": "beans",
        "fa": "عدس سبز",
        "it": "Lenticchie",
        "desc": "عدس سبز درجه یک.",
        "brand": "رویا",
        "weight": "1 kg",
        "price": 4.00,
        "image_url": "",
    },
    "beans_red": {
        "cat": "beans",
        "fa": "لوبیا قرمز",
        "it": "Fagioli Rossi",
        "desc": "لوبیا قرمز تازه.",
        "brand": "یک‌ویک",
        "weight": "1 kg",
        "price": 4.20,
        "image_url": "",
    },
    "beans_chickpea": {
        "cat": "beans",
        "fa": "نخود",
        "it": "Ceci",
        "desc": "نخود کرمانشاه.",
        "brand": "آوا",
        "weight": "1 kg",
        "price": 3.80,
        "image_url": "",
    },

    # --- SPICE ---
    "spice_mint": {
        "cat": "spice",
        "fa": "نعناع خشک",
        "it": "Menta secca",
        "desc": "نعناع خشک ۱۰۰٪ طبیعی.",
        "brand": "گلها",
        "weight": "100 g",
        "price": 2.50,
        "image_url": "",
    },
    "spice_cinnamon": {
        "cat": "spice",
        "fa": "دارچین",
        "it": "Cannella",
        "desc": "پودر دارچین خالص.",
        "brand": "سحرخیز",
        "weight": "100 g",
        "price": 3.00,
        "image_url": "",
    },
    "spice_turmeric": {
        "cat": "spice",
        "fa": "زردچوبه",
        "it": "Curcuma",
        "desc": "زردچوبه مرغوب.",
        "brand": "گلستان",
        "weight": "250 g",
        "price": 3.50,
        "image_url": "",
    },
    "spice_saffron": {
        "cat": "spice",
        "fa": "زعفران ایرانی",
        "it": "Zafferano",
        "desc": "نیم گرم زعفران ممتاز.",
        "brand": "قائنات",
        "weight": "0.5 g",
        "price": 6.00,
        "image_url": "",
    },

    # --- NUTS ---
    "nuts_pistachio": {
        "cat": "nuts",
        "fa": "پسته احمدآقایی",
        "it": "Pistacchio",
        "desc": "برشته و نمکی.",
        "brand": "گلپایگان",
        "weight": "500 g",
        "price": 12.00,
        "image_url": "",
    },
    "nuts_dates": {
        "cat": "nuts",
        "fa": "خرمای مضافتی",
        "it": "Datteri",
        "desc": "خرمای تازه جنوب.",
        "brand": "بم",
        "weight": "600 g",
        "price": 5.50,
        "image_url": "",
    },
    "nuts_sunflower": {
        "cat": "nuts",
        "fa": "تخمه آفتابگردان",
        "it": "Semi di Girasole",
        "desc": "بوداده و نمکی.",
        "brand": "گلستان",
        "weight": "250 g",
        "price": 2.80,
        "image_url": "",
    },
    "nuts_raisin": {
        "cat": "nuts",
        "fa": "کشمش پلویی",
        "it": "Uvetta",
        "desc": "کشمش طلایی درجه یک.",
        "brand": "زعفران‌زار",
        "weight": "300 g",
        "price": 3.90,
        "image_url": "",
    },

    # --- DRINK ---
    "drink_dough_abali": {
        "cat": "drink",
        "fa": "دوغ آبعلی",
        "it": "Doogh Abali",
        "desc": "دوغ گازدار طعم‌دار.",
        "brand": "آبعلی",
        "weight": "1.5 L",
        "price": 2.80,
        "image_url": "",
    },
    "drink_dough_plain": {
        "cat": "drink",
        "fa": "دوغ ساده",
        "it": "Doogh",
        "desc": "دوغ بدون گاز.",
        "brand": "کاله",
        "weight": "1.5 L",
        "price": 2.50,
        "image_url": "",
    },
    "drink_dough_golpar": {
        "cat": "drink",
        "fa": "دوغ با گلپر",
        "it": "Doogh al Golpar",
        "desc": "دوغ سنتی با گلپر.",
        "brand": "کاله",
        "weight": "1.5 L",
        "price": 2.90,
        "image_url": "",
    },

    # --- CANNED ---
    "can_fruit_mix": {
        "cat": "canned",
        "fa": "کمپوت میوه مخلوط",
        "it": "Macedonia",
        "desc": "کمپوت مخلوط میوه.",
        "brand": "یک‌ویک",
        "weight": "420 g",
        "price": 3.20,
        "image_url": "",
    },
    "can_fesenjan": {
        "cat": "canned",
        "fa": "کنسرو فسنجون",
        "it": "Fesenjan",
        "desc": "خورشت فسنجون آماده.",
        "brand": "ماهیدس",
        "weight": "380 g",
        "price": 4.50,
        "image_url": "",
    },
    "can_eggplant": {
        "cat": "canned",
        "fa": "کنسرو خورشت بادمجان",
        "it": "Khoresh Bademjan",
        "desc": "خورشت بادمجان آماده.",
        "brand": "ماهیدس",
        "weight": "380 g",
        "price": 4.30,
        "image_url": "",
    },
    "can_gheimeh": {
        "cat": "canned",
        "fa": "کنسرو قیمه",
        "it": "Gheymeh",
        "desc": "خورشت قیمه آماده.",
        "brand": "ماهیدس",
        "weight": "380 g",
        "price": 4.30,
        "image_url": "",
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

NO_PAY     = "❌ پرداخت آنلاین فعال نیست؛ لطفاً سفارش نقدی (پروجا) را انتخاب کنید."
CART_EMPTY = "سبد خرید شما خالی است."

# ─────────── keyboards
def cart_count(ctx): return sum(i["quantity"] for i in ctx.user_data.get("cart", []))

def kb_main(ctx):  # منوی اصلی
    rows = [[InlineKeyboardButton(v, callback_data=f"cat_{k}")]
            for k, v in CATEGORIES.items()]
    rows.append([InlineKeyboardButton(
        f"🛒 سبد خرید ({cart_count(ctx)})" if cart_count(ctx) else "🛒 سبد خرید",
        callback_data="show_cart")])
    return InlineKeyboardMarkup(rows)

def kb_category(cat, ctx):
    rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}",
                                  callback_data=f"prd_{code}")]
            for code, p in PRODUCTS.items() if p["cat"] == cat]
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_product(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن به سبد", callback_data=f"add_{code}")],
        [InlineKeyboardButton("⬅️ بازگشت",
                              callback_data=f"back_{PRODUCTS[code]['cat']}")],
    ])

def kb_cart():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تکمیل سفارش", callback_data="checkout")],
        [InlineKeyboardButton("🗑️ پاک کردن سبد", callback_data="clear_cart")],
        [InlineKeyboardButton("⬅️ ادامه خرید", callback_data="back_main")],
    ])

# ─────────── router
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data: str = q.data
    await q.answer()

    if data == "back_main":
        await q.edit_message_text(WELCOME, parse_mode="HTML",
                                  reply_markup=kb_main(ctx))
        return

    if data.startswith("back_"):
        cat = data[5:]
        await q.edit_message_text(CATEGORIES[cat],
                                  reply_markup=kb_category(cat, ctx))
        return

    if data.startswith("cat_"):
        cat = data[4:]
        await q.edit_message_text(CATEGORIES[cat],
                                  reply_markup=kb_category(cat, ctx))
        return

    if data.startswith("prd_"):  # نمایش کارت محصول
        code = data[4:]
        p = PRODUCTS[code]
        cap = (
            f"<b>{html.escape(p['fa'])} / {html.escape(p['it'])}</b>\n"
            f"برند/Marca: {html.escape(p['brand'])}\n"
            f"{html.escape(p['desc'])}\n"
            f"وزن/Peso: {p['weight']}\n"
            f"قیمت/Prezzo: €{p['price']:.2f}"
        )

        # ابتدا پیام جدید (عکس یا متن) بفرستیم
        if p["image_url"]:
            await q.message.chat.send_photo(
                p["image_url"], caption=cap, parse_mode="HTML",
                reply_markup=kb_product(code))
        else:
            await q.message.chat.send_message(
                cap, parse_mode="HTML", reply_markup=kb_product(code))
        # سپس پیام فهرست قبلی را حذف کنیم (در صورت امکان)
        try:
            await q.message.delete()
        except Exception:
            pass
        return

    if data.startswith("add_"):
        code = data[4:]
        cart = ctx.user_data.setdefault("cart", [])
        for it in cart:
            if it["code"] == code:
                it["quantity"] += 1
                break
        else:
            cart.append({"code": code, "quantity": 1})
        await q.message.reply_text("✅ به سبد افزوده شد.")
        # به‌روزرسانی شمارنده سبد در منوی اصلی
        await q.edit_message_reply_markup(kb_main(ctx))
        return

    if data == "show_cart":
        cart = ctx.user_data.get("cart", [])
        if not cart:
            await q.edit_message_text(CART_EMPTY, reply_markup=kb_main(ctx))
            return
        total = 0.0
        txt = "🛒 <b>سبد خرید:</b>\n"
        for it in cart:
            p = PRODUCTS[it["code"]]
            cost = p["price"] * it["quantity"]
            total += cost
            txt += f"• {p['fa']} × {it['quantity']} = €{cost:.2f}\n"
        txt += f"\n<b>مجموع: €{total:.2f}</b>"
        ctx.user_data["total"] = total
        await q.edit_message_text(txt, parse_mode="HTML",
                                  reply_markup=kb_cart())
        return

    if data == "clear_cart":
        ctx.user_data.clear()
        await q.edit_message_text("🗑️ سبد خرید خالی شد.",
                                  reply_markup=kb_main(ctx))
        return

    if data == "checkout":
        if not ctx.user_data.get("cart"):
            await q.answer("سبد خالی است.", show_alert=True)
            return
        await q.edit_message_text(
            "نحوه تحویل و پرداخت:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 پروجا (نقدی)",
                                      callback_data="dest_Perugia")],
                [InlineKeyboardButton("📦 ایتالیا (آنلاین)",
                                      callback_data="dest_Italia")],
            ])
        )
        return

    if data.startswith("dest_"):
        dest = data[5:]
        ctx.user_data["dest"] = dest
        if dest == "Italia" and not STRIPE:
            await q.answer(NO_PAY, show_alert=True)
            return
        await q.message.reply_text("👤 نام و نام خانوادگی:")
        return NAME

# ─────────── form steps
async def step_name(u, ctx):
    name = u.message.text.strip()
    if not name:
        await u.message.reply_text("❌ نام خالی است. دوباره:")
        return NAME
    ctx.user_data["name"] = name
    await u.message.reply_text("📍 آدرس کامل:")
    return ADDRESS

async def step_address(u, ctx):
    address = u.message.text.strip()
    if not address:
        await u.message.reply_text("❌ آدرس خالی است. دوباره:")
        return ADDRESS
    ctx.user_data["address"] = address
    if ctx.user_data["dest"] == "Italia":
        await u.message.reply_text("🔢 کد پستی (۵ رقم):")
        return POSTAL
    await u.message.reply_text("☎️ تلفن:")
    return PHONE

async def step_postal(u, ctx):
    p = u.message.text.strip()
    if not p.isdigit() or len(p) != 5:
        await u.message.reply_text("❌ کد پستی ۵ رقمی وارد کنید:")
        return POSTAL
    ctx.user_data["postal"] = p
    await u.message.reply_text("☎️ تلفن:")
    return PHONE

async def step_phone(u, ctx):
    ph = u.message.text.strip()
    if not ph.replace("+", "").replace(" ", "").isdigit():
        await u.message.reply_text("❌ شماره معتبر نیست. دوباره:")
        return PHONE
    ctx.user_data["phone"] = ph
    await u.message.reply_text("📝 یادداشت (اختیاری):")
    return NOTES

async def step_notes(u, ctx):
    ctx.user_data["notes"] = u.message.text or "-"
    status = "COD"
    if ctx.user_data["dest"] == "Italia":
        amt_cents = int(ctx.user_data["total"] * 100)
        await u.message.reply_invoice(
            title="سفارش بازارینو",
            description="پرداخت سفارش",
            payload=f"order-{uuid.uuid4()}",
            provider_token=STRIPE,
            currency="EUR",
            prices=[LabeledPrice("سبد خرید", amt_cents)],
        )
        status = "Pending"
    else:
        await u.message.reply_text("✅ سفارش ثبت شد؛ به‌زودی تماس می‌گیریم.",
                                   reply_markup=ReplyKeyboardRemove())
    await save_order(u, ctx, status)
    return ConversationHandler.END

# ─────────── save order
async def save_order(u, ctx, status):
    cart = ctx.user_data["cart"]
    summary, total = [], 0.0
    for it in cart:
        p = PRODUCTS[it["code"]]
        cost = p["price"] * it["quantity"]
        summary.append(f"{p['fa']}×{it['quantity']}(€{cost:.2f})")
        total += cost
    row = [
        dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        u.effective_chat.id,
        f"@{u.effective_user.username}" if u.effective_user.username else "-",
        ctx.user_data["dest"],
        ", ".join(summary),
        f"{total:.2f}",
        ctx.user_data["name"],
        ctx.user_data["address"],
        ctx.user_data.get("postal", "-"),
        ctx.user_data["phone"],
        ctx.user_data["notes"],
        status,
    ]
    await asyncio.get_running_loop().run_in_executor(
        None, partial(sheet.append_row, row))
    ctx.user_data.clear()
    if ADMIN_ID:
        await u.get_bot().send_message(
            ADMIN_ID,
            f"📥 سفارش جدید\n🏷 مقصد: {row[3]}\n📦 {row[4]}\n💰 €{row[5]}\n"
            f"👤 {row[6]}\n📍 {row[7]} {row[8]}\n☎️ {row[9]}\n📝 {row[10]}",
            parse_mode="HTML",
        )

# ─────────── payment
async def precheckout(update, _):  # تایید قبل از پرداخت
    await update.pre_checkout_query.answer(ok=True)

async def paid(update, _):  # پرداخت موفق
    await update.message.reply_text(
        "💳 پرداخت موفق! سفارش ثبت و در حال پردازش است.",
        reply_markup=ReplyKeyboardRemove())

# ─────────── cancel
async def cancel(u, ctx):
    ctx.user_data.clear()
    await u.message.reply_text("⛔️ سفارش لغو شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ─────────── commands
async def cmd_start(u, ctx):
    await u.message.reply_html(WELCOME, reply_markup=kb_main(ctx))

async def cmd_about(u, _): pass  # درباره‌ (در صورت نیاز اضافه کن)
async def cmd_privacy(u, _): pass  # حریم خصوصی

# ─────────── main
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("privacy", cmd_privacy))

    # تمام callback-ها را بپذیر
    app.add_handler(CallbackQueryHandler(router,
        pattern="^(back_|cat_|prd_|add_|show_cart|clear_cart|checkout|dest_).*$"))

    # فرم سفارش
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

    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}",
    )

if __name__ == "__main__":
    main()
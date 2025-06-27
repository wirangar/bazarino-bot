#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – final version with shopping cart
--------------------------------------------------------

• منوی دو‌زبانه (فارسی/ایتالیایی) + سبد چند‌محصولی.
• ذخیره سفارش در Google Sheets با وضعیت (Pending / COD).
• پرداخت تلگرامی (Stripe) برای مقصد «Italia».
• python-telegram-bot v20.7 - Python 3.11.
"""

from __future__ import annotations

import asyncio, datetime, json, logging, os, textwrap, uuid
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
logging.basicConfig(level=logging.INFO, format="%(asctime)s|%(levelname)s|%(message)s")
log = logging.getLogger("bazarino")

# ─────────── ENV
TOKEN  = os.getenv("TELEGRAM_TOKEN")
URL    = os.getenv("BASE_URL")
ADMIN  = int(os.getenv("ADMIN_CHAT_ID", "0"))
CREDS  = os.getenv("GOOGLE_CREDS_JSON")
STRIPE = os.getenv("PAYMENT_PROVIDER_TOKEN")
SHEET  = "Bazarnio Orders"

if not all([TOKEN, URL, CREDS]):
    raise SystemExit("❗️ TELEGRAM_TOKEN / BASE_URL / GOOGLE_CREDS_JSON must be set")

# ─────────── Google Sheets
scope  = ["https://spreadsheets.google.com/feeds",
          "https://www.googleapis.com/auth/drive"]
creds  = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(CREDS), scope)
sheet  = gspread.authorize(creds).open(SHEET).sheet1
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
    "rice_hashemi":  dict(cat="rice",  fa="برنج هاشمی", it="Riso Hashemi",
                          desc="عطر بالا / Profumato", weight="1 kg",
                          price=6.0, image_url="https://i.imgur.com/paddy.jpg"),
    "bean_lentil":   dict(cat="beans", fa="عدس", it="Lenticchie",
                          desc="عدس سبز / Lenticchie verdi", weight="1 kg",
                          price=4.0, image_url="https://i.imgur.com/lentil.jpg"),
}

# ─────────── texts
WELCOME = textwrap.dedent("""\
🍇 به بازارینو خوش آمدید! 🇮🇷🇮🇹
Benvenuto in Bazarino!
🏠 فروشگاه ایرانی‌های پروجا

👇 لطفاً یک دسته را انتخاب کنید:
""")
ABOUT   = "بازارینو توسط دانشجویان ایرانی در پروجا اداره می‌شود."
PRIVACY = "اطلاعات شما فقط برای پردازش سفارش استفاده می‌شود."
NO_PAY  = "❌ پرداخت آنلاین فعال نیست؛ لطفاً «سفارش پروجا» را انتخاب کنید."
CART_EMPTY = "سبد خرید شما خالی است."

# ─────────── helpers: keyboards
def cart_count(ctx) -> int:
    return sum(i["quantity"] for i in ctx.user_data.get("cart", []))

def kb_main(ctx) -> InlineKeyboardMarkup:
    btns = [[InlineKeyboardButton(lbl, callback_data=f"cat_{k}")]
            for k, lbl in CATEGORIES.items()]
    cnt  = cart_count(ctx)
    btns.append([InlineKeyboardButton(f"🛒 سبد خرید من ({cnt})" if cnt else "🛒 سبد خرید من",
                                      callback_data="show_cart")])
    return InlineKeyboardMarkup(btns)

def kb_category(cat, ctx) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"prd_{code}")]
            for code, p in PRODUCTS.items() if p["cat"] == cat]
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_product(code) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن به سبد خرید", callback_data=f"add_{code}")],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data=f"back_{PRODUCTS[code]['cat']}")],
    ])

def kb_cart() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تکمیل سفارش", callback_data="checkout")],
        [InlineKeyboardButton("🗑️ پاک کردن سبد", callback_data="clear_cart")],
        [InlineKeyboardButton("⬅️ ادامه خرید", callback_data="back_main")],
    ])

# ─────────── callback router
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q, uid = update.callback_query, update.effective_user.id
    await q.answer()
    data = q.data

    # navigation
    if data == "back_main":
        await q.edit_message_text(WELCOME, reply_markup=kb_main(ctx))
    elif data.startswith("back_"):
        cat = data[5:]
        await q.edit_message_text(CATEGORIES.get(cat, "❓"), reply_markup=kb_category(cat, ctx))
    elif data.startswith("cat_"):
        cat = data[4:]
        await q.edit_message_text(CATEGORIES.get(cat, "❓"), reply_markup=kb_category(cat, ctx))

    # show product
    elif data.startswith("prd_"):
        code = data[4:]; p = PRODUCTS[code]
        cap = f"<b>{p['fa']} / {p['it']}</b>\n{p['desc']}\nوزن: {p['weight']}\nقیمت: €{p['price']:.2f}"
        await q.message.delete()
        await q.message.chat.send_photo(p["image_url"], cap, parse_mode="HTML", reply_markup=kb_product(code))

    # add to cart
    elif data.startswith("add_"):
        code = data[4:]; cart = ctx.user_data.setdefault("cart", [])
        for item in cart:
            if item["code"] == code:
                item["quantity"] += 1; break
        else:
            cart.append(dict(code=code, quantity=1))
        await q.message.reply_text("✅ به سبد افزوده شد.")
        await q.edit_message_reply_markup(kb_main(ctx))

    # show cart
    elif data == "show_cart":
        if not ctx.user_data.get("cart"):
            await q.edit_message_text(CART_EMPTY, reply_markup=kb_main(ctx))
            return
        total, txt = 0.0, "🛒 <b>سبد خرید:</b>\n"
        for it in ctx.user_data["cart"]:
            p = PRODUCTS[it["code"]]; line = p['price']*it['quantity']; total += line
            txt += f"• {p['fa']} × {it['quantity']} = €{line:.2f}\n"
        txt += f"\n<b>مجموع: €{total:.2f}</b>"
        ctx.user_data["total"] = total
        await q.edit_message_text(txt, parse_mode="HTML", reply_markup=kb_cart())

    # clear cart
    elif data == "clear_cart":
        ctx.user_data.clear()
        await q.edit_message_text("🗑️ سبد خرید خالی شد.", reply_markup=kb_main(ctx))

    # checkout choose dest
    elif data == "checkout":
        if not ctx.user_data.get("cart"):
            await q.answer("سبد خالی است.", show_alert=True); return
        await q.edit_message_text(
            "نحوه تحویل و پرداخت را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 پروجا (نقدی)", callback_data="dest_Perugia")],
                [InlineKeyboardButton("📦 ایتالیا (آنلاین)", callback_data="dest_Italia")],
            ]))

    # start form
    elif data.startswith("dest_"):
        dest = data[5:]; ctx.user_data["dest"] = dest
        if dest == "Italia" and not STRIPE:
            await q.answer(NO_PAY, show_alert=True); return
        await q.message.reply_text("👤 نام و نام خانوادگی:")
        return NAME

# ─────────── form steps
async def step_name(u, ctx):    ctx.user_data["name"]=u.message.text.strip(); await u.message.reply_text("📍 آدرس:"); return ADDRESS
async def step_address(u, ctx): ctx.user_data["address"]=u.message.text.strip(); 
                                if ctx.user_data["dest"]=="Italia": await u.message.reply_text("🔢 کد پستی:"); return POSTAL
                                await u.message.reply_text("☎️ تلفن:"); return PHONE
async def step_postal(u, ctx):  p=u.message.text.strip(); 
                                if not p.isdigit() or len(p)!=5: await u.message.reply_text("❌ کد پستی ۵ رقمی وارد کنید:"); return POSTAL
                                ctx.user_data["postal"]=p; await u.message.reply_text("☎️ تلفن:"); return PHONE
async def step_phone(u, ctx):   ctx.user_data["phone"]=u.message.text.strip(); await u.message.reply_text("📝 یادداشت (اختیاری):"); return NOTES
async def step_notes(u, ctx):
    ctx.user_data["notes"]=u.message.text or "-"
    if ctx.user_data["dest"]=="Italia":
        amt=int(ctx.user_data["total"]*100)
        await u.message.reply_invoice(
            title="سفارش بازارینو", description="پرداخت سفارش",
            payload=f"order:{uuid.uuid4()}", provider_token=STRIPE,
            currency="EUR", prices=[LabeledPrice("سبد خرید", amt)])
        status="Pending"
    else:
        await u.message.reply_text("✅ سفارش ثبت شد؛ به‌زودی تماس می‌گیریم.", reply_markup=ReplyKeyboardRemove())
        status="COD"
    await save_order(u, ctx, status); return ConversationHandler.END

# ─────────── save order
async def save_order(u, ctx, status):
    cart = ctx.user_data["cart"]; summary=[]; total=0
    for it in cart:
        p=PRODUCTS[it["code"]]; cost=p["price"]*it["quantity"]; total+=cost
        summary.append(f"{p['fa']}×{it['quantity']}(€{cost:.2f})")
    row=[datetime.datetime.utcnow().isoformat(" ", "seconds"), u.effective_chat.id,
         f"@{u.effective_user.username}" if u.effective_user.username else "-",
         ctx.user_data["dest"], ", ".join(summary), f"{total:.2f}",
         ctx.user_data["name"], ctx.user_data["address"], ctx.user_data.get("postal","-"),
         ctx.user_data["phone"], ctx.user_data["notes"], status]
    await asyncio.get_running_loop().run_in_executor(None, partial(sheet.append_row, row))
    ctx.user_data.clear()
    if ADMIN:
        msg = ("📥 <b>سفارش جدید</b>\n"
               f"🏷 مقصد: {row[3]}\n"
               f"📦 {row[4]}\n💰 €{total:.2f}\n"
               f"👤 {row[6]}\n📍 {row[7]} {row[8]}\n☎️ {row[9]}\n📝 {row[10]}")
        await u.get_bot().send_message(ADMIN, msg, parse_mode="HTML")

# ─────────── payments
async def precheckout(upd, _): await upd.pre_checkout_query.answer(ok=True)
async def paid(upd, ctx):
    await upd.message.reply_text("💳 پرداخت موفق! سفارش در حال پردازش است.", reply_markup=ReplyKeyboardRemove())
    # در صورت نیاز: به‌روزرسانی وضعیت در شیت

# ─────────── cancel
async def cancel(u, ctx):
    ctx.user_data.clear()
    await u.message.reply_text("⛔️ سفارش لغو و سبد خالی شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ─────────── commands
async def start(u, ctx): await u.message.reply_html(WELCOME, reply_markup=kb_main(ctx))
async def about(u,_):    await u.message.reply_html(ABOUT)
async def privacy(u,_):  await u.message.reply_html(PRIVACY)

# ─────────── main
def main():
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("privacy", privacy))
    # router (excluding dest_ which opens form)
    app.add_handler(CallbackQueryHandler(router, pattern="^(back_|cat_|prd_|add_|show_cart|clear_cart|checkout)$"))
    # form conversation
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(router, pattern="^dest_")],
        states={NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_name)],
                ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_address)],
                POSTAL:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_postal)],
                PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_phone)],
                NOTES:[MessageHandler(filters.TEXT & ~filters.COMMAND, step_notes)]},
        fallbacks=[CommandHandler("cancel", cancel)]))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    app.run_webhook(listen="0.0.0.0", port=int(os.getenv("PORT","8080")),
                    url_path=TOKEN, webhook_url=f"{URL}/{TOKEN}")

if __name__=="__main__": main()
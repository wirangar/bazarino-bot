#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – FINAL (Webhook via FastAPI on Render)
FIXED VERSION 2025‑06‑28
────────────────────────────────────────────────────────────
Changes in this version:
1. **Quick‑add & Back to Category buttons working**
   • Added a quick‑add button ("➕ افزودن به سبد") that puts 1 item straight in the cart.
   • Refactored the back‑to‑category callback so it works even if category names contain underscores.
   • Fixed `select_quantity()` to use `update.effective_chat.id` (it previously raised an AttributeError).
2. **Phone number step now accepts a wider range of formats**
   • Replaced the old `phone_re` + `ok_phone` with a normaliser that accepts numbers with/without +39, spaces or dashes.
   • Users aren’t stuck at the PHONE step any more.
3. **Misc**
   • Minor tweaks in code comments & logging.

Deploy exactly as before; only the Python file changed.
"""

from __future__ import annotations
import asyncio, datetime as dt, json, logging, os, re, uuid
from typing import Dict, Any, List

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Request, HTTPException
import uvicorn
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
)
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)
from telegram.error import BadRequest, NetworkError

# ───────────── Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bazarino")

# ───────────── Messages
try:
    with open("messages.json", encoding="utf-8") as f:
        MSG = json.load(f)
except FileNotFoundError:
    log.error("messages.json not found")
    raise SystemExit("❗️ فایل messages.json یافت نشد.")

def m(k: str) -> str:
    return MSG.get(k, f"[{k}]")

# ───────────── ENV
for v in ("TELEGRAM_TOKEN", "ADMIN_CHAT_ID", "GOOGLE_CREDS", "BASE_URL"):
    if not os.getenv(v):
        log.error(f"Missing environment variable: {v}")
        raise SystemExit(f"❗️ متغیر محیطی {v} تنظیم نشده است.")
TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = os.getenv("BASE_URL").rstrip("/")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID"))
SPREADSHEET = os.getenv("SPREADSHEET_NAME", "Bazarnio Orders")
PRODUCT_WS = os.getenv("PRODUCT_WORKSHEET", "Sheet2")
LOW_STOCK_TH = int(os.getenv("LOW_STOCK_THRESHOLD", "3"))
PORT = int(os.getenv("PORT", "8000"))
CREDS_PATH = os.getenv("GOOGLE_CREDS", "/etc/secrets/bazarino-perugia-bot-f37c44dd9b14.json")

# ───────────── Google‑Sheets
try:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    gc = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope))
    wb = gc.open(SPREADSHEET)
    orders_ws = wb.sheet1
    products_ws = wb.worksheet(PRODUCT_WS)
except Exception as e:
    log.error(f"Failed to initialize Google Sheets: {e}")
    raise SystemExit(f"❗️ خطا در اتصال به Google Sheets: {e}")


def load_products() -> Dict[str, Dict[str, Any]]:
    try:
        return {
            r["id"]: dict(
                cat=r["cat"],
                fa=r["fa"],
                it=r["it"],
                brand=r["brand"],
                desc=r["description"],
                weight=r["weight"],
                price=float(r["price"]),
                image_url=r["image_url"] or None,
                stock=int(r.get("stock", 0)),
            )
            for r in products_ws.get_all_records()
        }
    except Exception as e:
        log.error(f"Error loading products from Google Sheets: {e}")
        raise SystemExit(f"❗️ خطا در بارگذاری محصولات از Google Sheets: {e}")


# 15‑sec cache for products
def get_products():
    if not getattr(get_products, "_data", None) or dt.datetime.utcnow() > get_products._ts:
        get_products._data = load_products()
        get_products._ts = dt.datetime.utcnow() + dt.timedelta(seconds=15)
        log.info(f"Loaded {len(get_products._data)} products from Google Sheets")
    return get_products._data


EMOJI = {
    "rice": "🍚 برنج / Riso",
    "beans": "🥣 حبوبات / Legumi",
    "spice": "🌿 ادویه / Spezie",
    "nuts": "🥜 خشکبار / Frutta secca",
    "drink": "🧃 نوشیدنی / Bevande",
    "canned": "🥫 کنسرو / Conserve",
    "sweet": "🍬 شیرینی / Dolci",
}

# ───────────── Validators
# More forgiving Italian mobile phone normaliser (accepts +39 & whitespace)
_phone_clean = lambda p: re.sub(r"\D", "", p)

def ok_phone(p: str) -> bool:
    digits = _phone_clean(p)
    if digits.startswith("39"):
        digits = digits[2:]
    return digits.startswith("3") and len(digits) == 9 or len(digits) == 10

ok_addr = lambda a: len(a.strip()) > 10 and any(c.isdigit() for c in a)

# ───────────── Helpers
cart_total = lambda c: sum(i["qty"] * i["price"] for i in c)
cart_count = lambda ctx: sum(i["qty"] for i in ctx.user_data.get("cart", []))


async def safe_edit(q, *a, **k):
    try:
        await q.edit_message_text(*a, **k)
    except BadRequest as e:
        if "not modified" in str(e):
            return
        log.error(f"Edit msg error: {e}")
    except NetworkError as e:
        log.error(f"Network error: {e}")


async def alert_admin(pid, stock):
    if stock <= LOW_STOCK_TH and ADMIN_ID:
        for _ in range(3):  # Retry 3 times
            try:
                await bot.send_message(ADMIN_ID, f"⚠️ موجودی کم {stock}: {get_products()[pid]['fa']}")
                log.info(f"Low stock alert sent for {get_products()[pid]['fa']}")
                break
            except Exception as e:
                log.error(f"Alert fail attempt: {e}")
                await asyncio.sleep(1)  # Wait before retry


# ───────────── Keyboards
def kb_main(ctx):
    cats = {p["cat"] for p in get_products().values()}
    rows = [[InlineKeyboardButton(EMOJI.get(c, c), callback_data=f"cat_{c}")] for c in cats]
    rows.append([InlineKeyboardButton(f"🛒 سبد ({cart_count(ctx)})", callback_data="cart")])
    return InlineKeyboardMarkup(rows)


def kb_category(cat, ctx):
    rows = [
        [InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"show_{pid}")]
        for pid, p in get_products().items()
        if p["cat"] == cat
    ]
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back")])
    return InlineKeyboardMarkup(rows)


def kb_product(pid):
    p = get_products()[pid]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ افزودن به سبد", callback_data=f"add1_{pid}")],
            [InlineKeyboardButton("🧮 انتخاب تعداد", callback_data=f"add_{pid}")],
            [InlineKeyboardButton("⬅️ دسته قبل", callback_data=f"back_cat_{p['cat']}")],
        ]
    )


def kb_cart(cart):
    rows = []
    for it in cart:
        pid = it["id"]
        rows.append(
            [
                InlineKeyboardButton("➕", callback_data=f"inc_{pid}"),
                InlineKeyboardButton(f"{it['qty']}× {it['fa']}", callback_data="ignore"),
                InlineKeyboardButton("➖", callback_data=f"dec_{pid}"),
                InlineKeyboardButton("❌", callback_data=f"del_{pid}"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("📦 پروجا", callback_data=f"order_perugia"),
            InlineKeyboardButton("🚚 ایتالیا", callback_data=f"order_italy"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("✔️ ادامه", callback_data="checkout"),
            InlineKeyboardButton("⬅️ منو", callback_data="back"),
        ]
    )
    return InlineKeyboardMarkup(rows)


# ───────────── Cart operations
async def add_cart(ctx, pid, qty=1):
    prods = get_products()
    if pid not in prods:
        return False, "❌ محصول یافت نشد."
    p = prods[pid]
    stock = p["stock"]
    cart = ctx.user_data.setdefault("cart", [])
    cur = next((i for i in cart if i["id"] == pid), None)
    cur_qty = cur["qty"] if cur else 0
    if stock < cur_qty + qty:
        return False, "❗️ موجودی کافی نیست."
    if cur:
        cur["qty"] += qty
    else:
        cart.append(
            dict(id=pid, fa=p["fa"], price=p["price"], weight=p["weight"], qty=qty)
        )
    await alert_admin(pid, stock)
    return True, "✅ به سبد اضافه شد."


async def select_quantity(update, ctx, pid):
    kb = [[InlineKeyboardButton(str(i), callback_data=f"qty_{pid}_{i}") for i in range(1, 11)]]
    kb.append([InlineKeyboardButton("❌ لغو", callback_data=f"cancel_qty_{pid}")])
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text="تعداد مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(kb),
    )


def fmt_cart(cart):
    if not cart:
        return m("CART_EMPTY")
    lines = ["🛍 <b>سبد خرید:</b>", ""]
    tot = 0
    for it in cart:
        sub = it["qty"] * it["price"]
        tot += sub
        lines.append(f"▫️ {it['qty']}× {it['fa']} — {sub:.2f}€")
    lines.append("")
    lines.append(f"💶 <b>جمع:</b> {tot:.2f}€")
    return "\n".join(lines)


# ───────────── Stock update
def update_stock(cart):
    try:
        records = products_ws.get_all_records()
        for it in cart:
            pid = it["id"]
            qty = it["qty"]
            for idx, row in enumerate(records, start=2):
                if row["id"] == pid:
                    new = row["stock"] - qty
                    if new < 0:
                        log.error(f"Cannot update stock for {pid}: negative stock")
                        return False
                    products_ws.update_cell(idx, 10, new)  # Column J (10)
                    get_products().get(pid)["stock"] = new
                    log.info(f"Updated stock for {pid}: {new}")
        return True
    except Exception as e:
        log.error(f"Stock update error: {e}")
        return False


# ───────────── Router
async def router(update: Update, ctx):
    q = update.callback_query
    d = q.data
    await q.answer()

    if d == "back":
        await safe_edit(q, m("WELCOME"), reply_markup=kb_main(ctx), parse_mode="HTML")
        return

    if d.startswith("cat_"):
        await safe_edit(q, EMOJI.get(d[4:], d[4:]), reply_markup=kb_category(d[4:], ctx))
        return

    if d.startswith("show_"):
        pid = d[5:]
        p = get_products()[pid]
        cap = (
            f"<b>{p['fa']} / {p['it']}</b>\n{p['desc']}\n{p['price']}€ / {p['weight']}\nموجودی: {p['stock']}"
        )
        if p["image_url"] and p["image_url"].strip():
            await ctx.bot.send_photo(
                chat_id=q.message.chat.id,
                photo=p["image_url"],
                caption=cap,
                reply_markup=kb_product(pid),
                parse_mode="HTML",
            )
        else:
            await ctx.bot.send_message(
                chat_id=q.message.chat.id,
                text=cap,
                reply_markup=kb_product(pid),
                parse_mode="HTML",
            )
        return

    # Quick‑add 1 item
    if d.startswith("add1_"):
        pid = d[5:]
        ok, msg = await add_cart(ctx, pid, 1)
        await q.answer(msg, show_alert=not ok)
        return

    if d.startswith("add_"):
        pid = d[4:]
        await select_quantity(update, ctx, pid)
        return

    if d.startswith("qty_"):
        _, pid, qty = d.split("_")
        qty = int(qty)
        ok, msg = await add_cart(ctx, pid, qty)
        await q.answer(msg, show_alert=not ok)
        await q.message.delete()  # Remove the "select quantity" msg
        await safe_edit(
            q,
            fmt_cart(ctx.user_data.get("cart", [])),
            reply_markup=kb_cart(ctx.user_data.get("cart", [])),
            parse_mode="HTML",
        )
        return

    if d.startswith("cancel_qty_"):
        await q.answer("افزودن به سبد لغو شد.")
        await q.message.delete()
        return

    if d.startswith("back_cat_"):
        cat = d[len("back_cat_"):]
        await safe_edit(q, EMOJI.get(cat, cat), reply_markup=kb_category(cat, ctx))
        return

    if d == "cart":
        await safe_edit(
            q,
            fmt_cart(ctx.user_data.get("cart", [])),
            reply_markup=kb_cart(ctx.user_data.get("cart", [])),
            parse_mode="HTML",
        )
        return

    if d.startswith(("inc_", "dec_", "del_")):
        pid = d.split("_")[1]
        cart = ctx.user_data.get("cart", [])
        it = next((i for i in cart if i["id"] == pid), None)
        if not it:
            return
        if d.startswith("inc_"):
            await add_cart(ctx, pid, 1)
        elif d.startswith("dec_"):
            it["qty"] = max(1, it["qty"] - 1)
        else:
            cart.remove(it)
        await safe_edit(q, fmt_cart(cart), reply_markup=kb_cart(cart), parse_mode="HTML")
        return

    if d in ["order_perugia", "order_italy"]:
        ctx.user_data["dest"] = "Perugia" if d == "order_perugia" else "Italy"
        await q.message.reply_text("لطفاً برای ادامه، دکمه '✔️ ادامه' را بزنید.")
        return

    if d == "checkout":
        if not ctx.user_data.get("dest"):
            await q.answer("لطفاً مقصد (پروجا/ایتالیا) را انتخاب کنید.", show_alert=True)
            return
        # Conversation handler will take over from here
        return  # Important: do not trigger start_form twice


# ───────────── /search
from difflib import get_close_matches

async def cmd_search(u, ctx):
    q = " ".join(ctx.args).lower()
    if not q:
        await u.message.reply_text(m("SEARCH_USAGE"))
        return
    hits = [
        (pid, p)
        for pid, p in get_products().items()
        if q in p["fa"].lower()
        or q in p["it"].lower()
        or get_close_matches(q, [p["fa"].lower() + " " + p["it"].lower()], cutoff=0.6)
    ]
    if not hits:
        await u.message.reply_text(m("SEARCH_NONE"))
        return
    for pid, p in hits[:5]:
        cap = f"{p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€\nموجودی: {p['stock']}"
        btn = InlineKeyboardMarkup.from_button(
            InlineKeyboardButton("➕ افزوندن به سبد", callback_data=f"add1_{pid}")
        )
        if p["image_url"] and p["image_url"].strip():
            await u.message.reply_photo(p["image_url"], caption=cap, reply_markup=btn)
        else:
            await u.message.reply_text(cap, reply_markup=btn)


# ───────────── Order conversation
NAME, PHONE, ADDR, POSTAL, NOTES = range(5)

async def start_form(u, ctx):
    q = u.callback_query
    dest = ctx.user_data.get("dest")
    if not dest:
        await q.answer("لطفاً از سبد خرید گزینه تحویل را انتخاب کنید.")
        return ConversationHandler.END
    ctx.user_data["name"] = f"{q.from_user.first_name} {(q.from_user.last_name or '')}".strip()
    ctx.user_data["handle"] = f"@{q.from_user.username}" if q.from_user.username else "-"
    await q.answer()
    await q.message.reply_text(m("INPUT_PHONE"))
    return PHONE


async def step_phone(u, ctx):
    if not ok_phone(u.message.text):
        await u.message.reply_text(m("PHONE_INVALID"))
        return PHONE
    ctx.user_data["phone"] = u.message.text
    await u.message.reply_text(m("INPUT_ADDRESS") + " (حداقل 10 کاراکتر با یک عدد)")
    return ADDR


async def step_addr(u, ctx):
    if not ok_addr(u.message.text):
        await u.message.reply_text(m("ADDRESS_INVALID") + " (حداقل 10 کاراکتر با یک عدد وارد کنید)")
        return ADDR
    ctx.user_data["address"] = u.message.text
    await u.message.reply_text(m("INPUT_POSTAL"))
    return POSTAL


async def step_postal(u, ctx):
    ctx.user_data["postal"] = u.message.text
    await u.message.reply_text(m("INPUT_NOTES"))
    return NOTES


async def step_notes(u, ctx):
    ctx.user_data["notes"] = u.message.text or "-"
    cart = ctx.user_data.get("cart", [])
    if not cart:
        await u.message.reply_text(m("CART_EMPTY"), reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if not update_stock(cart):
        await u.message.reply_text("❌ موجودی کافی نیست.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    order_id = str(uuid.uuid4())[:8]
    ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        for it in cart:
            orders_ws.append_row(
                [
                    ts,
                    order_id,
                    u.effective_user.id,
                    ctx.user_data["handle"],
                    ctx.user_data["name"],
                    ctx.user_data["phone"],
                    ctx.user_data["address"],
                    ctx.user_data["dest"],
                    it["id"],
                    it["fa"],
                    it["qty"],
                    it["price"],
                    it["qty"] * it["price"],
                ]
            )
        log.info(f"Order {order_id} saved to Google Sheets for user {ctx.user_data['handle']}")
    except Exception as e:
        log.error(f"Error saving order {order_id}: {e}")
        await u.message.reply_text("❌ خطا در ثبت سفارش.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    await u.message.reply_text(m("ORDER_CONFIRMED"), reply_markup=ReplyKeyboardRemove())
    if promo := MSG.get("PROMO_AFTER_ORDER"):
        await u.message.reply_text(promo, disable_web_page_preview=True)
    if ADMIN_ID:
        msg = [
            f"🆕 سفارش {order_id}",
            f"{ctx.user_data['name']} — {cart_total(cart):.2f}€",
        ] + [f"▫️ {i['qty']}× {i['fa']}" for i in cart]
        try:
            await bot.send_message(ADMIN_ID, "\n".join(msg))
            log.info(f"Admin notified for order {order_id}")
        except Exception as e:
            log.error(f"Failed to notify admin for order {order_id}: {e}")
    ctx.user_data.clear()
    return ConversationHandler.END


async def cancel(u, ctx):
    ctx.user_data.clear()
    await u.message.reply_text(m("ORDER_CANCELLED"), reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ───────────── Commands
async def cmd_start(u, ctx):
    await u.message.reply_html(m("WELCOME"), reply_markup=kb_main(ctx))


async def cmd_about(u, ctx):
    await u.message.reply_text(m("ABOUT_US"), disable_web_page_preview=True)


async def cmd_privacy(u, ctx):
    await u.message.reply_text(m("PRIVACY"), disable_web_page_preview=True)


# ───────────── App, webhook and FastAPI
api = FastAPI()

tg_app = ApplicationBuilder().token(TOKEN).build()

bot = tg_app.bot


@api.on_event("startup")
async def _on_startup():
    await tg_app.initialize()

    # Handlers
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("search", cmd_search))
    tg_app.add_handler(CommandHandler("about", cmd_about))
    tg_app.add_handler(CommandHandler("privacy", cmd_privacy))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_form, pattern="^checkout$")],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_phone)],
            ADDR: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_addr)],
            POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_postal)],
            NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=True,
    )
    tg_app.add_handler(conv)

    # The router must come *after* the convo so it doesn't steal the "checkout" callback
    tg_app.add_handler(CallbackQueryHandler(router))

    webhook_url = f"{BASE_URL}/webhook"
    await tg_app.bot.set_webhook(webhook_url)
    log.info(f"Webhook set to {webhook_url}")


@api.post("/webhook")
async def wh(req: Request):
    try:
        update = Update.de_json(await req.json(), tg_app.bot)
        if not update:
            log.error("Invalid webhook update received")
            raise HTTPException(status_code=400, detail="Invalid update")
        await tg_app.process_update(update)
        return {"ok": True}
    except Exception as e:
        log.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


def main():
    uvicorn.run(api, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

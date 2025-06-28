
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazarino Telegram Bot – Full version (Phases 1‑4)
- Dynamic products from Google Sheets
- Stock check + low‑stock alert to admin
- Rich cart UI with + / – / ❌
- /search command
- Order buttons (Perugia / Italy)
- Order form with auto‑prefill name & username
- Structured order saving to Google Sheets
- Confirmation message to user and admin
- Optional promo message (PROMO_AFTER_ORDER) from messages.json
"""

from __future__ import annotations
import asyncio, datetime as dt, json, logging, os, re, uuid
from functools import partial
from typing import Dict, Any, List

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
)
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)
from telegram.error import BadRequest

# ───────────── Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bazarino")

# ───────────── Load localisation messages
with open("messages.json", encoding="utf-8") as f:
    MSG = json.load(f)
def m(key: str) -> str: return MSG.get(key, f"[{key}]")

# ───────────── ENV
TOKEN = os.getenv("TELEGRAM_TOKEN"); BASE_URL = os.getenv("BASE_URL")
SPREADSHEET = os.getenv("SPREADSHEET_NAME", "Bazarnio Orders")
PRODUCT_WS  = os.getenv("PRODUCT_WORKSHEET", "Sheet2")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

CREDS_INFO = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
gc = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(CREDS_INFO, scope))
wb = gc.open(SPREADSHEET)
orders_ws   = wb.sheet1
products_ws = wb.worksheet(PRODUCT_WS)

# ───────────── Load products
def load_products() -> Dict[str, Dict[str, Any]]:
    data = products_ws.get_all_records()
    prod = {}
    for r in data:
        prod[r["id"]] = {
            "cat": r["cat"], "fa": r["fa"], "it": r["it"],
            "brand": r["brand"], "desc": r["description"], "weight": r["weight"],
            "price": float(r["price"]), "image_url": r["image_url"],
            "stock": int(r.get("stock", 0)),
        }
    log.info("Loaded %d products", len(prod))
    return prod
PRODUCTS = load_products()

EMOJI = {"rice":"🍚 برنج / Riso","beans":"🥣 حبوبات / Legumi","spice":"🌿 ادویه / Spezie",
         "nuts":"🥜 خشکبار / Frutta secca","drink":"🧃 نوشیدنی / Bevande",
         "canned":"🥫 کنسرو / Conserve","sweet":"🍬 شیرینی / Dolci"}
CATEGORIES = {p["cat"]: EMOJI.get(p["cat"], p["cat"]) for p in PRODUCTS.values()}

# ───────────── Validators
phone_re = re.compile(r"^\+?\d{8,15}$")
def ok_phone(p:str)->bool: return bool(phone_re.fullmatch(p.strip()))
def ok_addr(a:str)->bool:  return len(a.strip())>10 and any(ch.isdigit() for ch in a)

# ───────────── Helpers
def cart_total(cart): return sum(i["qty"]*i["price"] for i in cart)
def cart_count(ctx):  return sum(i["qty"] for i in ctx.user_data.get("cart",[]))

async def safe_edit(q,*a,**k):
    try: await q.edit_message_text(*a,**k)
    except BadRequest as e:
        if "not modified" in str(e): return
        raise

# ───────────── Keyboards
def kb_main(ctx):
    rows=[[InlineKeyboardButton(lbl, callback_data=f"cat_{c}")]
          for c,lbl in CATEGORIES.items()]
    rows.append([InlineKeyboardButton(f"🛒 سبد ({cart_count(ctx)})",callback_data="cart")])
    return InlineKeyboardMarkup(rows)

def kb_category(cat, ctx):
    rows=[[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"show_{pid}")]
          for pid,p in PRODUCTS.items() if p["cat"]==cat]
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def kb_product(pid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن به سبد", callback_data=f"add_{pid}")],
        [
            InlineKeyboardButton("📦 پروجا",  callback_data=f"order_perugia_{pid}"),
            InlineKeyboardButton("🚚 ایتالیا", callback_data=f"order_italy_{pid}")
        ],
        [InlineKeyboardButton("⬅️ دسته قبل", callback_data=f"back_cat_{PRODUCTS[pid]['cat']}")]
    ])

def kb_cart(cart):
    rows=[]
    for it in cart:
        pid=it["id"]; qty=it["qty"]
        rows.append([
            InlineKeyboardButton("➕",callback_data=f"inc_{pid}"),
            InlineKeyboardButton(f"{qty}× {it['fa']}",callback_data="ignore"),
            InlineKeyboardButton("➖",callback_data=f"dec_{pid}"),
            InlineKeyboardButton("❌",callback_data=f"del_{pid}")
        ])
    rows.append([InlineKeyboardButton("✔️ ادامه",callback_data="checkout"),
                 InlineKeyboardButton("⬅️ منو",callback_data="back")])
    return InlineKeyboardMarkup(rows)

# ───────────── Stock, cart ops, admin alert
def alert_admin(pid):
    p=PRODUCTS[pid]; stock=p["stock"]
    if stock<=3 and ADMIN_ID:
        try: bot.send_message(ADMIN_ID, f"⚠️ موجودی کم: {p['fa']} - {stock}")
        except: pass

def add_cart(ctx, pid, qty=1):
    if pid not in PRODUCTS: return False,"❌ یافت نشد."
    p=PRODUCTS[pid]; stock=p["stock"]
    cart=ctx.user_data.setdefault("cart",[])
    cur=next((i for i in cart if i["id"]==pid),None)
    cur_qty=cur["qty"] if cur else 0
    if stock<=cur_qty:
        return False,"❗️ موجودی کافی نیست"
    if cur: cur["qty"]+=qty
    else: cart.append({"id":pid,"fa":p["fa"],"weight":p["weight"],
                       "price":p["price"],"qty":qty})
    alert_admin(pid)
    return True,"✅ افزوده شد"

# ───────────── Format Cart
def fmt_cart(cart):
    if not cart: return m("CART_EMPTY")
    lines=["🛍 <b>سبد خرید:</b>",""]
    total=0
    for it in cart:
        sub=it["qty"]*it["price"]; total+=sub
        lines.append(f"▫️{it['qty']}× {it['fa']} ({it['weight']}) — {it['price']:.2f}€ = <b>{sub:.2f}€</b>")
    lines.append(""); lines.append(f"💶 <b>جمع:</b> {total:.2f}€")
    return "\n".join(lines)

# ───────────── Router
async def router(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; d=q.data; await q.answer()
    if d=="back":
        await safe_edit(q,m("WELCOME"),reply_markup=kb_main(ctx),parse_mode="HTML"); return
    if d.startswith("cat_"):
        await safe_edit(q,EMOJI.get(d[4:],d[4:]),reply_markup=kb_category(d[4:],ctx)); return
    if d.startswith("show_"):
        pid=d[5:]; p=PRODUCTS[pid]
        cap=f"<b>{p['fa']} / {p['it']}</b>\n{p['desc']}\n{p['price']}€ / {p['weight']}"
        await q.message.answer_photo(p["image_url"],caption=cap,reply_markup=kb_product(pid),parse_mode="HTML"); return
    if d.startswith("add_"):
        ok,msg=add_cart(ctx,d[4:]); await q.answer(msg,show_alert=not ok); return
    if d=="cart":
        cart=ctx.user_data.get("cart",[]); await safe_edit(q,fmt_cart(cart),parse_mode="HTML",reply_markup=kb_cart(cart)); return
    # inc/dec/del
    if d.startswith(("inc_","dec_","del_")):
        pid=d.split("_")[1]; cart=ctx.user_data.get("cart",[])
        item=next((i for i in cart if i["id"]==pid),None)
        if not item: return
        if d.startswith("inc_"): add_cart(ctx,pid,1)
        elif d.startswith("dec_"): item["qty"]=max(1,item["qty"]-1)
        else: cart.remove(item)
        await safe_edit(q,fmt_cart(cart),parse_mode="HTML",reply_markup=kb_cart(cart)); return

# ───────────── Search command
from difflib import get_close_matches
async def cmd_search(u,ctx):
    q=" ".join(ctx.args).lower()
    if not q: await u.message.reply_text(m("SEARCH_USAGE")); return
    res=[(pid,p) for pid,p in PRODUCTS.items()
         if q in p['fa'].lower() or q in p['it'].lower()
         or get_close_matches(q,[p['fa'].lower()+" "+p['it'].lower()],cutoff=0.6)]
    if not res: await u.message.reply_text(m("SEARCH_NONE")); return
    for pid,p in res[:5]:
        cap=f"🛍 {p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€ / {p['weight']}"
        btn=InlineKeyboardMarkup.from_button(InlineKeyboardButton("➕",callback_data=f"add_{pid}"))
        await u.message.reply_photo(p["image_url"],caption=cap,reply_markup=btn)

# ───────────── Order Conversation
NAME,PHONE,ADDR,POSTAL,NOTES = range(5)
async def start_form(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; dest=q.data.split("_")[1]; ctx.user_data["dest"]=dest
    user=q.from_user
    ctx.user_data["name"]=f"{user.first_name} {user.last_name or ''}".strip()
    ctx.user_data["handle"]=f"@{user.username}" if user.username else "-"
    await q.answer()
    if ctx.user_data["name"]:
        await q.message.reply_text(m("INPUT_PHONE")); return PHONE
    await q.message.reply_text(m("INPUT_NAME")); return NAME

async def step_name(u,ctx): ctx.user_data["name"]=u.message.text; await u.message.reply_text(m("INPUT_PHONE")); return PHONE
async def step_phone(u,ctx):
    if not ok_phone(u.message.text): await u.message.reply_text(m("PHONE_INVALID")); return PHONE
    ctx.user_data["phone"]=u.message.text; await u.message.reply_text(m("INPUT_ADDRESS")); return ADDR
async def step_addr(u,ctx):
    if not ok_addr(u.message.text): await u.message.reply_text(m("ADDRESS_INVALID")); return ADDR
    ctx.user_data["address"]=u.message.text; await u.message.reply_text(m("INPUT_POSTAL")); return POSTAL
async def step_postal(u,ctx): ctx.user_data["postal"]=u.message.text; await u.message.reply_text(m("INPUT_NOTES")); return NOTES
async def step_notes(u,ctx):
    ctx.user_data["notes"]=u.message.text or "-"
    cart=ctx.user_data.get("cart",[])
    # -------- Save to Sheets --------
    ts=dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    order_id=str(uuid.uuid4())[:8]
    for it in cart:
        orders_ws.append_row([
            ts,order_id,u.effective_user.id,ctx.user_data["handle"],
            ctx.user_data["name"],ctx.user_data["phone"],ctx.user_data["address"],
            ctx.user_data["dest"],it["id"],it["fa"],it["qty"],it["price"],it["qty"]*it["price"]
        ])
    # -------- Confirmation --------
    await u.message.reply_text(m("ORDER_CONFIRMED"),reply_markup=ReplyKeyboardRemove())
    promo=MSG.get("PROMO_AFTER_ORDER")
    if promo: await u.message.reply_text(promo,disable_web_page_preview=True)
    if ADMIN_ID:
        total=cart_total(cart)
        admin_msg=f"🆕 سفارش جدید {order_id}\nنام: {ctx.user_data['name']}\nمجموع: {total:.2f}€"
        await u.get_bot().send_message(ADMIN_ID,admin_msg)
    ctx.user_data.clear()
    return ConversationHandler.END

async def cancel(u,ctx): ctx.user_data.clear(); await u.message.reply_text(m("ORDER_CANCELLED"),reply_markup=ReplyKeyboardRemove()); return ConversationHandler.END

# ───────────── Start & error handlers
async def cmd_start(u,ctx): await u.message.reply_html(m("WELCOME"),reply_markup=kb_main(ctx))
async def error_handler(u,ctx): log.error("ERROR:",exc_info=ctx.error)

def main():
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",cmd_start))
    app.add_handler(CommandHandler("search",cmd_search))
    # Form conversation
    conv=ConversationHandler(
        entry_points=[CallbackQueryHandler(start_form, pattern="^order_")],
        states={NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND,step_name)],
                PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND,step_phone)],
                ADDR:[MessageHandler(filters.TEXT & ~filters.COMMAND,step_addr)],
                POSTAL:[MessageHandler(filters.TEXT & ~filters.COMMAND,step_postal)],
                NOTES:[MessageHandler(filters.TEXT & ~filters.COMMAND,step_notes)]},
        fallbacks=[CommandHandler("cancel",cancel)]
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(router,pattern=".*"))
    app.add_error_handler(error_handler)
    app.run_polling()

if __name__=="__main__":
    main()

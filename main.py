import asyncio
import io
import json
import logging
import os
import zipfile
from typing import Dict, List, Optional, Any
import uuid
import datetime as dt
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display
import gspread
import requests
import yaml
from fastapi import FastAPI, HTTPException, Request

# ✅ ایمپورت‌های درست برای کتابخانه python-telegram-bot v21.4
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    JobQueue,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters
)


logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
log = logging.getLogger("bazarino")

with open("config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)
with open("messages.json", "r", encoding="utf-8") as f:
    MSG = json.load(f)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", 0))
BASE_URL = os.getenv("BASE_URL")
GOOGLE_CREDS = json.loads(os.getenv("GOOGLE_CREDS", "{}"))
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Bazarnio Orders")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "EhsaNegar1394")
PORT = int(os.getenv("PORT", 8000))
EMOJI = CFG.get("emoji", {})
FONT = CFG.get("font", "fonts/Vazir.ttf")
FONT_SIZE = CFG.get("font_size", 20)
IMG_WIDTH = CFG.get("image_width", 800)
IMG_HEIGHT = CFG.get("image_height", 1200)
LOGO_PATH = CFG.get("logo", "logo.png")
PATTERN_PATH = CFG.get("pattern", "background_pattern.png")

tg_app = None
bot = None
gc = gspread.service_account_from_dict(GOOGLE_CREDS)
ss = gc.open(SPREADSHEET_NAME)
log.info(f"Successfully opened spreadsheet: {SPREADSHEET_NAME}")
orders_ws = ss.worksheet("Sheet1")
products_ws = ss.worksheet("Sheet2")
log.info(f"Worksheets loaded: orders=Sheet1, products=Sheet2")
abandoned_cart_ws = ss.worksheet("AbandonedCarts")
log.info(f"Worksheet loaded: abandoned_carts=AbandonedCarts")
discounts_ws = ss.worksheet("Sheet3")
log.info(f"Worksheet loaded: discounts=Sheet3")
uploads_ws = ss.worksheet("UserUploads")
log.info(f"Worksheet loaded: uploads=UserUploads")

async def validate_sheets():
    try:
        sheets = [
            (orders_ws, "orders", ["timestamp", "order_id", "user_id", "handle", "name", "phone", "address", "destination", "product_id", "product_name", "quantity", "price", "subtotal", "notes", "discount_code", "discount_amount", "status", "notified"]),
            (products_ws, "products", ["id", "cat", "fa", "it", "brand", "description", "weight", "price", "image_url", "stock", "is_bestseller", "version"]),
            (discounts_ws, "discounts", ["code", "discount_percent", "valid_until", "is_active"]),
            (abandoned_cart_ws, "abandoned_carts", ["timestamp", "user_id", "cart"]),
            (uploads_ws, "uploads", ["timestamp", "user_id", "handle", "file_id"])
        ]
        for ws, name, expected in sheets:
            headers = await asyncio.to_thread(ws.row_values, 1)
            log.info(f"Headers for sheet '{name}' ({ws.title}): {headers}")
            headers = [h.lower().strip() for h in headers]
            log.info(f"Cleaned headers for sheet '{name}' ({ws.title}): {headers}")
            for col in expected:
                if col not in headers:
                    raise ValueError(f"❗️ ستون '{col}' در شیت '{name}' ({ws.title}) یافت نشد.")
                log.info(f"Column '{col}' found in sheet '{name}' ({ws.title})")
        log.info("All Google Sheets validated successfully")
    except Exception as e:
        log.error(f"Error validating sheets: {e}", exc_info=True)
        raise

def m(key: str) -> str:
    return MSG.get(key, f"Missing message: {key}")

async def get_products() -> Dict[str, Any]:
    try:
        if not hasattr(get_products, "_data"):
            records = await asyncio.to_thread(products_ws.get_all_records)
            get_products._data = {
                r["id"]: {
                    "cat": r["cat"],
                    "fa": r["fa"],
                    "it": r["it"],
                    "brand": r["brand"],
                    "desc": r["description"],
                    "weight": float(r["weight"]),
                    "price": float(r["price"]),
                    "image_url": r.get("image_url", ""),
                    "stock": int(r["stock"]),
                    "is_bestseller": r["is_bestseller"].lower() == "true",
                    "version": r.get("version", "1")
                } for r in records
            }
        return get_products._data
    except Exception as e:
        log.error(f"Error loading products: {e}", exc_info=True)
        raise

async def load_discounts() -> Dict[str, Any]:
    try:
        records = await asyncio.to_thread(discounts_ws.get_all_records)
        return {r["code"]: {"discount_percent": float(r["discount_percent"]), "valid_until": r["valid_until"], "is_active": r["is_active"].lower() == "true"} for r in records}
    except Exception as e:
        log.error(f"Error loading discounts: {e}", exc_info=True)
        raise

async def alert_admin(pid: str, stock: int):
    try:
        if stock <= 5 and ADMIN_ID and bot:
            p = (await get_products())[pid]
            await bot.send_message(ADMIN_ID, f"⚠️ موجودی کم: {p['fa']} ({pid})\nموجودی: {stock}")
    except Exception as e:
        log.error(f"Error sending admin alert for product {pid}: {e}", exc_info=True)

def cart_count(ctx: ContextTypes.DEFAULT_TYPE) -> int:
    return sum(i["qty"] for i in ctx.user_data.get("cart", []))

def cart_total(cart: List[Dict[str, Any]]) -> float:
    return sum(i["qty"] * i["price"] for i in cart)

async def safe_edit(query: Any, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None, parse_mode: Optional[str] = None):
    try:
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        log.error(f"Error editing message: {e}", exc_info=True)
        try:
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e2:
            log.error(f"Error sending new message: {e2}", exc_info=True)

async def generate_invoice(order_id: str, user_data: Dict[str, Any], cart: List[Dict[str, Any]], total: float, discount: float) -> io.BytesIO:
    try:
        img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), color="white")
        if os.path.exists(PATTERN_PATH):
            bg = Image.open(PATTERN_PATH).resize((IMG_WIDTH, IMG_HEIGHT))
            img.paste(bg, (0, 0))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(FONT, FONT_SIZE)
        logo = Image.open(LOGO_PATH).resize((150, 150)) if os.path.exists(LOGO_PATH) else None
        if logo:
            img.paste(logo, (IMG_WIDTH - 170, 20), logo if logo.mode == "RGBA" else None)
        y = 200
        lines = [
            f"سفارش / Ordine #{order_id}",
            f"مشتری / Cliente: {user_data['name']}",
            f"تلفن / Telefono: {user_data['phone']}",
            f"آدرس / Indirizzo: {user_data['address']} | {user_data['postal']}",
            f"مقصد / Destinazione: {user_data['dest']}",
            "",
            "اقلام / Articoli:"
        ]
        for it in cart:
            lines.append(f"{it['qty']}× {it['fa']} — {it['qty'] * it['price']:.2f}€")
        lines.extend([
            "",
            f"جمع / Totale: {total + discount:.2f}€",
            f"تخفیف / Sconto: {discount:.2f}€",
            f"پرداخت نهایی / Totale finale: {total:.2f}€",
            f"یادداشت / Nota: {user_data['notes'] or 'بدون یادداشت'}"
        ])
        for line in lines:
            reshaped = get_display(arabic_reshaper.reshape(line))
            draw.text((50, y), reshaped, fill="black", font=font, align="right")
            y += FONT_SIZE + 10
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
    except Exception as e:
        log.error(f"Error generating invoice: {e}", exc_info=True)
        raise
# ───────────── Order States
ASK_NAME, ASK_PHONE, ASK_ADDRESS, ASK_POSTAL, ASK_DISCOUNT, ASK_NOTES = range(6)

# ───────────── Order Process
async def start_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        q = update.callback_query
        if not ctx.user_data.get("dest"):
            await q.message.reply_text(f"{m('CART_GUIDE')}\n\n{fmt_cart(ctx.user_data.get('cart', []))}", reply_markup=kb_cart(ctx), parse_mode="HTML")
            return ConversationHandler.END
        ctx.user_data["name"] = f"{q.from_user.first_name} {(q.from_user.last_name or '')}".strip()
        ctx.user_data["handle"] = f"@{q.from_user.username}" if q.from_user.username else "-"
        ctx.user_data["user_id"] = update.effective_user.id
        await q.message.reply_text(m("INPUT_NAME"))
        return ASK_NAME
    except Exception as e:
        log.error(f"Error in start_order: {e}", exc_info=True)
        await q.message.reply_text("❗️ خطا در شروع سفارش. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data["name"] = update.message.text.strip()
        await update.message.reply_text(m("INPUT_PHONE"))
        return ASK_PHONE
    except Exception as e:
        log.error(f"Error in ask_phone: {e}", exc_info=True)
        await update.message.reply_text("❗️ خطا در ثبت نام. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        phone = update.message.text.strip()
        if not phone.startswith("+39") or len(phone) < 10:
            await update.message.reply_text(m("PHONE_INVALID"))
            return ASK_PHONE
        ctx.user_data["phone"] = phone
        await update.message.reply_text(m("INPUT_ADDRESS"))
        return ASK_ADDRESS
    except Exception as e:
        log.error(f"Error in ask_address: {e}", exc_info=True)
        await update.message.reply_text("❗️ خطا در ثبت شماره تلفن. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_postal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        address = update.message.text.strip()
        if len(address) < 10:
            await update.message.reply_text(m("ADDRESS_INVALID"))
            return ASK_ADDRESS
        ctx.user_data["address"] = address
        await update.message.reply_text(m("INPUT_POSTAL"))
        return ASK_POSTAL
    except Exception as e:
        log.error(f"Error in ask_postal: {e}", exc_info=True)
        await update.message.reply_text("❗️ خطا در ثبت آدرس. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_discount(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data["postal"] = update.message.text.strip()
        await update.message.reply_text("🎁 کد تخفیف دارید؟ وارد کنید یا /skip را بزنید.\nHai un codice sconto? Inseriscilo o premi /skip.")
        return ASK_DISCOUNT
    except Exception as e:
        log.error(f"Error in ask_discount: {e}", exc_info=True)
        await update.message.reply_text("❗️ خطا در ثبت کد پستی. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def ask_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if update.message.text == "/skip":
            ctx.user_data["discount_code"] = None
        else:
            code = update.message.text.strip()
            discounts = await load_discounts()
            if code in discounts and discounts[code]["is_active"] and dt.datetime.strptime(discounts[code]["valid_until"], "%Y-%m-%d") >= dt.datetime.utcnow():
                ctx.user_data["discount_code"] = code
            else:
                await update.message.reply_text("❌ کد تخفیف نامعتبر است. لطفاً دوباره وارد کنید یا /skip کنید.\nCodice sconto non valido.")
                return ASK_DISCOUNT
        await update.message.reply_text(m("INPUT_NOTES"))
        return ASK_NOTES
    except Exception as e:
        log.error(f"Error in ask_notes: {e}", exc_info=True)
        await update.message.reply_text("❗️ خطا در بررسی کد تخفیف. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def confirm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if update.message.text == "/skip":
            ctx.user_data["notes"] = ""
        else:
            ctx.user_data["notes"] = update.message.text.strip()
        cart = ctx.user_data.get("cart", [])
        if not cart:
            await update.message.reply_text(m("CART_EMPTY"), reply_markup=ReplyKeyboardRemove())
            ctx.user_data.clear()
            return ConversationHandler.END

        if not await update_stock(cart):
            await update.message.reply_text(m("STOCK_EMPTY"), reply_markup=ReplyKeyboardRemove())
            ctx.user_data.clear()
            return ConversationHandler.END

        order_id = str(uuid.uuid4())[:8]
        ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        total = cart_total(cart)
        discount = 0
        if ctx.user_data.get("discount_code"):
            discounts = await load_discounts()
            discount = total * (discounts[ctx.user_data["discount_code"]]["discount_percent"] / 100)
            total -= discount
        address_full = f"{ctx.user_data['address']} | {ctx.user_data['postal']}"
        try:
            for it in cart:
                await asyncio.to_thread(
                    orders_ws.append_row,
                    [ts, order_id, ctx.user_data["user_id"], ctx.user_data["handle"],
                     ctx.user_data["name"], ctx.user_data["phone"], address_full,
                     ctx.user_data["dest"], it["id"], it["fa"], it["qty"], it["price"],
                     it["qty"] * it["price"], ctx.user_data["notes"],
                     ctx.user_data.get("discount_code", ""), discount, "preparing", "FALSE"]
                )
            log.info(f"Order {order_id} saved to Google Sheets for user {ctx.user_data['handle']}")
            invoice_buffer = await generate_invoice(order_id, ctx.user_data, cart, total, discount)
            await update.message.reply_photo(
                photo=invoice_buffer,
                caption=f"{m('ORDER_CONFIRMED')}\n\n📍 مقصد / Destinazione: {ctx.user_data['dest']}\n💶 مجموع / Totale: {total:.2f}€\n🎁 تخفیف / Sconto: {discount:.2f}€\n📝 یادداشت / Nota: {ctx.user_data['notes'] or 'بدون یادداشت'}",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            log.error(f"Error saving order {order_id}: {e}", exc_info=True)
            await update.message.reply_text(m("ERROR_SHEET"), reply_markup=ReplyKeyboardRemove())
            ctx.user_data.clear()
            return ConversationHandler.END

        if promo := MSG.get("PROMO_AFTER_ORDER"):
            await update.message.reply_text(promo, disable_web_page_preview=True)
        if ADMIN_ID and bot:
            msg = [f"🆕 سفارش / Ordine {order_id}", f"{ctx.user_data['name']} — {total:.2f}€",
                   f"🎁 تخفیف / Sconto: {discount:.2f}€ ({ctx.user_data.get('discount_code', 'بدون کد')})",
                   f"📝 یادداشت / Nota: {ctx.user_data['notes'] or 'بدون یادداشت'}"] + \
                  [f"▫️ {i['qty']}× {i['fa']}" for i in cart]
            try:
                invoice_buffer.seek(0)
                await bot.send_photo(ADMIN_ID, photo=invoice_buffer, caption="\n".join(msg))
                log.info(f"Admin notified for order {order_id}")
            except Exception as e:
                log.error(f"Failed to notify admin for order {order_id}: {e}", exc_info=True)
            try:
                await asyncio.to_thread(abandoned_cart_ws.clear)
            except Exception as e:
                log.error(f"Error clearing abandoned carts: {e}", exc_info=True)
        ctx.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        log.error(f"Error in confirm_order: {e}", exc_info=True)
        await update.message.reply_text("❗️ خطا در ثبت سفارش. لطفاً دوباره امتحان کنید.")
        ctx.user_data.clear()
        return ConversationHandler.END

async def cancel_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data.clear()
        await update.message.reply_text(m("ORDER_CANCELLED"), reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    except Exception as e:
        log.error(f"Error in cancel_order: {e}", exc_info=True)
        await update.message.reply_text("❗️ خطا در لغو سفارش. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

# ───────────── Photo Upload
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        if not ctx.user_data.get("awaiting_photo"):
            return
        photo = update.message.photo[-1]
        if photo.file_size > 2 * 1024 * 1024:
            await update.message.reply_text(m("ERROR_FILE_SIZE"), reply_markup=await kb_main(ctx))
            ctx.user_data["awaiting_photo"] = False
            return
        file = await photo.get_file()
        try:
            await asyncio.to_thread(
                uploads_ws.append_row,
                [dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                 update.effective_user.id,
                 f"@{update.effective_user.username or '-'}",
                 file.file_id]
            )
            await bot.send_photo(
                ADMIN_ID,
                file.file_id,
                caption=f"تصویر از کاربر @{update.effective_user.username or update.effective_user.id}\n📝 توضیح: {ctx.user_data.get('photo_note', 'بدون توضیح')}"
            )
            await update.message.reply_text(m("PHOTO_UPLOADED"))
            ctx.user_data["awaiting_photo"] = False
            ctx.user_data["photo_note"] = ""
            await update.message.reply_text(m("SUPPORT_MESSAGE"), reply_markup=await kb_main(ctx))
        except Exception as e:
            log.error(f"Error handling photo upload: {e}", exc_info=True)
            await update.message.reply_text(m("ERROR_UPLOAD"), reply_markup=await kb_main(ctx))
    except Exception as e:
        log.error(f"Error in handle_photo: {e}", exc_info=True)
        await update.message.reply_text("❗️ خطا در آپلود تصویر. لطفاً دوباره امتحان کنید.")
        ctx.user_data["awaiting_photo"] = False

# ───────────── Keyboards
async def kb_main(ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    try:
        cats = {p["cat"] for p in (await get_products()).values()}
        rows = [[InlineKeyboardButton(EMOJI.get(c, c), callback_data=f"cat_{c}")] for c in sorted(cats)]
        cart = ctx.user_data.get("cart", [])
        cart_summary = f"{m('BTN_CART')} ({cart_count(ctx)} آیتم - {cart_total(cart):.2f}€)" if cart else m("BTN_CART")
        rows.append([
            InlineKeyboardButton(m("BTN_SEARCH"), callback_data="search"),
            InlineKeyboardButton("🔥 پرفروش‌ها / Più venduti", callback_data="bestsellers")
        ])
        rows.append([
            InlineKeyboardButton(cart_summary, callback_data="cart")
        ])
        rows.append([
            InlineKeyboardButton("📞 پشتیبانی / Supporto", callback_data="support")
        ])
        return InlineKeyboardMarkup(rows)
    except Exception as e:
        log.error(f"Error in kb_main: {e}", exc_info=True)
        raise

async def kb_category(cat: str, ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    try:
        if not cat:
            log.error("Invalid category: empty or None")
            return InlineKeyboardMarkup([[InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")]])
        rows = [[InlineKeyboardButton(f"{p['fa']} / {p['it']}", callback_data=f"show_{pid}")]
                for pid, p in (await get_products()).items() if p["cat"] == cat]
        rows.append([
            InlineKeyboardButton(m("BTN_SEARCH"), callback_data="search"),
            InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")
        ])
        return InlineKeyboardMarkup(rows)
    except Exception as e:
        log.error(f"Error in kb_category for category {cat}: {e}", exc_info=True)
        raise

def kb_product(pid: str, cat: str) -> InlineKeyboardMarkup:
    try:
        p = get_products._data.get(pid, None)
        if not p:
            log.error(f"Product {pid} not found in cached products")
            raise KeyError(f"Product {pid} not found")
        if not cat or "_" in cat or " " in cat:
            log.error(f"Invalid category '{cat}' for product {pid}")
            raise ValueError(f"Invalid category '{cat}'")
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(m("CART_ADDED").split("\n")[0], callback_data=f"add_{pid}_{p['cat']}")],
            [InlineKeyboardButton(m("BTN_BACK"), callback_data=f"back_cat_{cat}")]
        ])
    except Exception as e:
        log.error(f"Error in kb_product for product {pid}: {e}", exc_info=True)
        raise

def kb_cart(ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    try:
        cart = ctx.user_data.get("cart", [])
        rows = []
        for it in cart:
            pid = it["id"]
            rows.append([
                InlineKeyboardButton("➕", callback_data=f"inc_{pid}"),
                InlineKeyboardButton(f"{it['qty']}× {it['fa']}", callback_data="ignore"),
                InlineKeyboardButton("➖", callback_data=f"dec_{pid}"),
                InlineKeyboardButton("❌", callback_data=f"del_{pid}")
            ])
        if ctx.user_data.get("dest"):
            rows.append([
                InlineKeyboardButton(m("BTN_ORDER_PERUGIA"), callback_data="order_perugia"),
                InlineKeyboardButton(m("BTN_ORDER_ITALY"), callback_data="order_italy")
            ])
            rows.append([
                InlineKeyboardButton(m("BTN_CONTINUE"), callback_data="checkout"),
                InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")
            ])
        else:
            rows.append([
                InlineKeyboardButton(m("BTN_ORDER_PERUGIA"), callback_data="order_perugia"),
                InlineKeyboardButton(m("BTN_ORDER_ITALY"), callback_data="order_italy")
            ])
            rows.append([
                InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")
            ])
        return InlineKeyboardMarkup(rows)
    except Exception as e:
        log.error(f"Error in kb_cart: {e}", exc_info=True)
        raise

def kb_support() -> InlineKeyboardMarkup:
    try:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📷 ارسال تصویر / Invia immagine", callback_data="upload_photo")],
            [InlineKeyboardButton(m("BTN_BACK"), callback_data="back_main")]
        ])
    except Exception as e:
        log.error(f"Error in kb_support: {e}", exc_info=True)
        raise

# ───────────── Cart operations
async def add_cart(ctx: ContextTypes.DEFAULT_TYPE, pid: str, qty: int = 1, update: Optional[Update] = None) -> tuple[bool, str]:
    try:
        prods = await get_products()
        if pid not in prods:
            log.error(f"Product {pid} not found in products")
            return False, m("STOCK_EMPTY")
        p = prods[pid]
        stock = p.get("stock", 0)
        if not isinstance(stock, int):
            log.error(f"Invalid stock for product {pid}: {stock}")
            return False, "❗️ خطا در بررسی موجودی محصول."
        cart = ctx.user_data.setdefault("cart", [])
        cur = next((i for i in cart if i["id"] == pid), None)
        cur_qty = cur["qty"] if cur else 0
        if stock < cur_qty + qty:
            log.warning(f"Insufficient stock for {pid}: available={stock}, requested={cur_qty + qty}")
            return False, m("STOCK_EMPTY")
        if cur:
            cur["qty"] += qty
        else:
            cart.append(dict(
                id=pid,
                fa=p["fa"],
                it=p.get("it", "N/A"),
                price=p["price"],
                weight=p["weight"],
                qty=qty
            ))
        await alert_admin(pid, stock - qty)
        try:
            await asyncio.to_thread(
                abandoned_cart_ws.append_row,
                [dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                 ctx.user_data.get("user_id", update.effective_user.id if update else 0),
                 json.dumps(cart)]
            )
            log.info(f"Abandoned cart saved for user {ctx.user_data.get('user_id', 'unknown')}")
        except Exception as e:
            log.error(f"Error saving abandoned cart: {e}", exc_info=True)
        return True, m("CART_ADDED")
    except Exception as e:
        log.error(f"Error in add_cart for product {pid}: {e}", exc_info=True)
        return False, "❗️ خطا در افزودن به سبد خرید."

def fmt_cart(cart: List[Dict[str, Any]]) -> str:
    try:
        if not cart:
            return m("CART_EMPTY")
        lines = ["🛍 **سبد خرید / Carrello:**", ""]
        tot = 0
        for it in cart:
            sub = it["qty"] * it["price"]
            tot += sub
            lines.append(f"▫️ {it['qty']}× {it['fa']} — {sub:.2f}€")
        lines.append("")
        lines.append(f"💶 **جمع / Totale:** {tot:.2f}€")
        return "\n".join(lines)
    except Exception as e:
        log.error(f"Error in fmt_cart: {e}", exc_info=True)
        return "❗️ خطا در نمایش سبد خرید."

# ───────────── Stock update
async def update_stock(cart: List[Dict[str, Any]]) -> bool:
    try:
        records = await asyncio.to_thread(products_ws.get_all_records)
        for it in cart:
            pid = it["id"]
            qty = it["qty"]
            for idx, row in enumerate(records, start=2):
                if row["id"] == pid:
                    try:
                        new = int(row["stock"]) - qty
                    except (ValueError, TypeError) as e:
                        log.error(f"Invalid stock value for {pid} in Google Sheets: {row.get('stock', 'N/A')}. Error: {e}", exc_info=True)
                        return False
                    if new < 0:
                        log.error(f"Cannot update stock for {pid}: negative stock")
                        return False
                    await asyncio.to_thread(products_ws.update_cell, idx, 10, new)
                    (await get_products())[pid]["stock"] = new
                    log.info(f"Updated stock for {pid}: {new}")
                    await alert_admin(pid, new)
        return True
    except gspread.exceptions.APIError as e:
        log.error(f"Google Sheets API error during stock update: {e}", exc_info=True)
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در به‌روزرسانی موجودی: {e}")
        return False
    except Exception as e:
        log.error(f"Stock update error: {e}", exc_info=True)
        return False

# ───────────── Push Notifications for Order Status
async def check_order_status(context: ContextTypes.DEFAULT_TYPE):
    try:
        last_checked_row = getattr(check_order_status, "_last_checked_row", 1)
        shipped_cells = await asyncio.to_thread(orders_ws.findall, "shipped")
        preparing_cells = await asyncio.to_thread(orders_ws.findall, "preparing")
        for cell in shipped_cells + preparing_cells:
            if cell.row <= last_checked_row:
                continue
            row_data = await asyncio.to_thread(orders_ws.row_values, cell.row)
            if len(row_data) < 18 or row_data[17] == "TRUE":
                continue
            user_id = int(row_data[2])
            order_id = row_data[1]
            status = row_data[16]
            msg = {
                "preparing": f"📦 سفارش شما (#{order_id}) در حال آماده‌سازی است!\nIl tuo ordine (#{order_id}) è in preparazione!",
                "shipped": f"🚚 سفارش شما (#{order_id}) ارسال شد!\nIl tuo ordine (#{order_id}) è stato spedito!"
            }[status]
            await context.bot.send_message(user_id, msg, reply_markup=await kb_main(context))
            await asyncio.to_thread(orders_ws.update_cell, cell.row, 18, "TRUE")
            log.info(f"Sent {status} notification for order {order_id} to user {user_id}")
        check_order_status._last_checked_row = max(last_checked_row, max((c.row for c in shipped_cells + preparing_cells), default=1))
    except Exception as e:
        log.error(f"Error checking order status: {e}", exc_info=True)
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در بررسی وضعیت سفارشات: {e}")

# ───────────── Backup Google Sheets
async def backup_sheets(context: ContextTypes.DEFAULT_TYPE):
    try:
        sheets = [orders_ws, products_ws, discounts_ws, abandoned_cart_ws, uploads_ws]
        for sheet in sheets:
            records = await asyncio.to_thread(sheet.get_all_values)
            csv_content = "\n".join([",".join(row) for row in records])
            csv_file = io.BytesIO()
            with zipfile.ZipFile(csv_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{sheet.title}.csv", csv_content.encode("utf-8"))
            csv_file.seek(0)
            csv_file.name = f"{sheet.title}_backup_{dt.datetime.utcnow().strftime('%Y%m%d')}.zip"
            await context.bot.send_document(ADMIN_ID, document=csv_file, caption=f"📊 بکاپ {sheet.title} - {dt.datetime.utcnow().strftime('%Y-%m-%d')}")
            log.info(f"Backup sent for {sheet.title}")
    except Exception as e:
        log.error(f"Error creating backup: {e}", exc_info=True)
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در ایجاد بکاپ: {e}")

# ───────────── Abandoned Cart Reminder
async def send_cart_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        records = await asyncio.to_thread(abandoned_cart_ws.get_all_records)
        for record in records:
            cart = json.loads(record["cart"])
            user_id = int(record["user_id"])
            if cart:
                await context.bot.send_message(
                    user_id,
                    f"🛒 سبد خرید شما هنوز منتظر شماست!\nHai lasciato qualcosa nel carrello!\n{fmt_cart(cart)}\n👉 برای تکمیل سفارش: /start",
                    reply_markup=await kb_main(context)
                )
        await asyncio.to_thread(abandoned_cart_ws.clear)
    except Exception as e:
        log.error(f"Error sending cart reminders: {e}", exc_info=True)
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در ارسال یادآور سبد خرید: {e}")

# ───────────── /search
from difflib import get_close_matches
async def cmd_search(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        q = " ".join(ctx.args).lower()
        if not q:
            await u.message.reply_text(m("SEARCH_USAGE"))
            return
        hits = [(pid, p) for pid, p in (await get_products()).items()
                if q in p['fa'].lower() or q in p['it'].lower()
                or get_close_matches(q, [p['fa'].lower() + " " + p['it'].lower()], cutoff=0.6)]
        if not hits:
            await u.message.reply_text(m("SEARCH_NONE"))
            return
        for pid, p in hits[:5]:
            cap = f"{p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€\nموجودی / Stock: {p['stock']}"
            btn = InlineKeyboardMarkup.from_button(InlineKeyboardButton(m("CART_ADDED").split("\n")[0], callback_data=f"add_{pid}_{p['cat']}"))
            if p["image_url"] and p["image_url"].strip():
                try:
                    await u.message.reply_photo(p["image_url"], caption=cap, reply_markup=btn)
                except Exception as e:
                    log.warning(f"Failed to send image for product {pid}: {e}")
                    await u.message.reply_text(cap, reply_markup=btn)
            else:
                await u.message.reply_text(cap, reply_markup=btn)
    except Exception as e:
        log.error(f"Error in cmd_search: {e}", exc_info=True)
        await u.message.reply_text("❗️ خطا در جستجو. لطفاً دوباره امتحان کنید.")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در /search: {e}")

# ───────────── Commands
async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["user_id"] = u.effective_user.id
        await u.message.reply_html(m("WELCOME"), reply_markup=await kb_main(ctx))
    except Exception as e:
        log.error(f"Error in cmd_start: {e}", exc_info=True)
        await u.message.reply_text("❗️ خطایی در بارگذاری منو رخ داد. لطفاً بعداً امتحان کنید یا با پشتیبانی تماس بگیرید.\nErrore nel caricamento del menu. Riprova più tardi o contatta il supporto.")
        if ADMIN_ID and bot:
            await bot.send_message(ADMIN_ID, f"⚠️ خطا در /start: {e}")
        raise

async def cmd_about(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await u.message.reply_text(m("ABOUT_US"), disable_web_page_preview=True)
    except Exception as e:
        log.error(f"Error in cmd_about: {e}", exc_info=True)
        await u.message.reply_text("❗️ خطا در نمایش اطلاعات. لطفاً دوباره امتحان کنید.")

async def cmd_privacy(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await u.message.reply_text(m("PRIVACY"), disable_web_page_preview=True)
    except Exception as e:
        log.error(f"Error in cmd_privacy: {e}", exc_info=True)
        await u.message.reply_text("❗️ خطا در نمایش سیاست حریم خصوصی. لطفاً دوباره امتحان کنید.")

# ───────────── Callback Query Router
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        data = query.data

        if data != "back_main" and not data.startswith("back_cat_"):
            ctx.user_data["last_menu"] = data

        if data.startswith("cat_"):
            cat = data[4:]
            if not cat:
                log.error("Empty category in cat_ callback")
                await safe_edit(query, "❗️ دسته‌بندی نامعتبر است.", reply_markup=await kb_main(ctx))
                return
            ctx.user_data["current_cat"] = cat
            await safe_edit(query, f"دسته‌بندی: {EMOJI.get(cat, cat)}", reply_markup=await kb_category(cat, ctx))

        elif data.startswith("show_"):
            pid = data[5:]
            prods = await get_products()
            if pid not in prods:
                log.error(f"Product {pid} not found in show_ callback")
                await safe_edit(query, m("STOCK_EMPTY"), reply_markup=await kb_main(ctx))
                return
            p = prods[pid]
            cap = f"{p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€\nموجودی / Stock: {p['stock']}"
            ctx.user_data["current_product"] = pid
            ctx.user_data["current_cat"] = p["cat"]
            if p["image_url"] and p["image_url"].strip():
                try:
                    await query.message.delete()
                    await query.message.reply_photo(p["image_url"], caption=cap, reply_markup=kb_product(pid, p["cat"]))
                except Exception as e:
                    log.warning(f"Failed to send image for product {pid}: {e}")
                    await safe_edit(query, cap, reply_markup=kb_product(pid, p["cat"]))
            else:
                await safe_edit(query, cap, reply_markup=kb_product(pid, p["cat"]))

        elif data.startswith("add_"):
            parts = data.split("_")
            if len(parts) != 3:
                log.error(f"Invalid add_ callback data: {data}")
                await safe_edit(query, "❗️ خطا در افزودن محصول. لطفاً دوباره امتحان کنید.", reply_markup=await kb_main(ctx))
                return
            pid, cat = parts[1], parts[2]
            success, msg = await add_cart(ctx, pid, update=update)
            prods = await get_products()
            if pid not in prods:
                log.error(f"Product {pid} not found after add_cart")
                await safe_edit(query, m("STOCK_EMPTY"), reply_markup=await kb_category(cat, ctx))
                return
            p = prods[pid]
            cap = f"{msg}\n\n{p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€\nموجودی / Stock: {p['stock']}"
            await safe_edit(query, cap, reply_markup=await kb_category(cat, ctx))

        elif data.startswith("inc_"):
            pid = data[4:]
            success, msg = await add_cart(ctx, pid, update=update)
            cart = ctx.user_data.get("cart", [])
            await safe_edit(query, fmt_cart(cart), reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data.startswith("dec_"):
            pid = data[4:]
            cart = ctx.user_data.get("cart", [])
            item = next((i for i in cart if i["id"] == pid), None)
            if item and item["qty"] > 1:
                item["qty"] -= 1
            elif item:
                cart.remove(item)
            await safe_edit(query, fmt_cart(cart), reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data.startswith("del_"):
            pid = data[4:]
            cart = ctx.user_data.get("cart", [])
            cart[:] = [i for i in cart if i["id"] != pid]
            await safe_edit(query, fmt_cart(cart), reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data == "cart":
            cart = ctx.user_data.get("cart", [])
            if not ctx.user_data.get("dest"):
                await safe_edit(query, f"{m('CART_GUIDE')}\n\n{fmt_cart(cart)}", reply_markup=kb_cart(ctx), parse_mode="HTML")
            else:
                await safe_edit(query, fmt_cart(cart), reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data == "order_perugia":
            ctx.user_data["dest"] = "Perugia"
            cart = ctx.user_data.get("cart", [])
            await safe_edit(query, f"مقصد: Perugia\n\n{fmt_cart(cart)}", reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data == "order_italy":
            ctx.user_data["dest"] = "Italia"
            cart = ctx.user_data.get("cart", [])
            await safe_edit(query, f"مقصد: Italia\n\n{fmt_cart(cart)}", reply_markup=kb_cart(ctx), parse_mode="HTML")

        elif data == "back_main":
            await safe_edit(query, m("WELCOME"), reply_markup=await kb_main(ctx), parse_mode="HTML")

        elif data.startswith("back_cat_"):
            cat = data[9:]
            if not cat:
                log.error("Invalid category in back_cat_ callback")
                await safe_edit(query, "❗️ دسته‌بندی نامعتبر است.", reply_markup=await kb_main(ctx))
                return
            ctx.user_data["current_cat"] = cat
            await safe_edit(query, f"دسته‌بندی: {EMOJI.get(cat, cat)}", reply_markup=await kb_category(cat, ctx))

        elif data == "bestsellers":
            prods = await get_products()
            bestsellers = [(pid, p) for pid, p in prods.items() if p["is_bestseller"]]
            if not bestsellers:
                await safe_edit(query, "❌ هیچ محصول پرفروشی یافت نشد.\nNessun prodotto bestseller trovato.", reply_markup=await kb_main(ctx))
                return
            try:
                await query.message.delete()
            except Exception:
                pass
            for pid, p in bestsellers[:5]:
                cap = f"{p['fa']} / {p['it']}\n{p['desc']}\n{p['price']}€\nموجودی / Stock: {p['stock']}"
                btn = InlineKeyboardMarkup.from_button(InlineKeyboardButton(m("CART_ADDED").split("\n")[0], callback_data=f"add_{pid}_{p['cat']}"))
                if p["image_url"] and p["image_url"].strip():
                    try:
                        await query.message.reply_photo(p["image_url"], caption=cap, reply_markup=btn)
                    except Exception as e:
                        log.warning(f"Failed to send image for product {pid}: {e}")
                        await query.message.reply_text(cap, reply_markup=btn)
                else:
                    await query.message.reply_text(cap, reply_markup=btn)
            await query.message.reply_text("🔥 محصولات پرفروش / Prodotti più venduti", reply_markup=await kb_main(ctx))

        elif data == "search":
            await safe_edit(query, m("SEARCH_USAGE"))

        elif data == "support":
            await safe_edit(query, m("SUPPORT_MESSAGE"), reply_markup=kb_support())

        elif data == "upload_photo":
            ctx.user_data["awaiting_photo"] = True
            await safe_edit(query, m("UPLOAD_PHOTO"), reply_markup=kb_support())
    except Exception as e:
        log.error(f"Error in router: {e}", exc_info=True)
        await safe_edit(query, "❗️ خطا در پردازش درخواست. لطفاً دوباره امتحان کنید.", reply_markup=await kb_main(ctx))
# ───────────── FastAPI and Webhook
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global tg_app, bot
    try:
        log.info("Starting up FastAPI application")
        log.info("Validating Google Sheets structure")
        await validate_sheets()

        critical_files = [
            "config.yaml",
            "messages.json",
            "/etc/secrets/bazarino-perugia-bot-f37c44dd9b14.json"
        ]
        optional_files = [
            "fonts/Vazir.ttf",
            "fonts/arial.ttf",
            "fonts/Nastaliq.ttf",
            "background_pattern.png",
            "logo.png"
        ]
        for f in critical_files:
            if not os.path.exists(f):
                log.error(f"Critical file not found: {f}")
                raise FileNotFoundError(f"❗️ فایل حیاتی '{f}' یافت نشد.")
            else:
                log.info(f"Critical file found: {f}")
        for f in optional_files:
            if not os.path.exists(f):
                log.warning(f"Optional file not found: {f}, using defaults where applicable")
            else:
                log.info(f"Optional file found: {f}")

        log.info("Validating Telegram token")
        for attempt in range(3):
            try:
                response = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=5)
                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    log.error(f"Invalid Telegram token response: {data}")
                    raise ValueError(f"❗️ توکن تلگرام نامعتبر است: {data}")
                log.info(f"Telegram token validated successfully: {data['result']['username']}")
                break
            except requests.RequestException as e:
                log.error(f"Failed to validate Telegram token (attempt {attempt + 1}): {e}", exc_info=True)
                if attempt < 2:
                    await asyncio.sleep(2)
                else:
                    raise SystemExit(f"❗️ خطا در اعتبارسنجی توکن تلگرام پس از 3 تلاش: {e}")

        log.info("Building Telegram application")
        builder = ApplicationBuilder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown)
        tg_app = builder.build()
        log.info("Telegram application built successfully")

        bot = tg_app.bot
        log.info("Bot initialized successfully")

        log.info("Initializing Telegram application")
        await tg_app.initialize()
        log.info("Telegram application initialized successfully")

        log.info("Accessing JobQueue")
        if tg_app.job_queue is None:
            log.error("JobQueue is not available. Ensure python-telegram-bot[job-queue] is installed.")
            raise SystemExit("❗️ JobQueue is not available. Ensure python-telegram-bot[job-queue] is installed.")

        log.info("Scheduling jobs")
        tg_app.job_queue.run_daily(send_cart_reminder, time=dt.time(hour=18, minute=0))
        tg_app.job_queue.run_repeating(check_order_status, interval=600)
        tg_app.job_queue.run_daily(backup_sheets, time=dt.time(hour=0, minute=0))
        log.info("Jobs scheduled successfully")

        log.info("Adding handlers to Telegram application")
        order_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(start_order, pattern="^checkout$")],
            states={
                ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
                ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
                ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_postal)],
                ASK_POSTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_discount)],
                ASK_DISCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_notes)],
                ASK_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_order)],
            },
            fallbacks=[CommandHandler("cancel", cancel_order)],
            per_user=True,
            per_chat=True
        )

        tg_app.add_handler(CommandHandler("start", cmd_start))
        tg_app.add_handler(CommandHandler("about", cmd_about))
        tg_app.add_handler(CommandHandler("privacy", cmd_privacy))
        tg_app.add_handler(CommandHandler("search", cmd_search))
        tg_app.add_handler(order_conv)
        tg_app.add_handler(CallbackQueryHandler(router))
        tg_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        log.info("Handlers added successfully")

        log.info("Starting Telegram application")
        await tg_app.start()
        log.info("Telegram application started successfully")

        yield  # Control is passed to FastAPI application

    except Exception as e:
        log.error(f"Startup error: {e}", exc_info=True)
        tg_app = None
        if ADMIN_ID and bot:
            try:
                await bot.send_message(ADMIN_ID, f"⚠️ خطا در راه‌اندازی اپلیکیشن: {e}")
            except Exception as admin_e:
                log.error(f"Failed to notify admin: {admin_e}", exc_info=True)
        raise SystemExit(f"❗️ خطا در راه‌اندازی اپلیکیشن: {e}")

    finally:
        log.info("Shutting down FastAPI application")
        if tg_app:
            try:
                await tg_app.stop()
                await tg_app.shutdown()
                log.info("Telegram application shutdown completed")
            except Exception as e:
                log.error(f"Error during shutdown: {e}", exc_info=True)

async def post_init(app: Application):
    try:
        log.info("Setting webhook")
        webhook_url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
        await app.bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET)
        log.info(f"Webhook set to {webhook_url}")
    except Exception as e:
        log.error(f"Error setting webhook: {e}", exc_info=True)
        raise

async def post_shutdown(app: Application):
    try:
        log.info("Deleting webhook")
        await app.bot.delete_webhook()
        log.info("Webhook deleted successfully")
    except Exception as e:
        log.error(f"Error deleting webhook: {e}", exc_info=True)

app = FastAPI(lifespan=lifespan)

@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def webhook(request: Request):
    global tg_app
    try:
        if not tg_app:
            log.error("Telegram application not initialized")
            raise HTTPException(status_code=503, detail="Application not initialized")
        update = Update.de_json(await request.json(), bot)
        if not update:
            log.error("Invalid update received")
            raise HTTPException(status_code=400, detail="Invalid update")
        await tg_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        log.error(f"Webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")

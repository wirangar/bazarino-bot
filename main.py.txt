# main.py – Bazarnio Bot (PTB-20 + run_webhook)
import os, datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

TOKEN      = os.environ["TELEGRAM_TOKEN"]
ADMIN_ID   = int(os.getenv("ADMIN_CHAT_ID", "0"))
SHEET_NAME = os.getenv("SHEET_NAME", "Bazarnio Orders")
PORT       = int(os.environ.get("PORT", 8080))
BASE_URL   = os.environ["BASE_URL"]          # ← در Cloud Run تعریف می‌کنیم

scope  = ["https://spreadsheets.google.com/feeds",
          "https://www.googleapis.com/auth/drive"]
creds  = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
sheet  = gspread.authorize(creds).open(SHEET_NAME).sheet1

NAME, ADDRESS, PHONE, PRODUCT, QTY, NOTES = range(6)

async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    kb = [["🛍 مشاهده منو"], ["📝 ثبت سفارش"], ["ℹ️ درباره ما", "📞 تماس"]]
    await u.message.reply_html(
        "🍊 خوش آمدی به <b>Bazarnio</b> – طعم ایران در قلب پروجا 🇮🇷🇮🇹\n\n"
        "🎉 برای شروع یکی را انتخاب کن:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def about(u, _):    await u.message.reply_text("بازارینو – طعم خونه 🇮🇷🇮🇹")
async def contact(u, _):  await u.message.reply_text("📞 +39 …\nIG: @bazarnio")
async def menu(u, _):     await u.message.reply_text("🍚 برنج\n🌿 ادویه\n🍬 تنقلات …")

async def start_order(u, _):          await u.message.reply_text("👤 نام:"); return NAME
async def get_name(u, c):    c.user_data["name"]=u.message.text; await u.message.reply_text("🏠 آدرس:"); return ADDRESS
async def get_address(u, c): c.user_data["address"]=u.message.text; await u.message.reply_text("📞 تلفن:"); return PHONE
async def get_phone(u, c):   c.user_data["phone"]=u.message.text; await u.message.reply_text("📦 محصول:"); return PRODUCT
async def get_product(u,c):  c.user_data["product"]=u.message.text; await u.message.reply_text("🔢 تعداد:"); return QTY
async def get_qty(u, c):     c.user_data["qty"]=u.message.text;  await u.message.reply_text("📝 توضیح:"); return NOTES

async def get_notes(u, c):
    c.user_data["notes"]=u.message.text
    row=[str(datetime.datetime.utcnow()),c.user_data[k] for k in ("name","address","phone","product","qty","notes")]
    row.append(f"@{u.effective_user.username}" if u.effective_user.username else "-")
    sheet.append_row(row)
    await u.message.reply_text("✅ سفارش ثبت شد!")
    if ADMIN_ID: await c.bot.send_message(ADMIN_ID, "📥 سفارش جدید:\n"+ "\n".join(row[1:7]))
    return ConversationHandler.END

async def cancel(u,_): await u.message.reply_text("لغو شد."); return ConversationHandler.END

def build_app():
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🛍"), menu))
    app.add_handler(MessageHandler(filters.Regex("^ℹ"), about))
    app.add_handler(MessageHandler(filters.Regex("^📞"), contact))
    conv=ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝"), start_order)],
        states={NAME:[MessageHandler(filters.TEXT, get_name)],
                ADDRESS:[MessageHandler(filters.TEXT, get_address)],
                PHONE:[MessageHandler(filters.TEXT, get_phone)],
                PRODUCT:[MessageHandler(filters.TEXT, get_product)],
                QTY:[MessageHandler(filters.TEXT, get_qty)],
                NOTES:[MessageHandler(filters.TEXT, get_notes)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(conv); return app

if __name__ == "__main__":
    build_app().run_webhook(
        listen="0.0.0.0", port=PORT,
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}"
    )

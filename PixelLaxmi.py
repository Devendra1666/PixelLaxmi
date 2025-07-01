import logging
import uuid
import os
import re
import smtplib
from email.message import EmailMessage
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.ext._application import Application
from fastapi import FastAPI, Request
import uvicorn
import asyncio

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

orders = {}
waiting_for_status = set()

ADMIN_CHAT_ID = 8178524981
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = "https://pixellaxmi.onrender.com/webhook"

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

RAZORPAY_LINKS = {
    20: "https://rzp.io/r/0YOfrpS",
    30: "https://rzp.io/r/NTJ69QRD",
    50: "https://rzp.io/r/rSAe7dZ"
}

app = FastAPI()
telegram_app: Application = None

def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def plan_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Basic ₹20", callback_data="plan_20")],
        [InlineKeyboardButton("High ₹30", callback_data="plan_30")],
        [InlineKeyboardButton("Ultra ₹50", callback_data="plan_50")],
    ])

def admin_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View Original Image", callback_data=f"view_img|{order_id}")],
        [InlineKeyboardButton("View Payment Proof", callback_data=f"view_proof|{order_id}")],
        [InlineKeyboardButton("Approve Payment ✅", callback_data=f"approve|{order_id}")],
        [InlineKeyboardButton("Reject Payment ❌", callback_data=f"reject|{order_id}")],
        [InlineKeyboardButton("Request New Payment Proof 🔄", callback_data=f"ask_proof|{order_id}")],
        [InlineKeyboardButton("Send Upscaled Image 🚀", callback_data=f"send_upscaled|{order_id}")],
    ])

def send_email_with_image(to_email, file_id, order_id):
    try:
        msg = EmailMessage()
        msg['Subject'] = f"Your Upscaled Image - Order {order_id}"
        msg['From'] = EMAIL_USER
        msg['To'] = to_email
        msg.set_content(f"Hi! Your upscaled image for Order {order_id} is attached. Thank you!")
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

@app.get("/")
async def root():
    return {"status": "PixelLaxmi Bot is running"}

@app.post("/webhook")
async def telegram_webhook(req: Request):
    global telegram_app
    if telegram_app is None:
        return {"ok": False, "error": "Bot not initialized yet"}
    data = await req.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨ Welcome! Please upload your image to start your order. ✨")

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await update.message.reply_text("For any queries please contact @Devendra_1666")
    text = f"📩 Contact Request:\nUser: {user.full_name} (ID: {user.id})\nUsername: @{user.username or 'N/A'}"
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)

def find_pending_order(user_id):
    for oid, order in orders.items():
        if order['user_id'] == user_id and order['status'] in ['waiting_plan', 'waiting_payment', 'waiting_email']:
            return oid
    return None

async def user_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    for oid, order in orders.items():
        if order['user_id'] == user.id and order['status'] == 'waiting_payment':
            proof_id = update.message.photo[-1].file_id
            order['payment_proof'] = proof_id
            order['status'] = 'waiting_email'
            await update.message.reply_text("✅ Payment proof received.\n📧 Please enter your email address so we can send the upscaled image there too.")
            return

    file_id = update.message.photo[-1].file_id
    new_oid = str(uuid.uuid4())[:8]
    orders[new_oid] = {
        'user_id': user.id,
        'user_name': user.full_name,
        'file_id': file_id,
        'plan': None,
        'payment_proof': None,
        'upscaled_file_id': None,
        'email': None,
        'status': 'waiting_plan'
    }
    await update.message.reply_text(
        f"🆔 Your Order ID is: `{new_oid}`\nPlease select a plan:",
        parse_mode="Markdown",
        reply_markup=plan_keyboard()
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.from_user.id
    args = context.args

    if args:
        order_id = args[0]
        order = orders.get(order_id)
        if order and order['user_id'] == chat_id:
            await update.message.reply_text(f"📦 Order {order_id} status: {order['status']}")
        else:
            await update.message.reply_text("❌ Order not found or does not belong to you.")
    else:
        waiting_for_status.add(chat_id)
        await update.message.reply_text("🔐 Please send your Order ID to check the status. Example: `a1b2c3d4`", parse_mode="Markdown")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.from_user.id
    text = update.message.text.strip()

    if chat_id in waiting_for_status and not text.startswith('/'):
        waiting_for_status.remove(chat_id)
        order = orders.get(text)
        if order and order['user_id'] == chat_id:
            await update.message.reply_text(f"📦 Order {text} status: {order['status']}")
        else:
            await update.message.reply_text("❌ Order not found or does not belong to you.")
        return

    for oid, order in orders.items():
        if order['user_id'] == chat_id and order['status'] == 'waiting_email':
            if is_valid_email(text):
                order['email'] = text
                order['status'] = 'waiting_admin'
                await update.message.reply_text("✅ Email saved! Please wait while admin reviews your payment.")

                # Notify admin after email is saved
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"💰 Payment Received for Order {oid}\nUser: {order['user_name']} (ID: {order['user_id']})\nPlan: ₹{order['plan']}",
                    reply_markup=admin_keyboard(oid)
                )
            else:
                await update.message.reply_text("❌ Invalid email. Please enter a valid email address (example@example.com)")
            return

    pending = find_pending_order(chat_id)
    if pending:
        await update.message.reply_text("⚠️ Please complete your pending order or send /cancel to cancel it.")
    else:
        await update.message.reply_text("✨ Main Menu ✨\n/start - Upload image\n/status - Check status\n/contact - Contact admin\n/cancel - Cancel order")

async def plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, price = query.data.split('_')
    for oid, order in orders.items():
        if order['user_id'] == query.from_user.id and order['status'] == 'waiting_plan':
            order['plan'] = int(price)
            order['status'] = 'waiting_payment'
            payment_link = RAZORPAY_LINKS.get(int(price), "")
            await query.message.edit_text(f"💡 You selected the ₹{price} plan. Pay here: {payment_link}\nAfter payment, upload screenshot here.")
            return
    await query.message.reply_text("No pending order found.")

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, oid = query.data.split('|')
    order = orders.get(oid)
    if not order:
        return

    if action == 'view_img':
        await context.bot.send_photo(ADMIN_CHAT_ID, order['file_id'], caption=f"🖼️ Original Image for Order {oid}")
    elif action == 'view_proof' and order.get('payment_proof'):
        await context.bot.send_photo(ADMIN_CHAT_ID, order['payment_proof'], caption=f"💳 Payment Proof for Order {oid}")
    elif action == 'approve':
        order['status'] = 'approved'
        await context.bot.send_message(order['user_id'], f"✅ Your payment for Order {oid} has been approved!")
    elif action == 'reject':
        order['status'] = 'rejected'
        await context.bot.send_message(order['user_id'], f"❌ Your payment for Order {oid} has been rejected. Please contact support.")
    elif action == 'ask_proof':
        order['status'] = 'waiting_payment'
        await context.bot.send_message(order['user_id'], f"🔄 Please re-upload valid payment proof for Order {oid}.")
    elif action == 'send_upscaled':
        order['status'] = 'awaiting_upscaled'
        await context.bot.send_message(ADMIN_CHAT_ID, f"🚀 Please upload the upscaled image for Order {oid}.")

async def handle_admin_upscaled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for oid, order in orders.items():
        if order['status'] == 'awaiting_upscaled':
            file_id = update.message.photo[-1].file_id
            order['upscaled_file_id'] = file_id
            await context.bot.send_photo(order['user_id'], file_id, caption="✨ Here is your upscaled image!")
            if order.get('email'):
                send_email_with_image(order['email'], file_id, oid)
            await context.bot.send_message(order['user_id'], f"🎉 Order {oid} complete! Thank you!")
            order['status'] = 'complete'
            await update.message.reply_text(f"✅ Order {oid} marked as complete.")
            return

async def main():
    global telegram_app
    telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("contact", contact))
    telegram_app.add_handler(CommandHandler("status", status))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.User(ADMIN_CHAT_ID), text_handler))
    telegram_app.add_handler(MessageHandler(filters.PHOTO & ~filters.User(ADMIN_CHAT_ID), user_photo_handler))
    telegram_app.add_handler(MessageHandler(filters.PHOTO & filters.User(ADMIN_CHAT_ID), handle_admin_upscaled))
    telegram_app.add_handler(CallbackQueryHandler(plan_choice, pattern=r"^plan_"))
    telegram_app.add_handler(CallbackQueryHandler(handle_admin_actions, pattern=r"^(view_img|view_proof|approve|reject|ask_proof|send_upscaled)\|"))

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.bot.set_webhook(WEBHOOK_URL)
    print("Webhook set: True\nBot started with webhook...")

if __name__ == "__main__":
    async def run():
        await main()
        config = uvicorn.Config(app=app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(run())

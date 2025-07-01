import logging
import uuid
import os
import re
import smtplib
from io import BytesIO
from email.message import EmailMessage
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.ext._application import Application
from fastapi import FastAPI, Request
import uvicorn
import asyncio
from functools import partial
import nest_asyncio

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
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

COMMON_MISTAKES = ["gamil.com", "gmial.com", "gnail.com", "yahho.com", "yhoo.com"]

def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def has_typo(email):
    domain = email.split("@")[1]
    return any(m in domain for m in COMMON_MISTAKES)

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

async def send_email_with_image(to_email, file_id, order_id):
    try:
        bot = telegram_app.bot
        tg_file = await bot.get_file(file_id)
        file_bytes = BytesIO()
        await tg_file.download_to_memory(out=file_bytes)
        file_bytes.seek(0)

        msg = EmailMessage()
        msg['Subject'] = f"Your Upscaled Image - Order {order_id}"
        msg['From'] = EMAIL_USER
        msg['To'] = to_email
        msg.set_content(f"""
        <html>
            <body style="font-family:Arial, sans-serif; color:#333;">
                <h2>🎉 Your Upscaled Image is Ready!</h2>
                <p>Hi there,</p>
                <p>Thanks for choosing <strong>PixelLaxmi</strong>! Your upscaled image for <strong>Order {order_id}</strong> is attached to this email.</p>
                <p>If you love the result, feel free to visit our bot again and place a new order anytime. We're always here to help your images shine ✨</p>
                <p style="margin-top:20px;">Warm regards,<br><strong>Team PixelLaxmi</strong></p>
            </body>
        </html>
        """, subtype='html')

        msg.add_attachment(file_bytes.read(), maintype='image', subtype='jpeg', filename=f"upscaled_{order_id}.jpg")

        def send():
            with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
                smtp.starttls()
                smtp.login(EMAIL_USER, EMAIL_PASS)
                smtp.send_message(msg)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, send)

        return True
    except Exception as e:
        logger.error(f"❌ Failed to send email with image: {e}")
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

async def user_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    for oid, order in orders.items():
        if order['user_id'] == user.id and order['status'] == 'waiting_payment':
            proof_id = update.message.photo[-1].file_id
            order['payment_proof'] = proof_id
            order['status'] = 'approved'
            await update.message.reply_text("✅ Payment proof received.")
            await update.message.reply_text("📧 Please send your email address where we can deliver the upscaled image (optional). Or just wait and receive it here on Telegram.")
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"💰 Payment Received for Order {oid}\nUser: {order['user_name']} (ID: {order['user_id']})\nPlan: ₹{order['plan']}",
                reply_markup=admin_keyboard(oid)
            )
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
        'status': 'waiting_plan',
        'email': None
    }
    await update.message.reply_text(f"🆔 Your Order ID is: {new_oid}\nPlease select a plan:", reply_markup=plan_keyboard())

async def plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, price = query.data.split('_')
    for oid, order in orders.items():
        if order['user_id'] == query.from_user.id and order['status'] == 'waiting_plan':
            order['plan'] = int(price)
            order['status'] = 'waiting_payment'
            payment_link = RAZORPAY_LINKS.get(int(price), "")
            await query.message.edit_text(f"💡 You selected the ₹{price} plan. Please pay using this link: {payment_link}\n\nAfter payment, upload the payment screenshot here.")
            return
    await query.message.reply_text("No pending order found.")

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, oid = query.data.split('|')
    order = orders.get(oid)
    if not order:
        return
    if action == 'approve':
        order['status'] = 'approved'
        await context.bot.send_message(order['user_id'], f"✅ Your payment for Order {oid} has been approved! Please send your email address (optional).")
        await context.bot.send_message(ADMIN_CHAT_ID, f"✅ Payment for Order {oid} has been approved.")
    elif action == 'reject':
        order['status'] = 'rejected'
        await context.bot.send_message(order['user_id'], f"❌ Your payment for Order {oid} has been rejected. Please contact support.")
    elif action == 'ask_proof':
        order['status'] = 'waiting_payment'
        await context.bot.send_message(order['user_id'], f"🔄 Please re-upload valid payment proof for Order {oid}.")
    elif action == 'send_upscaled':
        order['status'] = 'awaiting_upscaled'
        await context.bot.send_message(ADMIN_CHAT_ID, f"🚀 Please upload the upscaled image for Order {oid}.")
    elif action == 'view_img':
        await context.bot.send_photo(ADMIN_CHAT_ID, order['file_id'], caption=f"🖼️ Original Image for Order {oid}")
    elif action == 'view_proof':
        await context.bot.send_photo(ADMIN_CHAT_ID, order['payment_proof'], caption=f"💳 Payment Proof for Order {oid}")

async def handle_admin_upscaled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for oid, order in orders.items():
        if order['status'] == 'awaiting_upscaled':
            file_id = update.message.photo[-1].file_id
            order['upscaled_file_id'] = file_id
            await context.bot.send_photo(order['user_id'], file_id, caption="✨ Here is your upscaled image!")
            await context.bot.send_message(order['user_id'], f"🎉 Your order is complete!\nOrder ID: {oid}\nThank you for using our service!")
            await context.bot.send_message(ADMIN_CHAT_ID, f"✅ Order {oid} has been completed and upscaled image has been delivered.")
            order['status'] = 'complete'
            if order.get('email') and is_valid_email(order['email']) and not has_typo(order['email']):
                await send_email_with_image(order['email'], file_id, oid)
            return

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id
    for oid, order in orders.items():
        if order['user_id'] == user_id and order['status'] == 'approved':
            if is_valid_email(text) and not has_typo(text):
                order['email'] = text
                order['status'] = 'awaiting_upscaled'
                await update.message.reply_text("📨 Email received. You will get your upscaled image soon via Telegram and Email!")
            else:
                await update.message.reply_text("❗ Invalid email or typo detected. Please retype your correct email.")
            return
    await update.message.reply_text("Send /start to begin a new order or upload an image to continue.")

async def main():
    global telegram_app
    telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("contact", contact))
    telegram_app.add_handler(CallbackQueryHandler(plan_choice, pattern=r"^plan_"))
    telegram_app.add_handler(CallbackQueryHandler(handle_admin_actions, pattern=r"^(view_img|view_proof|approve|reject|ask_proof|send_upscaled)\|"))
    telegram_app.add_handler(MessageHandler(filters.PHOTO & ~filters.User(ADMIN_CHAT_ID), user_photo_handler))
    telegram_app.add_handler(MessageHandler(filters.PHOTO & filters.User(ADMIN_CHAT_ID), handle_admin_upscaled))
    telegram_app.add_handler(MessageHandler(filters.TEXT, text_handler))

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.bot.set_webhook(WEBHOOK_URL)
    print("✅ Bot is running with webhook")

nest_asyncio.apply()
loop = asyncio.get_event_loop()
loop.create_task(main())
uvicorn.run(app, host="0.0.0.0", port=10000)

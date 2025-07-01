import logging
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re

orders = {}
waiting_for_status = set()

COMMON_MISTAKES = ["gamil.com", "gmial.com", "gnail.com", "yahho.com", "yhoo.com"]

ADMIN_CHAT_ID = 8178524981

RAZORPAY_LINKS = {
    20: "https://rzp.io/r/0YOfrpS",
    30: "https://rzp.io/r/NTJ69QRD",
    50: "https://rzp.io/r/rSAe7dZ"
}

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨ Welcome! Please upload your image to start your order. ✨")

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await update.message.reply_text("For any queries please contact @Devendra_1666")
    text = f"📩 Contact Request:\nUser: {user.full_name} (ID: {user.id})\nUsername: @{user.username or 'N/A'}"
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    for oid, order in list(orders.items()):
        if order['user_id'] == user_id and order['status'] in ['waiting_plan', 'waiting_payment', 'waiting_email']:
            del orders[oid]
            await update.message.reply_text(f"🗑️ Order {oid} cancelled successfully.")
            return
    await update.message.reply_text("❌ You have no pending orders to cancel.")

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    chat_id = update.message.from_user.id
    if not args:
        await update.message.reply_text("Please enter your Order ID to check status.")
        waiting_for_status.add(chat_id)
        return
    order_id = args[0]
    order = orders.get(order_id)
    if not order or order['user_id'] != chat_id:
        await update.message.reply_text(f"❌ Order {order_id} not found.")
    else:
        await update.message.reply_text(f"📦 Order {order_id} status: {order['status']}")

async def user_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    for oid, order in orders.items():
        if order['user_id'] == user.id and order['status'] == 'waiting_payment':
            proof_id = update.message.photo[-1].file_id
            order['payment_proof'] = proof_id
            order['status'] = 'waiting_email'
            await update.message.reply_text("✅ Payment proof received. Please enter your email address (optional). Or type /skip to continue without email.")
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
    await query.message.reply_text("❌ No pending order found.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    if user_id in waiting_for_status:
        waiting_for_status.remove(user_id)
        order = orders.get(text)
        if not order or order['user_id'] != user_id:
            await update.message.reply_text(f"❌ Order {text} not found.")
        else:
            await update.message.reply_text(f"📦 Order {text} status: {order['status']}")
        return
    for oid, order in orders.items():
        if order['user_id'] == user_id and order['status'] == 'waiting_email':
            if text.lower() == "/skip":
                order['status'] = 'waiting_admin'
                await update.message.reply_text("📨 Skipped email. Your order will be reviewed by admin shortly.")
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"💰 Payment Received for Order {oid}\nUser: {order['user_name']} (ID: {order['user_id']})\nPlan: ₹{order['plan']}",
                    reply_markup=admin_keyboard(oid)
                )
                return
            elif is_valid_email(text) and not has_typo(text):
                order['email'] = text
                order['status'] = 'waiting_admin'
                await update.message.reply_text("📨 Email saved. Your order will be reviewed by admin shortly.")
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"💰 Payment Received for Order {oid}\nUser: {order['user_name']} (ID: {order['user_id']})\nPlan: ₹{order['plan']}",
                    reply_markup=admin_keyboard(oid)
                )
                return
            else:
                await update.message.reply_text("❗ Invalid email or typo detected. Please retype your correct email or use /skip.")
                return
    if any(order['user_id'] == user_id and order['status'] in ['waiting_plan','waiting_payment','waiting_email'] for order in orders.values()):
        await update.message.reply_text("⚠️ You have an ongoing order. Type /cancel to cancel it or complete it before starting a new one.")
    else:
        await update.message.reply_text("✨ Main Menu ✨\n/start - Upload an image to place an order\n/status - Check your order status\n/contact - Contact admin for support\n/cancel - Cancel your current order")

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
        await context.bot.send_message(order['user_id'], f"✅ Your payment for Order {oid} has been approved! You will receive the upscaled image shortly.")
        await context.bot.send_message(ADMIN_CHAT_ID, f"✅ Order {oid} payment approved.")
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
    admin_id = update.message.from_user.id
    for oid, order in orders.items():
        if order['status'] == 'awaiting_upscaled':
            file_id = update.message.photo[-1].file_id
            order['upscaled_file_id'] = file_id
            await context.bot.send_photo(order['user_id'], file_id, caption="✨ Here is your upscaled image!")
            await context.bot.send_message(order['user_id'], f"🎉 Your order is complete!\nOrder ID: {oid}\nThank you for using our service!")
            await context.bot.send_message(admin_id, f"✅ Upscaled image sent. Order {oid} marked complete.")
            order['status'] = 'complete'
            return

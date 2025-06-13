import logging
import uuid
import os   # <-- Yeh import add kiya hai

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ContextTypes
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# In-memory order storage
orders = {}  # order_id -> order details
waiting_for_status = set()  # chat_id waiting for order ID after using /status

# Replace with your actual admin chat ID
ADMIN_CHAT_ID = 1069307863

# Bot token (ab env variable se le rahe hain)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Plan selection keyboard
def plan_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Basic ₹20", callback_data="plan_20")],
        [InlineKeyboardButton("High ₹30", callback_data="plan_30")],
        [InlineKeyboardButton("Ultra ₹50", callback_data="plan_50")],
    ])

# Admin control keyboard
def admin_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View Original Image", callback_data=f"view_img|{order_id}")],
        [InlineKeyboardButton("View Payment Proof", callback_data=f"view_proof|{order_id}")],
        [InlineKeyboardButton("Approve Payment ✅", callback_data=f"approve|{order_id}")],
        [InlineKeyboardButton("Reject Payment ❌", callback_data=f"reject|{order_id}")],
        [InlineKeyboardButton("Request New Payment Proof 🔄", callback_data=f"ask_proof|{order_id}")],
        [InlineKeyboardButton("Send Upscaled Image 🚀", callback_data=f"send_upscaled|{order_id}")],
    ])

# /start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ Welcome! Please upload your image to start your order. ✨"
    )

# /status command handler
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    chat_id = update.message.from_user.id
    if not args:
        await update.message.reply_text("Please enter your Order ID to check the status.")
        waiting_for_status.add(chat_id)
        return
    order_id = args[0]
    order = orders.get(order_id)
    if not order or order['user_id'] != chat_id:
        await update.message.reply_text(f"Order {order_id} not found.")
    else:
        await update.message.reply_text(f"Order {order_id} status: {order['status']}")

# /cancel command handler
async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    order_id = next((oid for oid, o in orders.items() 
                     if o['user_id'] == user_id and o['status'] in ['waiting_plan','waiting_payment']), None)
    if not order_id:
        await update.message.reply_text("No pending order found.")
    else:
        del orders[order_id]
        await update.message.reply_text(f"🗑️ Order {order_id} has been cancelled.")

# /contact command handler
async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    # Acknowledgement message to user
    await update.message.reply_text(
        "For any queries please contact @Dev7896"
    )

    # Forward the request to admin
    text = (
        f"📩 Contact Request:\n"
        f"User: {user.full_name} (ID: {user.id})\n"
        f"Username: @{user.username or 'N/A'}"
    )
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)

# Helper to find a pending order
def find_pending_order(user_id):
    for oid, order in orders.items():
        if order['user_id'] == user_id and order['status'] in ['waiting_plan', 'waiting_payment']:
            return oid
    return None

# Handle user image uploads (order image or payment proof)
async def user_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    # Check if this is a payment proof
    for oid, order in orders.items():
        if order['user_id'] == user.id and order['status'] == 'waiting_payment':
            proof_id = update.message.photo[-1].file_id
            order['payment_proof'] = proof_id
            order['status'] = 'waiting_admin'
            await update.message.reply_text("✅ Payment proof received. Awaiting admin approval.")
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"💰 Payment Received for Order {oid}\nUser: {order['user_name']} (ID: {order['user_id']})\nPlan: ₹{order['plan']}",
                reply_markup=admin_keyboard(oid)
            )
            return

    # If it's a new image, start a new order
    file_id = update.message.photo[-1].file_id
    new_oid = str(uuid.uuid4())[:8]
    orders[new_oid] = {
        'user_id': user.id,
        'user_name': user.full_name,
        'file_id': file_id,
        'plan': None,
        'payment_proof': None,
        'upscaled_file_id': None,
        'status': 'waiting_plan'
    }
    await update.message.reply_text(
        f"🆔 Your Order ID is: {new_oid}\nPlease select a plan:",
        reply_markup=plan_keyboard()
    )

# Handle plain text (order status check or general prompts)
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.from_user.id
    text = update.message.text.strip()

    if chat_id in waiting_for_status:
        waiting_for_status.remove(chat_id)
        order = orders.get(text)
        if not order or order['user_id'] != chat_id:
            await update.message.reply_text(f"Order {text} not found.")
        else:
            await update.message.reply_text(f"Order {text} status: {order['status']}")
        return

    pending = find_pending_order(chat_id)
    if pending:
        await update.message.reply_text(
            "⚠️ Please complete your pending order (choose plan / upload payment proof), or send /cancel to cancel the order."
        )
    else:
        await update.message.reply_text(
            "✨ Main Menu ✨\n"
            "/start - Upload an image to place an order\n"
            "/status - Check your order status\n"
            "/contact - Contact admin for support\n"
            "/cancel - Cancel your current order"
        )

# Handle plan selection
async def plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, price = query.data.split('_')
    for oid, order in orders.items():
        if order['user_id'] == query.from_user.id and order['status'] == 'waiting_plan':
            order['plan'] = int(price)
            order['status'] = 'waiting_payment'
            await query.message.edit_text(f"💡 You selected the ₹{price} plan. Please make the payment and upload proof.")
            return
    await query.message.reply_text("No pending order found.")

# Handle admin actions (button callbacks)
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
    elif action == 'reject':
        order['status'] = 'rejected'
        await context.bot.send_message(order['user_id'], f"❌ Your payment for Order {oid} has been rejected. Please contact support.")
    elif action == 'ask_proof':
        order['status'] = 'waiting_payment'
        await context.bot.send_message(order['user_id'], f"🔄 Please re-upload valid payment proof for Order {oid}.")
    elif action == 'send_upscaled':
        order['status'] = 'awaiting_upscaled'
        await context.bot.send_message(ADMIN_CHAT_ID, f"🚀 Please upload the upscaled image for Order {oid}.")

# Handle admin uploading the upscaled image
async def handle_admin_upscaled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for oid, order in orders.items():
        if order['status'] == 'awaiting_upscaled':
            file_id = update.message.photo[-1].file_id
            order['upscaled_file_id'] = file_id
            await context.bot.send_photo(order['user_id'], file_id, caption="✨ Here is your upscaled image!")
            await context.bot.send_message(
                order['user_id'],
                f"🎉 Your order is complete!\nOrder ID: {oid}\nThank you for using our service!"
            )
            order['status'] = 'complete'
            await update.message.reply_text(f"✅ Order {oid} has been marked as complete.")
            return

# Main bot setup
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.bot.set_my_commands([
        BotCommand("start", "Upload an image to start your order"),
        BotCommand("status", "Check the status of your order"),
        BotCommand("contact", "Contact support"),
        BotCommand("cancel", "Cancel your current order"),
    ])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cancel", cancel_order))
    app.add_handler(CommandHandler("contact", contact))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.User(ADMIN_CHAT_ID), text_handler))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.User(ADMIN_CHAT_ID), user_photo_handler))
    app.add_handler(MessageHandler(filters.PHOTO & filters.User(ADMIN_CHAT_ID), handle_admin_upscaled))

    app.add_handler(CallbackQueryHandler(plan_choice, pattern=r"^plan_"))
    app.add_handler(CallbackQueryHandler(handle_admin_actions,
        pattern=r"^(view_img|view_proof|approve|reject|ask_proof|send_upscaled)\|"))

    print("Bot started...")
    app.run_polling()

if __name__ == '__main__':
    main()

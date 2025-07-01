from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import uuid
import logging

logger = logging.getLogger(__name__)

orders = {}
ADMIN_CHAT_ID = 8178524981


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

def user_has_active_order(user_id):
    return any(o for o in orders.values() if o['user_id'] == user_id and o['status'] not in ['completed', 'cancelled'])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_has_active_order(user_id):
        return

    order_id = str(uuid.uuid4())[:8]
    orders[order_id] = {
        'user_id': user_id,
        'status': 'waiting_image'
    }
    await context.bot.send_message(chat_id=user_id, text="✨ Welcome! Please upload your image to start your order. ✨")

async def user_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not user_has_active_order(user_id):
        await start(update, context)
        return

    order_id = next((oid for oid, o in orders.items() if o['user_id'] == user_id and o['status'] == 'waiting_image'), None)
    if not order_id:
        await context.bot.send_message(chat_id=user_id, text="🚧 You have an ongoing order. Please complete it first or send /cancel to start a new one.")
        return

    photo = update.message.photo[-1]
    orders[order_id]['original_image'] = photo.file_id
    orders[order_id]['status'] = 'waiting_plan'

    await context.bot.send_message(chat_id=user_id, text="💡 Please select a plan:", reply_markup=plan_keyboard())

async def plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    order_id = next((oid for oid, o in orders.items() if o['user_id'] == user_id and o['status'] == 'waiting_plan'), None)
    if not order_id:
        await query.edit_message_text("Order not found or plan already selected.")
        return

    selected_plan = int(query.data.split('_')[1])
    orders[order_id]['plan'] = selected_plan
    orders[order_id]['status'] = 'waiting_payment'

    await context.bot.send_message(chat_id=user_id, text=f"💡 You selected ₹{selected_plan} plan. Pay via this link: https://rzp.io/r/NTJ69QRD\n\nAfter payment, upload the payment screenshot here.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message.text.strip().lower()

    if message == "/cancel":
        await cancel_order(update, context)
        return

    if user_has_active_order(user_id):
        order = next((o for o in orders.values() if o['user_id'] == user_id and o['status'] not in ['completed', 'cancelled']), None)
        if order and order['status'] != 'waiting_payment_proof':
            await context.bot.send_message(chat_id=user_id, text="🚧 You have an ongoing order. Please complete it first or send /cancel to start a new one.")
            return

    await start(update, context)

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    for oid, order in orders.items():
        if order['user_id'] == user_id and order['status'] not in ['completed', 'cancelled']:
            order['status'] = 'cancelled'
            await context.bot.send_message(chat_id=user_id, text=f"❌ Order {oid} cancelled successfully.")
            return

    await context.bot.send_message(chat_id=user_id, text="⚠️ No active order to cancel.")

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📩 Contact: pixellaxmi@gmail.com")

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    order = next(((oid, o) for oid, o in orders.items() if o['user_id'] == user_id and o['status'] not in ['completed', 'cancelled']), None)
    if order:
        oid, o = order
        await update.message.reply_text(f"📌 Your Order ID: {oid}\nStatus: {o['status']}")
    else:
        await update.message.reply_text("ℹ️ You have no active order.")

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = query.from_user.id
    action_data = query.data.split('|')
    action = action_data[0]
    order_id = action_data[1] if len(action_data) > 1 else None

    if admin_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ You are not authorized.")
        return

    order = orders.get(order_id)
    if not order:
        await query.edit_message_text("⚠️ Order not found.")
        return

    if action == "approve":
        order['status'] = 'approved'
        await context.bot.send_message(chat_id=order['user_id'], text=f"✅ Your payment for Order {order_id} has been approved!")
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"✅ Payment for Order {order_id} approved.")
    elif action == "reject":
        order['status'] = 'rejected'
        await context.bot.send_message(chat_id=order['user_id'], text=f"❌ Your payment for Order {order_id} was rejected.")
    elif action == "ask_proof":
        order['status'] = 'waiting_payment'
        await context.bot.send_message(chat_id=order['user_id'], text=f"🔄 Please re-upload valid payment proof for Order {order_id}.")
    elif action == "view_img":
        await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=order.get('original_image'), caption=f"🖼️ Original Image for Order {order_id}")
    elif action == "view_proof":
        await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=order.get('payment_proof'), caption=f"💳 Payment Proof for Order {order_id}")
    elif action == "send_upscaled":
        order['status'] = 'awaiting_upscaled'
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"🚀 Please upload the upscaled image for Order {order_id}.")

async def handle_admin_upscaled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id != ADMIN_CHAT_ID:
        return

    if not update.message.photo:
        return

    file_id = update.message.photo[-1].file_id

    for oid, order in orders.items():
        if order['status'] == 'awaiting_upscaled':
            order['status'] = 'completed'
            order['upscaled_image'] = file_id
            await context.bot.send_photo(chat_id=order['user_id'], photo=file_id, caption="✨ Here is your upscaled image!")
            await context.bot.send_message(chat_id=order['user_id'], text=f"🎉 Order {oid} completed successfully!")
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"✅ Order {oid} has been completed and image sent to user.")
            break

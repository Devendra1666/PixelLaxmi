from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import uuid
import logging
import os

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

def user_active_pending_order(user_id):
    for oid, o in orders.items():
        # Only if not complete/cancelled/rejected/approved & not waiting email input/admin action
        if o['user_id'] == user_id and o['status'] in ['waiting_image', 'waiting_plan', 'waiting_payment']:
            return oid
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_active_pending_order(user_id):
        return
    order_id = str(uuid.uuid4())[:8]
    orders[order_id] = {
        'user_id': user_id,
        'status': 'waiting_image'
    }
    await context.bot.send_message(chat_id=user_id, text="✨ Welcome! Please upload your image to start your order. ✨")

async def user_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    oid = user_active_pending_order(user_id)
    if not oid:
        await start(update, context)
        return

    order = orders[oid]
    if order['status'] == 'waiting_image':
        order['original_image'] = update.message.photo[-1].file_id
        order['status'] = 'waiting_plan'
        await context.bot.send_message(chat_id=user_id, text="💡 Please select a plan:", reply_markup=plan_keyboard())
    elif order['status'] == 'waiting_payment':
        order['payment_proof'] = update.message.photo[-1].file_id
        order['status'] = 'waiting_email'
        await context.bot.send_message(
            chat_id=user_id,
            text="📩 (Optional) Enter your email address to receive the upscaled image (or type 'skip'):"
        )

async def plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    oid = user_active_pending_order(user_id)
    if not oid:
        await query.edit_message_text("Order not found or already processed.")
        return
    order = orders[oid]
    if order['status'] == 'waiting_plan':
        selected_plan = int(query.data.split('_')[1])
        order['plan'] = selected_plan
        order['status'] = 'waiting_payment'
        await context.bot.send_message(
            chat_id=user_id,
            text=f"💡 You selected ₹{selected_plan} plan. Pay via this link: https://rzp.io/r/NTJ69QRD\n\nAfter payment, upload the payment screenshot here."
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message.text.strip()

    # /cancel handled in separate handler
    if msg == "/cancel":
        await cancel_order(update, context)
        return

    # EMAIL INPUT STAGE
    oid = next((oid for oid, o in orders.items() if o['user_id'] == user_id and o['status'] == 'waiting_email'), None)
    if oid:
        order = orders[oid]
        if msg.lower() != "skip":
            order['email'] = msg
        order['status'] = 'waiting_admin_action'
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🆕 New Order Received!\nOrder ID: {oid}",
            reply_markup=admin_keyboard(oid)
        )
        await context.bot.send_message(chat_id=user_id, text="🕐 Payment proof submitted. Waiting for admin approval.")
        return

    # ONGOING ORDER: ANY OTHER TEXT (not email stage, not payment proof, not commands)
    if user_active_pending_order(user_id):
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🚧 You have an ongoing order!\n\n"
                "👉 Order continue karne ke liye image upload karo ya payment proof bhejo.\n"
                "❌ Order cancel karna hai toh /cancel type karo."
            )
        )
        return

    await start(update, context)

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    for oid, o in orders.items():
        if o['user_id'] == user_id and o['status'] not in ['completed', 'cancelled', 'rejected']:
            o['status'] = 'cancelled'
            await context.bot.send_message(chat_id=user_id, text=f"❌ Order {oid} cancelled successfully.")
            return
    await context.bot.send_message(chat_id=user_id, text="⚠️ No active order to cancel.")

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, oid = query.data.split('|')
    order = orders.get(oid)

    if update.effective_user.id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Not authorized.")
        return

    if not order:
        await query.edit_message_text("⚠️ Order not found.")
        return

    if action == "approve":
        order['status'] = 'approved'
        await context.bot.send_message(chat_id=order['user_id'], text=f"✅ Your payment for Order {oid} has been approved!")
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"✅ Payment for Order {oid} approved.")
    elif action == "reject":
        order['status'] = 'rejected'
        await context.bot.send_message(chat_id=order['user_id'], text=f"❌ Your payment for Order {oid} was rejected.")
    elif action == "ask_proof":
        order['status'] = 'waiting_payment'
        await context.bot.send_message(chat_id=order['user_id'], text="🔄 Please re-upload valid payment proof.")
    elif action == "view_img":
        await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=order['original_image'], caption=f"🖼️ Original Image for Order {oid}")
    elif action == "view_proof":
        await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=order['payment_proof'], caption=f"💳 Payment Proof for Order {oid}")
    elif action == "send_upscaled":
        order['status'] = 'awaiting_upscaled'
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"📤 Please upload upscaled image for Order {oid}.")

async def handle_admin_upscaled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    photo = update.message.photo[-1].file_id
    for oid, o in orders.items():
        if o['status'] == 'awaiting_upscaled':
            o['status'] = 'completed'
            await context.bot.send_photo(chat_id=o['user_id'], photo=photo, caption="✨ Here is your upscaled image!")
            await context.bot.send_message(chat_id=o['user_id'], text=f"🎉 Order {oid} completed successfully!")
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"✅ Order {oid} has been completed and upscaled image sent.")
            break

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📩 Contact: pixellaxmi@gmail.com")

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    order = next(((oid, o) for oid, o in orders.items() if o['user_id'] == user_id and o['status'] not in ['completed', 'cancelled', 'rejected']), None)
    if order:
        oid, o = order
        await update.message.reply_text(f"📌 Your Order ID: {oid}\nStatus: {o['status']}")
    else:
        await update.message.reply_text("ℹ️ You have no active order.")

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_order))
    app.add_handler(CommandHandler("contact", contact))
    app.add_handler(CommandHandler("status", check_status))
    app.add_handler(MessageHandler(filters.PHOTO, user_photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(handle_admin_actions))
    app.add_handler(MessageHandler(filters.PHOTO & filters.User(user_id=ADMIN_CHAT_ID), handle_admin_upscaled))

    print("Bot started...")
    app.run_polling()

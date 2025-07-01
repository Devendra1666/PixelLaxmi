from telegram import Update
from telegram.ext import ContextTypes
from main import orders, plan_keyboard, admin_keyboard, is_valid_email, has_typo, send_email_with_image, user_has_active_order

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\u2728 Welcome! Please upload your image to start your order. \u2728")

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await update.message.reply_text("For any queries please contact @Devendra_1666")
    text = f"\ud83d\udce9 Contact Request:\nUser: {user.full_name} (ID: {user.id})\nUsername: @{user.username or 'N/A'}"
    await context.bot.send_message(chat_id=8178524981, text=text)

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    for oid, o in list(orders.items()):
        if o['user_id'] == user_id and o['status'] in ['waiting_plan', 'waiting_payment', 'waiting_email']:
            del orders[oid]
            await update.message.reply_text(f"\ud83d\uddd1\ufe0f Order {oid} has been cancelled.")
            return
    await update.message.reply_text("No active order found to cancel.")

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    for oid, order in orders.items():
        if order['user_id'] == user_id:
            await update.message.reply_text(f"\u2139\ufe0f Order ID: {oid}\nStatus: {order['status']}")
            return
    await update.message.reply_text("You have no active orders.")

async def user_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    photo = update.message.photo[-1].file_id
    for oid, order in orders.items():
        if order['user_id'] == user.id and order['status'] == 'waiting_payment':
            order['payment_proof'] = photo
            order['status'] = 'waiting_email'
            await update.message.reply_text("\u2705 Payment proof received!\n\ud83d\udce7 If you want the image on email, please type your email now. (optional)")
            await context.bot.send_message(
                chat_id=8178524981,
                text=f"\ud83d\udcb0 Payment Received for Order {oid}\nUser: {order['user_name']} (ID: {order['user_id']})\nPlan: \u20b9{order['plan']}",
                reply_markup=admin_keyboard(oid)
            )
            return

    new_oid = str(uuid.uuid4())[:8]
    orders[new_oid] = {
        'user_id': user.id,
        'user_name': user.full_name,
        'file_id': photo,
        'plan': None,
        'payment_proof': None,
        'upscaled_file_id': None,
        'status': 'waiting_plan',
        'email': None
    }
    await update.message.reply_text(f"\ud83c\udd94 Your Order ID is: {new_oid}\nPlease select a plan:", reply_markup=plan_keyboard())

async def plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, price = query.data.split('_')
    for oid, order in orders.items():
        if order['user_id'] == query.from_user.id and order['status'] == 'waiting_plan':
            order['plan'] = int(price)
            order['status'] = 'waiting_payment'
            link = {
                20: "https://rzp.io/r/0YOfrpS",
                30: "https://rzp.io/r/NTJ69QRD",
                50: "https://rzp.io/r/rSAe7dZ"
            }.get(int(price))
            await query.message.edit_text(f"\ud83d\udca1 You selected \u20b9{price}. Please pay here: {link}\nAfter payment, upload the screenshot here.")
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
        await context.bot.send_message(order['user_id'], f"\u2705 Your payment for Order {oid} has been approved! Please send your email address if you want.")
        await query.message.reply_text(f"\ud83d\udd39 Order {oid} approved successfully.")
    elif action == 'reject':
        order['status'] = 'rejected'
        await context.bot.send_message(order['user_id'], f"\u274c Payment rejected for Order {oid}. Contact support.")
        await query.message.reply_text(f"\u274c Order {oid} rejected.")
    elif action == 'ask_proof':
        order['status'] = 'waiting_payment'
        await context.bot.send_message(order['user_id'], f"\ud83d\udd04 Please re-upload valid payment proof for Order {oid}.")
        await query.message.reply_text(f"\u27f3 Re-requested payment proof for Order {oid}.")
    elif action == 'send_upscaled':
        order['status'] = 'awaiting_upscaled'
        await context.bot.send_message(8178524981, f"\ud83d\ude80 Please upload the upscaled image for Order {oid}.")

    elif action == 'view_img':
        await context.bot.send_photo(8178524981, order['file_id'], caption=f"\ud83d\uddbc\ufe0f Original Image for Order {oid}")
    elif action == 'view_proof':
        await context.bot.send_photo(8178524981, order['payment_proof'], caption=f"\ud83d\udcb3 Payment Proof for Order {oid}")

async def handle_admin_upscaled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.message.from_user.id
    for oid, order in orders.items():
        if order['status'] == 'awaiting_upscaled':
            file_id = update.message.photo[-1].file_id
            order['upscaled_file_id'] = file_id
            order['status'] = 'complete'
            await context.bot.send_photo(order['user_id'], file_id, caption="\u2728 Here is your upscaled image!")
            await context.bot.send_message(order['user_id'], f"\ud83c\udf89 Your order {oid} is complete! Thank you!")
            if order.get('email') and is_valid_email(order['email']) and not has_typo(order['email']):
                await send_email_with_image(order['email'], file_id, oid)
            await update.message.reply_text(f"\u2705 Order {oid} completed.")
            return

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id
    for oid, order in orders.items():
        if order['user_id'] == user_id and order['status'] == 'waiting_email':
            if is_valid_email(text) and not has_typo(text):
                order['email'] = text
                order['status'] = 'awaiting_upscaled'
                await update.message.reply_text("\ud83d\udce7 Email saved. You'll receive your upscaled image soon!")
            else:
                await update.message.reply_text("\u26a0\ufe0f Invalid email or typo. Please resend.")
            return
    if user_has_active_order(user_id):
        await update.message.reply_text("\u26a0\ufe0f You have an ongoing order. Complete it or send /cancel to cancel.")
    else:
        await update.message.reply_text("\u2728 Main Menu \u2728\n/start - Upload an image\n/status - Check order status\n/contact - Contact support\n/cancel - Cancel order")

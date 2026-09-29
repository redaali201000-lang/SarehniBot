import os
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, PreCheckoutQueryHandler
)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

sender_targets = {}
reply_targets = {}

# رسالة مجهولة -> بياناتها اللازمة لكشف الهوية بعد دفع 100 ⭐
reveal_messages = {}
REVEAL_PRICE = 100

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    payload = context.args[0] if context.args else None

    if payload and payload.startswith("msg_"):
        try:
            recipient_id = int(payload[4:])
        except ValueError:
            await update.message.reply_text("الرابط غير صالح.")
            return
        if recipient_id == user.id:
            await update.message.reply_text("هذا رابطك أنت 😄")
            return
        sender_targets[user.id] = recipient_id
        await update.message.reply_text("✉️ اكتب رسالتك هسه، وراح توصل بشكل مجهول لصاحب الرابط.")
        return

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=msg_{user.id}"
    await update.message.reply_text(
        f"🎭 بوت صارحني\n\nرابطك الخاص:\n{link}\n\nشارك الرابط ويا أصدقائك."
    )

async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=msg_{update.effective_user.id}"
    await update.message.reply_text("🔗 رابطك:\n" + link)

async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    recipient_id = sender_targets.pop(user.id, None)

    if not recipient_id:
        await update.message.reply_text("استخدم رابط المصارحة أولاً حتى ترسل رسالة مجهولة.")
        return

    reveal_id = uuid.uuid4().hex
    reveal_messages[reveal_id] = {
        "sender_id": user.id,
        "recipient_id": recipient_id,
        "text": update.message.text,
        "revealed": False,
    }

    sent = await context.bot.send_message(
        recipient_id,
        "📩 وصلت رسالة مجهولة:\n\n" + update.message.text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ رد", callback_data=f"reply:{user.id}")],
            [InlineKeyboardButton("🔓 كشف هوية المرسل — 100 ⭐", callback_data=f"reveal:{reveal_id}")]
        ])
    )
    reply_targets[sent.message_id] = user.id
    await update.message.reply_text("✅ وصلت رسالتك بشكل مجهول.")

async def reveal_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    reveal_id = q.data.split(":", 1)[1]
    item = reveal_messages.get(reveal_id)

    if not item:
        await q.message.reply_text("❌ هذه الرسالة لم تعد متاحة للكشف.")
        return

    if q.from_user.id != item["recipient_id"]:
        await q.answer("هذا الزر مو مخصص إلك.", show_alert=True)
        return

    if item["revealed"]:
        await q.message.reply_text("ℹ️ تم كشف هوية هذه الرسالة مسبقاً.")
        return

    payload = f"reveal:{reveal_id}"
    await context.bot.send_invoice(
        chat_id=q.from_user.id,
        title="كشف هوية المرسل",
        description="كشف هوية الشخص الذي أرسل لك هذه الرسالة المجهولة.",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice("كشف الهوية", REVEAL_PRICE)],
        start_parameter=f"reveal_{reveal_id}",
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    payload = query.invoice_payload

    if not payload.startswith("reveal:"):
        await query.answer(ok=False, error_message="طلب دفع غير صالح.")
        return

    reveal_id = payload.split(":", 1)[1]
    item = reveal_messages.get(reveal_id)

    if not item:
        await query.answer(ok=False, error_message="هذه الرسالة لم تعد متاحة.")
        return

    if query.from_user.id != item["recipient_id"]:
        await query.answer(ok=False, error_message="هذا الطلب ليس مخصصاً لك.")
        return

    if query.currency != "XTR" or query.total_amount != REVEAL_PRICE:
        await query.answer(ok=False, error_message="قيمة الدفع غير صحيحة.")
        return

    if item["revealed"]:
        await query.answer(ok=False, error_message="تم كشف هذه الهوية مسبقاً.")
        return

    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload

    if not payload.startswith("reveal:"):
        return

    reveal_id = payload.split(":", 1)[1]
    item = reveal_messages.get(reveal_id)

    if not item:
        await update.message.reply_text("⚠️ تم الدفع، لكن بيانات الرسالة غير متاحة حالياً.")
        return

    if update.effective_user.id != item["recipient_id"]:
        return

    if payment.currency != "XTR" or payment.total_amount != REVEAL_PRICE:
        return

    if item["revealed"]:
        await update.message.reply_text("ℹ️ تم كشف هذه الهوية مسبقاً.")
        return

    item["revealed"] = True

    sender = await context.bot.get_chat(item["sender_id"])
    name = sender.full_name or "مستخدم تيليگرام"
    username = f"@{sender.username}" if sender.username else "لا يوجد @username"

    await update.message.reply_text(
        "🔓 تم كشف هوية المرسل مقابل 100 ⭐\\n\\n"
        f"👤 الاسم: {name}\\n"
        f"🔗 المعرف: {username}"
    )


async def reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sender_id = int(q.data.split(":")[1])
    context.user_data["reply_to"] = sender_id
    await q.message.reply_text("✍️ اكتب الرد هسه.")

async def send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = context.user_data.get("reply_to")
    if not sender_id:
        return
    await context.bot.send_message(sender_id, "💬 رد على رسالتك المجهولة:\n\n" + update.message.text)
    context.user_data.pop("reply_to", None)
    await update.message.reply_text("✅ تم إرسال الرد.")

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("reply_to"):
        await send_reply(update, context)
    else:
        await receive_message(update, context)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("link", mylink))
    app.add_handler(CallbackQueryHandler(reveal_button, pattern=r"^reveal:[a-f0-9]+$"))
    app.add_handler(CallbackQueryHandler(reply_button, pattern=r"^reply:\d+$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

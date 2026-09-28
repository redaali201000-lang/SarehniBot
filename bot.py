import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

sender_targets = {}
reply_targets = {}

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

    sent = await context.bot.send_message(
        recipient_id,
        "📩 وصلت رسالة مجهولة:\n\n" + update.message.text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ رد", callback_data=f"reply:{user.id}")
        ]])
    )
    reply_targets[sent.message_id] = user.id
    await update.message.reply_text("✅ وصلت رسالتك بشكل مجهول.")

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
    app.add_handler(CallbackQueryHandler(reply_button, pattern=r"^reply:\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

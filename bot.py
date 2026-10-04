import os
import uuid
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    PreCheckoutQueryHandler,
)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

# -----------------------------
# In-memory data
# NOTE: This data resets when the bot restarts.
# For production, move these dictionaries to SQLite/PostgreSQL.
# -----------------------------
sender_targets = {}
reply_targets = {}
reveal_messages = {}

# user_id -> {"messages_received": int, "messages_sent": int, "referrals": int,
#             "blocked": set(), "referred_by": int|None}
users = {}

# recipient_id -> set(sender_id)
blocked_users = {}

# report_id -> report data
reports = {}

REVEAL_PRICE = 50
REQUIRED_REFERRALS = 5

# Developer: free reveal access
DEVELOPER_USERNAME = "xi_vea"


def is_developer(user):
    if not user:
        return False
    username = (user.username or "").strip().lstrip("@").lower()
    return username == DEVELOPER_USERNAME.lower().lstrip("@")



def referral_link(bot_username, user_id):
    return f"https://t.me/{bot_username}?start=ref_{user_id}"


def get_referral_count(user_id):
    return users.get(user_id, {}).get("referrals", 0)



def ensure_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "messages_received": 0,
            "messages_sent": 0,
            "referrals": 0,
            "referred_by": None,
            "free_reveal_uses": 0,
        }
    blocked_users.setdefault(user_id, set())
    return users[user_id]


def main_menu(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔗 رابط صارحني", callback_data="menu:link"),
            InlineKeyboardButton("📊 إحصائياتي", callback_data="menu:stats"),
        ],
        [
            InlineKeyboardButton("🎁 دعوة أصدقاء", callback_data="menu:ref"),
            InlineKeyboardButton("🔓 كشف مجاني", callback_data="menu:free_reveal"),
        ],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)

    payload = context.args[0] if context.args else None

    # Existing message-link flow
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
        await update.message.reply_text(
            "✉️ اكتب رسالتك هسه، وراح توصل بشكل مجهول لصاحب الرابط."
        )
        return

    # Referral flow
    if payload and payload.startswith("ref_"):
        try:
            referrer_id = int(payload[4:])
        except ValueError:
            referrer_id = None

        if referrer_id and referrer_id != user.id:
            ensure_user(referrer_id)

            # Give credit only once per user.
            if users[user.id]["referred_by"] is None:
                users[user.id]["referred_by"] = referrer_id
                users[referrer_id]["referrals"] += 1

    # Referral flow: credit a new user only once.
    if payload and payload.startswith("ref_"):
        try:
            referrer_id = int(payload[4:])
        except ValueError:
            referrer_id = None
        if referrer_id and referrer_id != user.id:
            ensure_user(referrer_id)
            if users[user.id]["referred_by"] is None:
                users[user.id]["referred_by"] = referrer_id
                users[referrer_id]["referrals"] += 1

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=msg_{user.id}"

    await update.message.reply_text(
        f"🎭 بوت صارحني\n\n"
        f"🔗 رابطك الخاص:\n{link}\n\n"
        f"شارك الرابط ويا أصدقائك وخليهم يصارحوك 👀",
        reply_markup=main_menu(user.id),
    )


async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=msg_{user.id}"

    await update.message.reply_text(
        "🔗 رابطك:\n" + link,
        reply_markup=main_menu(user.id),
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    ensure_user(user_id)

    action = q.data.split(":", 1)[1]

    if action == "link":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=msg_{user_id}"
        await q.message.reply_text(
            f"🔗 هذا رابطك الخاص:\n{link}\n\n"
            "شاركه حتى الناس يرسلون لك رسائل مجهولة."
        )

    elif action == "stats":
        data = users[user_id]
        await q.message.reply_text(
            "📊 إحصائياتك:\n\n"
            f"📩 رسائل مستلمة: {data['messages_received']}\n"
            f"📤 رسائل مرسلة: {data['messages_sent']}\n"
            f"👥 الدعوات المكتملة: {data['referrals']}/5\n"
            f"🎁 كشف مجاني متاح كل 5 دعوات."
        )

    elif action == "ref":
        me = await context.bot.get_me()
        ref_link = f"https://t.me/{me.username}?start=ref_{user_id}"
        await q.message.reply_text(
            "🎁 رابط دعوتك:\n"
            f"{ref_link}\n\n"
            "شاركه ويا أصدقائك حتى ينضمون للبوت."
        )

    elif action == "free_reveal":
        count = get_referral_count(user_id)
        remaining = max(0, REQUIRED_REFERRALS - count)
        me = await context.bot.get_me()
        ref_link = referral_link(me.username, user_id)
        if remaining == 0:
            await q.message.reply_text(
                "🎉 عندك 5 دعوات مكتملة!\n\n"
                "تگدر تستخدم الكشف المجاني من زر الرسالة المجهولة بعد وصول رسالة جديدة."
            )
        else:
            await q.message.reply_text(
                f"🔓 الكشف المجاني يحتاج 5 أشخاص يدخلون من رابط دعوتك.\n\n"
                f"👥 المكتمل: {count}/5\n"
                f"⏳ باقي: {remaining}\n\n"
                f"🔗 رابط دعوتك:\n{ref_link}"
            )


async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)

    recipient_id = sender_targets.pop(user.id, None)

    if not recipient_id:
        await update.message.reply_text(
            "استخدم رابط المصارحة أولاً حتى ترسل رسالة مجهولة."
        )
        return

    ensure_user(recipient_id)

    # Do not allow a blocked sender to contact the recipient.
    if user.id in blocked_users.get(recipient_id, set()):
        await update.message.reply_text(
            "🚫 ما تگدر ترسل لهذا المستخدم لأنه حاجبك."
        )
        return

    reveal_id = uuid.uuid4().hex
    reveal_messages[reveal_id] = {
        "sender_id": user.id,
        "recipient_id": recipient_id,
        "text": update.message.text,
        "revealed": False,
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "↩️ رد",
                callback_data=f"reply:{user.id}",
            ),
            InlineKeyboardButton(
                "🎁 كشف مجاني — 5 دعوات",
                callback_data=f"free_reveal:{reveal_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⭐ كشف فوري — 50 ⭐",
                callback_data=f"reveal:{reveal_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "🚫 حظر المرسل",
                callback_data=f"block:{user.id}",
            ),
            InlineKeyboardButton(
                "⚠️ إبلاغ",
                callback_data=f"report:{reveal_id}",
            ),
        ],
    ])

    sent = await context.bot.send_message(
        recipient_id,
        "📩 وصلت رسالة مجهولة:\n\n" + update.message.text,
        reply_markup=keyboard,
    )

    reply_targets[sent.message_id] = user.id

    users[user.id]["messages_sent"] += 1
    users[recipient_id]["messages_received"] += 1

    await update.message.reply_text("✅ وصلت رسالتك بشكل مجهول.")


async def block_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    sender_id = int(q.data.split(":", 1)[1])
    recipient_id = q.from_user.id
    ensure_user(recipient_id)

    blocked_users.setdefault(recipient_id, set()).add(sender_id)

    await q.message.reply_text(
        "🚫 تم حظر هذا المرسل. لن يتمكن من إرسال رسائل جديدة لك."
    )


async def report_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    reveal_id = q.data.split(":", 1)[1]
    item = reveal_messages.get(reveal_id)

    if not item:
        await q.message.reply_text("❌ بيانات الرسالة غير متاحة.")
        return

    if q.from_user.id != item["recipient_id"]:
        await q.answer("هذا الزر مو مخصص إلك.", show_alert=True)
        return

    report_id = uuid.uuid4().hex
    reports[report_id] = {
        "reporter_id": q.from_user.id,
        "sender_id": item["sender_id"],
        "message": item["text"],
    }

    await q.message.reply_text(
        "⚠️ تم تسجيل البلاغ. راجع إدارة البوت الرسالة عند الحاجة."
    )


async def free_reveal_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    user = ensure_user(q.from_user.id)

    # Developer can reveal identities for free without referrals.
    if is_developer(q.from_user):
        item["revealed"] = True
        sender = await context.bot.get_chat(item["sender_id"])
        name = sender.full_name or "مستخدم تيليگرام"
        username = f"@{sender.username}" if sender.username else "لا يوجد @username"
        await q.message.reply_text(
            "👨‍💻 تم كشف هوية المرسل للمطور مجاناً ✅\\n\\n"
            f"👤 الاسم: {name}\\n"
            f"🔗 المعرف: {username}"
        )
        return

    if user["referrals"] < REQUIRED_REFERRALS:
        remaining = REQUIRED_REFERRALS - user["referrals"]
        me = await context.bot.get_me()
        ref_link = referral_link(me.username, q.from_user.id)
        await q.message.reply_text(
            f"❌ بعدك ما مكمل الشرط.\n\n"
            f"👥 عندك {user['referrals']}/5 دعوات.\n"
            f"⏳ باقي {remaining} أشخاص.\n\n"
            f"🔗 رابط الدعوة:\n{ref_link}"
        )
        return

    item["revealed"] = True
    # Consume 5 referrals for this free reveal, so the same 5 users can't be reused.
    user["referrals"] -= REQUIRED_REFERRALS

    sender = await context.bot.get_chat(item["sender_id"])
    name = sender.full_name or "مستخدم تيليگرام"
    username = f"@{sender.username}" if sender.username else "لا يوجد @username"
    await q.message.reply_text(
        "🔓 تم كشف هوية المرسل مجاناً 🎁\n\n"
        f"👤 الاسم: {name}\n"
        f"🔗 المعرف: {username}"
    )


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

    # Developer gets reveal for free and never receives a payment invoice.
    if is_developer(q.from_user):
        item["revealed"] = True
        sender = await context.bot.get_chat(item["sender_id"])
        name = sender.full_name or "مستخدم تيليگرام"
        username = f"@{sender.username}" if sender.username else "لا يوجد @username"
        await q.message.reply_text(
            "👨‍💻 تم كشف هوية المرسل للمطور مجاناً ✅\\n\\n"
            f"👤 الاسم: {name}\\n"
            f"🔗 المعرف: {username}"
        )
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


async def precheckout_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.pre_checkout_query
    payload = query.invoice_payload

    if not payload.startswith("reveal:"):
        await query.answer(ok=False, error_message="طلب دفع غير صالح.")
        return

    reveal_id = payload.split(":", 1)[1]
    item = reveal_messages.get(reveal_id)

    if not item:
        await query.answer(
            ok=False,
            error_message="هذه الرسالة لم تعد متاحة.",
        )
        return

    if query.from_user.id != item["recipient_id"]:
        await query.answer(
            ok=False,
            error_message="هذا الطلب ليس مخصصاً لك.",
        )
        return

    if query.currency != "XTR" or query.total_amount != REVEAL_PRICE:
        await query.answer(
            ok=False,
            error_message="قيمة الدفع غير صحيحة.",
        )
        return

    if item["revealed"]:
        await query.answer(
            ok=False,
            error_message="تم كشف هذه الهوية مسبقاً.",
        )
        return

    await query.answer(ok=True)


async def successful_payment_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    payment = update.message.successful_payment
    payload = payment.invoice_payload

    if not payload.startswith("reveal:"):
        return

    reveal_id = payload.split(":", 1)[1]
    item = reveal_messages.get(reveal_id)

    if not item:
        await update.message.reply_text(
            "⚠️ تم الدفع، لكن بيانات الرسالة غير متاحة حالياً."
        )
        return

    if update.effective_user.id != item["recipient_id"]:
        return

    if payment.currency != "XTR" or payment.total_amount != REVEAL_PRICE:
        return

    if item["revealed"]:
        await update.message.reply_text(
            "ℹ️ تم كشف هذه الهوية مسبقاً."
        )
        return

    item["revealed"] = True

    sender = await context.bot.get_chat(item["sender_id"])
    name = sender.full_name or "مستخدم تيليگرام"
    username = (
        f"@{sender.username}"
        if sender.username
        else "لا يوجد @username"
    )

    await update.message.reply_text(
        "🔓 تم كشف هوية المرسل مقابل 50 ⭐\n\n"
        f"👤 الاسم: {name}\n"
        f"🔗 المعرف: {username}"
    )


async def reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    sender_id = int(q.data.split(":")[1])

    # Only the recipient of the original message should use this button.
    context.user_data["reply_to"] = sender_id
    await q.message.reply_text("✍️ اكتب الرد هسه.")


async def send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = context.user_data.get("reply_to")

    if not sender_id:
        return

    if update.effective_user.id in blocked_users.get(sender_id, set()):
        await update.message.reply_text(
            "🚫 ما تگدر ترسل رد لهذا المستخدم لأنه حاجبك."
        )
        context.user_data.pop("reply_to", None)
        return

    await context.bot.send_message(
        sender_id,
        "💬 رد على رسالتك المجهولة:\n\n" + update.message.text,
    )

    users.setdefault(sender_id, {
        "messages_received": 0,
        "messages_sent": 0,
        "referrals": 0,
        "referred_by": None,
    })
    users.setdefault(update.effective_user.id, {
        "messages_received": 0,
        "messages_sent": 0,
        "referrals": 0,
        "referred_by": None,
    })

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

    app.add_handler(
        CallbackQueryHandler(
            menu_callback,
            pattern=r"^menu:(link|stats|ref|free_reveal)$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            free_reveal_button,
            pattern=r"^free_reveal:[a-f0-9]+$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            reveal_button,
            pattern=r"^reveal:[a-f0-9]+$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            reply_button,
            pattern=r"^reply:\d+$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            block_button,
            pattern=r"^block:\d+$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            report_button,
            pattern=r"^report:[a-f0-9]+$",
        )
    )

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment_callback,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

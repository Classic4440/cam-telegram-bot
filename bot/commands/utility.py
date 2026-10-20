"""Utility commands: reminders, time, search."""
from __future__ import annotations

import logging
from datetime import datetime, timezone as utc_timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.content import ContentLibrary
from bot.formatting import safe_reply
from bot.registry import callback, command, register
from bot.services.timeparse import TimeParseError, get_zone, parse_reminder
from bot.state import get_state
from bot.store import PersistenceFailure

logger = logging.getLogger(__name__)
ASK_REMINDER_TIME, ASK_REMINDER_MESSAGE = range(2)
_TIMEZONE_OPTIONS = (
    ("Africa/Kampala", "Africa/Kampala (EAT)"),
    ("Africa/Nairobi", "Africa/Nairobi (EAT)"),
    ("UTC", "UTC"),
    ("Europe/London", "Europe/London"),
    ("America/New_York", "America/New York"),
    ("Asia/Tokyo", "Asia/Tokyo"),
)


def _timezone_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                label,
                callback_data=f"timezone:{user_id}:{name}",
            )
        ]
        for name, label in _TIMEZONE_OPTIONS
    ]
    return InlineKeyboardMarkup(rows)


async def _user_timezone(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    state = get_state(context)
    profile = await state.store.get_profile(user_id)
    return str(profile.get("timezone") or state.settings.default_timezone)


@command(
    "timezone",
    description="Choose and save your timezone for local times and reminders",
    category="Core",
    usage="/timezone",
)
async def cmd_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Choose a timezone to save to your profile."""
    user = update.effective_user
    if user is None:
        return
    current = await _user_timezone(context, user.id)
    await safe_reply(
        update,
        f"Your saved timezone is **{current}**. Choose a timezone:",
        reply_markup=_timezone_keyboard(user.id),
    )


@callback("timezone")
async def handle_timezone_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    payload: str,
) -> None:
    query = update.callback_query
    parts = payload.split(":", 1)
    try:
        user_id = int(parts[0])
        timezone_name = parts[1]
    except (ValueError, IndexError):
        await query.edit_message_text("This timezone button has expired. Send /timezone to choose again.")
        return
    if update.effective_user is None or update.effective_user.id != user_id:
        return
    try:
        get_zone(timezone_name)
    except TimeParseError:
        await query.edit_message_text("This timezone option is invalid. Send /timezone to choose again.")
        return

    store = get_state(context).store
    try:
        await store.set_timezone(user_id, timezone_name)
    except PersistenceFailure as exc:
        await query.edit_message_text(str(exc))
        return
    saved_status = (
        "Timezone saved to your profile"
        if store.durable
        else "Timezone set for this process only; it may be lost when the bot restarts"
    )
    await query.edit_message_text(
        f"✅ {saved_status}: {timezone_name}\n\n"
        "Choose another timezone below to change it.",
        reply_markup=_timezone_keyboard(user_id),
    )


async def _schedule_reminder(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    due: datetime,
    message: str,
    timezone_name: str,
) -> bool:
    job_queue = context.job_queue
    chat = update.effective_chat
    if job_queue is None or chat is None:
        await safe_reply(update, "❌ Reminders are unavailable right now. Please try again later.")
        return False

    job_queue.run_once(
        _send_reminder,
        when=due.astimezone(utc_timezone.utc),
        data={"chat_id": chat.id, "message": message},
    )
    local_due = due.astimezone(get_zone(timezone_name))
    await safe_reply(
        update,
        f"✅ Reminder set for {local_due.strftime('%Y-%m-%d %H:%M %Z')} ({timezone_name})"
        f"\n📝 Message: {message}",
    )
    return True


async def _schedule_reminder_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    user = update.effective_user
    if user is None:
        return
    try:
        timezone_name = await _user_timezone(context, user.id)
        due, message = parse_reminder(text, tz_name=timezone_name)
        await _schedule_reminder(update, context, due, message, timezone_name)
    except TimeParseError as exc:
        await safe_reply(update, f"❌ {exc}")


@register("remind")
async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set a reminder; without arguments, start the cancelable guided flow."""
    text = " ".join(context.args).strip() if context.args else ""
    if not text:
        await safe_reply(
            update,
            "Usage: /remind [when] [message]\n"
            "Examples: /remind 10m drink water · /remind tomorrow 9am gym",
        )
        return
    await _schedule_reminder_text(update, context, text)


async def _remind_conversation_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = " ".join(context.args).strip() if context.args else ""
    if text:
        await _schedule_reminder_text(update, context, text)
        return ConversationHandler.END

    user = update.effective_user
    if user is None:
        return ConversationHandler.END
    await safe_reply(
        update,
        "When should I remind you? For example, `10m`, `tomorrow 9am`, or `18:30`.",
        reply_markup=_cancel_reminder_keyboard(user.id),
    )
    return ASK_REMINDER_TIME


def _cancel_reminder_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Cancel", callback_data=f"remind:cancel:{user_id}")]]
    )


async def _remind_receive_time(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or not message.text:
        return ASK_REMINDER_TIME
    try:
        timezone_name = await _user_timezone(context, user.id)
        due, _ = parse_reminder(f"{message.text.strip()} reminder", tz_name=timezone_name)
    except TimeParseError as exc:
        await safe_reply(
            update,
            f"❌ {exc}\n\nPlease enter a time such as `10m` or `tomorrow 9am`, or cancel.",
            reply_markup=_cancel_reminder_keyboard(user.id),
        )
        return ASK_REMINDER_TIME

    context.user_data["reminder_due"] = due
    context.user_data["reminder_timezone"] = timezone_name
    await safe_reply(
        update,
        "What should I remind you about?",
        reply_markup=_cancel_reminder_keyboard(user.id),
    )
    return ASK_REMINDER_MESSAGE


async def _remind_receive_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or not message.text or not message.text.strip():
        if user is not None:
            await safe_reply(
                update,
                "Please enter a reminder message, or cancel.",
                reply_markup=_cancel_reminder_keyboard(user.id),
            )
        return ASK_REMINDER_MESSAGE
    due = context.user_data.pop("reminder_due", None)
    timezone_name = context.user_data.pop("reminder_timezone", None)
    if not isinstance(due, datetime) or not isinstance(timezone_name, str):
        await safe_reply(update, "This reminder setup expired. Please start again with /remind.")
        return ConversationHandler.END

    await _schedule_reminder(update, context, due, message.text.strip(), timezone_name)
    context.user_data.pop("reminder_due", None)
    context.user_data.pop("reminder_timezone", None)
    return ConversationHandler.END


async def _cancel_reminder_conversation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
        user = update.effective_user
        if user is None:
            return ConversationHandler.END
        parts = (query.data or "").split(":")
        if len(parts) != 3 or parts[2] != str(user.id):
            return ASK_REMINDER_MESSAGE if context.user_data.get("reminder_due") else ASK_REMINDER_TIME
        context.user_data.pop("reminder_due", None)
        context.user_data.pop("reminder_timezone", None)
        await query.edit_message_text("Reminder setup cancelled.")
        return ConversationHandler.END
    except Exception:
        logger.exception("Reminder cancel callback failed")
        try:
            await query.answer(text="An error occurred.", show_alert=True)
        except Exception:
            logger.exception("Could not show reminder cancel error alert")
        return ConversationHandler.END


async def _cancel_reminder_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.pop("reminder_due", None)
    context.user_data.pop("reminder_timezone", None)
    await safe_reply(update, "Reminder setup cancelled.")
    return ConversationHandler.END


def build_reminder_conversation_handler() -> ConversationHandler:
    """Create the multi-step /remind handler, including explicit cancel paths."""
    cancel_callback = CallbackQueryHandler(
        _cancel_reminder_conversation,
        pattern=r"^remind:cancel:\d+$",
    )
    cancel_command = CommandHandler("cancel", _cancel_reminder_command)
    return ConversationHandler(
        entry_points=[CommandHandler("remind", _remind_conversation_start)],
        states={
            ASK_REMINDER_TIME: [
                cancel_callback,
                cancel_command,
                MessageHandler(filters.TEXT & ~filters.COMMAND, _remind_receive_time),
            ],
            ASK_REMINDER_MESSAGE: [
                cancel_callback,
                cancel_command,
                MessageHandler(filters.TEXT & ~filters.COMMAND, _remind_receive_message),
            ],
        },
        fallbacks=[cancel_callback, cancel_command],
        allow_reentry=True,
    )


async def _send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deliver a scheduled reminder."""
    job = context.job
    if job is None:
        raise RuntimeError("Reminder callback ran without a scheduled job")
    await context.bot.send_message(
        chat_id=job.data["chat_id"],
        text=f"⏰ Reminder: {job.data['message']}",
    )


@register("time")
async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current time and parse time expressions."""
    user = update.effective_user
    if user is None:
        return
    timezone_name = await _user_timezone(context, user.id)
    try:
        zone = get_zone(timezone_name)
    except TimeParseError as exc:
        await safe_reply(update, f"❌ Your saved timezone is invalid: {exc} Use /timezone to update it.")
        return
    now = datetime.now(zone)
    response = f"⏰ **Current time**: {now.strftime('%Y-%m-%d %H:%M:%S %Z')} ({timezone_name})"
    await safe_reply(update, response)


@register("search")
async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search content library."""
    if not context.args:
        await safe_reply(update, "Usage: /search [kind] [term]\nExample: /search jokes funny")
        return

    try:
        lib: ContentLibrary = context.bot_data.get("content_lib")
        if not lib:
            await safe_reply(update, "❌ Content library not initialized")
            return

        kind = context.args[0]
        term = " ".join(context.args[1:])

        results = lib.search(kind, term, limit=5)
        if not results:
            await safe_reply(update, f"No results for '{term}' in {kind}")
            return

        response = f"🔍 Search results for '{term}' in {kind}:\n\n"
        for i, item in enumerate(results, 1):
            if isinstance(item, dict):
                text = item.get("text") or item.get("q") or str(item)[:100]
            else:
                text = str(item)[:100]
            response += f"{i}. {text}\n\n"

        await safe_reply(update, response)
    except Exception as e:
        logger.exception("Search failed")
        await safe_reply(update, f"❌ Search error: {e}")

"""Info commands: /start, /help."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.formatting import markdown_to_html, safe_reply
from bot.registry import callback, register, visible_commands

logger = logging.getLogger(__name__)

_HELP_CATEGORIES = (
    ("games", "🎮 Games"),
    ("tools", "🛠️ Tools"),
    ("ai_media", "🤖 AI & Media"),
    ("settings", "⚙️ Settings"),
)
_HELP_COMMANDS = {
    "games": {"game", "dice", "tictactoe", "hangman", "guess", "blackjack"},
    "tools": {
        "math", "prime", "factor", "logic", "units", "convert", "chord", "scale",
        "time", "remind", "search", "joke", "quote", "facts", "compliment", "fortune",
    },
    "ai_media": {"translate", "image", "weather"},
    "settings": {"start", "help", "version", "myrights", "delete", "stats", "admin", "reload"},
}


def _help_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"help:{user_id}:category:{slug}",
                )
            ]
            for slug, label in _HELP_CATEGORIES
        ]
    )


def _category_commands(slug: str) -> list[str]:
    specs = visible_commands(include_admin=True)
    names = _HELP_COMMANDS.get(slug, set())
    selected = [spec for spec in specs if spec.name in names]
    if slug == "settings":
        assigned = set().union(*_HELP_COMMANDS.values())
        selected.extend(spec for spec in specs if spec.name not in assigned)
    return [f"/{spec.name} — {spec.description}" for spec in selected]


async def _show_help_category(query, user_id: int, slug: str) -> None:
    labels = dict(_HELP_CATEGORIES)
    if slug not in labels:
        await query.edit_message_text("This help menu has expired. Send /help to open it again.")
        return
    commands = _category_commands(slug)
    body = "\n".join(commands) or "No commands are available in this category."
    if slug == "ai_media":
        body += "\n\nSend a photo for OCR and image description, or send audio/voice for transcription."
    await query.edit_message_text(
        markdown_to_html(f"**{labels[slug]}**\n\n{body}"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data=f"help:{user_id}:back")]]
        ),
    )


@callback("help")
async def handle_help_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    payload: str,
) -> None:
    query = update.callback_query
    parts = payload.split(":")
    try:
        owner_id = int(parts[0])
    except (ValueError, IndexError):
        await query.answer("This help button has expired.")
        return
    if update.effective_user is None or update.effective_user.id != owner_id:
        await query.answer("This help menu belongs to another user.", show_alert=True)
        return
    if len(parts) == 2 and parts[1] == "back":
        await query.answer()
        await query.edit_message_text(
            markdown_to_html("👋 **Welcome! Choose a category to see available commands:**"),
            parse_mode="HTML",
            reply_markup=_help_menu_keyboard(owner_id),
        )
        return
    if len(parts) == 3 and parts[1] == "category":
        slug = parts[2]
        if slug not in dict(_HELP_CATEGORIES):
            await query.answer("This help category has expired.")
            return
        await query.answer()
        await _show_help_category(query, owner_id, slug)
        return
    await query.answer("This help button has expired.")


@register("start")
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command."""
    response = """👋 **Welcome to Telegram Bot!**

This is the largest, most capable Telegram bot ever built with:
• 🎮 **Games**: dice, tic-tac-toe, hangman, blackjack
• 🔢 **Math**: safe calc, primes, factorization, equation solver
• 🎵 **Music**: scales, chords, transposition, tempo
• 🔤 **Text**: codecs, morse, ROT13, base64, ciphers
• 📸 **Media**: image OCR, audio transcription, voice notes
• 🤖 **AI**: 12 personas, intent routing, smart responses
• ⏰ **Utilities**: reminders, time parsing, unit conversion

Type /help for full command list.
"""
    await safe_reply(update, response)


@register("help")
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help command."""
    user = update.effective_user
    if user is None:
        return
    await safe_reply(
        update,
        "👋 **Welcome! Choose a category to see available commands:**",
        reply_markup=_help_menu_keyboard(user.id),
    )

"""Utility commands: reminders, time, search."""
from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from bot.content import ContentLibrary
from bot.formatting import safe_reply
from bot.registry import register
from bot.services.timeparse import TimeParseError, parse_reminder

logger = logging.getLogger(__name__)


@register("time")
async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current time and parse time expressions."""
    now = datetime.now()
    response = f"⏰ **Current time**: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    await safe_reply(update, response)


@register("remind")
async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set a reminder."""
    text = " ".join(context.args) if context.args else None
    if not text:
        await safe_reply(update, "Usage: /remind [when] [message]\nExamples:\n/remind 10m drink water\n/remind tomorrow 9am gym\n/remind 18:30 standup")
        return

    try:
        due, message = parse_reminder(text)
        response = f"✅ Reminder set for {due.strftime('%Y-%m-%d %H:%M UTC')}\n📝 Message: {message}"
        await safe_reply(update, response)
    except TimeParseError as e:
        await safe_reply(update, f"❌ {e}")


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

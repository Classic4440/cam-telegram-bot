"""Version information command."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import safe_reply
from bot.registry import register
from bot.version import RELEASE_NOTES, __version__


@register("version")
async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the bot version and release notes."""
    await safe_reply(
        update,
        f"Version {__version__}\n\nRelease notes:\n{RELEASE_NOTES}",
    )

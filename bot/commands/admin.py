"""Admin commands."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import code_block, safe_reply
from bot.registry import register

logger = logging.getLogger(__name__)

def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is admin."""
    state = context.bot_data.get("state")
    settings = getattr(state, "settings", None)
    return settings is not None and user_id in settings.admin_ids


@register("admin")
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin panel."""
    user = update.effective_user
    if user is None or not is_admin(user.id, context):
        await safe_reply(update, "❌ Admin only")
        return

    response = """👨‍💼 **Admin Panel**

/stats - Show statistics
/reload - Reload content
/users - List active users
/cache - Show cache stats
"""
    await safe_reply(update, response)


@register("stats")
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot statistics."""
    try:
        state = context.bot_data.get("state")
        lib = context.bot_data.get("content_lib")

        stats = {
            "users_total": len(getattr(state, "user_stats", {})) if state else 0,
            "content_kinds": len(lib.kinds()) if lib else 0,
            "content_total": lib.total() if lib else 0,
        }

        response = f"""📊 **Bot Statistics**

Users: {stats['users_total']}
Content kinds: {stats['content_kinds']}
Total entries: {stats['content_total']}
"""
        await safe_reply(update, response)
    except Exception as e:
        logger.exception("Stats failed")
        await safe_reply(update, f"❌ Error: {e}")


@register("reload")
async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reload content library."""
    user = update.effective_user
    if user is None or not is_admin(user.id, context):
        await safe_reply(update, "❌ Admin only")
        return

    try:
        lib = context.bot_data.get("content_lib")
        if lib:
            counts = lib.reload()
            response = f"✅ Content reloaded\n\n{code_block(str(counts))}"
        else:
            response = "❌ Content library not initialized"

        await safe_reply(update, response)
    except Exception as e:
        logger.exception("Reload failed")
        await safe_reply(update, f"❌ Error: {e}")

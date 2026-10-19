"""Admin commands."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.formatting import code_block, safe_reply
from bot.registry import register

logger = logging.getLogger(__name__)


_ADMIN_PERMISSIONS = (
    ("can_manage_chat", "Manage chat"),
    ("can_delete_messages", "Delete messages"),
    ("can_manage_video_chats", "Manage video chats"),
    ("can_restrict_members", "Restrict members"),
    ("can_promote_members", "Promote members"),
    ("can_change_info", "Change group info"),
    ("can_invite_users", "Invite users"),
    ("can_post_messages", "Post messages"),
    ("can_edit_messages", "Edit messages"),
    ("can_pin_messages", "Pin messages"),
    ("can_manage_topics", "Manage topics"),
    ("can_post_stories", "Post stories"),
    ("can_edit_stories", "Edit stories"),
    ("can_delete_stories", "Delete stories"),
    ("can_manage_direct_messages", "Manage direct messages"),
)


def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is admin."""
    state = context.bot_data.get("state")
    settings = getattr(state, "settings", None)
    return settings is not None and user_id in settings.admin_ids


@register("myrights")
async def cmd_myrights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check the bot's current status and permissions in this group."""
    chat = update.effective_chat
    if chat is None or chat.type not in {"group", "supergroup"}:
        await safe_reply(update, "Use /myrights in a group or supergroup to check my permissions.")
        return

    try:
        member = await context.bot.get_chat_member(
            chat_id=chat.id,
            user_id=context.bot.id,
        )
    except TelegramError:
        logger.exception("Could not check bot permissions in chat %s", chat.id)
        await safe_reply(update, "I couldn't verify my permissions in this group. Please try again.")
        return

    if member.status in {"administrator", "creator"}:
        if member.status == "creator":
            response = "✅ I am the group owner/creator and have all administrator permissions."
        else:
            permissions = [
                label
                for attribute, label in _ADMIN_PERMISSIONS
                if getattr(member, attribute, False)
            ]
            response = "✅ I am an administrator."
            response += "\n\nPermissions:\n" + (
                "\n".join(f"• {permission}" for permission in permissions)
                if permissions
                else "No administrator permissions are enabled."
            )
    else:
        response = f"ℹ️ I am not an administrator in this group (status: {member.status})."

    await safe_reply(update, response)


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

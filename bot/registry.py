"""Decorator-based command registry with auto-discovery.

Adding a feature = adding a function in ``bot/commands/<anything>.py``::

    @command("hello", description="Say hello", category="Fun", usage="/hello [name]")
    async def hello(update, context):
        await reply(update.effective_message, "Hello!")

The registry then (a) builds the Telegram handlers, (b) publishes the slash-command menu, (c) generates
``/help``, and (d) feeds the AI system prompt, so those four can never drift apart.

Every registered handler is wrapped with the same middleware: admin gate, token-bucket rate limit,
usage metrics, XP, and a single error boundary that turns exceptions into friendly replies.
"""
from __future__ import annotations

import importlib
import logging
import math
import pkgutil
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from telegram import BotCommand
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler

from .errors import AIUnavailable, UserError
from .formatting import reply
from .state import get_state

logger = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[None]]
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

CATEGORY_ORDER = ["Core", "AI", "Fun", "Games", "Logic", "Tools", "Music", "Info", "Productivity", "Admin"]
CATEGORY_ICONS = {
    "Core": "🧭", "AI": "🧠", "Fun": "🎉", "Games": "🎮", "Logic": "🧮", "Tools": "🛠",
    "Music": "🎧", "Info": "🌍", "Productivity": "🗓", "Admin": "🔒",
}


@dataclass(slots=True)
class CommandSpec:
    name: str
    handler: Handler
    description: str
    category: str = "Core"
    usage: str = ""
    aliases: tuple[str, ...] = ()
    admin_only: bool = False
    hidden: bool = False
    cost: float = 1.0
    xp: int = 1


REGISTRY: dict[str, CommandSpec] = {}
CALLBACKS: dict[str, Handler] = {}


def command(
    name: str,
    *,
    description: str,
    category: str = "Core",
    usage: str = "",
    aliases: tuple[str, ...] = (),
    admin_only: bool = False,
    hidden: bool = False,
    cost: float = 1.0,
    xp: int = 1,
) -> Callable[[Handler], Handler]:
    names = (name, *aliases)
    for item in names:
        if not _NAME.match(item):
            raise ValueError(f"Invalid command name {item!r}")
        if item in REGISTRY or any(item in spec.aliases for spec in REGISTRY.values()):
            raise ValueError(f"Duplicate command name {item!r}")

    def decorator(func: Handler) -> Handler:
        REGISTRY[name] = CommandSpec(
            name=name, handler=func, description=description, category=category,
            usage=usage or f"/{name}", aliases=aliases, admin_only=admin_only, hidden=hidden,
            cost=cost, xp=xp,
        )
        return func

    return decorator


def callback(prefix: str) -> Callable[[Handler], Handler]:
    """Register an inline-keyboard handler for ``callback_data`` of the form ``"<prefix>:<payload>"``."""
    if ":" in prefix or not prefix:
        raise ValueError("callback prefix must be non-empty and contain no colon")

    def decorator(func: Handler) -> Handler:
        if prefix in CALLBACKS:
            raise ValueError(f"Duplicate callback prefix {prefix!r}")
        CALLBACKS[prefix] = func
        return func

    return decorator


def discover(package: str = "bot.commands") -> list[str]:
    """Import every module in the commands package so their decorators run."""
    pkg = importlib.import_module(package)
    loaded = []
    for module in pkgutil.iter_modules(pkg.__path__):
        if module.name.startswith("_"):
            continue
        importlib.import_module(f"{package}.{module.name}")
        loaded.append(module.name)
    return loaded


# --------------------------------------------------------------------------------------
# introspection (help text, bot menu, AI prompt)
# --------------------------------------------------------------------------------------
def visible_commands(include_admin: bool = False) -> list[CommandSpec]:
    specs = [s for s in REGISTRY.values() if not s.hidden and (include_admin or not s.admin_only)]
    order = {name: i for i, name in enumerate(CATEGORY_ORDER)}
    return sorted(specs, key=lambda s: (order.get(s.category, 99), s.name))


def command_summary(include_admin: bool = False) -> list[tuple[str, str]]:
    return [(s.name, s.description) for s in visible_commands(include_admin)]


def grouped_commands(include_admin: bool = False) -> dict[str, list[CommandSpec]]:
    groups: dict[str, list[CommandSpec]] = {}
    for spec in visible_commands(include_admin):
        groups.setdefault(spec.category, []).append(spec)
    return groups


def bot_menu() -> list[BotCommand]:
    """Telegram allows 100 menu entries of <=256 chars; we publish the non-admin visible ones."""
    return [BotCommand(s.name, s.description[:250]) for s in visible_commands()][:100]


# --------------------------------------------------------------------------------------
# middleware
# --------------------------------------------------------------------------------------
def _wrap(spec: CommandSpec) -> Handler:
    async def wrapper(update, context) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return
        state = get_state(context)

        if spec.admin_only and user.id not in state.settings.admin_ids:
            await reply(message, "🔒 That command is for bot admins only.")
            return

        wait = state.limiter.consume(user.id, spec.cost)
        if wait > 0:
            await reply(message, f"⏳ Easy there! Try again in {math.ceil(wait)}s.")
            return

        state.stats.commands[spec.name] += 1
        try:
            await spec.handler(update, context)
        except UserError as exc:
            await reply(message, exc.message)
        except AIUnavailable:
            await reply(message, "🤖 The AI is busy right now. Please try again in a moment.")
        except TelegramError:
            state.stats.errors += 1
            logger.exception("Telegram error in /%s", spec.name)
            await _safe_reply(message, "⚠️ Telegram rejected that response. Please try again.")
        except Exception:  # noqa: BLE001 - last-resort error boundary
            state.stats.errors += 1
            logger.exception("Unhandled error in /%s", spec.name)
            await _safe_reply(message, "⚠️ Something went wrong on my side. Please try again.")
        else:
            state.store.add_xp(user.id, user.username or user.first_name, spec.xp)

    wrapper.__name__ = f"cmd_{spec.name}"
    return wrapper


async def _safe_reply(message, text: str) -> None:
    try:
        await reply(message, text)
    except Exception:  # noqa: BLE001
        logger.exception("Could not deliver error message")


async def dispatch_callback(update, context) -> None:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    state = get_state(context)
    prefix, _, payload = query.data.partition(":")
    handler = CALLBACKS.get(prefix)
    if handler is None:
        await query.answer("This button has expired.")
        return
    if state.limiter.consume(update.effective_user.id, 0.5) > 0:
        await query.answer("Slow down a little 🙂")
        return
    state.stats.callbacks += 1
    try:
        await handler(update, context, payload)
    except UserError as exc:
        await _answer(query, exc.message)
    except Exception:  # noqa: BLE001
        state.stats.errors += 1
        logger.exception("Unhandled error in callback %s", prefix)
        await _answer(query, "Something went wrong.")


async def _answer(query, text: str) -> None:
    try:
        await query.answer(text[:190], show_alert=False)
    except TelegramError:
        pass


def build_handlers() -> list:
    handlers: list = []
    for spec in REGISTRY.values():
        handlers.append(CommandHandler([spec.name, *spec.aliases], _wrap(spec)))
    handlers.append(CallbackQueryHandler(dispatch_callback))
    return handlers

"""Curated light-hearted and motivational commands."""
from __future__ import annotations

import random

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import reply_ai
from bot.registry import command
from scripts.curated_jokes import JOKES
from scripts.curated_quotes_facts import FACTS, QUOTES

COMPLIMENTS = (
    "You bring a thoughtful perspective to the people around you.",
    "Your effort and persistence make a real difference.",
    "You have a knack for making complicated things easier to understand.",
    "Your curiosity is a strength; keep asking good questions.",
    "You deserve credit for how far you have come.",
)

FORTUNES = (
    "A small step today may open a useful door tomorrow.",
    "An unexpected conversation could give you a fresh perspective.",
    "Patience will help you notice an opportunity others miss.",
    "A practical idea is closer than it seems; write it down.",
    "The next chapter may be better than the last one.",
)


def _choose(groups: dict[str, list[str]]) -> str:
    choices = [entry for entries in groups.values() for entry in entries]
    if not choices:
        raise ValueError("No curated entries are available.")
    return random.choice(choices)


async def _send_random(update: Update, groups: dict[str, list[str]]) -> None:
    message = update.effective_message
    if message is None:
        return
    try:
        await reply_ai(message, _choose(groups))
    except ValueError as exc:
        await reply_ai(message, str(exc))


@command("joke", description="Tell a joke", category="Fun", usage="/joke")
async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_random(update, JOKES)


@command("quote", description="Share a quote", category="Fun", usage="/quote")
async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_random(update, QUOTES)


@command("facts", description="Share an interesting fact", category="Info", usage="/facts")
async def facts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_random(update, FACTS)


@command("compliment", description="Get an encouraging compliment", category="Fun", usage="/compliment")
async def compliment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_random(update, {"general": list(COMPLIMENTS)})


@command("fortune", description="Get a light-hearted fortune", category="Fun", usage="/fortune")
async def fortune(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_random(update, {"general": list(FORTUNES)})

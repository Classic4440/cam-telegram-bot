"""cam-telegram-bot: a modular, plugin-style Telegram bot.

Layout
------
bot/config.py        typed environment configuration
bot/registry.py      decorator-based command/callback registry + auto-discovery
bot/commands/*.py    drop-in command modules (every module is auto-imported)
bot/services/*.py    pure-Python engines (math, logic, units, dice, ...) with no Telegram imports
bot/data/*.json      content packs (jokes, quotes, facts, trivia, ...) loaded at startup
"""

from .version import __version__

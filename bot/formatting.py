"""Telegram-safe text helpers.

Design rule: the application default parse mode is *None* (plain text).  Anything that should render as
rich text goes through ``reply_html`` / ``reply_ai`` which escape user-controlled data first.  This
removes a whole class of "can't parse entities" failures (for example a usage string such as
``/image <description>`` is an unsupported HTML tag when parse_mode=HTML).
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
SAFE_CHUNK = 3900

esc = html.escape


def e(text: object) -> str:
    """HTML-escape any value (quotes included, so it is safe inside attributes too)."""
    return html.escape(str(text), quote=True)


# --------------------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------------------
def chunk_text(text: str, limit: int = SAFE_CHUNK) -> list[str]:
    """Split ``text`` into pieces <= ``limit`` chars, preferring paragraph, line then word boundaries."""
    text = text.strip()
    if not text:
        return [""]
    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "), window.rfind(" "))
        if cut < limit // 3:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


# --------------------------------------------------------------------------------------
# markdown -> Telegram HTML
# --------------------------------------------------------------------------------------
_SEPARATOR_CELL = re.compile(r":?-{3,}:?")


def markdown_table_to_list(text: str) -> str:
    """Replace pipe-delimited Markdown tables (unsupported by Telegram) with bullet lists."""
    if "|" not in text:
        return text
    lines = text.splitlines()
    output: list[str] = []
    headers: list[str] | None = None

    def split_row(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    def is_separator(line: str) -> bool:
        return "|" in line and all(_SEPARATOR_CELL.fullmatch(c) for c in split_row(line))

    for index, line in enumerate(lines):
        if "|" not in line:
            headers = None
            output.append(line)
            continue
        cells = split_row(line)
        if is_separator(line):
            continue
        if index + 1 < len(lines) and is_separator(lines[index + 1]):
            headers = cells
            continue
        if headers:
            items = [f"{h}: {v}" for h, v in zip(headers, cells) if h and v]
            output.append("• " + "; ".join(items))
        else:
            output.append("• " + "; ".join(c for c in cells if c))
    return "\n".join(output)


_FENCE = re.compile(r"```[ \t]*([\w+#.-]*)[ \t]*\n?(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_HEADER = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_BULLET = re.compile(r"^([ \t]*)[*+-][ \t]+", re.MULTILINE)
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_BOLD_US = re.compile(r"(?<![\w_])__(?=\S)(.+?)(?<=\S)__(?![\w_])")
_ITALIC = re.compile(r"(?<![\*\w])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\*\w])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")


def markdown_to_html(text: str) -> str:
    """Convert a conservative subset of Markdown to Telegram HTML.

    Code is extracted first so nothing inside it is reformatted, everything else is escaped, then the
    tags we emit are balanced by construction.  If Telegram still rejects the result the sender falls
    back to plain text (see ``reply_ai``).
    """
    text = markdown_table_to_list(text)
    stash: list[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    def fence(match: re.Match[str]) -> str:
        lang = match.group(1)
        body = html.escape(match.group(2).rstrip("\n"), quote=False)
        if lang and re.fullmatch(r"[\w+#.-]{1,20}", lang):
            return keep(f'<pre><code class="language-{lang}">{body}</code></pre>')
        return keep(f"<pre>{body}</pre>")

    text = _FENCE.sub(fence, text)
    text = _INLINE_CODE.sub(lambda m: keep(f"<code>{html.escape(m.group(1), quote=False)}</code>"), text)
    text = html.escape(text, quote=True)
    text = _HEADER.sub(r"<b>\1</b>", text)
    text = _BULLET.sub(lambda m: f"{m.group(1)}• ", text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _BOLD_US.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)
    text = _LINK.sub(r'<a href="\2">\1</a>', text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def html_heading(text: str) -> str:
    """Format an escaped, Telegram-safe HTML heading."""
    return f"<b>{html.escape(text)}</b>"


def html_footer(text: str) -> str:
    """Format an escaped, Telegram-safe footer."""
    return f"<i>{html.escape(text)}</i>"


def present_message(title: str, body: str = "", footer: str | None = None) -> str:
    """Compose a consistent HTML message from a heading, Markdown body, and optional footer."""
    sections = [html_heading(title)]
    if body:
        sections.append(markdown_to_html(body))
    if footer:
        sections.append(html_footer(footer))
    return "\n\n".join(sections)


# --------------------------------------------------------------------------------------
# sending
# --------------------------------------------------------------------------------------
async def reply(message, text: str, **kwargs):
    """Send plain text (auto-chunked).  Returns the last message sent."""
    sent = None
    for chunk in chunk_text(str(text)):
        sent = await message.reply_text(chunk, parse_mode=None, **kwargs)
    return sent


async def reply_html(message, html_text: str, **kwargs):
    """Send pre-escaped HTML.  Falls back to tag-stripped text if Telegram rejects the markup."""
    try:
        return await message.reply_text(html_text[:TELEGRAM_LIMIT], parse_mode=ParseMode.HTML, **kwargs)
    except BadRequest:
        logger.warning("HTML rejected by Telegram, falling back to plain text")
        plain = html.unescape(re.sub(r"<[^>]+>", "", html_text))
        return await message.reply_text(plain[:TELEGRAM_LIMIT], parse_mode=None, **kwargs)


async def reply_ai(message, markdown: str, **kwargs):
    """Send model output: Markdown -> HTML with a plain-text fallback, chunked for long answers."""
    sent = None
    chunks = chunk_text(markdown)
    for index, chunk in enumerate(chunks):
        chunk_kwargs = dict(kwargs)
        if index < len(chunks) - 1:
            chunk_kwargs.pop("reply_markup", None)
        try:
            sent = await message.reply_text(
                markdown_to_html(chunk), parse_mode=ParseMode.HTML, **chunk_kwargs
            )
        except BadRequest:
            sent = await message.reply_text(chunk, parse_mode=None, **chunk_kwargs)
    return sent


async def safe_reply(update, text: str, **kwargs):
    """Reply to an update using the project's safe Markdown-to-HTML sender."""
    message = update.effective_message
    if message is None:
        return None
    return await reply_ai(message, text, **kwargs)


def code_block(text: str) -> str:
    """Wrap plain text in a Markdown code fence for safe Telegram rendering."""
    return f"```\n{text}\n```"


@asynccontextmanager
async def typing_indicator(message, action: str = ChatAction.TYPING) -> AsyncIterator[None]:
    """Keep the "typing…" indicator alive while a slow operation runs."""

    async def pulse() -> None:
        while True:
            with suppress(TelegramError, Exception):
                await message.chat.send_action(action)
            await asyncio.sleep(4.0)

    task = asyncio.create_task(pulse())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    parts = []
    for label, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        value, seconds = divmod(seconds, size)
        if value:
            parts.append(f"{value}{label}")
    return " ".join(parts[:3]) or "0s"


def format_number(value: float | int, digits: int = 12) -> str:
    """Human friendly number: integers verbatim (grouped if long), floats with trimmed precision."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        text = str(value)
        return text if len(text) <= 40 else f"{value:.12e}"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.{digits}g}"

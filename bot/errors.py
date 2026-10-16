"""Exception types shared across the bot."""
from __future__ import annotations


class UserError(Exception):
    """A problem the *user* can fix (bad arguments, unknown unit, ...).

    The message is shown to the user verbatim as plain text, so it must never contain secrets.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AIUnavailable(Exception):
    """Every configured model failed or the AI provider rejected our credentials."""

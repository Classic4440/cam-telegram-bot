"""Application version and release notes."""

__version__ = "2.5.0"

RELEASE_NOTES = (
    "Updated image OCR and descriptions to use the supported Groq Qwen 3.8 27B vision model, with clearer "
    "provider error logging. Added admin-only message deletion with verified group permissions and "
    "natural-language requests when replying to a message. Also includes group permission reporting, "
    "voice transcription with conversation context and saved profile memory, generated content packs, "
    "scheduled reminders, and stateful games. Added interactive start, help, and game menus, complete "
    "categorized command discovery, and profile-persisted timezone preferences for /time and /remind, "
    "including a cancelable guided reminder conversation."
)

"""Application version and release notes."""

__version__ = "2.6.2"

RELEASE_NOTES = (
    "Updated image OCR and descriptions to use the supported Groq Qwen 3.8 27B vision model, with clearer "
    "provider error logging. Added admin-only message deletion with verified group permissions and "
    "natural-language requests when replying to a message. Also includes group permission reporting, "
    "voice transcription with conversation context and saved profile memory, generated content packs, "
    "scheduled reminders, and stateful games. Added interactive start, help, and game menus, complete "
    "categorized command discovery, and profile-persisted timezone preferences for /time and /remind, "
    "including a cancelable guided reminder conversation. Added AI response regeneration, per-user "
    "message and media rate limiting, and private persistent notes with /save, /saved, and /unsave. "
    "Fixed Supabase PGRST205 missing-table errors by adding the complete profiles/notes schema, "
    "service-role RLS policies, and XP RPC. Fixed unresponsive inline menus by acknowledging callbacks "
    "before routing and showing a logged error alert if callback processing fails."
)

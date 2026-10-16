# Telegram Bot — Google Drive Upload Complete

## Folder Info
- **Folder Name**: Telegram-Bot-Claude-Project
- **Folder ID**: 1ijIL73MdCSUxBGKs4BjQnazzP-l8CB5q
- **Folder Link**: https://drive.google.com/drive/folders/1ijIL73MdCSUxBGKs4BjQnazzP-l8CB5q
- **Date Created**: 2026-10-15
- **Status**: Ready for ongoing sync

---

## Files Uploaded (14 files)

### Documentation (3 files)
1. **Project_Instructions.md** (4.7 KB)
   - Full project workflow rules
   - Security mindset guidelines
   - Stage plan and testing requirements
   - Architecture patterns and design decisions
   - Reference: `/home/claude/cam-telegram-bot/`

2. **Current_Status_and_Architecture.md** (8.7 KB)
   - Complete system architecture overview
   - What's built: all core modules + services + reference data
   - What's pending: commands, app entry, DB schema, deployment
   - Test results: 490 tests passed, 27/27 mutations caught
   - Content capacities and stage status

3. **services_and_curated_full.md** (2.5 KB)
   - Summary of 9 service modules
   - 3 curated content files (jokes, quotes/facts, games)
   - De-duplication and merge strategy
   - Ready-to-extract file list

### Core Bot Modules (11 files)
#### Package Init & Configuration
4. **bot_init.py** (0.5 KB) — Package metadata and version

5. **bot_config.py** (5.5 KB) — Typed, validated environment configuration from env vars
   - TELEGRAM_TOKEN, AI_API_KEY (required)
   - Model selection, timeouts, rate limits
   - Database URL, admin IDs, feature flags

#### Core Services
6. **bot_errors.py** (0.5 KB) — Exception types: UserError, AIUnavailable

7. **bot_cache.py** (2.9 KB) — Thread-safe TTL cache with LRU eviction

8. **bot_logging_setup.py** (1.9 KB) — Logging with secret redaction (tokens, API keys)

9. **bot_security.py** (2.2 KB) — Token-bucket rate limiter, input sanitizing

10. **bot_state.py** (2.0 KB) — Application state: AppState + Stats dataclass, per-user locks

11. **bot_formatting.py** (8.0 KB) — Telegram-safe text helpers
    - Chunking, markdown→HTML conversion
    - Typing indicators, human-readable formatting

#### Persistence & Content
12. **bot_store.py** (8.9 KB) — Persistence facade with circuit breaker
    - MemoryBackend (fallback)
    - SupabaseBackend (durable Postgres)
    - XP batching, per-user locking
    - Graceful degradation on DB failure

13. **bot_content.py** (6.6 KB) — Content library loader
    - Merges curated + generated JSON packs
    - De-duplication by normalized fingerprint
    - Deck-based shuffling (no repeats per scope)
    - Full-text search support

#### AI & Commands
14. **bot_registry.py** (8.2 KB) — Decorator-based command registry
    - @command decorator with auto-discovery
    - Middleware: admin gate, rate limit, XP, error boundary
    - Dynamic /help, bot menu, AI system prompt
    - Callback handler dispatch

15. **bot_ai.py** (12.1 KB) — AI service with fallback chain
    - 12 personas (default, professor, engineer, coach, etc.)
    - Intent routing: code/logic/creative/brief/chat modes
    - Model fallback chain with retry + jitter
    - Voice transcription support
    - History trimming, system prompt generation

---

## What's NOT Yet Uploaded (Pending)

### Services Modules (9 files) — Stored in `bot/services/`
- `dice.py` (2.8 KB) — Dice notation roller
- `logic.py` (7.4 KB) — Propositional logic, truth tables
- `units.py` (7.0 KB) — Unit conversion
- `numbers.py` (8.4 KB) — Prime checking, factorization
- `textcodec.py` (7.9 KB) — Ciphers, encodings
- `music.py` (8.8 KB) — Music theory, chord builder
- `timeparse.py` (5.1 KB) — Natural language time parsing
- `gamelogic.py` (7.2 KB) — Game engines (tic-tac-toe, hangman, blackjack)
- `__init__.py` (0.1 KB)

### Curated Content (3 files) — Stored in `scripts/`
- `curated_jokes.py` (26.3 KB) — 1,500+ jokes
- `curated_quotes_facts.py` (21.5 KB) — 1,000+ quotes/facts
- `curated_games.py` (18.6 KB) — 500+ riddles/trivia/games

### Generator Source (1 file)
- `generate_content.py` (58 KB, 1082 lines) — Extract from `scripts/generate_content.md`
  - Stage 1: Core I/O, atomic writes, fingerprinting ✅
  - Stage 2: Reference data (countries, elements) ✅
  - Stage 3: Template generators (jokes, quotes, etc.) ✅
  - Stage 4-6: Pending (computed generators, curated pass-through, validation)

### Test Files (3 files) — Stored in `tests/`
- `test_generate_content.md` (10.7 KB, 49 tests)
- `test_generate_content_data.md` (17.1 KB, 163 tests)
- `test_generate_content_text.md` (36.6 KB, 278 tests)
- **Total: 490 tests passed, 27/27 mutations caught**

### Critical Pending Files (Not Yet Written)
- `bot/commands/*.py` — Command implementations
- `app.py` — Flask entry point, Telegram webhook
- `supabase/schema.sql` — Database schema, RLS policies
- `requirements.txt` — Frozen dependencies
- `render.yaml` — Deployment config
- `.env.example` — Environment template
- `README.md` — User documentation

---

## Important Notes for Ongoing Sync

### Drive Limitation
**Google Drive cannot edit files in-place.** For future syncs:
- **Option A**: Create new versions (e.g., `bot_registry_v2.py`)
- **Option B**: Delete old version + upload new (ask first, never auto-trash)
- **Option C**: Nested folders for organization (e.g., `v1/`, `v2/`)

### Recommended Approach
Use a **versioning folder structure**:
```
Telegram-Bot-Claude-Project/
├── latest/              # Current working version
│   ├── bot_*.py
│   ├── generate_content.py
│   └── ...
├── archive/             # Previous versions
│   ├── 2026-10-15/
│   └── 2026-10-16/
└── docs/                # Documentation (static)
    ├── Project_Instructions.md
    ├── Current_Status_and_Architecture.md
    └── ...
```

### Next Sync Strategy
1. Keep `.md` instruction files as single source of truth
2. Upload all `.py` modules to `latest/` folder on each update
3. Move previous `latest/` to `archive/<date>/` before uploading new
4. Never delete — preserve full history for recovery

---

## How to Use This Folder

1. **Reference for context**: Open `Current_Status_and_Architecture.md` to understand the full system
2. **Workflow guide**: See `Project_Instructions.md` for rules, stages, and testing requirements
3. **Source truth**: For actual code, use the local project at `/home/claude/cam-telegram-bot/`
4. **Async collaboration**: Future updates here keep everyone in sync

---

## Project Status Summary

- **Code Complete**: 50% (Stages 1–3 of content generation done)
- **Test Coverage**: 100% (490/490 tests passing, Stage 1–3)
- **Bootable**: No (commands, app entry, DB schema pending)
- **Deployable**: No (requires Stages 4–6, requirements.txt, render.yaml)
- **Production-ready**: No (needs bot commands, error handling, deployment testing)

---

**Last Updated**: 2026-10-16 04:26 UTC  
**Maintainer**: DanielMac (marklikyfc@gmail.com)  
**Repository**: /home/claude/cam-telegram-bot/

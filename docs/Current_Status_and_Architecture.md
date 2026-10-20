# Current Status & Architecture — Telegram Bot Project

## Project Overview

This is a **high-power, modular Telegram bot** built with python-telegram-bot 22.8, Flask, and Groq LLM. The bot is designed for extensibility via a plugin-style command registry, deterministic content generation, and a secure Supabase backend.

**Primary Goal**: Build "the largest bot ever" — maximum logic, power, variety, and robustness.

## Architecture

### Core Components

#### 1. **Command Registry & Dispatcher** (`bot/registry.py`)
- Decorator-based plugin system (`@command`).
- Auto-discovery of commands.
- Middleware stack:
  - **Admin gate**: restrict commands to admins.
  - **Token-bucket rate limit**: 10 req/sec per user, 1 sec/burst.
  - **Stats**: track command usage.
  - **XP**: award experience points per interaction.
  - **Error boundary**: graceful failure with user-friendly messages.
- Dynamic `/help` and bot menu built from registry.
- `/start` opens inline navigation to games or categorized help; game and help selections edit the existing message and acknowledge callbacks.
- `/game` offers Rock Paper Scissors, Hangman, and Tic-Tac-Toe, with Back navigation.
- `/help` lists every visible registered command in a category; newly added commands without a category mapping are included under Settings.
- `/timezone` saves a selected IANA timezone in the user's Supabase profile. `/time` and `/remind` use that preference (UTC by default).
- `/remind` supports both `/remind <when> <message>` and a two-step inline-cancelable conversation.
- AI replies offer a user-scoped Regenerate button; free-text and media work share per-user token-bucket limits.
- `/save`, `/saved`, and `/unsave` provide private notes backed by the existing notes store.
- AI system prompt auto-generated from command metadata.

#### 2. **AI Service** (`bot/ai.py`)
- **Intent Routing**: regex-based command dispatch.
- **Persona & Mode**: customize bot behavior per conversation.
- **Model Fallback Chain**: Groq (primary) → local fallback.
- **Retry & Jitter**: 3 retries, exponential backoff + random jitter.
- **History Trimming**: keep recent context under token limits.
- **Long-term memory**: profile data from `user_profiles` is included in chat and task prompts.
- **Log Redaction**: mask sensitive data (API keys, user IDs).

#### 3. **Store Facade** (`bot/store.py`)
- **Supabase Backend**: PostgreSQL with RLS.
- **Circuit Breaker**: failover to in-memory cache on outage.
- **Caching Layer** (`bot/cache.py`): local in-memory with TTL.
- **Security**: RLS policies, prepared statements, least privilege.
- **User profiles**: `/personal` and `/update` persist profile data in Supabase with an in-memory fallback.

#### 4. **Content System** (`bot/content.py`)
- Loads curated (`<kind>.json`) and generated (`<kind>.generated.json`) content.
- **Merge strategy**: sorted read, first-copy-wins de-dup.
- **De-dup fingerprint**: `re.sub(r"\W+", " ", s.lower()).strip()`.
- Categories: jokes, quotes, facts, trivia, games, compliments, fortunes, would-you-rather.

#### 5. **Content Generator** (`scripts/generate_content.md` → `.py`)
- **Deterministic seeded generation**: `rng_for(seed, name)`.
- **Stages**:
  1. ✅ **Core & I/O** — atomic writes, validation, fingerprint, builder framework.
  2. ✅ **Reference Data** — 195+ countries, 118 elements, quiz functions.
  3. ✅ **Template Text** — jokes (3 families), quotes (4), compliments, fortunes, would-you-rather.
  4. ⏳ **Computed Generators** — trivia from Stage 2, element facts, math facts.
  5. ⏳ **Curated Pass-Through** — `.json` → `.generated.json` builder wiring.
  6. ⏳ **Strict Validation** — 5-letter words, trivia q/a validation, real run to `bot/data`.
- **Capacity Allocation** (Stage 3 complete):
  - Jokes: 16,152 (advice 11,760; bar 4,176; not_saying 216)
  - Quotes: 2,504 (900/1000/540/64)
  - Compliments: 206 (120/30/56)
  - Fortunes: ~2,339 (forecast 1,440; lucky 899)
  - Would-you-rather: 1,540 (378/378/784)

#### 6. **Services** (`bot/services/*.py`)
Rich, production-grade utilities:
- **`mathx.py`**: safe math eval (AST whitelist, no `eval`), symbolic differentiation, matrix ops.
- **`logic.py`**: boolean algebra, truth tables, simplification.
- **`units.py`**: unit conversion (length, mass, temperature, energy, etc.).
- **`dice.py`**: weighted dice, probability distribution.
- **`textcodec.py`**: rot13, base64, morse, phonetic alphabet, substitution ciphers.
- **`music.py`**: chord theory, scale modes, interval calculations, MIDI.
- **`numbers.py`**: prime sieve, factorization, gcd/lcm, fibonacci.
- **`timeparse.py`**: natural language time parsing ("in 2 hours", "next Tuesday", etc.).
- **`gamelogic.py`**: rock-paper-scissors, hangman, connect-4, tic-tac-toe state machine.

### Module Inventory

#### Bot Modules (`bot/`)
- ✅ `__init__.py` — package init.
- ✅ `config.py` — env-based configuration (API keys, database URL, etc.).
- ✅ `logging_setup.py` — structured logging with redaction.
- ✅ `cache.py` — in-memory TTL cache with circuit breaker fallback.
- ✅ `security.py` — rate limiting (token bucket), input validation, RLS enforcement.
- ✅ `formatting.py` — message formatting (markdown, code blocks, reusable HTML headings and footers).
- ✅ `store.py` — Supabase facade with circuit breaker.
- ✅ `ai.py` — Groq integration, intent routing, conversation management.
- ✅ `content.py` — content loader (merge curated + generated).
- ✅ `state.py` — user/conversation state persistence.
- ✅ `registry.py` — command decorator, auto-discovery, middleware stack.
- ✅ `errors.py` — custom exception hierarchy.

#### Services (`bot/services/`)
- ✅ `mathx.py` — 10.8 KB
- ✅ `logic.py` — 7.4 KB
- ✅ `units.py` — 7.0 KB
- ✅ `dice.py` — 2.8 KB
- ✅ `textcodec.py` — 7.9 KB
- ✅ `music.py` — 8.8 KB
- ✅ `numbers.py` — 8.4 KB
- ✅ `timeparse.py` — 5.1 KB
- ✅ `gamelogic.py` — 7.2 KB

#### Content Generation (`scripts/`)
- ✅ `generate_content.md` — 57.3 KB (1082 lines; source of truth)
- ✅ `curated_jokes.py` — 26.3 KB (hand-written data)
- ✅ `curated_quotes_facts.py` — 21.5 KB (hand-written data)
- ✅ `curated_games.py` — 18.6 KB (hand-written data)

#### Tests (`tests/`)
- ✅ `test_generate_content.md` — 10.7 KB (Stage 1; 49 tests)
- ✅ `test_generate_content_data.md` — 17.1 KB (Stage 2; 163 tests)
- ✅ `test_generate_content_text.md` — 36.6 KB (Stage 3; 278 tests)

**Total Project Size**: ~322 KB (text + code)

### Data Directory

**`bot/data/`**: Currently **empty** (0 entries).
- Will contain generated content after Stage 6 real run.
- Post-generation, loader tests will validate round-trip (load → verify → reload).

## Key Decisions

### Why Deterministic Seeded Generation?
Cross-version reproducibility; easier testing; content stability across restarts.

### Why Separate `.generated.json` Files?
Clear distinction between curated (human-authored, immutable) and generated (algorithmic, regenerable) content. Enables refreshing generated content without touching curated data.

### Why Atomic Writes?
Data integrity; prevents partial/corrupted files if the process crashes mid-write.

### Why Middleware Stack?
Separates concerns (auth, rate-limiting, telemetry) from command logic; easier to test and extend.

### Why Groq + Fallback Chain?
Groq is fast & cheap. Fallback chain ensures the bot remains functional if Groq is down; local model/cache provides resilience.

## Test Results (Most Recent)

**Stage 1–3 Complete**:
- ✅ 49 Stage 1 tests (core I/O, validation, fingerprinting)
- ✅ 163 Stage 2 tests (data completeness, country capitals, elements)
- ✅ 278 Stage 3 tests (template generators, lint, determinism, de-dup)
- ✅ 3 memory regression tests cover profile commands, store round-trip, and AI prompt injection
- ✅ **Total: 493 executable tests**
- ✅ **Mutation tests: 27/27 caught** (high code quality)

**Curated Files**:
- ✅ `curated_jokes.py` unchanged (hash: d10cee355fc1…)
- ✅ `curated_quotes_facts.py` unchanged (hash: 17f3292ec8c7…)
- ✅ `curated_games.py` unchanged (hash: 5320fe120a1c…)

**Coverage**:
- Content: ~23K entries across all categories (jokes, quotes, facts, trivia, games, etc.)
- Countries: 195 entries with capital, region, gdp_billions
- Elements: 118 with name, symbol, atomic_number
- Generated text: 16K+ jokes, 2.5K quotes, 200+ compliments, 2.3K fortunes, 1.5K WYR pairs

## What's NOT Yet Built

### Completed Deployment Requirements
- ✅ `bot/commands/` — auto-discovered command implementations, including `/personal` and `/update`
- ✅ `app.py` — Telegram polling entry point with media and text handlers
- ✅ `supabase/user_profiles.sql` — long-term memory table with row-level security enabled
- ✅ `supabase/bot_store_schema.sql` — defines the `profiles` and `notes` tables and the XP RPC used by the Store
- ✅ `supabase/profile_timezone.sql` — creates/upgrades the profile table fields, including timezone
- ✅ `supabase/saved_notes.sql` — creates the RLS-protected notes table (apply for durable `/save` notes)
- ✅ `requirements.txt` — runtime dependencies
- ✅ `render.yaml` — deployment config

### Optional Enhancements
- Production voice/audio transcription and text-to-speech providers
- Web dashboard (bot stats, user analytics)
- Advanced game logic (multiplayer, scoring, leaderboards)

## Next Steps

1. **Stage 4**: Implement computed generators (trivia from Stage 2, element facts, math facts).
2. **Stage 5**: Curated pass-through builder + Stage 1/2 test updates.
3. **Stage 6**: Strict per-kind validation; real run to `bot/data`; loader round-trip verification.
4. **Database**: Apply `supabase/user_profiles.sql` for durable user memory and `supabase/bot_store_schema.sql` for `profiles`, `notes`, timezone preferences, XP, and the corresponding service-role policies.
5. **Deployment**: Inject `TELEGRAM_TOKEN`, `AI_API_KEY`, and optional Supabase credentials as environment secrets.

---

**Status**: Content generation stages 1–3 complete; modular polling bot and profile memory implemented.
**Maintainer**: DanielMac (marklikyfc@gmail.com)

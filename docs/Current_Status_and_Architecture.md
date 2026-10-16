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
- AI system prompt auto-generated from command metadata.

#### 2. **AI Service** (`bot/ai.py`)
- **Intent Routing**: regex-based command dispatch.
- **Persona & Mode**: customize bot behavior per conversation.
- **Model Fallback Chain**: Groq (primary) → local fallback.
- **Retry & Jitter**: 3 retries, exponential backoff + random jitter.
- **History Trimming**: keep recent context under token limits.
- **Log Redaction**: mask sensitive data (API keys, user IDs).

#### 3. **Store Facade** (`bot/store.py`)
- **Supabase Backend**: PostgreSQL with RLS.
- **Circuit Breaker**: failover to in-memory cache on outage.
- **Caching Layer** (`bot/cache.py`): local in-memory with TTL.
- **Security**: RLS policies, prepared statements, least privilege.

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
- ✅ `formatting.py` — message formatting (markdown, code blocks, etc.).
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
- ✅ **Total: 490 tests passed**
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

### Critical Path (Blocking Bot Boot)
- ❌ `bot/commands/` — command implementations
- ❌ `app.py` — Flask/waitress entry point, Telegram webhook handler, reminders, XP flush
- ❌ `supabase/schema.sql` — database schema, RLS policies
- ❌ `requirements.txt` — frozen dependency list
- ❌ `render.yaml` — deployment config
- ❌ `.env.example` — environment template
- ❌ `README.md` — user-facing documentation

### Optional Enhancements
- Voice message handler (audio transcription + response)
- Web dashboard (bot stats, user analytics)
- Advanced game logic (multiplayer, scoring, leaderboards)

## Next Steps

1. **Stage 4**: Implement computed generators (trivia from Stage 2, element facts, math facts).
2. **Stage 5**: Curated pass-through builder + Stage 1/2 test updates.
3. **Stage 6**: Strict per-kind validation; real run to `bot/data`; loader round-trip verification.
4. **Bot Commands**: Implement command handlers in `bot/commands/`.
5. **App Entry**: Write `app.py` with Flask/waitress, Telegram webhook, job queue.
6. **Database**: Schema, RLS policies, migrations.
7. **Deployment**: `requirements.txt`, `render.yaml`, CI/CD.

---

**Status**: Content generation 50% complete (Stages 1–3 done; bot structure modular but not yet bootable).  
**Last Updated**: 2026-10-16  
**Maintainer**: DanielMac (marklikyfc@gmail.com)

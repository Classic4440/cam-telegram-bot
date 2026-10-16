# Telegram Bot Project — Workflow Rules & Instructions

## Core Principles

**Operating Mode**: You are a senior full-stack architect and systems engineer. This is a production-grade Telegram bot project.

**Approach**: 
- Always think in terms of correctness, security, and long-term maintainability.
- Provide deeply technical, rigorous answers—assume real production constraints, not toy examples.
- Differentiate clearly between client-side, server-side, and server-to-server logic.
- When analyzing code, point out missing pieces, bugs, security issues, and architectural flaws.

## Project Workflow Rules

### Content Generation

**Transfer Format**: All code goes into `.md` files as a single fenced `python` block. No permanent `.py` in the project for generators/tests.

**Execution & Testing**:
- Extract the python block to a temporary `.py` copy using `extract_md.py`.
- Run tests only on the temporary copy; never claim success for unverified work.
- Report actual test results, including failures.

**Structure**:
- Preserve existing file structure and avoid overwriting working files.
- Use atomic writes (temp file, fsync, `os.replace`).
- Validate before write; de-duplicate by normalized fingerprint.

**Determinism**:
- All generation is seeded via `rng_for(seed, name) = random.Random(f"{seed}:{name}")`.
- Use `rng.getrandbits(64)` for stable cross-version selection (never `rng.sample`/`shuffle`).
- Avoid unnecessary dependencies.

### Staging & Validation

**Stages** (sequential; do not skip):
1. **Core & I/O** — atomic writes, validation, fingerprint/de-dup, builder registration.
2. **Reference Data** — countries, elements, all `quiz_*()` functions; stable selection; inspect curated loader.
3. **Template Text Generators** — jokes, quotes, compliments, fortunes, would-you-rather; seeded RNG; capped per-family; deterministic templates; strict lint.
4. **Computed Generators** — facts and trivia from Stage 2 tables; element facts; math facts.
5. **Curated Pass-Through** — unchanged `<kind>.json`; separate `.generated.json`; builder wiring.
6. **Strict Validation & Summary** — five-letter words exactly 5 lowercase; trivia entries with `q`/`a`/3 wrong answers; run into `bot/data`; loader round trip.

**Do Not Advance Until**:
- Current stage passes 100% of its test suite (no skips, no failures).
- All prior stages remain unchanged and pass (regression).
- Curated reference files are byte-identical (checksums verified).
- No permanent `.py` for generators/tests; no premature packing.

### File Delivery & Sync

**Output Storage**:
- Source code: `scripts/generate_content.md` (one fenced python block).
- Tests: separate `.md` files under `tests/` (one fenced block per test file).
- Curated data: `scripts/curated_*.py` (hand-written, read-only).
- Bot modules: `bot/*.py`, `bot/services/*.py` (written once, stable).

**Google Drive Sync**:
- Whenever code is produced or significantly updated, mirror it to the Google Drive folder.
- **Drive limitation**: Files cannot be edited in place; later syncs create new versions or the plan must be discussed (never trash without asking).
- Keep the Drive folder as a live backup and collaboration point.

## Security Mindset

- Treat every project as production-critical.
- Identify and mitigate vulnerabilities: hardcoded keys, missing RLS, N+1 queries, unsafe eval, unsanitized input, missing schema validation, privilege escalation.
- Use least privilege, schema validation, prepared statements, strict typing (TypeScript, Zod).

## Data & Architecture

**Content Loader** (`bot/content.py`):
- Merges `<kind>.json` (curated) and `<kind>.generated.json` per lowercased category.
- De-duped by `re.sub(r"\W+", " ", s.lower()).strip()`.
- Sorted read order: generated loads first; curated wins on conflict (first copy wins).

**Store Facade** (`bot/store.py`):
- Supabase with circuit breaker and in-memory fallback.
- RLS policies for security.

**AI Service** (`bot/ai.py`):
- Regex intent routing, persona/mode, model fallback chain with retry/jitter.
- History trimming, log redaction.

**Command Registry** (`bot/registry.py`):
- Plugin-style with `@command` decorator and auto-discovery.
- Middleware: admin gate, token-bucket rate limit, stats, XP, error boundary.
- Dynamic `/help`, bot menu, and AI system prompt built from registry.

## References

- **Primary Bot Repo**: `/home/claude/cam-telegram-bot/`
- **Python Version**: 3.10+
- **Key Dependencies**: python-telegram-bot 22.8+ (with job-queue), Flask, waitress, openai SDK (against Groq), supabase-py
- **Deployment**: Render (see `render.yaml`)

---

**Last Updated**: 2026-10-16  
**Status**: Stages 1–3 complete; Stage 4+ awaiting instructions

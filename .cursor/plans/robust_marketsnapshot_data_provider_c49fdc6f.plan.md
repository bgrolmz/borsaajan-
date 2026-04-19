---
name: Robust MarketSnapshot data provider
overview: Introduce a typed MarketSnapshot provider with per-section caching + fallback and explicit availability/errors, then refactor QUICK/DEEP and /ai-insight so LLM output can’t degrade below deterministic QUICK and is rejected/fallbacked when required fields are missing.
todos:
  - id: add-market-snapshot-models
    content: Create `borsaajan_backend/market_snapshot.py` with MarketSnapshot + per-section availability/errors models and a `get_market_snapshot()` function.
    status: pending
  - id: add-sqlite-section-cache
    content: Add a small `market_snapshot_section_cache` table and get/set helpers in `borsaajan_backend/database.py`.
    status: pending
  - id: wire-quick-to-snapshot
    content: Refactor `get_canonical_quick_analysis()` to use MarketSnapshot and to include snapshot availability/errors in evidence when requested.
    status: pending
  - id: enforce-deep-quality-gates
    content: Add required-field validation for DEEP; on failure return QUICK + `deep_failed_reason` and log.
    status: pending
  - id: tighten-news-no-llm-in-quick
    content: Ensure `get_news(..., use_llm=0)` does not call any LLM helpers so QUICK stays deterministic.
    status: pending
  - id: ai-insight-non-degradation
    content: In `get_ai_insight()`, skip LLM and fall back to template if snapshot lacks required sections; pass snapshot availability into prompt when LLM runs.
    status: pending
---

# Robust MarketSnapshot provider + QUICK/DEEP quality gates

## What’s already in place (so we can keep changes minimal)

- Canonical endpoints exist: `/analysis/quick/{sembol}` and `/analysis/deep/{sembol}` in [`c:\Users\msi-nb\Desktop\Borsa_Projem\BorsaAjan_Backend\borsaajan_backend\main.py`](c:\Users\msi-nb\Desktop\Borsa_Projem\BorsaAjan_Backend\borsaajan_backend\main.py) calling helpers in `logic.py`.
- QUICK is already deterministic and DEEP is already a “narrative patch” merged with a divergence guard in [`logic.py`](c:\Users\msi-nb\Desktop\Borsa_Projem\BorsaAjan_Backend\borsaajan_backend\logic.py) and typed by [`canonical_decision.py`](c:\Users\msi-nb\Desktop\Borsa_Projem\BorsaAjan_Backend\borsaajan_backend\canonical_decision.py).

We’ll build on that by moving all market-data gathering into a single `MarketSnapshot` layer and ensuring QUICK/DEEP consume the same snapshot.

## Design: MarketSnapshot interface (backend)

Create a new module (minimal surface area) e.g.:

- [`...\borsaajan_backend\market_snapshot.py`](c:\Users\msi-nb\Desktop\Borsa_Projem\BorsaAjan_Backend\borsaajan_backend\market_snapshot.py)

### Types (Pydantic, strict-ish)

- `SnapshotSection = Literal["quote","ohlc","fundamentals","news"]`
- `SectionAvailability`: `{ available: bool, stale: bool = False }`
- `MarketSnapshotError`: `{ section, provider, error_type, message, timestamp }` (non-fatal)
- `MarketSnapshot` fields:
- `symbol`, `mode`, `analysis_as_of`
- **as_of stamps**: `quote_as_of`, `ohlc_as_of`, `fundamentals_as_of`, `news_as_of`
- **data_availability**: per-section `SectionAvailability`
- `errors: list[MarketSnapshotError]`
- payload sections used by downstream:
- `quote: dict | None` (current/active price, pre/post if available)
- `ohlc: list[dict] | None` (daily OHLCV bars, cached)
- `fundamentals: dict | None`
- `news: dict | None` (already normalized list of items)

## Caching + fallback strategy (hybrid: memory + SQLite)

### SQLite cache table (persistent)

Extend [`database.py`](c:\Users\msi-nb\Desktop\Borsa_Projem\BorsaAjan_Backend\borsaajan_backend\database.py) with a small “section cache” table:

- `market_snapshot_section_cache(symbol TEXT, mode TEXT, section TEXT, as_of TEXT, fetched_at TEXT, expires_at TEXT, payload_json TEXT, PRIMARY KEY(symbol,mode,section))`

Add helper functions:

- `get_snapshot_section_cache(symbol, mode, section) -> dict | None`
- `set_snapshot_section_cache(symbol, mode, section, as_of, expires_at, payload_dict)`

### In-memory TTL cache (fast)

In `market_snapshot.py`, keep a module-level dict keyed by `(symbol, mode, section)` with `{expires_at, payload}`.

### TTL policy

- Quote: 15–30 min (pick 20 min default; env override)
- News: 15–30 min (pick 20 min default; env override)
- OHLC: longer (e.g. 6–12h) because chart cache already self-heals via DB; we’ll treat DB bars as primary.
- Fundamentals: long (e.g. 24h)

### Provider chain (fallback)

Implement “primary -> secondary” per section:

- **OHLC**:
- Primary: `get_chart_data()` (already cache-first + remote backfill in `logic.py`)
- Secondary: if primary returns empty, use cached section (SQLite/memory) if available (even if stale, mark `stale=true`).
- **Quote**:
- Primary: derive from latest OHLC bar + (optional) extended hours via `services/finance_service.get_extended_hours_price`.
- Secondary: cached quote section.
- **Fundamentals**:
- Primary: existing `get_fundamental_data()`
- Secondary: cached fundamentals.
- **News**:
- Primary: `get_news(..., use_llm=0)` but **remove/disable the `gemini_text()` per-item comment** when `use_llm=0` so QUICK stays deterministic and LLM-free.
- Secondary: cached news.

**Rule**: never silently return empty defaults. If a section fails/empty, set availability `available=false`, keep payload `None` (or empty list), and append a `MarketSnapshotError`.

## Refactor QUICK to consume MarketSnapshot

Update [`logic.py`](c:\Users\msi-nb\Desktop\Borsa_Projem\BorsaAjan_Backend\borsaajan_backend\logic.py) `get_canonical_quick_analysis()`:

- Build one `snapshot = get_market_snapshot(symbol, mode, as_of)`
- Compute decision/action_plan deterministically from snapshot-derived technical/fundamental/news inputs.
- Populate freshness stamps from snapshot:
- Keep `as_of.analysis` as requested/now, but set `quote/fundamentals/news` from snapshot; optionally add `ohlc` if we extend the model.
- If `include_evidence=1`, include snapshot `data_availability` + `errors` inside `evidence` so UI can inspect.

## Refactor DEEP: enforce contract + quality gates

Update `get_canonical_deep_analysis()` in `logic.py`:

- Keep current flow: compute QUICK first, then attempt narrative patch.
- **Quality gate** before returning DEEP:
- Required non-empty: `decision`, `why_bullets`, `action_plan`, `glossary_terms`.
- If invalid: return QUICK JSON + `deep_failed_reason` (new optional field) and log `[deep_quality_gate_failed]`.
- Keep divergence guard; ensure we log `deep_divergence_blocked` when decision mismatch is forced back.

Update typing/schema:

- Extend [`canonical_decision.py`](c:\Users\msi-nb\Desktop\Borsa_Projem\BorsaAjan_Backend\borsaajan_backend\canonical_decision.py) `CanonicalDecisionResponse` with optional `deep_failed_reason: Optional[str]` (so we can return it without breaking validation).
- Update [`schemas.py`](c:\Users\msi-nb\Desktop\Borsa_Projem\BorsaAjan_Backend\borsaajan_backend\schemas.py) `CANONICAL_DECISION_SCHEMA` to allow `deep_failed_reason` (optional) and optionally add `ohlc` under `as_of` if we expose it.

## /ai-insight (LLM full) can’t degrade below QUICK

Update `get_ai_insight()` in `logic.py`:

- Always build `snapshot` once and reuse it.
- If `use_llm=1` but required snapshot sections are missing (at least quote+ohlc, and news if detail=full), **skip LLM** and fall back to template path (`use_llm=0`), adding a `data_quality_flags`/meta note like `llm_skipped_reason` (TODO if the exact field is unclear).
- If LLM is used, inject snapshot availability into the prompt and instruct model to acknowledge missing sections rather than invent numbers.

## Logging

- Use existing `print()` style for consistency, but make logs structured:
- `[snapshot] section=quote source=... cache_hit=... stale=...`
- `[snapshot_error] section=... provider=... type=...`
- `[deep_quality_gate_failed] reason=...`
- `deep_divergence_blocked`

## Minimal-change philosophy

- Keep existing decision engine and schemas where possible.
- Add TODO comments when we need to decide exact thresholds/fields.
# Borsa Ajanı — Session Work Log

## Session 1 ✅ (2025-05-09)

**Tasks:** Geçmiş Analizler debug + Haber TR çeviri

### #1 Geçmiş Analizler boş — Root cause: Silent exception + decision field bug

**Changes:**
- `main.py:2506` — `result.get("decision")` → `result.get("verdict")` (analyze_ticker döndürüyor)
- `main.py:2519` — print + traceback yerine → full logging
- `database.py:924` — `json.dumps(full_analysis_json, ensure_ascii=False, default=str)` (numpy type safety)

**Impact:** save_analysis failures artık visible, risk_level doğru hesaplanıyor

### #2 Haber TR çeviri — Hermes pipeline batch translate + persist

**Changes:**
- `database.py` — ALTER TABLE `news_analysis_history` ADD COLUMN `title_tr TEXT`
- `database.py` — SELECT queries `title_tr` ekle
- `database.py:_parse_news_row` — `title_tr` field return
- `news_pipeline.py:enrich_news_with_llm` — prompt schema `title_tr` alanı ekle
- `news_pipeline.py` — INSERT `title_tr` kolon + parametre
- `Home.razor:NewsItem` — `TitleTr` property + `DisplayTitle` computed
- `Home.razor:TranslateNewsItemsAsync` — TitleTr boş olanları çevir (DB'den persistent)
- `Home.razor:rendering` — Title → DisplayTitle (TR varsa TR, yoksa EN + fallback translate)

**Impact:** News titles now persist Turkish translation in DB, no re-translation on page refresh

## Session 2 ✅ (2025-05-10)

**Tasks:** Watchlist instant quotes + Portfolio real transactions UI

### #1 Watchlist anlık fiyat — Fast batch endpoint

**Problem:** `/api/watchlist/sync` slow — per-symbol `history(3mo)` loop (~20-30s per symbol)

**Solution:**
- New `GET /watchlist/quotes` — batch `yf.download(period="2d")` single HTTP call
- Mentor tag: `change% > 1.5%` → "Al Fırsatı", `< -1.5%` → "Dikkat", else → "İzle"
- `Watchlist.razor RefreshQuotes()` — POST → GET (same response format)

**Impact:** Watchlist refresh ~10x faster (2-3s vs 20-30s)

**Commits:**
- `a0a996d` feat(watchlist): fast batch quotes endpoint + wire frontend

### #2 Portfolio real transaction history

**Problem:** Real portföy transactions logged nowhere. Only paper trading had history.

**Solution:**
- `/portfolio/add` → use `add_portfolio_transaction("BUY")` instead of direct `add_to_portfolio`
- `/portfolio/delete` → log SELL at current market price via yfinance
- New `GET /portfolio/transactions` → query portfolio_transactions table (BUY/SELL history)
- `PaperTrading.razor` — "Geçmiş İşlemler" tab split into Gerçek/Simüle sub-tabs
  - Real: call `/portfolio/transactions`, render BUY/SELL table + summary cards
  - Paper: existing `/paper/trades` logic (unchanged)
  - Sub-tab toggle: `SwitchHistorySub()` loads lazy

**Impact:** Real portfolio now has auditable transaction log with timestamps, quantities, prices

**Commits:**
- `360a437` feat(portfolio): real transaction history + GET /portfolio/transactions

## Next: Session 3

1. TBD — check project_next_sessions.md
2. Escalate model (Sonnet 4.6 high effort tasks)

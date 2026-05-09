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

## Next: Session 2

1. **Watchlist anlık fiyat+değişim** — /watchlist/quotes endpoint, batch yfinance
2. **Portföy Gerçek+Simüle ayır** — new DB table real_portfolio, 2-tab refactor

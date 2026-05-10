import sys
import os
# NOTE: main.py does NOT need genai import - all LLM calls go through logic.py
# The logic.py module uses the new google-genai SDK with dynamic model discovery

print("=== BACKEND STARTUP (main.py) ===")
print("sys.executable:", sys.executable)
print("GOOGLE_API_KEY set?", bool(os.environ.get("GOOGLE_API_KEY")))
print("Using google-genai SDK via logic.py (not deprecated google.generativeai)")
print("=========================")

from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware # <-- YENİ EKLENDİ
from pydantic import BaseModel
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from .logic import generate_ai_report, get_market_data_fast, get_ai_insight, create_chart, analyze_portfolio, backtest_lite, whale_watch, chat_with_mentor, gemini_text, FALLBACK_AI_MESSAGE, get_canonical_quick_analysis, get_canonical_deep_analysis, get_mentor_news, analyze_news_with_gemini
from .database import add_test_data, add_to_portfolio, remove_from_portfolio, get_portfolio, get_all_history, get_notifications, init_db, get_user_profile, update_user_profile, get_portfolio_analysis_history, get_db_path, get_monthly_llm_usage, get_connection, get_connection, get_watched_symbols, add_watched_symbol, remove_watched_symbol, get_news_history, get_all_news_history, get_similar_news_outcomes, save_price_snapshot, get_pending_snapshots, mark_snapshot_done, save_news_outcome
from .chat_helpers import should_use_llm, llm_explain

# region agent log
_AGENT_DEBUG_LOG_PATH = r"c:\Users\msi-nb\Desktop\Borsa_Projem\.cursor\debug.log"
def _agent_log(location: str, message: str, data: dict, hypothesisId: str, runId: str = "pre") -> None:
    try:
        import json, time
        import os as _os
        _os.makedirs(_os.path.dirname(_AGENT_DEBUG_LOG_PATH), exist_ok=True)
        payload = {
            "sessionId": "debug-session",
            "runId": runId,
            "hypothesisId": hypothesisId,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(_AGENT_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # never throw from debug logging
        return
# endregion


def _mentor_risk_note(decision: str) -> str:
    d = (decision or "HOLD").upper()
    if d == "BUY":
        return "Risk: Trend tersine dönerse zarar büyüyebilir; kademeli ilerle ve net bir stop planı kullan."
    if d == "REDUCE":
        return "Risk: Düşüş uzayabilir; azaltmayı geciktirmek konsantrasyon riskini artırır."
    if d == "AVOID":
        return "Risk: Belirsizlikte yanlış giriş hızlı kayıpla sonuçlanabilir; veri netleşene kadar kenarda kal."
    return "Risk: Veri/sinyaller karışık olabilir; netleşene kadar küçük adımlarla ilerle ve yeniden değerlendir."


def _mentor_text_from_canonical(c: dict) -> str:
    """
    Builds a mentor-style readable text from canonical decision fields.
    No emojis, no hype.
    """
    decision = (c.get("decision") or "HOLD").upper()
    confidence = c.get("confidence")
    horizon_days = c.get("horizon_days")
    why = c.get("why_bullets") or []
    plan = c.get("action_plan") or []
    scenario = c.get("mentor_scenario") or ""
    risk_note = c.get("risk_note") or ""

    lines = []
    lines.append(f"Decision: {decision} (confidence: {confidence}/100, horizon: {horizon_days}d)")
    if why:
        lines.append("Why:")
        for w in why[:3]:
            if isinstance(w, str) and w.strip():
                lines.append(f"- {w.strip()}")
    if plan:
        lines.append("Action plan:")
        for item in plan[:4]:
            if not isinstance(item, dict):
                continue
            t = (item.get("type") or "").strip()
            r = (item.get("rationale_short") or "").strip()
            if t or r:
                lines.append(f"- {t}: {r}".strip())
    if scenario and isinstance(scenario, str) and scenario.strip():
        lines.append(f"Mentor scenario: {scenario.strip()}")
    if risk_note and isinstance(risk_note, str) and risk_note.strip():
        lines.append(f"Risk note: {risk_note.strip()}")
    return "\n".join(lines).strip()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # Startup: Initialize database
    try:
        # Get DB path first (will log if needed)
        db_path = get_db_path()
        # Log DB path at startup (single source of truth)
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[DB] Using DB: {db_path}")
        print(f"INFO [DB] Using DB: {db_path}")
        
        # Initialize database tables
        init_db()
        # Initialize paper trading tables
        from .paper_trading import init_paper_trading_tables
        init_paper_trading_tables()
        
        # Run integrity check
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchone()
            integrity_ok = integrity_result and integrity_result[0] == "ok"
            conn.close()
            
            if integrity_ok:
                logger.info("[DB] Integrity check: OK")
                print("✅ [DB] Integrity check: OK")
            else:
                logger.warning(f"[DB] Integrity check: {integrity_result}")
                print(f"⚠️ [DB] Integrity check: {integrity_result}")
        except Exception as integrity_err:
            logger.warning(f"[DB] Integrity check failed: {integrity_err}")
            print(f"⚠️ [DB] Integrity check failed: {integrity_err}")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"[DB] Failed to initialize database: {e}", exc_info=True)
        print(f"❌ [DB] Failed to initialize database: {e}")
        raise
    
    yield
    
    # Shutdown: cleanup if needed
    pass

app = FastAPI(lifespan=lifespan)

# Initialize scheduler (REQUIRED for notifications)
# Use a global flag to prevent duplicate initialization (e.g., in reload/dev mode)
_scheduler_initialized = False
scheduler = None

def initialize_scheduler():
    """Initialize scheduler with all jobs. Safe to call multiple times (idempotent)."""
    global scheduler, _scheduler_initialized
    
    if _scheduler_initialized:
        print("⚠️ Scheduler already initialized, skipping...")
        return scheduler
    
    try:
        # Import required modules
        import sys
        import os
        # Ensure current directory is in path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        
        # Try importing apscheduler first
        import apscheduler
        print(f"✅ apscheduler version: {apscheduler.__version__}")
        
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
        import pytz
        print("✅ apscheduler modules imported successfully")
        
        # Get timezone from ENV or default
        tz_str = os.getenv("TZ", "Europe/Istanbul")
        tz = pytz.timezone(tz_str)
        
        # Initialize scheduler (only if not already running)
        if scheduler is None or not scheduler.running:
            scheduler = BackgroundScheduler(timezone=tz)
            scheduler.start()
            print(f"✅ Scheduler initialized with {tz_str} timezone")
        else:
            print("⚠️ Scheduler already running")
        
        # Import alert system functions
        from .services.alert_system import send_market_summary, check_critical_news
        print("✅ Alert system functions imported successfully")
        
        # GeminiBorsaBot (eski bot) DEVRE DIŞI — spam yapıyor (150+ mesaj/gün)
        # send_market_summary ve check_critical_news artık çalışmıyor.
        # Yeni bot (Hermes / news_pipeline) bu görevleri üstlendi.
        print("⏭️  GeminiBorsaBot jobları devre dışı (send_market_summary, check_critical_news)")
        
        # Schedule QUICK portfolio analysis (configurable times)
        quick_times_str = os.getenv("QUICK_SCHEDULE_TIMES", "09:00,21:00")
        quick_times = [t.strip() for t in quick_times_str.split(",")]
        
        def run_quick_portfolio_analysis():
            """Run QUICK portfolio analysis job."""
            try:
                from .database import get_portfolio
                from .logic import analyze_portfolio
                from datetime import datetime
                
                portfolio = get_portfolio()
                if not portfolio:
                    print("[SCHEDULED] Portfolio is empty, skipping analysis")
                    return
                
                print(f"[SCHEDULED] Running QUICK portfolio analysis at {datetime.now()}")
                result = analyze_portfolio(portfolio, use_llm=False, force=False, detail_level="detailed")
                
                if result.get("success"):
                    analysis_id = result.get("meta", {}).get("analysis_id")
                    print(f"[SCHEDULED] QUICK analysis completed successfully (analysis_id={analysis_id})")
                else:
                    print(f"[SCHEDULED] QUICK analysis failed: {result.get('message', 'Unknown error')}")
            except Exception as e:
                import traceback
                print(f"[SCHEDULED] Error in QUICK portfolio analysis: {e}")
                traceback.print_exc()
        
        for i, time_str in enumerate(quick_times):
            try:
                hour, minute = map(int, time_str.split(":"))
                scheduler.add_job(
                    run_quick_portfolio_analysis,
                    trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
                    id=f'quick_portfolio_analysis_{i}',
                    replace_existing=True
                )
                print(f"✅ QUICK portfolio analysis scheduled at {time_str}")
            except Exception as e:
                print(f"⚠️ Failed to schedule QUICK analysis at {time_str}: {e}")
        
        # Schedule daily backup job
        def run_daily_backup():
            """Run daily backup job."""
            try:
                from .database import get_db_path
                from datetime import datetime
                import shutil
                import os
                
                db_path = get_db_path()
                if not db_path.exists():
                    print("[BACKUP] Database file not found, skipping backup")
                    return
                
                # Create backups directory
                backups_dir = db_path.parent / "backups"
                backups_dir.mkdir(exist_ok=True)
                
                # Create backup filename
                backup_filename = f"borsa_{datetime.now().strftime('%Y%m%d')}.db"
                backup_path = backups_dir / backup_filename
                
                # Copy database file
                shutil.copy2(db_path, backup_path)
                print(f"[BACKUP] Backup created: {backup_path}")
                
                # Clean old backups (keep last N days)
                keep_days = int(os.getenv("BACKUP_KEEP_DAYS", "14"))
                cutoff_date = datetime.now().date() - timedelta(days=keep_days)
                
                for backup_file in backups_dir.glob("borsa_*.db"):
                    try:
                        # Extract date from filename
                        date_str = backup_file.stem.split("_")[1]
                        file_date = datetime.strptime(date_str, "%Y%m%d").date()
                        
                        if file_date < cutoff_date:
                            backup_file.unlink()
                            print(f"[BACKUP] Deleted old backup: {backup_file.name}")
                    except Exception as e:
                        print(f"[BACKUP] Error processing {backup_file.name}: {e}")
                        
            except Exception as e:
                import traceback
                print(f"[BACKUP] Error in daily backup: {e}")
                traceback.print_exc()
        
        scheduler.add_job(
            run_daily_backup,
            trigger=CronTrigger(hour=2, minute=0, timezone=tz),  # 2 AM daily
            id='daily_backup',
            replace_existing=True
        )
        print("✅ Daily backup scheduled at 02:00")
        
        # Schedule outcome backfill job (once per day)
        def run_outcome_backfill():
            """Run outcome backfill job."""
            try:
                from .database import get_analyses_without_outcomes, save_portfolio_outcome, get_portfolio
                from datetime import datetime, timedelta
                import yfinance as yf
                
                print(f"[BACKFILL] Starting outcome backfill at {datetime.now()}")
                
                for horizon in [1, 3, 7]:
                    analyses = get_analyses_without_outcomes(horizon=horizon, limit=50)
                    if not analyses:
                        continue
                    
                    print(f"[BACKFILL] Processing {len(analyses)} analyses for {horizon}-day horizon")
                    
                    portfolio = get_portfolio()
                    if not portfolio:
                        continue
                    
                    processed = 0
                    for analysis in analyses:
                        try:
                            analysis_id = analysis["id"]
                            as_of_str = analysis.get("as_of", "")
                            full_json = analysis.get("full_json", {})
                            
                            # Parse as_of date
                            try:
                                as_of_date = datetime.fromisoformat(as_of_str.replace("Z", "+00:00")).date()
                            except:
                                try:
                                    as_of_date = datetime.strptime(as_of_str.split("T")[0], "%Y-%m-%d").date()
                                except:
                                    continue
                            
                            target_date = as_of_date + timedelta(days=horizon)
                            
                            holdings = full_json.get("holdings", [])
                            if not holdings:
                                continue
                            
                            value_as_of = 0
                            value_target = 0
                            
                            for holding in holdings:
                                symbol = holding.get("symbol", "")
                                quantity = holding.get("quantity", 0)
                                
                                if not symbol or quantity <= 0:
                                    continue
                                
                                try:
                                    ticker = yf.Ticker(symbol)
                                    hist_as_of = ticker.history(start=as_of_date, end=as_of_date + timedelta(days=1))
                                    if not hist_as_of.empty:
                                        price_as_of = hist_as_of['Close'].iloc[0]
                                        value_as_of += price_as_of * quantity
                                    
                                    hist_target = ticker.history(start=target_date, end=target_date + timedelta(days=1))
                                    if not hist_target.empty:
                                        price_target = hist_target['Close'].iloc[0]
                                        value_target += price_target * quantity
                                    else:
                                        hist_latest = ticker.history(period="1d")
                                        if not hist_latest.empty:
                                            price_target = hist_latest['Close'].iloc[-1]
                                            value_target += price_target * quantity
                                        else:
                                            value_target += price_as_of * quantity
                                except:
                                    continue
                            
                            if value_as_of == 0:
                                continue
                            
                            return_usd = value_target - value_as_of
                            return_pct = ((value_target - value_as_of) / value_as_of) * 100 if value_as_of > 0 else 0
                            
                            save_portfolio_outcome(analysis_id, horizon, return_pct, return_usd)
                            processed += 1
                        except Exception as e:
                            print(f"[BACKFILL] Error processing analysis {analysis.get('id')}: {e}")
                    
                    print(f"[BACKFILL] Processed {processed} analyses for {horizon}-day horizon")
                
                print(f"[BACKFILL] Outcome backfill completed")
            except Exception as e:
                import traceback
                print(f"[BACKFILL] Error in outcome backfill: {e}")
                traceback.print_exc()
        
        scheduler.add_job(
            run_outcome_backfill,
            trigger=CronTrigger(hour=3, minute=0, timezone=tz),  # 3 AM daily
            id='outcome_backfill',
            replace_existing=True
        )
        print("✅ Outcome backfill scheduled at 03:00")
        
        # Schedule Hermes news processing (every 30 minutes)
        def run_hermes_news_processing():
            """Run Hermes intelligent news processing for watched symbols."""
            try:
                from .news_pipeline import process_news_pipeline
                from datetime import datetime
                
                print(f"[HERMES SCHEDULED] Running news processing at {datetime.now()}")
                result = process_news_pipeline(
                    mode="DEEP",  # Always use DEEP for impact analysis
                    confidence_threshold=50,
                    llm_threshold=60,
                    use_watchlist=True  # Only process watched symbols
                )
                
                print(f"[HERMES SCHEDULED] Processed {len(result)} news items")
                if result:
                    print(f"[HERMES SCHEDULED] Sample symbols: {[item.get('symbol') for item in result[:3]]}")
            except Exception as e:
                import traceback
                print(f"[HERMES SCHEDULED] Error in news processing: {e}")
                traceback.print_exc()
        
        scheduler.add_job(
            run_hermes_news_processing,
            trigger=IntervalTrigger(minutes=30),
            id='hermes_news_processing',
            replace_existing=True
        )
        print("✅ Hermes news processing scheduled every 30 minutes")

        def run_news_outcome_checker():
            try:
                import yfinance as yf
                from datetime import datetime, timezone, timedelta
                from .database import get_pending_snapshots, mark_snapshot_done, save_news_outcome

                pending = get_pending_snapshots(older_than_minutes=120)
                if not pending:
                    return

                print(f"[outcome_checker] {len(pending)} bekleyen snapshot işlenecek")

                CRYPTO_SUFFIXES = ("-USD", "-USDT")

                for snap in pending:
                    snap_id    = snap["id"]
                    sym        = snap["symbol"]
                    price_then = snap["price_at_news"]
                    news_hash  = snap["news_hash"]

                    try:
                        is_crypto = any(sym.endswith(s) for s in CRYPTO_SUFFIXES) or sym in ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "DOT")
                        ticker_sym = sym if "-" in sym else (f"{sym}-USD" if is_crypto else sym)

                        ticker = yf.Ticker(ticker_sym)
                        hist = ticker.history(period="1d", interval="5m")
                        if hist.empty:
                            hist = ticker.history(period="5d")
                        if hist.empty:
                            print(f"⚠️ [outcome_checker] {sym} için fiyat verisi alınamadı, snapshot ertelendi")
                            continue

                        price_now   = float(hist["Close"].iloc[-1])
                        if price_then <= 0:
                            mark_snapshot_done(snap_id)
                            continue
                        change_pct  = ((price_now - price_then) / price_then) * 100
                        actual_impact = "POSITIVE" if change_pct >= 0.5 else "NEGATIVE" if change_pct <= -0.5 else "NEUTRAL"

                        save_news_outcome(sym, news_hash, actual_impact, change_pct)
                        mark_snapshot_done(snap_id)

                        print(f"✅ [outcome_checker] {sym} | {price_then:.2f}→{price_now:.2f} | {change_pct:+.2f}% | {actual_impact}")
                    except Exception as e:
                        print(f"⚠️ [outcome_checker] {sym} işlenemedi: {e}")

            except Exception as e:
                import traceback
                print(f"❌ [outcome_checker] Hata: {e}")
                traceback.print_exc()

        scheduler.add_job(
            run_news_outcome_checker,
            trigger=IntervalTrigger(minutes=10),
            id='news_outcome_checker',
            replace_existing=True
        )
        print("✅ News outcome checker scheduled every 10 minutes")

        # Self-improving AI: compute symbol-level prediction outcomes every 6 hours
        def run_symbol_outcome_checker():
            try:
                from .logic import compute_pending_outcomes
                compute_pending_outcomes()
            except Exception as e:
                import traceback
                print(f"[OUTCOMES] Error: {e}")
                traceback.print_exc()

        scheduler.add_job(
            run_symbol_outcome_checker,
            trigger=IntervalTrigger(hours=6),
            id='symbol_outcome_checker',
            replace_existing=True
        )
        print("✅ Symbol outcome checker scheduled every 6 hours")

        _scheduler_initialized = True
        print("✅ All scheduled jobs registered successfully")
    
    except ImportError as e:
        print(f"❌ ERROR: Scheduler not available - {e}")
        print(f"   Missing module: {str(e)}")
        print("   Please manually run:")
        print(f"   {sys.executable} -m pip install apscheduler requests pytz")
        print("   Then restart the server.")
    except Exception as e:
        import traceback
        print(f"❌ ERROR: Failed to initialize scheduler: {e}")
        print(f"   Error type: {type(e).__name__}")
        print(f"   Traceback:")
        traceback.print_exc()
        print("   ⚠️  Notifications will not be scheduled automatically.")
        print("   ⚠️  Backend will continue to work, but scheduled notifications are disabled.")

# Call scheduler initialization
try:
    initialize_scheduler()
except Exception as e:
    print(f"⚠️ Scheduler initialization failed: {e}")

# Database initialization will happen in startup event

# --- GÜVENLİK İZNİ (CORS) ---
# Bu ayar sayesinde C# uygulaması Python'a bağlanabilir.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Tüm kaynaklara izin ver (Geliştirme için)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"Durum": "Borsa Ajanı Beyni Aktif", "Versiyon": "4.0 Self-Learning Engine"}

@app.get("/analiz/{sembol}")
def analiz_yap(sembol: str, maliyet: float = None, adet: float = 1, mode: str = "STOCK"):
    """Legacy endpoint: Returns full analysis (market data + AI). Kept for backward compatibility."""
    print(f"İstek Geldi: {sembol} - Mode: {mode}") # Terminalde görmek için log
    sonuc = generate_ai_report(sembol.upper(), maliyet, adet, mode.upper())
    return sonuc

@app.get("/market-data/{sembol}")
def market_data(sembol: str, mode: str = "STOCK"):
    """
    Fast endpoint: Returns ONLY price, chart, and technical indicators.
    Should complete in under 1 second (no AI).
    """
    print(f"⚡ Fast Market Data Request: {sembol} - Mode: {mode}")
    try:
        sonuc = get_market_data_fast(sembol.upper(), mode.upper())
        
        # Add mentor news cards for this symbol (filtered)
        try:
            all_mentor_cards = get_mentor_news(mode="QUICK", confidence_threshold=50)
            symbol_cards = [card for card in all_mentor_cards if card.get("symbol", "").upper() == sembol.upper()]
            if symbol_cards:
                sonuc["mentor_news_cards"] = symbol_cards
        except Exception as e:
            print(f"⚠️ Error adding mentor news cards: {e}")
            # Don't fail the request if mentor news fails
        
        return sonuc
    except Exception as e:
        print(f"❌ Error in /market-data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/mentor/news")
def get_mentor_news_endpoint(mode: str = "QUICK", confidence_threshold: int = 50, llm_threshold: int = 60):
    """
    Get mentor-interpreted news for all relevant symbols.
    Returns only MentorNewsCard objects (no raw news).
    
    Pipeline: symbol selection → fetch → normalize → dedupe → score → enrich → notify → store
    
    Args:
        mode: "QUICK" (local scoring only) or "DEEP" (LLM enrichment above threshold)
        confidence_threshold: Minimum confidence for inclusion (0-100, default: 50)
        llm_threshold: Minimum local score to trigger LLM enrichment (0-100, default: 60, only for DEEP mode)
    
    Returns:
        dict with mentor_news_cards array and metadata
    """
    print(f"📰 Mentor News Request: mode={mode}, confidence_threshold={confidence_threshold}, llm_threshold={llm_threshold}")
    try:
        cards = get_mentor_news(mode=mode, confidence_threshold=confidence_threshold, llm_threshold=llm_threshold)
        return {
            "mentor_news_cards": cards,
            "count": len(cards),
            "mode": mode,
            "confidence_threshold": confidence_threshold,
            "llm_threshold": llm_threshold if mode.upper() == "DEEP" else None
        }
    except Exception as e:
        print(f"❌ Error in /mentor/news: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class MentorChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    text: str

class MentorChatRequest(BaseModel):
    user_message: str
    context_data: dict = {}
    history: List[MentorChatMessage] = []

@app.post("/mentor/chat")
def mentor_chat(request: MentorChatRequest):
    """Chat with Mentor AI as senior portfolio manager. Multi-turn, rich context."""
    try:
        from .logic import _get_genai_client
        from google.genai import types as _genai_types
        import time as _time

        client = _get_genai_client()
        if client is None:
            return {"success": False, "reply": "API anahtarı eksik."}

        ctx = request.context_data or {}
        ctx_lines = []
        if ctx.get("symbol"):
            ctx_lines.append(f"- Sembol: {ctx['symbol']}")
        if ctx.get("name"):
            ctx_lines.append(f"- Şirket: {ctx['name']} ({ctx.get('sector','')})")
        if ctx.get("price") is not None:
            ctx_lines.append(f"- Fiyat: ${ctx['price']:.2f} ({ctx.get('change_pct',0):+.2f}%)")
        if ctx.get("decision"):
            ctx_lines.append(f"- Sistem Kararı: {ctx['decision']} (güven: {ctx.get('confidence','—')})")
        if ctx.get("ev") is not None:
            ctx_lines.append(f"- EV (Beklenen Değer): ${ctx['ev']:.2f} (ROI %{ctx.get('roi_pct',0):.1f})")
        if ctx.get("kelly_pct") is not None:
            ctx_lines.append(f"- Kelly çeyrek: %{ctx['kelly_pct']:.1f} → {ctx.get('kelly_shares','?')} hisse / ${ctx.get('kelly_dollar','?')}")
        if ctx.get("bayes_posterior") is not None:
            ctx_lines.append(f"- Bayes posterior: %{ctx['bayes_posterior']} (önsel %{ctx.get('bayes_prior','?')})")
        if ctx.get("entry") is not None:
            ctx_lines.append(f"- Hedef plan: Giriş ${ctx['entry']:.2f} / Hedef ${ctx.get('target',0):.2f} / Stop ${ctx.get('stop',0):.2f}")
        if ctx.get("rsi") is not None:
            ctx_lines.append(f"- RSI: {ctx['rsi']:.1f}")
        if ctx.get("pe_ratio") is not None:
            ctx_lines.append(f"- F/K: {ctx['pe_ratio']:.1f}")
        if ctx.get("analyst_target") is not None:
            ctx_lines.append(f"- Analist hedef: ${ctx['analyst_target']:.2f} ({ctx.get('analyst_count','?')} analist)")
        if ctx.get("news"):
            news_lines = []
            for i, n in enumerate(ctx["news"][:5], 1):
                if isinstance(n, dict):
                    sent = n.get("sentiment", "nötr")
                    summary = n.get("summary_tr") or n.get("title", "")
                    news_lines.append(f"  {i}. [{sent}] {summary[:160]}")
                elif isinstance(n, str):
                    news_lines.append(f"  {i}. {n[:160]}")
            if news_lines:
                ctx_lines.append("- Son haberler:\n" + "\n".join(news_lines))
        if ctx.get("bull_thesis"):
            ctx_lines.append(f"- Boğa tezi: {' | '.join(ctx['bull_thesis'][:3])}")
        if ctx.get("bear_thesis"):
            ctx_lines.append(f"- Ayı tezi: {' | '.join(ctx['bear_thesis'][:3])}")

        ctx_str = "\n".join(ctx_lines) if ctx_lines else "(analiz verisi henüz yok)"

        system_prompt = (
            "Sen 20 yıllık deneyimli bir KIDEMLİ PORTFÖY YÖNETİCİSİSİN. "
            "Müşterinle konuşuyorsun — bir broker, danışman gibi konuş.\n\n"
            "KURALLAR:\n"
            "1. NET POZISYON AL. 'Birçok faktör vardır', 'değerlendirilmesi önemlidir' tarzı boş laf YASAK.\n"
            "2. 'AL' / 'TUT' / 'SAT' / 'BEKLE' gibi NET tavsiye ver. Neden? Çünkü müşteri karar bekliyor.\n"
            "3. Sayılarla konuş: fiyat seviyesi, stop, hedef, pozisyon büyüklüğü.\n"
            "4. Piyasa kapalıysa AÇILIŞTA NE YAPMASI GEREKTİĞİNİ söyle — 'analiz edemem' deme. Mevcut data + son haberlerle senaryo kur.\n"
            "5. 'Yatırım tavsiyesi değildir' / 'Profesyonel danışman ile görüş' tarzı sigortalanma cümleleri YASAK. Sen zaten profesyonelsin.\n"
            "6. Maksimum 5-6 cümle. Madde madde gerekiyorsa 3 madde yeterli.\n"
            "7. Bağlamdaki sayılara (EV, Kelly, Bayes, haber) referans ver — sistemin verdiği datayı kullanmazsan değersizsin.\n"
            "8. Müşterinin önceki sorularını HATIRLA — konuşmayı sürdür, baştan başlama.\n"
        )

        contents_list = [system_prompt + "\n\n=== ANALİZ BAĞLAMI ===\n" + ctx_str + "\n=== /BAĞLAM ===\n"]
        for msg in (request.history or [])[-8:]:
            role_tag = "MÜŞTERİ" if msg.role == "user" else "MENTOR"
            contents_list.append(f"\n{role_tag}: {msg.text}")
        contents_list.append(f"\nMÜŞTERİ: {request.user_message}\nMENTOR:")

        prompt = "".join(contents_list)

        config = _genai_types.GenerateContentConfig(
            temperature=0.85,
            max_output_tokens=1024,
        )

        reply = ""
        last_err = None
        for model in ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]:
            for attempt in range(2):
                try:
                    resp = client.models.generate_content(model=model, contents=prompt, config=config)
                    if resp and resp.text:
                        reply = resp.text.strip()
                        print(f"[mentor/chat] OK via {model} (attempt {attempt+1}), len={len(reply)}")
                        break
                except Exception as e:
                    last_err = e
                    err_str = str(e)
                    print(f"[mentor/chat] {model} attempt {attempt+1} failed: {type(e).__name__}: {err_str[:200]}")
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str.upper():
                        _time.sleep(2)
                        continue
                    break
            if reply:
                break

        if not reply:
            reply = (
                "Şu an Gemini API rate limit'e takıldım (429). 30-60 saniye bekle ve tekrar dene. "
                "Bu süre zarfında: analiz kartlarındaki EV, Kelly ve Bayes verilerine bakarak ön karar verebilirsin."
            )

        return {"success": True, "reply": reply}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/ai-insight/{sembol}")
def ai_insight(sembol: str, maliyet: float = None, adet: float = 1, mode: str = "STOCK", use_llm: int = 1, detail: str = "medium"):
    """
    Slow endpoint: Returns ONLY AI analysis and strategy.
    
    **DEEP MODE ENFORCED**: Always uses LLM for institutional-grade analysis.
    
    Args:
        sembol: Stock/crypto symbol
        maliyet: Optional cost basis
        adet: Optional quantity
        mode: "STOCK" or "CRYPTO"
        use_llm: FORCED TO 1 (always use LLM - deep mode enforced in get_ai_insight)
        detail: "short" | "medium" | "full" (default: "medium")
    
    Returns:
        dict: Deep analysis result with hedge fund-grade insights
    """
    # FORCE DEEP MODE: Override to always use LLM (redundant since get_ai_insight also forces it, but explicit is better)
    use_llm = 1
    
    # Validate detail parameter
    detail_lower = detail.lower()
    if detail_lower not in ["short", "medium", "full"]:
        detail_lower = "medium"
    
    print(f"🔥 [DEEP MODE] AI Insight Request: {sembol} - Mode: {mode}, LLM: FORCED, detail: {detail_lower}")
    try:
        sonuc = get_ai_insight(sembol.upper(), maliyet, adet, mode.upper(), use_llm=1, detail=detail_lower)
        return sonuc
    except Exception as e:
        print(f"❌ Error in /ai-insight: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CANONICAL DECISION ENDPOINTS (QUICK + DEEP)
# QUICK: deterministic decision engine
# DEEP: narrative layer wrapping QUICK, guarded against divergence
# ============================================================================

@app.get("/analysis/quick/{sembol}")
def analysis_quick(
    sembol: str,
    maliyet: float = None,
    adet: float = 1,
    mode: str = "STOCK",
    as_of: str = None,
    evidence: int = 0,
):
    """
    QUICK canonical decision JSON (deterministic; no LLM).
    """
    try:
        return get_canonical_quick_analysis(
            symbol=sembol.upper(),
            cost=maliyet,
            qty=adet,
            mode=mode.upper(),
            as_of=as_of,
            include_evidence=bool(evidence),
        )
    except Exception as e:
        print(f"❌ Error in /analysis/quick: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analysis/deep/{sembol}")
def analysis_deep(
    sembol: str,
    maliyet: float = None,
    adet: float = 1,
    mode: str = "STOCK",
    as_of: str = None,
    force: int = 0,
    evidence: int = 0,
):
    """
    DEEP canonical decision JSON:
    - Computes QUICK for the same as_of timestamp (or uses cached DEEP by hash key)
    - Uses LLM only for wording + mentor_scenario
    - Enforces divergence guard + optional override contract
    """
    try:
        return get_canonical_deep_analysis(
            symbol=sembol.upper(),
            cost=maliyet,
            qty=adet,
            mode=mode.upper(),
            as_of=as_of,
            force=bool(force),
            include_evidence=bool(evidence),
        )
    except Exception as e:
        print(f"❌ Error in /analysis/deep: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ========== PORTFOLIO MANAGEMENT ENDPOINTS ==========

class PortfolioItem(BaseModel):
    symbol: str
    avg_cost: float
    quantity: float

@app.post("/portfolio/add")
def portfolio_add(item: PortfolioItem):
    """Add or update a stock in the portfolio."""
    try:
        result = add_to_portfolio(item.symbol, item.avg_cost, item.quantity)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/portfolio/delete/{symbol}")
def portfolio_delete(symbol: str, quantity: float = None):
    """Remove a stock from portfolio (partial or full)."""
    try:
        result = remove_from_portfolio(symbol, quantity)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("message"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/portfolio/list")
def portfolio_list():
    """Get all stocks in the portfolio."""
    try:
        portfolio = get_portfolio()
        return {
            "success": True,
            "portfolio": portfolio,
            "count": len(portfolio)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/portfolio/values")
def portfolio_values():
    """Real portfolio with live prices, PnL, and weights."""
    try:
        from .paper_trading import get_current_price
        portfolio = get_portfolio()
        items = []
        total_cost = 0.0
        total_value = 0.0
        for p in portfolio:
            sym = p.get("symbol", "")
            qty = float(p.get("quantity") or 0)
            avg = float(p.get("avg_cost") or 0)
            price = get_current_price(sym) or avg
            cost = qty * avg
            value = qty * price
            pnl = value - cost
            pnl_pct = (pnl / cost * 100.0) if cost > 0 else 0.0
            total_cost += cost
            total_value += value
            items.append({
                "symbol": sym,
                "quantity": qty,
                "avg_cost": round(avg, 4),
                "current_price": round(price, 4),
                "cost": round(cost, 2),
                "value": round(value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "weight_pct": 0.0,
                "updated_at": p.get("updated_at"),
            })
        for it in items:
            it["weight_pct"] = round((it["value"] / total_value * 100.0) if total_value > 0 else 0.0, 2)
        total_pnl = total_value - total_cost
        return {
            "success": True,
            "items": items,
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round((total_pnl / total_cost * 100.0) if total_cost > 0 else 0.0, 2),
            "count": len(items),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/portfolio/analyze")
def portfolio_analyze(mode: str = "quick", force_deep: int = 0, detail: str = "detailed"):
    """
    Get portfolio analysis (Quick or Deep mode).
    
    Args:
        mode: "quick" = Quick mode (no LLM, deterministic), "deep" = Deep mode (single LLM call, daily cache)
        force_deep: 0 = Use cache if available, 1 = Force new LLM call (ignore cache) - only applies if mode=deep
        detail: "basic" = Basic output, "detailed" = Enhanced output with scenarios (only for quick mode)
    
    Returns:
        dict: Portfolio analysis result with stable contract:
        {
            "success": true,
            "mode": "quick"|"deep",
            "detail_level": "basic"|"detailed",
            "as_of": "...",
            "portfolio": {...},
            "holdings": [...],
            "risk": {...},
            "news": [...],
            "action_bullets_tr": [...],
            "deep_summary_tr": "..." (optional),
            "scenarios": [...] (optional, detailed quick mode only),
            "position_risk_rows": [...] (optional, detailed quick mode only),
            "meta": {"llm_used": 0|1, "cache_hit": 0|1, "force": 0|1}
        }
    """
    try:
        portfolio = get_portfolio()
        if not portfolio:
            return {
                "success": False,
                "message": "Portfolio is empty. Add stocks first."
            }
        
        # Normalize mode parameter
        mode_lower = mode.lower()
        if mode_lower not in ["quick", "deep"]:
            mode_lower = "quick"
        
        # Normalize detail parameter
        detail_lower = detail.lower()
        if detail_lower not in ["basic", "detailed"]:
            detail_lower = "detailed"
        
        # Convert to legacy params for backward compatibility
        use_llm = (mode_lower == "deep")
        force = bool(force_deep)
        
        result = analyze_portfolio(portfolio, use_llm=use_llm, force=force, detail_level=detail_lower)
        
        # Log response structure for debugging
        print(f"[ENDPOINT] /portfolio/analyze mode={mode_lower} detail={detail_lower} response keys: {list(result.keys()) if isinstance(result, dict) else 'NOT A DICT'}")
        print(f"[ENDPOINT] success={result.get('success')}, mode={result.get('mode')}, llm_used={result.get('meta', {}).get('llm_used') if isinstance(result.get('meta'), dict) else 'N/A'}")
        
        return result
    except Exception as e:
        import traceback
        print(f"❌ Error in /portfolio/analyze: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/portfolio/backtest")
def portfolio_backtest():
    """Run backtest: portfolio performance vs S&P500 (1 month)."""
    try:
        portfolio = get_portfolio()
        if not portfolio:
            return {
                "success": False,
                "message": "Portfolio is empty. Add stocks first."
            }
        
        result = backtest_lite(portfolio)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/portfolio/whale-watch")
def portfolio_whale_watch():
    """Monitor institutional holders (whales) for portfolio stocks."""
    try:
        portfolio = get_portfolio()
        if not portfolio:
            return {
                "success": False,
                "message": "Portfolio is empty. Add stocks first."
            }
        
        symbols = [item["symbol"] for item in portfolio]
        result = whale_watch(symbols)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== HERMES WATCHLIST MANAGEMENT ENDPOINTS ==========

@app.get("/hermes/watchlist")
def get_watchlist():
    """Get all watched symbols (Hermes watchlist)."""
    try:
        watched = get_watched_symbols()
        return {
            "success": True,
            "watchlist": watched,
            "count": len(watched)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/hermes/watchlist/add")
def add_to_watchlist(symbol: str, mode: str = "STOCK"):
    """
    Add a symbol to the Hermes watchlist.
    
    Args:
        symbol: Stock/crypto symbol (e.g., "NVDA", "AAPL")
        mode: "STOCK" or "CRYPTO" (default: "STOCK")
    
    Returns:
        Dict with success status and message
    """
    try:
        result = add_watched_symbol(symbol, mode)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/hermes/watchlist/remove/{symbol}")
def remove_from_watchlist(symbol: str):
    """
    Remove a symbol from the Hermes watchlist.
    
    Args:
        symbol: Stock/crypto symbol to remove
    
    Returns:
        Dict with success status and message
    """
    try:
        result = remove_watched_symbol(symbol)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("message"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/watchlist/{symbol}")
def remove_from_watchlist_api(symbol: str):
    """
    ARCHITECT ALIAS: Short DELETE endpoint for watchlist removal.
    Allows deletion of ANY symbol including typos/invalid ones.
    
    Args:
        symbol: Stock/crypto symbol to remove (case-insensitive)
    
    Returns:
        Dict with status and symbol
    """
    try:
        result = remove_watched_symbol(symbol.upper())
        return {"status": "success" if result.get("success") else "failed", "symbol": symbol.upper()}
    except Exception as e:
        print(f"❌ Watchlist delete error for {symbol}: {e}")
        return {"status": "failed", "symbol": symbol.upper(), "error": str(e)}


@app.get("/watchlist/quotes")
def get_watchlist_quotes():
    """Fast batch price quotes for all watched symbols using yf.download (2-day window)."""
    try:
        import yfinance as yf

        watched = get_watched_symbols()
        if not watched:
            return {"success": True, "data": []}

        symbols = [item["symbol"] for item in watched]
        tickers_str = " ".join(symbols)

        # Batch download — much faster than individual Ticker.history(3mo) calls
        hist = yf.download(tickers_str, period="2d", auto_adjust=True, progress=False)

        results = []
        for item in watched:
            sym = item["symbol"]
            try:
                if len(symbols) == 1:
                    closes = hist["Close"]
                else:
                    closes = hist["Close"][sym]

                closes = closes.dropna()
                if len(closes) < 1:
                    continue

                current_price = float(closes.iloc[-1])
                change_percent = 0.0
                if len(closes) >= 2:
                    prev = float(closes.iloc[-2])
                    if prev > 0:
                        change_percent = ((current_price - prev) / prev) * 100

                # Simple mentor tag based on change magnitude
                if change_percent > 1.5:
                    mentor_tag = "Al Fırsatı"
                elif change_percent < -1.5:
                    mentor_tag = "Dikkat"
                else:
                    mentor_tag = "İzle"

                results.append({
                    "symbol": sym,
                    "price": round(current_price, 2),
                    "change_percent": round(change_percent, 2),
                    "mentor_tag": mentor_tag,
                })
            except Exception as sym_err:
                print(f"[watchlist/quotes] {sym}: {sym_err}")
                continue

        return {"success": True, "data": results}
    except Exception as e:
        import traceback
        print(f"[watchlist/quotes] ERROR: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/hermes/news/process")
def process_hermes_news(force: int = 0):
    """
    Manually trigger Hermes news processing for watched symbols.
    
    Args:
        force: 0 = normal processing, 1 = force processing (ignore cache)
    
    Returns:
        Dict with processing results
    """
    try:
        from .news_pipeline import process_news_pipeline
        
        print(f"[HERMES MANUAL] Starting news processing...")
        result = process_news_pipeline(
            mode="DEEP",
            confidence_threshold=50,
            llm_threshold=60,
            use_watchlist=True
        )
        
        return {
            "success": True,
            "processed_count": len(result),
            "news_items": result,
            "message": f"Processed {len(result)} news items for watched symbols"
        }
    except Exception as e:
        import traceback
        print(f"❌ Error in manual Hermes processing: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/watchlist/sync")
def sync_watchlist_data(symbols: Optional[List[str]] = None):
    """
    Fetch real-time data for watchlist symbols using yfinance.
    
    Args:
        symbols: List of stock symbols (e.g., ["NVDA", "TSLA", "AAPL"])
                If None, fetches from database watchlist
    
    Returns:
        List of objects with real-time price, change %, sentiment, and mentor tag
    """
    try:
        import yfinance as yf
        
        # If no symbols provided, get from database watchlist
        if not symbols:
            watched = get_watched_symbols()
            if not watched:
                return {
                    "success": True,
                    "data": [],
                    "message": "No symbols in watchlist"
                }
            symbols = [item["symbol"] for item in watched]
        
        results = []
        
        # Batch fetch for performance
        for symbol in symbols:
            try:
                # Normalize symbol
                from .logic import normalize_symbol, is_crypto
                norm_symbol = normalize_symbol(symbol)
                
                # Fetch yfinance data
                ticker = yf.Ticker(norm_symbol)
                
                # Get historical data for SMA50 calculation
                hist = ticker.history(period="3mo")
                
                if hist.empty:
                    print(f"⚠️ No data for {symbol}")
                    continue
                
                # Current price
                current_price = float(hist['Close'].iloc[-1])
                
                # Previous close for change % calculation
                if len(hist) >= 2:
                    prev_close = float(hist['Close'].iloc[-2])
                    change_percent = ((current_price - prev_close) / prev_close) * 100
                else:
                    change_percent = 0.0
                
                # Calculate SMA50 for sentiment
                if len(hist) >= 50:
                    sma50 = float(hist['Close'].rolling(window=50).mean().iloc[-1])
                else:
                    sma50 = float(hist['Close'].mean())
                
                # Determine sentiment based on price vs SMA50
                if current_price > sma50:
                    sentiment = "Bullish"
                    mentor_tag = "Al Fırsatı"
                elif current_price < sma50 * 0.95:  # 5% below SMA50
                    sentiment = "Bearish"
                    mentor_tag = "Dikkat"
                else:
                    sentiment = "Neutral"
                    mentor_tag = "İzle"
                
                results.append({
                    "symbol": symbol.upper(),
                    "price": round(current_price, 2),
                    "change_percent": round(change_percent, 2),
                    "sentiment": sentiment,
                    "mentor_tag": mentor_tag,
                    "sma50": round(sma50, 2)
                })
                
            except Exception as e:
                print(f"⚠️ Error fetching data for {symbol}: {e}")
                # Continue with next symbol instead of failing completely
                continue
        
        return {
            "success": True,
            "data": results,
            "count": len(results),
            "message": f"Fetched data for {len(results)} symbols"
        }
        
    except Exception as e:
        print(f"❌ Watchlist sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/portfolio/backfill-outcomes")
def backfill_portfolio_outcomes(horizon: int = 7, limit: int = 50):
    """
    Backfill portfolio outcomes for analyses without forward returns.
    Computes forward returns at 1/3/7 days using yfinance close prices.
    """
    try:
        from .database import get_analyses_without_outcomes, save_portfolio_outcome, get_portfolio
        from datetime import datetime, timedelta
        import yfinance as yf
        
        results = {
            "success": True,
            "processed": 0,
            "errors": 0,
            "details": []
        }
        
        # Get analyses without outcomes for the specified horizon
        analyses = get_analyses_without_outcomes(horizon=horizon, limit=limit)
        
        if not analyses:
            return {
                "success": True,
                "message": f"No analyses found without {horizon}-day outcomes",
                "processed": 0
            }
        
        # Get current portfolio to compute portfolio value
        portfolio = get_portfolio()
        if not portfolio:
            return {
                "success": False,
                "message": "Portfolio is empty. Cannot compute outcomes."
            }
        
        # Process each analysis
        for analysis in analyses:
            try:
                analysis_id = analysis["id"]
                as_of_str = analysis.get("as_of", "")
                full_json = analysis.get("full_json", {})
                
                # Parse as_of date
                try:
                    as_of_date = datetime.fromisoformat(as_of_str.replace("Z", "+00:00")).date()
                except:
                    # Try alternative format
                    try:
                        as_of_date = datetime.strptime(as_of_str.split("T")[0], "%Y-%m-%d").date()
                    except:
                        results["errors"] += 1
                        results["details"].append(f"Analysis {analysis_id}: Invalid as_of date")
                        continue
                
                # Calculate target date
                target_date = as_of_date + timedelta(days=horizon)
                
                # Get portfolio holdings from full_json
                holdings = full_json.get("holdings", [])
                if not holdings:
                    results["errors"] += 1
                    results["details"].append(f"Analysis {analysis_id}: No holdings data")
                    continue
                
                # Compute portfolio value at as_of and target_date
                value_as_of = 0
                value_target = 0
                
                for holding in holdings:
                    symbol = holding.get("symbol", "")
                    quantity = holding.get("quantity", 0)
                    
                    if not symbol or quantity <= 0:
                        continue
                    
                    try:
                        # Get price at as_of date
                        ticker = yf.Ticker(symbol)
                        hist_as_of = ticker.history(start=as_of_date, end=as_of_date + timedelta(days=1))
                        if not hist_as_of.empty:
                            price_as_of = hist_as_of['Close'].iloc[0]
                            value_as_of += price_as_of * quantity
                        
                        # Get price at target date
                        hist_target = ticker.history(start=target_date, end=target_date + timedelta(days=1))
                        if not hist_target.empty:
                            price_target = hist_target['Close'].iloc[0]
                            value_target += price_target * quantity
                        else:
                            # If target date is in the future, use latest available price
                            hist_latest = ticker.history(period="1d")
                            if not hist_latest.empty:
                                price_target = hist_latest['Close'].iloc[-1]
                                value_target += price_target * quantity
                            else:
                                # Fallback: use as_of price
                                value_target += price_as_of * quantity
                    except Exception as e:
                        print(f"⚠️ Error fetching price for {symbol}: {e}")
                        continue
                
                if value_as_of == 0:
                    results["errors"] += 1
                    results["details"].append(f"Analysis {analysis_id}: Could not compute as_of value")
                    continue
                
                # Calculate returns
                return_usd = value_target - value_as_of
                return_pct = ((value_target - value_as_of) / value_as_of) * 100 if value_as_of > 0 else 0
                
                # Save outcome
                save_portfolio_outcome(analysis_id, horizon, return_pct, return_usd)
                
                results["processed"] += 1
                results["details"].append(f"Analysis {analysis_id}: {horizon}d return = {return_pct:.2f}%")
                
            except Exception as e:
                results["errors"] += 1
                results["details"].append(f"Analysis {analysis.get('id', 'unknown')}: {str(e)}")
                print(f"⚠️ Error processing analysis {analysis.get('id')}: {e}")
        
        return results
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ========== AI CHAT MENTOR ENDPOINT ==========

class ChatRequest(BaseModel):
    user_message: str
    context_data: dict = {}  # Optional: Stock data or Portfolio summary (default to empty dict)
    use_llm: Optional[int] = None  # Optional: 0 = no LLM, 1 = use LLM, None = auto-detect
    detail_level: Optional[str] = "medium"  # Optional: "short", "medium", "full"

@app.get("/history/all")
def get_all_analyses():
    """Get all past analyses from database."""
    try:
        history = get_all_history()
        return {
            "success": True,
            "history": history,
            "count": len(history)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
def chat_with_user(request: ChatRequest):
    """
    AI Mentor chat endpoint (HYBRID approach).
    
    HYBRID Strategy:
    1. Get deterministic canonical decision (fast, reliable)
    2. Use LLM to customize explanation IF user_message warrants it
    3. NEVER override decision from canonical
    4. Always return complete schema (no null fields)

    Contract:
    - Always returns canonical mentor fields used by UI:
      decision, why_bullets, action_plan, news_impact, glossary_terms, mentor_scenario, risk_note
    - If data is missing/unavailable: returns decision=HOLD with low confidence and explanatory flags.
    - Flags: used_llm, missing_data, fallback_mode
    """
    try:
        # ========== COMPREHENSIVE LOGGING ==========
        user_msg = request.user_message or ""
        llm_toggle_received = request.use_llm
        detail_level_received = request.detail_level or "medium"
        
        print(f"🔍 [CHAT] ========== CHAT REQUEST START ==========")
        print(f"🔍 [CHAT] user_message: '{user_msg}'")
        print(f"🔍 [CHAT] user_message length: {len(user_msg)} chars")
        print(f"🔍 [CHAT] llm_toggle received: {llm_toggle_received}")
        print(f"🔍 [CHAT] detail_level received: {detail_level_received}")
        print(f"🔍 [CHAT] context_data keys: {list(request.context_data.keys()) if request.context_data else 'None'}")
        # =========================================

        _agent_log(
            location="borsaajan_backend/main.py:/chat",
            message="chat request received (HYBRID mode)",
            data={
                "userMessageLen": len(request.user_message or ""),
                "hasContext": bool(request.context_data),
                "contextKeys": list((request.context_data or {}).keys()),
            },
            hypothesisId="B",
        )
        
        # Build structured mentor response (deterministic-first for reliability)
        ctx = request.context_data or {}
        ctx_type = str(ctx.get("type") or "").lower().strip()
        symbol = str(ctx.get("symbol") or "").strip()
        mode = "STOCK"
        if ctx_type == "crypto":
            mode = "CRYPTO"

        # ========== GENERAL CHAT PATH (no symbol context) ==========
        # If user has a real question but no symbol, call Gemini directly
        # for a generic mentor response instead of returning the canned HOLD fallback.
        if not symbol and user_msg and len(user_msg.strip()) >= 3:
            try:
                from .logic import safe_gemini_call, GeminiCallError
                print(f"🔍 [CHAT GENERIC] No symbol — calling Gemini directly for: '{user_msg[:80]}'")
                generic_prompt = (
                    "Sen Borsa Ajanı uygulamasının kuantitatif yatırım mentörüsün. "
                    "Kullanıcının sorusunu Türkçe, kısa (3-5 cümle), net ve eyleme dönük yanıtla. "
                    "Finans/borsa/kripto/yatırım/strateji/risk konularında uzmanlaş. "
                    "Belirsizlik varsa açıkça söyle. Yatırım tavsiyesi yerine bilgi/eğitim ver.\n\n"
                    f"Kullanıcı sorusu: {user_msg}\n\n"
                    "JSON döndür: {\"answer\": \"...\", \"topic\": \"finans|teknik|risk|genel\"}"
                )
                schema = {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string"},
                        "topic": {"type": "string"},
                    },
                    "required": ["answer"],
                }
                gen_result = safe_gemini_call(
                    generic_prompt,
                    response_mode="json",
                    schema=schema,
                    max_retries=1,
                    purpose="chat_generic",
                    temperature=0.6,
                    max_output_tokens=1024,
                )
                if gen_result and gen_result.get("answer"):
                    answer_text = gen_result.get("answer").strip()
                    print(f"✅ [CHAT GENERIC] Gemini answered ({len(answer_text)} chars)")
                    return {
                        "success": True,
                        "decision": "INFO",
                        "why_bullets": [],
                        "action_plan": [],
                        "news_impact": [],
                        "glossary_terms": {},
                        "mentor_scenario": "",
                        "risk_note": "",
                        "confidence": 0,
                        "horizon_days": 0,
                        "symbol": "GENERAL",
                        "mode": "chat",
                        "errors": [],
                        "missing": [],
                        "flags": {"used_llm": True, "missing_data": False, "fallback_mode": False, "generic_chat": True},
                        "cache_key": None,
                        "response": answer_text,
                        "mentor": {"answer": answer_text, "topic": gen_result.get("topic", "genel")},
                    }
            except GeminiCallError as e:
                print(f"⚠️ [CHAT GENERIC] Gemini error: {e} — falling through to canonical path")
            except Exception as e:
                print(f"⚠️ [CHAT GENERIC] Unexpected error: {e} — falling through")
        # ============================================================

        # ========== DIAGNOSTIC LOGGING ==========
        print(f"🔍 [CHAT HYBRID] context_type: '{ctx_type}', symbol: '{symbol}', mode: '{mode}'")
        # =========================================

        errors: list[str] = []
        missing: list[str] = []
        flags = {
            "used_llm": False,
            "missing_data": False,
            "fallback_mode": False
        }

        canonical: dict = {}
        if ctx_type in ["stock", "crypto"] and symbol:
            try:
                # ========== STEP 1: GET CANONICAL DECISION (DETERMINISTIC) ==========
                print(f"🔍 [CHAT HYBRID] Step 1: Getting canonical decision from get_canonical_quick_analysis()")
                
                canonical = get_canonical_quick_analysis(symbol=symbol, mode=mode, include_evidence=False)
                
                print(f"🔍 [CHAT HYBRID] Canonical decision:")
                print(f"🔍 [CHAT HYBRID]   - Decision: {canonical.get('decision')}")
                print(f"🔍 [CHAT HYBRID]   - Confidence: {canonical.get('confidence')}")
                print(f"🔍 [CHAT HYBRID]   - Horizon: {canonical.get('horizon_days')} days")
                # ====================================================================
            except Exception as e:
                errors.append(f"canonical_quick_failed:{type(e).__name__}")
                canonical = {}
                flags["missing_data"] = True
        else:
            if ctx_type not in ["stock", "crypto"]:
                missing.append("missing_or_unsupported_context_type")
            if not symbol:
                missing.append("missing_symbol")
            flags["missing_data"] = True

        # Hard fallback (always valid schema)
        if not canonical:
            flags["fallback_mode"] = True
            canonical = {
                "symbol": symbol or "UNKNOWN",
                "mode": "quick",
                "as_of": {
                    "analysis": datetime.now().isoformat(),
                    "quote": datetime.now().isoformat(),
                    "fundamentals": datetime.now().isoformat(),
                    "news": datetime.now().isoformat(),
                    "ohlc": datetime.now().isoformat(),
                },
                "decision": "HOLD",
                "confidence": 25,
                "horizon_days": 7,
                "why_bullets": [
                    "Şu an için güvenilir veri/bağlam eksik; temkinli duruş daha doğru.",
                    "Sembol ve piyasa türü netleşmeden işlem kararı vermek doğru değil.",
                ],
                "action_plan": [
                    {"type": "WAIT", "rationale_short": "Sembol ve bağlam netleşene kadar bekle."},
                    {"type": "RECHECK", "timeframe": "24 saat", "rationale_short": "Yeni veriyle yeniden değerlendir."},
                ],
                "news_impact": [],
                "glossary_terms": {"RSI": "Momentum göstergesi (0-100).", "Stop-loss": "Zarar kes seviyesi."},
                "mentor_scenario": "Eğer veri gelirse karar netleşir. Eğer veri gelmezse bekleme stratejisi korunur.",
            }

        # ========== STEP 2: DECIDE IF LLM CUSTOMIZATION IS NEEDED ==========
        # Respect explicit use_llm parameter if provided, otherwise auto-detect
        cache_key = None
        if request.use_llm is not None:
            use_llm = bool(request.use_llm)
            print(f"🔍 [CHAT] Step 2: Explicit LLM toggle = {use_llm}")
        else:
            # Auto-detect based on user_message and context
            use_llm = should_use_llm(
                user_message=request.user_message,
                llm_toggle=True,
                context=request.context_data
            )
            print(f"🔍 [CHAT] Step 2: Auto-detected LLM = {use_llm}")
            print(f"🔍 [CHAT]   Reason: {'Mentor keywords/question detected' if use_llm else 'Short/test message or no keywords'}")
        
        # Generate cache key for LLM responses (if using LLM)
        if use_llm and canonical:
            import hashlib
            cache_input = f"{request.user_message}|{canonical.get('symbol')}|{canonical.get('decision')}|{canonical.get('quick_features_hash', '')}"
            cache_key = hashlib.sha256(cache_input.encode('utf-8')).hexdigest()[:16]
            print(f"🔍 [CHAT] cache_key: {cache_key}")
        # ====================================================================
        
        # ========== STEP 3: LLM CUSTOMIZATION (IF NEEDED) ==========
        if use_llm and not flags["fallback_mode"]:
            try:
                print(f"🔍 [CHAT] Step 3: Calling llm_explain() to customize response...")
                
                # Build context summary from canonical (canonical doesn't have "technical" field directly)
                # Get technical data from evidence if available, otherwise use defaults
                evidence = canonical.get("evidence", {})
                technical = evidence.get("technical", {}) if evidence else {}
                price = technical.get("current_price") or technical.get("fiyat") or canonical.get("symbol", "N/A")
                rsi = technical.get("rsi") or "N/A"
                trend = technical.get("trend") or "N/A"
                
                # Also include decision and confidence in context
                decision = canonical.get("decision", "HOLD")
                confidence = canonical.get("confidence", 50)
                
                context_summary = f"Karar: {decision} (Güven: {confidence}/100), Fiyat: {price}, RSI: {rsi}, Trend: {trend}"
                
                # Call LLM to customize explanation
                llm_customization = llm_explain(
                    canonical_result=canonical,
                    user_message=request.user_message,
                    context_summary=context_summary
                )
                
                if llm_customization:
                    # Merge LLM customization with canonical (NEVER override decision)
                    original_decision = canonical.get("decision")
                    
                    # Update only explanation fields
                    if "why_bullets" in llm_customization and llm_customization["why_bullets"]:
                        canonical["why_bullets"] = llm_customization["why_bullets"]
                    if "action_plan" in llm_customization and llm_customization["action_plan"]:
                        canonical["action_plan"] = llm_customization["action_plan"]
                    if "mentor_scenario" in llm_customization and llm_customization["mentor_scenario"]:
                        canonical["mentor_scenario"] = llm_customization["mentor_scenario"]
                    if "glossary_terms" in llm_customization and llm_customization["glossary_terms"]:
                        canonical["glossary_terms"] = llm_customization["glossary_terms"]
                    
                    # CRITICAL: Verify decision was not changed
                    if canonical.get("decision") != original_decision:
                        print(f"⚠️ [CHAT HYBRID] LLM attempted to change decision from {original_decision} to {canonical.get('decision')}")
                        canonical["decision"] = original_decision  # Restore original
                        errors.append("llm_attempted_override_decision")
                    
                    flags["used_llm"] = True
                    print(f"✅ [CHAT HYBRID] LLM customization applied successfully")
                else:
                    print(f"⚠️ [CHAT HYBRID] LLM customization failed, using canonical only")
                    flags["used_llm"] = False
                    
            except Exception as llm_error:
                print(f"❌ [CHAT HYBRID] LLM customization error: {llm_error}")
                errors.append(f"llm_customization_failed:{type(llm_error).__name__}")
                flags["used_llm"] = False
        else:
            print(f"🔍 [CHAT HYBRID] Step 3: Skipping LLM (use_llm={use_llm}, fallback_mode={flags['fallback_mode']})")
        # ============================================================

        # ========== STEP 4: ENSURE SCHEMA COMPLETENESS ==========
        # Ensure all arrays default to []
        if not canonical.get("why_bullets"):
            canonical["why_bullets"] = []
        if not canonical.get("action_plan"):
            canonical["action_plan"] = []
        if not canonical.get("news_impact"):
            canonical["news_impact"] = []
        
        # Ensure glossary_terms is dict
        if not canonical.get("glossary_terms"):
            canonical["glossary_terms"] = {}
        
        # Ensure mentor_scenario is string
        if not canonical.get("mentor_scenario"):
            canonical["mentor_scenario"] = ""
        
        # Add risk_note
        canonical["risk_note"] = _mentor_risk_note(canonical.get("decision"))
        # ========================================================

        # ========== STEP 5: GENERATE RESPONSE TEXT ==========
        print(f"🔍 [CHAT HYBRID] Step 5: Generating response text from canonical data")
        
        response_text = _mentor_text_from_canonical(canonical)

        print(f"🔍 [CHAT] Final response preview (first 200 chars): '{response_text[:200]}'")
        print(f"🔍 [CHAT] Flags: used_llm={flags['used_llm']}, missing_data={flags['missing_data']}, fallback_mode={flags['fallback_mode']}")
        print(f"🔍 [CHAT] ========== CHAT REQUEST END ==========")
        # ====================================================

        result = {
            "success": True,
            # Canonical schema fields (top-level for UI simplicity)
            "decision": canonical.get("decision", "HOLD"),
            "why_bullets": canonical.get("why_bullets") or [],
            "action_plan": canonical.get("action_plan") or [],
            "news_impact": canonical.get("news_impact") or [],
            "glossary_terms": canonical.get("glossary_terms") or {},
            "mentor_scenario": canonical.get("mentor_scenario") or "",
            "risk_note": canonical.get("risk_note") or "",
            # Extra useful fields
            "confidence": canonical.get("confidence", 50),
            "horizon_days": canonical.get("horizon_days", 7),
            "symbol": canonical.get("symbol") or symbol or "UNKNOWN",
            "mode": canonical.get("mode") or "quick",
            "errors": errors,
            "missing": missing,
            # HYBRID flags
            "flags": flags,
            # Debugging info
            "cache_key": cache_key,
            # Backward compatibility for existing UI
            "response": response_text,
            "mentor": canonical,  # full canonical payload
        }

        _agent_log(
            location="borsaajan_backend/main.py:/chat",
            message="chat response returned (HYBRID mode)",
            data={
                "resultType": type(result).__name__,
                "resultKeys": list(result.keys()) if isinstance(result, dict) else None,
                "success": (result.get("success") if isinstance(result, dict) else None),
                "decision": (result.get("decision") if isinstance(result, dict) else None),
                "used_llm": flags["used_llm"],
                "user_message": user_msg[:100],
                "llm_toggle_received": llm_toggle_received,
                "cache_key": cache_key,
            },
            hypothesisId="C",
        )
        
        print(f"✅ [CHAT] Response generated: used_llm={flags['used_llm']}, decision={result.get('decision')}, cache_key={cache_key}")
        return result
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ ERROR in /chat endpoint:")
        print(f"   Error Type: {type(e).__name__}")
        print(f"   Error Message: {str(e)}")
        print(f"   Full Traceback:")
        print(f"   {error_trace}")
        print(f"   Request Data: user_message='{request.user_message[:100]}', context_data={request.context_data}")
        _agent_log(
            location="borsaajan_backend/main.py:/chat",
            message="chat endpoint exception",
            data={"exType": type(e).__name__, "error": str(e)},
            hypothesisId="B",
        )
        return {
            "success": False,
            "response": f"Üzgünüm, bir hata oluştu: {str(e)}. Lütfen tekrar deneyin.",
            "error": str(e),
            "error_type": type(e).__name__
        }


@app.get("/chat/health")
def chat_health():
    """
    Chat health check (dependency-focused).
    - db reachable
    - data provider reachable (basic)
    - llm configured (optional; no token burn)
    """
    status = {
        "ok": True,
        "timestamp": datetime.now().isoformat(),
        "db": {"ok": True},
        "data_provider": {"ok": True, "kind": "yahoo_quote_basic"},
        "llm": {"ok": True, "configured": bool(os.environ.get("GOOGLE_API_KEY"))},
    }

    # DB
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        conn.close()
    except Exception as e:
        status["ok"] = False
        status["db"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)}"}

    # Data provider (basic HTTP ping with timeout)
    try:
        import requests
        r = requests.get("https://query1.finance.yahoo.com/v7/finance/quote?symbols=SPY", timeout=3)
        status["data_provider"] = {"ok": r.status_code == 200, "status_code": r.status_code, "kind": "yahoo_quote_basic"}
        if r.status_code != 200:
            status["ok"] = False
    except Exception as e:
        status["ok"] = False
        status["data_provider"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)}", "kind": "yahoo_quote_basic"}

    # LLM (optional, non-blocking)
    if not status["llm"]["configured"]:
        status["llm"] = {"ok": False, "configured": False}
        # Not necessarily fatal for chat now (we run deterministic), but report as not-ok for visibility.
        status["ok"] = False

    if status["ok"]:
        return status
    return status, 503

# ========== NOTIFICATIONS ENDPOINT ==========

@app.get("/notifications")
def get_notifications_list(limit: int = 50):
    """Get notification history from database."""
    try:
        notifications = get_notifications(limit)
        return {
            "success": True,
            "notifications": notifications,
            "count": len(notifications)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/notifications/test")
def test_notification():
    """Test notification system - sends a test message to Telegram and saves to DB."""
    try:
        from .services.alert_system import send_and_save_notification
        
        result = send_and_save_notification(
            title="🧪 Test Bildirimi",
            message="Bu bir test bildirimidir. Sistem çalışıyor! ✅",
            notification_type="ALERT"
        )
        
        return {
            "success": result.get("success", False),
            "message": "Test bildirimi gönderildi",
            "telegram_sent": result.get("telegram_sent", False),
            "saved_to_db": result.get("saved_to_db", False),
            "notification_id": result.get("notification_id")
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

# ========== USER PROFILE / RISK MODE ENDPOINTS ==========

class ProfileUpdateRequest(BaseModel):
    risk_profile: str = None
    system_instruction: str = None

@app.get("/profile/get")
def get_profile():
    """Get current user risk profile and system instruction."""
    try:
        profile = get_user_profile()
        return {
            "success": True,
            "profile": profile
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/profile/update")
def update_profile(request: ProfileUpdateRequest):
    """
    Update user risk profile and/or system instruction.
    
    Example risk_profile values:
    - "Defansif/Garantici" (default)
    - "Agresif/Büyüme Odaklı"
    - "Vur-Kaç (Scalper)"
    - Custom profile name
    
    Example system_instruction:
    - "Risk almayı seviyorum, stop-loss'ları geniş tut"
    - "Kısa vadeli işlemler yapmayı tercih ediyorum"
    """
    try:
        result = update_user_profile(
            risk_profile=request.risk_profile,
            system_instruction=request.system_instruction
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/set_mode")
def set_mode(risk_profile: str, system_instruction: str = None):
    """
    Legacy endpoint: Set risk mode/profile (alias for /profile/update).
    For backward compatibility.
    """
    try:
        result = update_user_profile(
            risk_profile=risk_profile,
            system_instruction=system_instruction
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/portfolio/analysis/history")
def portfolio_analysis_history(limit: int = 50):
    """Get portfolio analysis history from database."""
    try:
        history = get_portfolio_analysis_history(limit)
        return {
            "success": True,
            "history": history,
            "count": len(history)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/usage/monthly")
def get_usage_monthly(year: int, month: int):
    """
    Get monthly LLM usage statistics.
    
    Args:
        year: Year (e.g., 2025)
        month: Month (1-12)
    
    Returns:
        dict: Monthly usage statistics
    """
    try:
        if month < 1 or month > 12:
            raise HTTPException(status_code=400, detail="Month must be between 1 and 12")
        
        result = get_monthly_llm_usage(year, month)
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in /usage/monthly: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {"ok": True, "timestamp": datetime.now().isoformat()}

@app.get("/ready")
def readiness_check():
    """
    Readiness check: verifies database is reachable and can read tables.
    Returns 503 if not ready.
    """
    try:
        from .database import get_connection, init_db
        
        # Try to connect and read from a table
        conn = get_connection()
        cursor = conn.cursor()
        
        # Check if portfolio_analyses table exists and is readable
        cursor.execute("SELECT COUNT(*) FROM portfolio_analyses LIMIT 1")
        cursor.fetchone()
        
        # Integrity check
        cursor.execute("PRAGMA integrity_check")
        integrity_result = cursor.fetchone()
        integrity_ok = integrity_result and integrity_result[0] == "ok"
        
        conn.close()
        
        if integrity_ok:
            return {"ok": True, "db": "ok", "timestamp": datetime.now().isoformat()}
        else:
            return {"ok": False, "db": "integrity_check_failed", "timestamp": datetime.now().isoformat()}, 503
            
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Readiness check failed: {e}", exc_info=True)
        return {"ok": False, "db": "error", "error": str(e), "timestamp": datetime.now().isoformat()}, 503

@app.get("/notifications/scheduler/status")
def scheduler_status():
    """Check scheduler status and list all scheduled jobs."""
    try:
        if scheduler is None:
            return {
                "scheduler_active": False,
                "message": "Scheduler is not initialized",
                "jobs": []
            }
        
        jobs = []
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger)
            })
        
        return {
            "scheduler_active": True,
            "scheduler_running": scheduler.running,
            "timezone": str(scheduler.timezone) if hasattr(scheduler, 'timezone') else None,
            "jobs_count": len(jobs),
            "jobs": jobs
        }
    except Exception as e:
        return {
            "scheduler_active": False,
            "error": str(e),
            "jobs": []
        }

@app.get("/market/overview")
def market_overview():
    """
    Personalized Daily Market Overview.
    Returns market summary tailored to user's portfolio.
    """
    try:
        from .services.alert_system import send_market_summary
        from .database import get_portfolio
        import yfinance as yf
        import os
        
        # Step 1: Fetch user's portfolio symbols
        portfolio = get_portfolio()
        portfolio_symbols = [item["symbol"] for item in portfolio] if portfolio else []
        portfolio_list = ", ".join(portfolio_symbols) if portfolio_symbols else "Portföy boş"
        
        # Step 2: Get market data (VIX, DXY)
        vix_value = None
        dxy_value = None
        try:
            vix = yf.Ticker("^VIX")
            vix_data = vix.history(period="1d")
            if not vix_data.empty:
                vix_value = float(vix_data['Close'].iloc[-1])
        except Exception as e:
            print(f"⚠️ Error fetching VIX: {e}")
        
        try:
            dxy = yf.Ticker("DX-Y.NYB")
            dxy_data = dxy.history(period="1d")
            if not dxy_data.empty:
                dxy_value = float(dxy_data['Close'].iloc[-1])
        except Exception as e:
            print(f"⚠️ Error fetching DXY: {e}")
        
        # Get major indices
        indices = {
            "S&P 500": "^GSPC",
            "NASDAQ": "^IXIC",
            "DOW": "^DJI"
        }
        
        market_data = {}
        for name, symbol in indices.items():
            try:
                ticker = yf.Ticker(symbol)
                data = ticker.history(period="2d")
                if not data.empty:
                    current = data['Close'].iloc[-1]
                    previous = data['Close'].iloc[-2]
                    change = current - previous
                    change_pct = (change / previous) * 100
                    market_data[name] = {
                        "current": current,
                        "change": change,
                        "change_pct": change_pct
                    }
            except Exception as e:
                print(f"⚠️ Error fetching {name}: {e}")
        
        # Step 3: Get portfolio stock prices
        portfolio_data = []
        if portfolio_symbols:
            for symbol in portfolio_symbols[:10]:  # Limit to 10 stocks
                try:
                    ticker = yf.Ticker(symbol)
                    data = ticker.history(period="2d")
                    if not data.empty:
                        current = data['Close'].iloc[-1]
                        previous = data['Close'].iloc[-2]
                        change_pct = ((current - previous) / previous) * 100
                        portfolio_data.append({
                            "symbol": symbol,
                            "price": current,
                            "change_pct": change_pct
                        })
                except Exception as e:
                    print(f"⚠️ Error fetching {symbol}: {e}")
        
        # Step 4: Generate AI-powered personalized summary
        try:
            # Build market context
            market_context = "GENEL PİYASA DURUMU:\n"
            for name, data in market_data.items():
                emoji = "🟢" if data["change"] >= 0 else "🔴"
                market_context += f"{emoji} {name}: {data['change_pct']:+.2f}%\n"
            
            if vix_value:
                market_context += f"VIX (Korku Endeksi): {vix_value:.2f}\n"
            if dxy_value:
                market_context += f"DXY (Dolar Endeksi): {dxy_value:.2f}\n"
            
            portfolio_context = ""
            if portfolio_data:
                portfolio_context = "\nKULLANICININ PORTFÖYÜ:\n"
                for stock in portfolio_data:
                    emoji = "🟢" if stock["change_pct"] >= 0 else "🔴"
                    portfolio_context += f"{emoji} {stock['symbol']}: ${stock['price']:.2f} ({stock['change_pct']:+.2f}%)\n"
            else:
                portfolio_context = "\nKullanıcının portföyü boş.\n"
            
            # System prompt with portfolio focus - Enhanced per user requirements
            ai_prompt = f"""Sen gerçekçi bir hedge fund yöneticisisin. Aşağıdaki piyasa verilerini ve kullanıcının portföyünü analiz et.

GENEL PİYASA VERİLERİ:
{market_context}
VIX (Korku Endeksi): {f"{vix_value:.2f}" if vix_value is not None else "N/A"}
DXY (Dolar Endeksi): {f"{dxy_value:.2f}" if dxy_value is not None else "N/A"}

KULLANICININ PORTFÖYÜ: {portfolio_list}
{portfolio_context}

SİSTEM PROMPT: 
Bu özet, kullanıcının portföyündeki hisselere ({portfolio_list}) özel olarak odaklanmalı. 
Genel piyasa durumunu (VIX, DXY) ve kullanıcının portföyünü birleştirerek, piyasa koşullarının KULLANICININ HİSSELERİNİ nasıl etkilediğini gerçekçi bir şekilde açıkla.

ÖNEMLİ: 
- Kullanıcının portföyü: {portfolio_list}
- Bu özet, kullanıcının portföyündeki hisselere özel olarak yazılmalı
- Piyasa koşullarının (VIX, DXY) kullanıcının portföyündeki hisseleri nasıl etkilediğini açıkla
- Gerçekçi ol, gereksiz pozitiflik yapma

Günlük özet yaz. Özellikle:
1. Genel piyasa durumu (VIX, DXY) - kısa
2. Kullanıcının portföyündeki hisselerin ({portfolio_list}) nasıl etkilendiği - SPESİFİK ve DETAYLI
3. Risk uyarıları (varsa) - portföy odaklı
4. Öneriler (kısa ve net) - portföy bazlı

Gerçekçi ol. Gereksiz pozitiflik yapma. Türkçe yaz. Maksimum 300 kelime."""
            
            # Use unified gemini_text for consistent error handling
            result = gemini_text(ai_prompt)
            ai_summary = result.get("text", FALLBACK_AI_MESSAGE) if not result.get("fallback") else FALLBACK_AI_MESSAGE
            
            return {
                "success": True,
                "market_data": market_data,
                "vix": vix_value,
                "dxy": dxy_value,
                "portfolio_symbols": portfolio_symbols,
                "portfolio_data": portfolio_data,
                "ai_summary": ai_summary,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as ai_error:
            # Catch ALL exceptions to prevent crashes
            print("⚠️ Using fallback data")
            return {
                "success": True,
                "market_data": market_data,
                "vix": vix_value,
                "dxy": dxy_value,
                "portfolio_symbols": portfolio_symbols,
                "portfolio_data": portfolio_data,
                "ai_summary": FALLBACK_AI_MESSAGE,
                "error": "API error",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    except Exception as e:
        import traceback
        print(f"❌ Error in market overview: {e}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Webhook: n8n / dış otomasyon köprüsü
# ---------------------------------------------------------------------------

class WebhookNewsPayload(BaseModel):
    hisse_adi: str        # Sembol — "NVDA", "AAPL" vb.
    haber_metni: str      # Haber başlığı veya tam metin
    kaynak: str = ""      # Opsiyonel — n8n akış adı veya kaynak


_WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


def _get_current_price(symbol: str) -> Optional[float]:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        hist = ticker.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        return None
    except Exception as e:
        print(f"⚠️ [webhook] Fiyat çekilemedi ({symbol}): {e}")
        return None


def _is_market_open() -> bool:
    try:
        from datetime import datetime, timezone, timedelta
        et_offset = timedelta(hours=-4)
        now_et = datetime.now(timezone.utc) + et_offset
        if now_et.weekday() >= 5:
            return False
        market_open  = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)
        return market_open <= now_et <= market_close
    except Exception:
        return True


@app.post("/webhook/news-signal")
def webhook_news_signal(
    payload: WebhookNewsPayload,
    x_webhook_secret: Optional[str] = Header(default=None),
):
    """
    n8n veya diğer otomasyon araçlarından gelen anlık haber sinyalini alır,
    Gemini ile analiz eder, anlık fiyatı kaydeder ve 2 saat sonra
    fiyat değişimini otomatik ölçer.

    Header: X-Webhook-Secret  →  .env'deki WEBHOOK_SECRET ile eşleşmeli
    Body  : { "hisse_adi": "NVDA", "haber_metni": "...", "kaynak": "" }
    """
    if _WEBHOOK_SECRET and x_webhook_secret != _WEBHOOK_SECRET:
        print(f"⛔ [webhook] Yetkisiz istek — kaynak: {payload.kaynak or 'bilinmiyor'}")
        raise HTTPException(status_code=401, detail="Geçersiz veya eksik X-Webhook-Secret")

    _SYMBOL_KEYWORDS: dict[str, list[str]] = {
        "NVDA": ["nvidia", "nvda"],
        "AAPL": ["apple", "aapl", "iphone", "ipad", "macbook"],
        "GOOGL": ["google", "googl", "alphabet", "goog"],
        "GOOG": ["google", "googl", "alphabet", "goog"],
        "TSLA": ["tesla", "tsla", "elon musk"],
        "MSFT": ["microsoft", "msft", "azure", "windows"],
        "AMZN": ["amazon", "amzn", "aws"],
        "META": ["meta", "facebook", "instagram", "whatsapp"],
        "AMD": ["amd", "advanced micro"],
        "INTC": ["intel", "intc"],
        "NFLX": ["netflix", "nflx"],
        "CRM": ["salesforce", "crm"],
        "ORCL": ["oracle", "orcl"],
        "QCOM": ["qualcomm", "qcom"],
    }

    def _detect_symbol(text: str, raw_symbol: str) -> str:
        rs = raw_symbol.upper().strip()
        if rs and rs not in ("UNKNOWN", "N/A", "NONE", ""):
            text_lower = text.lower()
            for sym, keywords in _SYMBOL_KEYWORDS.items():
                if any(kw in text_lower for kw in keywords):
                    return sym
            return rs
        text_lower = text.lower()
        for sym, keywords in _SYMBOL_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return sym
        try:
            from .news_pipeline import detect_symbol_from_text
            detected = detect_symbol_from_text(text)
            if detected:
                return detected.upper().strip()
        except Exception:
            pass
        first_word = text.split()[0].upper() if text.split() else rs
        return first_word or rs

    symbol = _detect_symbol(payload.haber_metni.strip(), payload.hisse_adi)
    haber  = payload.haber_metni.strip()
    kaynak = payload.kaynak.strip() or "n8n"
    print(f"🔍 [webhook] Sembol: {symbol}")

    print(f"📡 [webhook] Sinyal alındı — sembol={symbol}, kaynak={kaynak}, haber={haber[:80]}...")

    try:
        import hashlib
        news_hash = hashlib.md5(f"{symbol}:{haber}".encode()).hexdigest()

        llm = analyze_news_with_gemini(symbol, haber)

        if not llm:
            import logging as _log
            _log.error(f"[webhook] Gemini analiz döndürmedi: {symbol}")
            return {"status": "skipped", "reason": f"Gemini analiz döndürmedi: {symbol}"}

        raw_impact = (llm.get("impact") or "").upper()
        impact = "POSITIVE" if raw_impact in ("POSITIVE", "BULLISH") else ("NEGATIVE" if raw_impact in ("NEGATIVE", "BEARISH") else "NEUTRAL")
        reason = llm.get("reason", "")
        action_plan = llm.get("action_plan", "")
        mentor_scenario = llm.get("mentor_scenario", "")
        risk_level = llm.get("risk_level", "Medium")
        risk_detail = llm.get("risk_detail", "")
        technical_rsi = llm.get("technical_rsi", "N/A")
        technical_resistance = llm.get("technical_resistance", "N/A")
        confidence = 70
        strategic_advice = action_plan
        comment = mentor_scenario

        print(f"✅ [webhook] Analiz → impact={impact}, rsi={technical_rsi}, direnç={technical_resistance}")

        from .database import get_connection as _get_conn
        try:
            _conn = _get_conn()
            _conn.execute(
                "UPDATE news_analysis_history SET advice = ?, comment = ? WHERE symbol = ? AND news_hash = ?",
                (strategic_advice, comment, symbol, news_hash)
            )
            _conn.commit()
            _conn.close()
        except Exception:
            pass

        price_now = _get_current_price(symbol)
        if price_now:
            save_price_snapshot(news_hash, symbol, price_now)
            print(f"💾 [webhook] Fiyat snapshot kaydedildi: {symbol}={price_now}")
        else:
            print(f"⚠️ [webhook] Fiyat alınamadı, snapshot atlandı")

        impact_emoji = {"POSITIVE": "🟢", "NEGATIVE": "🔴"}.get(impact, "🟡")
        impact_label_tr = {"POSITIVE": "Pozitif", "NEGATIVE": "Negatif"}.get(impact, "Nötr")
        decision = llm.get("decision", "TUT") if llm else "TUT"

        telegram_body = (
            f"📋 *{symbol}* — {haber[:120]}\n\n"
            f"🎯 Karar: {decision}\n"
            f"📊 Etki: {impact_emoji} {impact_label_tr}\n"
            f"💡 Yorum: {reason[:300]}\n"
            f"⚠️ Risk: {risk_level}\n"
            f"📈 Plan: {action_plan[:200]}\n"
            f"🔢 RSI: {technical_rsi} | Fiyat: {price_now if price_now else 'N/A'} | Direnç: {technical_resistance}\n"
            f"🏦 Mentor: {mentor_scenario[:200]}"
        )

        from .notification_service import send_and_save_notification
        notif_result = send_and_save_notification(
            symbol=symbol,
            impact=impact,
            reason=reason,
            title=haber[:100],
            mentor_summary=telegram_body,
            notification_type="ALERT",
        )

        keywords = [w for w in haber.split() if len(w) > 4][:6]
        past_outcomes = get_similar_news_outcomes(symbol, keywords, limit=5)

        return {
            "success": True,
            "symbol": symbol,
            "impact": impact,
            "confidence": confidence,
            "reason": reason,
            "action_plan": action_plan,
            "mentor_scenario": mentor_scenario,
            "risk_level": risk_level,
            "risk_detail": risk_detail,
            "technical_rsi": technical_rsi,
            "technical_resistance": technical_resistance,
            "strategic_advice": strategic_advice,
            "comment": comment,
            "price_snapshot": price_now,
            "llm_used": bool(llm),
            "telegram_sent": notif_result.get("telegram_sent", False),
            "saved_to_db": notif_result.get("saved_to_db", False),
            "notification_id": notif_result.get("notification_id"),
            "past_outcomes": past_outcomes,
        }

    except Exception as e:
        import logging as _log
        import traceback
        _log.error(f"[webhook] Hata — {e}\n{traceback.format_exc()}")
        return {"status": "skipped", "reason": str(e)}


@app.get("/news/history/all")
def news_history_all(limit: int = 50):
    data = get_all_news_history(limit=limit)
    return {"count": len(data), "history": data}


@app.get("/news/history/{symbol}")
def news_history(symbol: str, limit: int = 20):
    data = get_news_history(symbol.upper(), limit=limit)
    return {"symbol": symbol.upper(), "count": len(data), "history": data}


class TranslateTitlesRequest(BaseModel):
    titles: List[str]

@app.post("/news/translate")
def translate_news_titles(request: TranslateTitlesRequest):
    """Batch translate news titles to Turkish using Gemini."""
    titles = request.titles[:15]
    if not titles:
        return {"translations": {}}
    try:
        import os as _os
        _api_key = _os.environ.get("GOOGLE_API_KEY", "")
        if not _api_key:
            return {"translations": {}}
        from google import genai as _genai
        _client = _genai.Client(api_key=_api_key)
        items_str = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        prompt = (
            f"Aşağıdaki {len(titles)} İngilizce haber başlığını Türkçeye çevir. "
            f"Sadece numaralı çeviriler döndür, başka açıklama ekleme.\n\n{items_str}"
        )
        response_text = ""
        for model in ["gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                resp = _client.models.generate_content(model=model, contents=prompt)
                if resp and resp.text:
                    response_text = resp.text.strip()
                    break
            except Exception:
                continue
        translations = {}
        if response_text:
            lines = response_text.strip().split("\n")
            for i, original in enumerate(titles):
                for line in lines:
                    line = line.strip()
                    prefix = f"{i+1}."
                    if line.startswith(prefix):
                        translated = line[len(prefix):].strip()
                        if translated:
                            translations[original] = translated
                        break
        return {"translations": translations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PAPER TRADING ENDPOINTS
# ============================================================================

from .paper_trading import (
    init_paper_trading_tables, get_portfolio as pt_get_portfolio,
    buy as pt_buy, sell as pt_sell,
    get_trade_history, reset_portfolio
)

class BuyOrderRequest(BaseModel):
    symbol: str
    shares: float

class SellOrderRequest(BaseModel):
    symbol: str
    shares: float

@app.get("/paper/portfolio")
def paper_portfolio():
    """Get paper trading portfolio: cash, positions, PnL."""
    try:
        return pt_get_portfolio()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/paper/buy")
def paper_buy(order: BuyOrderRequest):
    """Simulate a BUY order."""
    if order.shares <= 0:
        raise HTTPException(status_code=400, detail="shares must be > 0")
    result = pt_buy(order.symbol, order.shares)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.post("/paper/sell")
def paper_sell(order: SellOrderRequest):
    """Simulate a SELL order."""
    if order.shares <= 0:
        raise HTTPException(status_code=400, detail="shares must be > 0")
    result = pt_sell(order.symbol, order.shares)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.get("/paper/trades")
def paper_trades(limit: int = 50):
    """Get trade history."""
    return {"trades": get_trade_history(limit)}

@app.post("/paper/reset")
def paper_reset(starting_cash: float = 100000.0):
    """Reset paper portfolio."""
    return reset_portfolio(starting_cash)


# ============================================================================
# FINANCIAL AGENT ENDPOINTS
# ============================================================================

from .financial_agent import analyze_ticker

class AnalyzeRequest(BaseModel):
    symbol: str
    portfolio_size: float = 10000
    target_upside_pct: float = 15.0
    stop_loss_pct: float = 7.0
    prior_probability: Optional[float] = None

@app.post("/analyze")
def analyze_stock(req: AnalyzeRequest):
    """Full stock analysis: EV + Kelly + Bayes + AI commentary."""
    result = analyze_ticker(
        symbol=req.symbol,
        portfolio_size=req.portfolio_size,
        target_upside_pct=req.target_upside_pct,
        stop_loss_pct=req.stop_loss_pct,
        prior_probability=req.prior_probability,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Analysis failed"))
    try:
        from .database import save_analysis as _save_analysis
        mode = "CRYPTO" if "-USD" in (req.symbol or "").upper() else "STOCK"
        summary = (result.get("ai_commentary") or result.get("summary") or "")[:500]
        verdict = (result.get("verdict") or result.get("decision") or "").upper()
        risk_level = 3 if verdict in ("AL", "BUY") else (1 if verdict in ("SAT/KACIN", "SAT", "SELL") else 2)
        price_at = float(result.get("price") or result.get("current_price") or 0.0)
        _save_analysis(
            symbol=req.symbol,
            mode=mode,
            raw_prompt="",
            raw_response="",
            summary=summary,
            risk_level=risk_level,
            full_analysis_json=result,
            price_at_analysis=price_at,
        )
        print(f"[analyze] saved: {req.symbol} mode={mode} risk={risk_level} price={price_at}")
    except Exception as e:
        import traceback
        print(f"[analyze] save_analysis FAILED: {e}\n{traceback.format_exc()}")
    return result

@app.get("/analyze/{symbol}")
def analyze_stock_get(symbol: str, portfolio_size: float = 10000):
    """Quick GET endpoint for stock analysis."""
    result = analyze_ticker(symbol=symbol, portfolio_size=portfolio_size)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Analysis failed"))
    return result
import sys
import os
import yfinance as yf
import feedparser
from google import genai
from google.genai import types as genai_types
import json
import re
import base64
import io
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server
import mplfinance as mpf
from datetime import datetime as _dt, timezone as _tz, timedelta
from dotenv import load_dotenv
from typing import Optional, Any, Dict, List, Literal, Tuple
from datetime import date
try:
    from .database import init_db, save_analysis, get_last_analysis, get_last_decision_for_symbol, get_user_profile, save_portfolio_analysis, get_symbol_analysis_history, get_memory_context, should_send_notification, log_notification, get_cached_market_bars, get_last_bar_date, upsert_market_bars, get_cached_range, get_missing_dates, generate_event_key, log_llm_usage, get_monthly_llm_usage, get_connection, get_latest_portfolio_analysis, save_portfolio_analysis_mentor, find_similar_analyses, get_deep_decision_cache, set_deep_decision_cache, get_relevant_symbols_for_news
    from .schemas import MASTER_ANALYSIS_SCHEMA, NEW_ANALYSIS_SCHEMA, PORTFOLIO_DEEP_SCHEMA, CANONICAL_DECISION_SCHEMA, DEEP_NARRATIVE_PATCH_SCHEMA
    from .news_analyzer import analyze_news_item
    from .canonical_decision import CanonicalDecisionResponse
except ImportError:
    from database import init_db, save_analysis, get_last_analysis, get_last_decision_for_symbol, get_user_profile, save_portfolio_analysis, get_symbol_analysis_history, get_memory_context, should_send_notification, log_notification, get_cached_market_bars, get_last_bar_date, upsert_market_bars, get_cached_range, get_missing_dates, generate_event_key, log_llm_usage, get_monthly_llm_usage, get_connection, get_latest_portfolio_analysis, save_portfolio_analysis_mentor, find_similar_analyses, get_deep_decision_cache, set_deep_decision_cache, get_relevant_symbols_for_news
    from schemas import MASTER_ANALYSIS_SCHEMA, NEW_ANALYSIS_SCHEMA, PORTFOLIO_DEEP_SCHEMA, CANONICAL_DECISION_SCHEMA, DEEP_NARRATIVE_PATCH_SCHEMA
    from news_analyzer import analyze_news_item
    from canonical_decision import CanonicalDecisionResponse
import time
from functools import lru_cache
from collections import deque
import hashlib
import json as json_lib

print("=== DEBUG GEMINI ENV (logic.py) ===")
print("sys.executable:", sys.executable)
print("google-genai SDK loaded")
print("GOOGLE_API_KEY set?", bool(os.environ.get("GOOGLE_API_KEY")))
print("=========================")

# Load environment variables from .env file if present
load_dotenv()

# Database initialization happens in main.py startup event
# Do NOT call init_db() here to avoid duplicate initialization

# SINGLE CONFIGURATION POINT: Google Gemini API Key
_GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not _GOOGLE_API_KEY:
    print("⚠️ WARNING: GOOGLE_API_KEY environment variable is not set!")
    print("⚠️ AI features will not work. Please set GOOGLE_API_KEY in your environment or .env file.")
else:
    print("✅ Google API key found - client will be created on demand")

# Cached model name for dynamic discovery (set on first use)
_CACHED_MODEL_NAME = None

def _get_genai_client():
    """Create a new genai Client with API key."""
    if not _GOOGLE_API_KEY:
        return None
    return genai.Client(api_key=_GOOGLE_API_KEY)

def _discover_model(client, prefer_flash: bool = True) -> Optional[str]:
    """
    Dynamically discover available model that supports generateContent.
    Caches the result for subsequent calls.
    
    Args:
        client: genai.Client instance
        prefer_flash: If True, prefer 'flash' models over others
    
    Returns:
        Model name string or None if no model found
    """
    global _CACHED_MODEL_NAME
    
    if _CACHED_MODEL_NAME:
        return _CACHED_MODEL_NAME
    
    try:
        # Fast path: try preferred model first without iterating all models
        for preferred in ("gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"):
            try:
                model_info = client.models.get(model=preferred)
                if model_info and "generateContent" in model_info.supported_actions:
                    _CACHED_MODEL_NAME = preferred
                    print(f"✅ Dinamik Model Keşfi: {_CACHED_MODEL_NAME} (preferred)")
                    return _CACHED_MODEL_NAME
            except Exception:
                pass

        flash_model = None
        fallback_model = None

        for model in client.models.list():
            if "generateContent" in model.supported_actions:
                model_name = model.name
                # Check if it's a flash model (faster/cheaper)
                if prefer_flash and "flash" in model_name.lower():
                    flash_model = model_name
                    break  # Found preferred flash model
                elif not fallback_model:
                    fallback_model = model_name

        _CACHED_MODEL_NAME = flash_model or fallback_model

        if _CACHED_MODEL_NAME:
            print(f"✅ Dinamik Model Keşfi: {_CACHED_MODEL_NAME}")
        else:
            print("❌ generateContent destekleyen model bulunamadı!")

        return _CACHED_MODEL_NAME
    except Exception as e:
        print(f"❌ Model discovery error: {e}")
        return None

# ============================================================================
# HELPER FUNCTION: Robust JSON Normalization
# ============================================================================
def ensure_dict(data):
    """
    Forces data to be a dictionary. If list, takes first item.
    
    CRITICAL FIX: Prevents AttributeError: 'list' object has no attribute 'get'
    when Gemini returns a list instead of a dict.
    
    Args:
        data: Any data (dict, list, or other)
    
    Returns:
        dict: Always returns a dictionary
    """
    if isinstance(data, list):
        # If list is not empty, take first item
        if data:
            first_item = data[0]
            # If first item is a dict, return it; otherwise return empty dict
            return first_item if isinstance(first_item, dict) else {}
        else:
            # Empty list -> empty dict
            return {}
    elif isinstance(data, dict):
        # Already a dict, return as-is
        return data
    else:
        # Other types (str, int, etc.) -> empty dict
        return {}


def clean_and_parse_json(raw_text: str) -> dict:
    """
    Architect-mandated cleaner.
    Removes Markdown fences, cleans whitespace, handles list wrapping.
    """
    if not raw_text:
        return {}
    
    # 1. Remove Markdown code blocks (```json ... ```)
    cleaned = re.sub(r"```json\s*", "", raw_text, flags=re.IGNORECASE)
    cleaned = re.sub(r"```", "", cleaned)
    
    # 2. Strip whitespace
    cleaned = cleaned.strip()
    
    # 3. Emergency Unwrap: If LLM returns a list [ {...} ], take the first item.
    if cleaned.startswith("[") and cleaned.endswith("]"):
        try:
            # Temporary parse to check if it is a list of dicts
            temp_parsed = json.loads(cleaned)
            if isinstance(temp_parsed, list) and len(temp_parsed) > 0:
                return temp_parsed[0]
        except:
            pass # Fallback to normal parsing if this fails

    # 4. Final Parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 5. Last Resort: Try to find the first '{' and last '}'
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(cleaned[start:end+1])
            except:
                pass
        return {} # Return empty dict instead of crashing


# Model discovery happens on first API call via _discover_model()
# This avoids startup errors and uses the new google-genai SDK
print("=== GEMINI MODEL DISCOVERY ===")
print("Model will be discovered dynamically on first API call (google-genai SDK)")
print("===============================\n")

# Common crypto symbols that need -USD suffix
CRYPTO_SYMBOLS = ['BTC', 'ETH', 'SOL', 'ADA', 'DOT', 'MATIC', 'AVAX', 'LINK', 'UNI', 'ATOM', 'XRP', 'DOGE', 'SHIB', 'LTC', 'BCH', 'XLM', 'ALGO', 'VET', 'TRX', 'ETC']

# Fallback message for when AI is unavailable
FALLBACK_AI_MESSAGE = "Şu anda gerçek zamanlı AI analizi yapılamıyor. Lütfen daha sonra tekrar deneyin."

# ========== JSON SAFE HELPER ==========
def _json_safe(obj):
    """
    Convert numpy types and other non-JSON-serializable types to native Python types.
    Recursively processes dicts, lists, tuples, and converts numpy scalars/arrays.
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj

# ========== LOCAL RATE LIMITING ==========
# datetime imported at top as _dt

# GOD MODE: Disabled internal budget limits - let Google API handle quotas
DAILY_REAL_CALL_LIMIT = 10000  # DISABLED: Was 10, now 10000 (effectively unlimited)
_daily_call_count = 0
_daily_call_date = None
_gemini_disabled_until = None  # datetime or None

def _reset_daily_counter_if_needed():
    """Reset daily counter if it's a new day."""
    global _daily_call_count, _daily_call_date
    today = date.today()
    if _daily_call_date != today:
        _daily_call_date = today
        _daily_call_count = 0

def _can_call_gemini_today() -> bool:
    """Check if we can make a Gemini call today (within daily limit and not disabled)."""
    global _gemini_disabled_until
    _reset_daily_counter_if_needed()
    
    now = _dt.now()
    if _gemini_disabled_until and now < _gemini_disabled_until:
        return False
    
    return _daily_call_count < DAILY_REAL_CALL_LIMIT

def _register_gemini_call():
    """Register a successful Gemini call."""
    global _daily_call_count
    _reset_daily_counter_if_needed()
    _daily_call_count += 1

# ========== UNIFIED GEMINI HELPER LAYER ==========

def get_gemini_model(name: Optional[str] = None, generation_config: Optional[dict] = None) -> Tuple[Any, str, Any]:
    """
    Get genai client, model name, and generation config for API calls.
    
    Uses new google-genai SDK with dynamic model discovery.
    
    Args:
        name: Model name (if None, will be discovered dynamically)
        generation_config: Generation config dict (may include response_mime_type, etc.)
    
    Returns:
        Tuple of (client, model_name, generation_config_object) or (None, None, None) if failed
    """
    if not _GOOGLE_API_KEY:
        return None, None, None
    
    client = _get_genai_client()
    if not client:
        return None, None, None
    
    # Use provided name or discover dynamically
    model_name_to_use = name or _discover_model(client, prefer_flash=True)
    if not model_name_to_use:
        print("❌ [get_gemini_model] No model available")
        return None, None, None
    
    # Build generation config using new SDK types
    config = generation_config or {}
    try:
        gen_config = genai_types.GenerateContentConfig(
            temperature=config.get("temperature", 0.7),
            top_p=config.get("top_p", 0.95),
            top_k=config.get("top_k", 64),
            max_output_tokens=config.get("max_output_tokens", 8192),
            response_mime_type=config.get("response_mime_type", "text/plain"),
        )
    except Exception as e:
        print(f"⚠️ [get_gemini_model] Config error: {e}")
        gen_config = None
    
    return client, model_name_to_use, gen_config


def dedupe_sentences(text: str) -> str:
    """
    Remove duplicate sentences from text while preserving order.
    
    Args:
        text: Input text that may contain duplicate sentences
    
    Returns:
        Text with duplicate sentences removed
    """
    if not text or not isinstance(text, str):
        return text
    
    # Split by sentence delimiters (period, exclamation, question mark, newline)
    import re
    sentences = re.split(r'[.!?\n]+', text)
    
    # Clean and filter empty sentences
    cleaned = []
    seen = set()
    for sent in sentences:
        sent = sent.strip()
        if sent and len(sent) > 3:  # Ignore very short fragments
            sent_lower = sent.lower()
            if sent_lower not in seen:
                seen.add(sent_lower)
                cleaned.append(sent)
    
    # Join with periods
    return '. '.join(cleaned) + '.' if cleaned else text


def dedupe_list_items(items: list) -> list:
    """
    Remove duplicate items from a list while preserving order.
    
    Args:
        items: List of strings that may contain duplicates
    
    Returns:
        List with duplicates removed
    """
    if not items or not isinstance(items, list):
        return items
    
    seen = set()
    result = []
    for item in items:
        if isinstance(item, str):
            item_lower = item.strip().lower()
            if item_lower and item_lower not in seen:
                seen.add(item_lower)
                result.append(item)
        else:
            result.append(item)
    
    return result


def gemini_text(prompt: str) -> dict:
    """
    Local, deterministic function for generating Turkish news comments.
    NO Gemini API calls - uses keyword-based sentiment detection.
    Returns: { "fallback": bool, "text": str }
    """
    import re
    
    print("[gemini_text] Local heuristic (no API call).")
    
    # Extract news title from prompt (first quoted string)
    title = None
    quoted_match = re.search(r'["\']([^"\']+)["\']', prompt)
    if quoted_match:
        title = quoted_match.group(1)
    else:
        # Fallback to prompt if parsing fails
        title = prompt[:100].strip()
    
    # Keyword-based sentiment detection
    bullish_keywords = ["surge", "jump", "beats", "beat", "record", "growth", "upgrade", "strong", 
                       "rally", "büyüme", "rekor", "artış", "talep", "kazanç", "pozitif", "yükseliş"]
    
    bearish_keywords = ["slump", "drop", "falls", "miss", "downgrade", "selloff", "risk", "warning",
                       "lawsuit", "fraud", "düşüş", "kayıp", "baskı", "negatif", "risk", "azalış", "daralma"]
    
    title_lower = title.lower()
    
    has_bullish = any(keyword in title_lower for keyword in bullish_keywords)
    has_bearish = any(keyword in title_lower for keyword in bearish_keywords)
    
    # Determine sentiment
    if has_bullish and not has_bearish:
        sentiment = "Bullish"
        comment = "Bullish - Başlık olumlu beklentiyi artırıyor ve fiyatı destekleyebilir."
    elif has_bearish and not has_bullish:
        sentiment = "Bearish"
        comment = "Bearish - Başlık aşağı yönlü riskleri artırıyor ve fiyatı baskılayabilir."
    else:
        sentiment = "Neutral"
        comment = "Neutral - Başlık net yön vermiyor; teyit için ek veri izlenmeli."
    
    # Always return success (no fallback since it's local)
    return {"fallback": False, "text": comment}

def _strip_code_fences(text: str) -> str:
    """
    Remove markdown code fences (```json ... ``` or ``` ... ```) from text.
    
    Args:
        text: Input text that may contain code fences
    
    Returns:
        Text with code fences removed
    """
    import re
    if not text or not isinstance(text, str):
        return text
    
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r'^```(?:json)?\s*\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```\s*$', '', text)
    
    return text.strip()


def _extract_json_object(text: str) -> Optional[str]:
    """
    Extract the first JSON object {...} from text, handling nested braces.
    
    Args:
        text: Input text that may contain JSON object
    
    Returns:
        Extracted JSON string or None if not found
    """
    import re
    if not text or not isinstance(text, str):
        return None
    
    # Find first { and match balanced braces
    start_idx = text.find('{')
    if start_idx == -1:
        return None
    
    brace_count = 0
    in_string = False
    escape_next = False
    
    for i in range(start_idx, len(text)):
        char = text[i]
        
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\':
            escape_next = True
            continue
        
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        
        if not in_string:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    # Found complete JSON object
                    return text[start_idx:i+1]
    
    return None


def _try_parse_json(text: str) -> Optional[dict]:
    """
    Try to parse JSON string, return dict on success, None on failure.
    
    Args:
        text: JSON string to parse
    
    Returns:
        Parsed dict or None if parsing fails
    """
    if not text or not isinstance(text, str):
        return None
    
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _sanitize_json_common(text: str) -> str:
    """
    Sanitize JSON string by removing control characters, fixing smart quotes, and trailing commas.
    
    Args:
        text: JSON string to sanitize
    
    Returns:
        Sanitized JSON string
    """
    import re
    if not text or not isinstance(text, str):
        return text
    
    # Remove control characters (except newline, tab, carriage return)
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
    
    # Replace smart quotes with regular quotes
    text = text.replace('"', '"').replace('"', '"')  # Smart double quotes
    text = text.replace(''', "'").replace(''', "'")  # Smart single quotes
    
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    
    return text


def _clean_json_response(raw: str) -> str:
    """
    Clean raw response for JSON parsing.
    Only removes markdown code fences if present.
    With response_mime_type="application/json", code fences should not appear.
    """
    import re
    
    if not raw:
        return raw
    
    # Strip whitespace
    text = raw.strip()
    
    # Remove markdown code fences (should not appear with response_mime_type="application/json")
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text, flags=re.MULTILINE)
    
    return text.strip()


# ============================================================================
# UNIFIED GEMINI CALL FUNCTION - NO JSON REPAIR
# ============================================================================

class GeminiCallError(Exception):
    """Exception raised when Gemini API call fails."""
    def __init__(self, message: str, reason: str, retry_after: Optional[float] = None):
        self.message = message
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(self.message)


def sanitize_json_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively remove JSON Schema keywords that Gemini doesn't accept.
    
    Removes: additionalProperties, maxLength, minLength, minimum, maximum,
    exclusiveMinimum, exclusiveMaximum, minItems, maxItems, pattern, format,
    oneOf, anyOf, allOf, not, $schema, $id, definitions, $defs, title, description
    
    Keeps only: type, properties, required, items, enum
    
    Args:
        schema: JSON Schema dict (may be nested)
    
    Returns:
        Sanitized schema dict compatible with Gemini
    """
    if not isinstance(schema, dict):
        return schema
    
    # Keywords to remove
    remove_keys = {
        "additionalProperties", "maxLength", "minLength",
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
        "minItems", "maxItems", "pattern", "format",
        "oneOf", "anyOf", "allOf", "not",
        "$schema", "$id", "definitions", "$defs", "title", "description"
    }
    
    # Keywords to keep
    keep_keys = {"type", "properties", "required", "items", "enum"}
    
    sanitized = {}
    
    for key, value in schema.items():
        if key in remove_keys:
            # Skip this key
            continue
        elif key in keep_keys:
            # Keep this key, but sanitize its value if needed
            if key == "properties" and isinstance(value, dict):
                # Recursively sanitize nested properties
                sanitized[key] = {
                    prop_key: sanitize_json_schema(prop_value)
                    for prop_key, prop_value in value.items()
                }
            elif key == "items" and isinstance(value, dict):
                # Recursively sanitize items schema
                sanitized[key] = sanitize_json_schema(value)
            elif key == "required" and isinstance(value, list):
                # Keep required as-is (list of strings)
                sanitized[key] = value
            elif key == "enum" and isinstance(value, list):
                # Keep enum as-is (list of allowed values)
                sanitized[key] = value
            elif key == "type":
                # Keep type as-is
                sanitized[key] = value
            else:
                # Unknown key in keep_keys - keep it as-is
                sanitized[key] = value
        else:
            # Unknown key - skip it (conservative approach)
            continue
    
    # If we have properties but no type, set type="object" (safe default)
    if "properties" in sanitized and "type" not in sanitized:
        sanitized["type"] = "object"
    
    return sanitized


def safe_gemini_call(
    prompt: str,
    *,
    response_mode: Literal["json", "text"] = "text",
    schema: Optional[Dict[str, Any]] = None,
    max_retries: int = 0,
    cooldown_policy: Optional[Dict[str, float]] = None,
    model_name: Optional[str] = None,
    temperature: float = 0.7,
    max_output_tokens: int = 8192,
    purpose: str = "generic",
    symbol: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not _GOOGLE_API_KEY:
        raise GeminiCallError("GOOGLE_API_KEY not set", reason="no_api_key")

    client = _get_genai_client()
    if not client:
        raise GeminiCallError("Client init failed", reason="no_client")

    discovered_model = model_name or _discover_model(client, prefer_flash=True)
    if not discovered_model:
        raise GeminiCallError("No model available", reason="no_model")

    time.sleep(5)

    # gemini-2.5-flash is a thinking model — disable thinking for JSON calls
    # so response.text contains only the JSON, not reasoning tokens
    thinking_config = None
    try:
        thinking_config = genai_types.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass  # SDK version doesn't support ThinkingConfig

    config_kwargs = dict(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
    )
    if thinking_config is not None:
        config_kwargs["thinking_config"] = thinking_config

    config = genai_types.GenerateContentConfig(**config_kwargs)

    global _CACHED_MODEL_NAME  # declared once at function scope
    # gemini-2.0-flash first: proven reliable JSON, non-thinking
    _FALLBACK_MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
    _API_MAX_RETRIES = 3

    last_api_error = None
    current_model = discovered_model
    for attempt in range(_API_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=current_model,
                contents=prompt,
                config=config,
            )
            # For thinking models: response.parts may have separate thought/text parts.
            # Collect only non-thought text parts to avoid reasoning tokens polluting JSON.
            raw = None
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "content") and candidate.content:
                    text_parts = []
                    for part in candidate.content.parts:
                        if hasattr(part, "thought") and part.thought:
                            continue  # skip thinking tokens
                        if hasattr(part, "text") and part.text:
                            text_parts.append(part.text)
                    if text_parts:
                        raw = "".join(text_parts)
            if not raw:
                raw = response.text  # fallback to convenience property
            if not raw:
                raise GeminiCallError("Empty response", reason="empty_response")
            print(f"[gemini] raw response (first 200): {raw[:200]}")
            _register_gemini_call()
            if current_model != discovered_model:
                _CACHED_MODEL_NAME = current_model
                print(f"✅ Switched to fallback model: {current_model}")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                start = raw.find("{")
                end = raw.rfind("}")
                if start != -1 and end != -1:
                    parsed = json.loads(raw[start:end + 1])
                else:
                    raise GeminiCallError("Invalid JSON response", reason="json_parse_error")
            if isinstance(parsed, list):
                return parsed[0] if parsed and isinstance(parsed[0], dict) else None
            return parsed if isinstance(parsed, dict) else None

        except GeminiCallError:
            raise
        except Exception as e:
            error_code = getattr(e, 'code', None) or getattr(e, 'status_code', None)
            error_str = str(e)
            is_429 = (error_code == 429) or ("429" in error_str) or ("RESOURCE_EXHAUSTED" in error_str) or ("quota" in error_str.lower()) or ("rate" in error_str.lower() and "limit" in error_str.lower())
            is_503 = (error_code == 503) or ("503" in error_str) or ("UNAVAILABLE" in error_str)
            is_404 = (error_code == 404) or ("404" in error_str) or ("NOT_FOUND" in error_str)
            if is_404:
                _CACHED_MODEL_NAME = None
                next_models = [m for m in _FALLBACK_MODELS if m != current_model]
                if next_models and attempt < _API_MAX_RETRIES:
                    current_model = next_models[attempt % len(next_models)]
                    print(f"⚠️ Gemini 404 on {current_model} (model not found), trying {current_model}...")
                    last_api_error = e
                    continue
            elif is_429:
                _CACHED_MODEL_NAME = None  # force re-discovery next call
                next_models = [m for m in _FALLBACK_MODELS if m != current_model]
                if next_models and attempt < _API_MAX_RETRIES:
                    current_model = next_models[attempt % len(next_models)]
                    print(f"⚠️ Gemini 429 on {discovered_model}, trying {current_model}...")
                    time.sleep(2)
                    last_api_error = e
                    continue
            elif is_503 and attempt < _API_MAX_RETRIES:
                wait = 2 ** (attempt + 1)
                print(f"⚠️ Gemini 503 (attempt {attempt+1}/{_API_MAX_RETRIES+1}), retrying in {wait}s...")
                time.sleep(wait)
                last_api_error = e
                continue
            print(f"❌ Gemini exception (code={error_code}): {error_str[:200]}")
            raise GeminiCallError(f"API error: {error_str[:100]}", reason=f"api_error_{error_code}")

    raise GeminiCallError(f"Failed after {_API_MAX_RETRIES} retries: {last_api_error}", reason="max_retries_exceeded")


def _get_safe_fallback(error_reason: str) -> None:
    print(f"❌ Gemini failed: {error_reason}")
    return None


# ============================================================================
# LLM USAGE TRACKING (Token estimation and cost calculation)
# ============================================================================

def estimate_token_count(text: str) -> int:
    """
    Estimate token count from text.
    Simple approximation: approx_tokens = ceil(len(text)/4)
    
    Args:
        text: Input text
    
    Returns:
        int: Estimated token count
    """
    import math
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def estimate_cost_usd(model: str, prompt_tokens: int, output_tokens: int) -> float:
    """
    Estimate cost in USD based on token counts.
    Uses environment variables for pricing (muhafazakar defaults).
    
    Args:
        model: Model name (e.g., "gemini-flash-latest")
        prompt_tokens: Number of prompt tokens
        output_tokens: Number of output tokens
    
    Returns:
        float: Estimated cost in USD
    """
    # Get pricing from environment variables (muhafazakar defaults)
    usd_per_1k_input = float(os.getenv("BORSA_LLM_USD_PER_1K_INPUT", "0.001"))
    usd_per_1k_output = float(os.getenv("BORSA_LLM_USD_PER_1K_OUTPUT", "0.002"))
    
    # Calculate cost
    input_cost = (prompt_tokens / 1000.0) * usd_per_1k_input
    output_cost = (output_tokens / 1000.0) * usd_per_1k_output
    
    return input_cost + output_cost


def check_llm_budget(purpose: str) -> Tuple[bool, str]:
    """
    Check if LLM call is allowed based on budget limits.
    
    **GOD MODE: BUDGET LIMITS DISABLED**
    This function now always returns (True, "allowed") to let Google API handle quotas.
    Internal software limits are removed - we trust Gemini 1.5 Flash's high quota.
    
    Args:
        purpose: Purpose of the call (for logging)
    
    Returns:
        Tuple[bool, str]: Always (True, "allowed") - budget checks disabled
    """
    # GOD MODE: Always allow - let Google API handle quota
    # We're using Gemini 1.5 Flash (high quota) - no need for internal limits
    return (True, "allowed")
    
    # DISABLED CODE (kept for reference):
    # try:
    #     # Get limits from environment (muhafazakar defaults)
    #     max_daily_calls = int(os.getenv("MAX_DAILY_LLM_CALLS", "2"))
    #     max_monthly_usd = float(os.getenv("MAX_MONTHLY_USD", "5.0"))
    #     
    #     # Check daily calls
    #     conn = get_connection()
    #     cursor = conn.cursor()
    #     
    #     today = _dt.now().strftime("%Y-%m-%d")
    #     cursor.execute("""
    #         SELECT COUNT(*) 
    #         FROM llm_usage_log
    #         WHERE date(created_at) = date(?)
    #     """, (today,))
    #     
    #     daily_count = cursor.fetchone()[0]
    #     if daily_count >= max_daily_calls:
    #         conn.close()
    #         return (False, "daily_limit")
    #     
    #     # Check monthly USD
    #     now = _dt.now()
    #     monthly_usage = get_monthly_llm_usage(now.year, now.month)
    #     if monthly_usage["total_cost_usd"] >= max_monthly_usd:
    #         conn.close()
    #         return (False, "monthly_limit")
    #     
    #     conn.close()
    #     return (True, "allowed")
    #     
    # except Exception as e:
    #     import logging
    #     logger = logging.getLogger(__name__)
    #     logger.error(f"❌ Failed to check LLM budget: {e}", exc_info=True)
    #     # On error, allow call (fail open)
    #     return (True, "allowed")


# ========== LEGACY COMPATIBILITY FUNCTIONS ==========
# gemini_json function removed - use safe_gemini_call(response_mode="json", schema=MASTER_ANALYSIS_SCHEMA) instead

def call_gemini_safe(prompt, use_json_mode=True):
    """
    Legacy function for backward compatibility.
    Returns: Response text or None if failed
    """
    if use_json_mode:
        try:
            result = safe_gemini_call(prompt, response_mode="json", max_retries=1, purpose="generic")
            return json.dumps(result) if isinstance(result, dict) else str(result)
        except GeminiCallError:
            return None
    else:
        result = gemini_text(prompt)
        if result["fallback"]:
            return None
        return result["text"]

def build_symbol_memory_context(symbol: str, limit: int = 5) -> str:
    """
    Builds a compact natural language summary of the last N AI analyses
    for this symbol, to be injected into the Gemini prompt.
    """
    try:
        history = get_symbol_analysis_history(symbol, limit)
    except Exception as e:
        print(f"⚠️ build_symbol_memory_context error: {e}")
        return ""
    
    if not history:
        return ""
    
    lines = ["\nÖNCEKİ AI ANALİZ GEÇMİŞİ:"]
    for row in history:
        dt = row.get("created_at") or row.get("date") or row.get("tarih") or "?"
        price = row.get("price_at_analysis") or row.get("fiyat") or "?"
        decision = row.get("ai_decision") or row.get("karar") or "?"
        score = row.get("confidence_score") or row.get("guven_skoru") or "?"
        reason = (row.get("ai_reasoning") or row.get("ana_neden") or "")[:200]
        lines.append(
            f"- {dt}: Fiyat=${price}, Karar={decision}, Güven={score} | Özet Neden: {reason}"
        )
    
    return "\n".join(lines)

def normalize_symbol(symbol: str, mode: Optional[str] = None) -> str:
    """
    Normalize symbol for yfinance. Auto-append -USD for crypto if needed.
    
    DEPRECATED: Use data_provider.normalize_symbol() for robust normalization.
    This function is kept for backward compatibility.
    """
    # Import robust normalization
    try:
        from .data_provider import normalize_symbol as robust_normalize
        normalized, _ = robust_normalize(symbol, mode)
        return normalized
    except Exception:
        # Fallback to simple normalization
        symbol_upper = symbol.upper().strip()
        
        # If already has -USD suffix, return as is
        if symbol_upper.endswith('-USD'):
            return symbol_upper
        
        # Check if it's a known crypto symbol
        if symbol_upper in CRYPTO_SYMBOLS:
            return f"{symbol_upper}-USD"
        
        # Return as is for stocks
        return symbol_upper

def is_crypto(symbol: str) -> bool:
    """Check if symbol is a cryptocurrency."""
    symbol_upper = symbol.upper().strip()
    return symbol_upper.endswith('-USD') or symbol_upper in CRYPTO_SYMBOLS

def get_market_data():
    try:
        vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        spy = yf.Ticker("^GSPC").history(period="2d")
        change = ((spy['Close'].iloc[-1] - spy['Close'].iloc[-2]) / spy['Close'].iloc[-2]) * 100
        return {"vix": round(vix, 2), "piyasa_durumu": "POZİTİF" if change > 0 else "NEGATİF"}
    except: return {"vix": 0, "piyasa_durumu": "N/A"}


def _get_price_yahoo_direct(symbol: str):
    """Bypass yfinance library; call Yahoo Finance v8 chart API directly."""
    try:
        import requests as _req
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        r = _req.get(url, headers=headers, timeout=8).json()
        meta = r["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        return float(price) if price else None
    except Exception:
        return None


def _get_price_alpha_vantage(symbol: str):
    try:
        import requests as _requests
        import os as _os
        av_key = _os.environ.get("ALPHA_VANTAGE_API_KEY", "demo")
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={av_key}"
        r = _requests.get(url, timeout=5).json()
        price = r.get("Global Quote", {}).get("05. price")
        return float(price) if price else None
    except Exception:
        return None


def get_live_technicals(symbol: str) -> Dict[str, Any]:
    if not symbol or not symbol.strip():
        return {"price": "N/A", "rsi": "N/A", "sma": "N/A"}

    yf_data = None
    try:
        is_crypto_sym = symbol.endswith("-USD") or symbol in ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA")
        yf_sym = symbol if "-" in symbol else (f"{symbol}-USD" if is_crypto_sym else symbol)
        hist = yf.Ticker(yf_sym).history(period="1mo")
        if not hist.empty:
            close = hist["Close"]
            price = round(float(close.iloc[-1]), 4)
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi_val = 100 - (100 / (1 + rs))
            rsi = round(float(rsi_val.iloc[-1]), 2) if not rsi_val.empty else "N/A"
            sma = round(float(close.rolling(20).mean().iloc[-1]), 4)
            yf_data = {"price": price, "rsi": rsi, "sma": sma}
    except Exception as e:
        print(f"⚠️ [get_live_technicals] yfinance failed for {symbol}: {e}")

    if yf_data:
        return yf_data

    print(f"⚠️ [get_live_technicals] falling back to Alpha Vantage for {symbol}")
    av_price = _get_price_alpha_vantage(symbol)
    return {"price": av_price if av_price is not None else "N/A", "rsi": "N/A", "sma": "N/A"}


def get_technical_data_for_news(symbol: str) -> Dict[str, Any]:
    return get_live_technicals(symbol)


_NEWS_SYMBOL_KEYWORDS: dict[str, list[str]] = {
    "NVDA":  ["nvidia", "nvda"],
    "AAPL":  ["apple", "aapl", "iphone", "ipad", "macbook"],
    "GOOGL": ["google", "googl", "alphabet", "goog"],
    "TSLA":  ["tesla", "tsla", "elon musk"],
    "MSFT":  ["microsoft", "msft", "azure", "windows"],
    "AMZN":  ["amazon", "amzn", "aws"],
    "META":  ["meta", "facebook", "instagram", "whatsapp"],
    "AMD":   ["amd", "advanced micro"],
    "INTC":  ["intel", "intc"],
    "QCOM":  ["qualcomm", "qcom"],
    "MRVL":  ["marvell", "mrvl"],
    "PLTR":  ["palantir", "pltr"],
    "NFLX":  ["netflix", "nflx"],
    "ORCL":  ["oracle", "orcl"],
    "CRM":   ["salesforce", "crm"],
    "COIN":  ["coinbase", "coin"],
}


def _clean_symbol(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip()
    if 1 <= len(s) <= 5 and s.isupper() and s.isalpha():
        return s
    text_lower = s.lower()
    for sym, keywords in _NEWS_SYMBOL_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return sym
    return None


def analyze_news_with_gemini(symbol: str, news_text: str) -> Optional[Dict[str, Any]]:
    if not _GOOGLE_API_KEY:
        print("❌ GOOGLE_API_KEY not set")
        return None

    clean = _clean_symbol(symbol)
    if not clean:
        print(f"⚠️ [analyze_news_with_gemini] unresolvable symbol: {symbol!r:.60}")
        return None
    symbol = clean

    tech = get_live_technicals(symbol)
    price = tech.get("price", "N/A")
    rsi = tech.get("rsi", "N/A")
    sma = tech.get("sma", "N/A")

    prompt = (
        f"You are a professional stock trader. Analyze the news and technical data below. "
        f"Respond in Turkish. Give a clear BUY/SELL/HOLD recommendation. "
        f"Include specific price action advice. Be direct and opinionated like a professional trader. "
        f"Respond ONLY with valid JSON, no extra text.\n\n"
        f"Symbol: {symbol}\n"
        f"News: {news_text}\n"
        f"Price: {price}\n"
        f"RSI(14): {rsi}\n"
        f"SMA(20): {sma}\n\n"
        f"Return exactly this JSON structure (all string values in Turkish, concise under 120 chars each):\n"
        f'{{"symbol":"{symbol}","impact":"POSITIVE/NEGATIVE/NEUTRAL","decision":"AL/SAT/TUT",'
        f'"reason":"2-3 cümle Türkçe yorumlu analiz","risk_level":"DÜŞÜK/ORTA/YÜKSEK",'
        f'"risk_detail":"kısa risk notu","action_plan":"somut fiyat hareketi tavsiyesi (seviye belirt)",'
        f'"mentor_scenario":"mentor yorumu Türkçe","technical_rsi":"{rsi}","technical_resistance":"{sma}"}}'
    )

    client = _get_genai_client()
    if not client:
        return None

    model_name = None
    for m in client.models.list():
        name = getattr(m, "name", "") or ""
        if "flash" in name.lower() and "generateContent" in (getattr(m, "supported_actions", None) or []):
            model_name = name
            break
    if not model_name:
        for m in client.models.list():
            if "generateContent" in (getattr(m, "supported_actions", None) or []):
                model_name = getattr(m, "name", None)
                break
    if not model_name:
        raise RuntimeError("Kullanılabilir Gemini modeli bulunamadı")

    time.sleep(3)

    config = genai_types.GenerateContentConfig(
        temperature=0.4,
        max_output_tokens=2048,
        response_mime_type="application/json",
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
        raw = response.text
        if not raw:
            return None
        _register_gemini_call()
        result = json.loads(raw)
        if isinstance(result, list):
            result = result[0] if result else None
        if not isinstance(result, dict):
            return None
        result.setdefault("symbol", symbol)
        result.setdefault("technical_rsi", str(rsi))
        result.setdefault("technical_resistance", str(sma))
        return result
    except Exception as e:
        raise RuntimeError(f"[analyze_news_with_gemini] {symbol}: {e}") from e

def get_last_known_price_from_db(symbol: str) -> Optional[float]:
    """
    Get last known price from database as fallback when yfinance fails.
    
    Checks in order:
    1. Recent analysis (last 24 hours)
    2. Cached market bars (last bar close price)
    
    Args:
        symbol: Stock/crypto symbol
    
    Returns:
        float: Last known price or None if not found
    """
    try:
        # Try 1: Get from recent analysis
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT price_at_analysis
            FROM analysis_history
            WHERE symbol = ? AND created_at >= datetime('now', '-24 hours')
            ORDER BY created_at DESC
            LIMIT 1
        """, (symbol.upper(),))
        row = cursor.fetchone()
        if row and row[0]:
            conn.close()
            price = float(row[0])
            print(f"[DB_FALLBACK] Using last known price from analysis: ${price} for {symbol}")
            return price
        
        # Try 2: Get from cached market bars (last close)
        try:
            bars = get_cached_market_bars(symbol, "STOCK", "1d", limit=1)
            if bars and len(bars) > 0:
                last_bar = bars[-1]
                close_price = last_bar.get("close")
                if close_price and close_price > 0:
                    conn.close()
                    print(f"[DB_FALLBACK] Using last cached bar close: ${close_price} for {symbol}")
                    return float(close_price)
        except Exception:
            pass
        
        conn.close()
        return None
        
    except Exception as e:
        print(f"⚠️ get_last_known_price_from_db error for {symbol}: {e}")
        return None


def get_technical_metrics(symbol):
    """
    Get technical metrics including extended hours (pre/post market) data.

    Enhanced with DB fallback: If yfinance fails, uses last known price from database.
    """
    try:
        normalized_symbol = normalize_symbol(symbol)
        import logging as _logging
        _logging.getLogger("yfinance").setLevel(_logging.CRITICAL)
        stock = yf.Ticker(normalized_symbol)
        hist = stock.history(period="1mo")
        if hist.empty:
            raise ValueError(f"yfinance returned empty history for {normalized_symbol}")
        current = hist['Close'].iloc[-1]
        
        # Get extended hours data (pre/post market) - NEW FEATURE
        pre_market_price = None
        post_market_price = None
        active_price_type = "regular"  # regular, pre_market, post_market
        
        try:
            # Get today's data with extended hours
            info = stock.info
            # Try to get pre/post market prices from info or recent history
            extended_hist = stock.history(period="1d", interval="1m", prepost=True)
            
            if not extended_hist.empty:
                # Get regular session close
                regular_close = hist['Close'].iloc[-1] if not hist.empty else None
                
                # Get pre-market data (before 9:30 AM ET / 4:30 PM Istanbul)
                # Get post-market data (after 4:00 PM ET / 11:00 PM Istanbul)
                try:
                    import pytz
                    # Get current time in market timezone
                    market_tz = pytz.timezone('America/New_York')
                    current_time_et = _dt.now(market_tz)
                    
                    # Market hours: 9:30 AM - 4:00 PM ET
                    hour_et = current_time_et.hour
                    minute_et = current_time_et.minute
                except ImportError:
                    # Fallback if pytz not available
                    hour_et = _dt.now().hour - 5  # Approximate EST (UTC-5)
                    minute_et = _dt.now().minute
                
                # Check if we have extended hours data
                if not extended_hist.empty:
                    latest_close = extended_hist['Close'].iloc[-1]
                    
                    # If current time is before market open, it's pre-market
                    if hour_et < 9 or (hour_et == 9 and minute_et < 30):
                        pre_market_price = float(latest_close)
                        active_price_type = "pre_market"
                    # If current time is after market close, it's post-market
                    elif hour_et >= 16:
                        post_market_price = float(latest_close)
                        active_price_type = "post_market"
                
                # Fallback: try to get from info dict
                if pre_market_price is None and post_market_price is None:
                    if 'preMarketPrice' in info and info['preMarketPrice']:
                        pre_market_price = float(info['preMarketPrice'])
                        if hour_et < 9 or (hour_et == 9 and minute_et < 30):
                            active_price_type = "pre_market"
                    if 'postMarketPrice' in info and info['postMarketPrice']:
                        post_market_price = float(info['postMarketPrice'])
                        if hour_et >= 16:
                            active_price_type = "post_market"
        except Exception as ext_error:
            print(f"⚠️ Extended hours data not available for {symbol}: {ext_error}")
            # Continue without extended hours data
        
        # RSI
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        # Bollinger Bands (SMA 20)
        sma20 = hist['Close'].rolling(window=20).mean()
        std = hist['Close'].rolling(window=20).std()
        upper = sma20 + (std * 2)
        lower = sma20 - (std * 2)

        # MACD (12, 26, 9)
        ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
        ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        # Moving Averages
        sma50 = hist['Close'].rolling(window=50).mean()
        sma200 = hist['Close'].rolling(window=200).mean()

        # Momentum (10)
        momentum10 = hist['Close'].diff(10)

        # Stochastic %K (14,3)
        low14 = hist['Low'].rolling(window=14).min()
        high14 = hist['High'].rolling(window=14).max()
        stoch_k = 100 * (hist['Close'] - low14) / (high14 - low14 + 1e-10)

        # Format price based on value
        crypto = is_crypto(symbol)
        if crypto:
            if current < 1:
                price_precision = 6
            elif current < 100:
                price_precision = 4
            else:
                price_precision = 2
        else:
            price_precision = 2

        def _safe_val(series, precision=2):
            try:
                v = series.iloc[-1]
                return round(float(v), precision) if v == v else None  # NaN check
            except Exception:
                return None

        # Determine which price to show as "current"
        if active_price_type == "pre_market" and pre_market_price:
            display_price = pre_market_price
        elif active_price_type == "post_market" and post_market_price:
            display_price = post_market_price
        else:
            display_price = current

        return {
            "fiyat": round(current, price_precision),
            "current_price": round(display_price, price_precision),
            "pre_market_price": round(pre_market_price, price_precision) if pre_market_price else None,
            "post_market_price": round(post_market_price, price_precision) if post_market_price else None,
            "active_price_type": active_price_type,
            "rsi": _safe_val(rsi),
            "bb_alt": _safe_val(lower, price_precision),
            "bb_ust": _safe_val(upper, price_precision),
            "bb_orta": _safe_val(sma20, price_precision),
            "macd": _safe_val(macd_line, 4),
            "macd_signal": _safe_val(macd_signal, 4),
            "macd_hist": _safe_val(macd_hist, 4),
            "momentum": _safe_val(momentum10, price_precision),
            "stoch_k": _safe_val(stoch_k),
            "sma20": _safe_val(sma20, price_precision),
            "sma50": _safe_val(sma50, price_precision),
            "sma200": _safe_val(sma200, price_precision),
        }
    except Exception as e:
        print(f"⚠️ Technical metrics error for {symbol}: {e}")
        
        # YAHOO DIRECT FALLBACK (priority 1 - same source, no lib dependency)
        yh_price = _get_price_yahoo_direct(symbol)
        if yh_price and yh_price > 0:
            print(f"✅ Using Yahoo Direct fallback price: ${yh_price} for {symbol}")
            return {
                "fiyat": yh_price,
                "current_price": yh_price,
                "pre_market_price": None,
                "post_market_price": None,
                "active_price_type": "yahoo_direct",
                "rsi": 50,
                "bb_alt": round(yh_price * 0.95, 2),
                "bb_ust": round(yh_price * 1.05, 2),
            }

        # DB FALLBACK: Try to get last known price from database
        fallback_price = get_last_known_price_from_db(symbol)
        if fallback_price and fallback_price > 0:
            print(f"✅ Using DB fallback price: ${fallback_price} for {symbol}")
            return {
                "fiyat": fallback_price,
                "current_price": fallback_price,
                "pre_market_price": None,
                "post_market_price": None,
                "active_price_type": "db_fallback",
                "rsi": 50,
                "bb_alt": round(fallback_price * 0.95, 2),
                "bb_ust": round(fallback_price * 1.05, 2),
            }

        # ALPHA VANTAGE FALLBACK: try external API
        av_price = _get_price_alpha_vantage(symbol)
        if av_price and av_price > 0:
            print(f"✅ Using Alpha Vantage fallback price: ${av_price} for {symbol}")
            return {
                "fiyat": av_price,
                "current_price": av_price,
                "pre_market_price": None,
                "post_market_price": None,
                "active_price_type": "av_fallback",
                "rsi": 50,
                "bb_alt": round(av_price * 0.95, 2),
                "bb_ust": round(av_price * 1.05, 2),
            }

        # No fallback available - return zeros
        return {"fiyat": 0, "current_price": 0, "pre_market_price": None, "post_market_price": None, "active_price_type": "regular", "rsi": 0, "bb_alt": 0, "bb_ust": 0}

def calculate_fair_value(symbol):
    """Calculate Fair Value using Graham Number formula."""
    try:
        normalized_symbol = normalize_symbol(symbol)
        stock = yf.Ticker(normalized_symbol)
        info = stock.info
        
        eps = info.get('trailingEps', None)
        book_value = info.get('bookValue', None)
        
        # Graham Number: sqrt(22.5 * EPS * Book Value per Share)
        if eps and book_value and eps > 0 and book_value > 0:
            graham_number = np.sqrt(22.5 * eps * book_value)
            return round(graham_number, 2)
        
        # Fallback: Use P/E and expected growth
        trailing_pe = info.get('trailingPE', None)
        earnings_growth = info.get('earningsQuarterlyGrowth', None)
        
        if trailing_pe and earnings_growth and trailing_pe > 0:
            current_price = info.get('currentPrice', None)
            if current_price:
                # Simple valuation: Price * (1 + growth) / PE
                fair_value = current_price * (1 + (earnings_growth or 0.1)) / trailing_pe
                return round(fair_value, 2)
        
        return None
    except Exception as e:
        print(f"⚠️ Fair value calculation error: {e}")
        return None

def get_insider_moves(ticker):
    """
    Intelligent Whale Radar: Get insider transactions with value calculation.
    Filters to show only significant moves (>$50k value).
    Returns: List of dicts with Date, Insider Name, Type (Buy/Sell), and Value.
    """
    try:
        normalized_symbol = normalize_symbol(ticker)
        stock = yf.Ticker(normalized_symbol)
        
        # Get current price to calculate transaction value
        try:
            hist = stock.history(period="5d")
            if len(hist) > 0:
                current_price = hist['Close'].iloc[-1]
            else:
                info = stock.info
                current_price = info.get('currentPrice', 0) if info else 0
        except:
            current_price = 0
        
        significant_moves = []
        
        try:
            insider_data = stock.insider_transactions
            if insider_data is not None and hasattr(insider_data, '__len__') and len(insider_data) > 0:
                if isinstance(insider_data, pd.DataFrame):
                    # Get most recent transactions
                    recent = insider_data.head(50) if len(insider_data) > 50 else insider_data
                    
                    for idx, row in recent.iterrows():
                        # Extract person name
                        person = "N/A"
                        for col in ['Name', 'Insider', 'Person', 'Officer']:
                            if col in row and pd.notna(row[col]):
                                person = str(row[col])
                                break
                        
                        # Extract transaction type
                        transaction_type = ""
                        transaction_code = ""
                        for col in ['Transaction', 'TransactionCode', 'Type']:
                            if col in row and pd.notna(row[col]):
                                if col == 'TransactionCode':
                                    transaction_code = str(row[col])
                                else:
                                    transaction_type = str(row[col])
                        
                        # Determine if BUY or SELL
                        is_buy = False
                        transaction_lower = transaction_type.lower() if transaction_type else ""
                        code_str = str(transaction_code).upper() if transaction_code else ""
                        
                        if any(word in transaction_lower for word in ["purchase", "buy", "acquisition", "option", "award"]):
                            is_buy = True
                        elif any(word in transaction_lower for word in ["sale", "sell", "disposition", "disposal"]):
                            is_buy = False
                        elif "P" in code_str or "A" in code_str:
                            is_buy = True
                        elif "S" in code_str or "D" in code_str:
                            is_buy = False
                        
                        # Extract shares
                        shares = 0
                        for col in ['Shares', 'Quantity', 'Amount']:
                            if col in row and pd.notna(row[col]):
                                try:
                                    shares = int(float(row[col]))
                                    break
                                except:
                                    pass
                        
                        # Extract price per share (if available)
                        price_per_share = current_price
                        for col in ['Price', 'Transaction Price', 'Value']:
                            if col in row and pd.notna(row[col]):
                                try:
                                    price_per_share = float(row[col])
                                    break
                                except:
                                    pass
                        
                        # Calculate transaction value
                        transaction_value = shares * price_per_share if shares > 0 and price_per_share > 0 else 0
                        
                        # Filter: Only significant moves (>$50k)
                        if transaction_value >= 50000:
                            # Extract date
                            date_str = "N/A"
                            for col in ['Date', 'Transaction Date', 'Filing Date']:
                                if col in row and pd.notna(row[col]):
                                    try:
                                        if isinstance(row[col], pd.Timestamp):
                                            date_str = row[col].strftime("%Y-%m-%d")
                                        else:
                                            date_str = str(row[col])
                                        break
                                    except:
                                        pass
                            
                            significant_moves.append({
                                "date": date_str,
                                "insider_name": person,
                                "type": "Buy" if is_buy else "Sell",
                                "value": round(transaction_value, 2),
                                "shares": shares,
                                "price_per_share": round(price_per_share, 2)
                            })
        except Exception as e1:
            print(f"⚠️ Error fetching insider transactions: {e1}")
        
        # Sort by date (most recent first) and value (highest first)
        significant_moves.sort(key=lambda x: (x["date"], -x["value"]), reverse=True)
        
        return significant_moves
    except Exception as e:
        print(f"⚠️ Insider moves error: {e}")
        return []

def get_insider_transactions_detailed(symbol):
    """Get detailed insider transactions for a stock. Returns list of transactions."""
    try:
        normalized_symbol = normalize_symbol(symbol)
        stock = yf.Ticker(normalized_symbol)
        
        transactions = []
        
        # Try to get insider transactions
        try:
            insider_data = stock.insider_transactions
            if insider_data is not None and hasattr(insider_data, '__len__') and len(insider_data) > 0:
                if isinstance(insider_data, pd.DataFrame):
                    # Get most recent 20 transactions
                    recent = insider_data.head(20) if len(insider_data) > 20 else insider_data
                    
                    for idx, row in recent.iterrows():
                        # Extract person name (try multiple column names)
                        person = "N/A"
                        for col in ['Name', 'Insider', 'Person', 'Officer']:
                            if col in row and pd.notna(row[col]):
                                person = str(row[col])
                                break
                        
                        # Extract transaction type
                        transaction_type = ""
                        transaction_code = ""
                        for col in ['Transaction', 'TransactionCode', 'Type']:
                            if col in row and pd.notna(row[col]):
                                if col == 'TransactionCode':
                                    transaction_code = str(row[col])
                                else:
                                    transaction_type = str(row[col])
                        
                        # Determine if BUY or SELL
                        is_buy = False
                        transaction_lower = transaction_type.lower() if transaction_type else ""
                        code_str = str(transaction_code).upper() if transaction_code else ""
                        
                        if any(word in transaction_lower for word in ["purchase", "buy", "acquisition", "option", "award"]):
                            is_buy = True
                        elif any(word in transaction_lower for word in ["sale", "sell", "disposition", "disposal"]):
                            is_buy = False
                        elif "P" in code_str or "A" in code_str:
                            is_buy = True
                        elif "S" in code_str or "D" in code_str:
                            is_buy = False
                        
                        # Extract shares
                        shares = 0
                        for col in ['Shares', 'Quantity', 'Amount']:
                            if col in row and pd.notna(row[col]):
                                try:
                                    shares = int(float(row[col]))
                                    break
                                except:
                                    pass
                        
                        # Extract date
                        date_str = "N/A"
                        for col in ['Date', 'Transaction Date', 'Filing Date']:
                            if col in row and pd.notna(row[col]):
                                try:
                                    if isinstance(row[col], pd.Timestamp):
                                        date_str = row[col].strftime("%Y-%m-%d")
                                    else:
                                        date_str = str(row[col])
                                    break
                                except:
                                    pass
                        
                        transactions.append({
                            "person": person,
                            "type": "BUY" if is_buy else "SELL",
                            "shares": shares,
                            "date": date_str
                        })
        except Exception as e1:
            print(f"⚠️ Error fetching insider transactions: {e1}")
        
        return transactions
    except Exception as e:
        print(f"⚠️ Insider transactions error: {e}")
        return []

def get_insider_intelligence(symbol):
    """Analyze insider transactions for the last 3 months. Returns summary string for backward compatibility."""
    try:
        transactions = get_insider_transactions_detailed(symbol)
        
        if not transactions:
            # Fallback to old method
            normalized_symbol = normalize_symbol(symbol)
            stock = yf.Ticker(normalized_symbol)
            
            try:
                major_holders = stock.major_holders
                if major_holders is not None:
                    return "Büyük yatırımcılar aktif (detaylı insider verisi yok)"
            except:
                pass
            
            try:
                institutional_holders = stock.institutional_holders
                if institutional_holders is not None and len(institutional_holders) > 0:
                    return "Kurumsal yatırımcılar aktif"
            except:
                pass
            
            return "Insider verisi mevcut değil"
        
        buy_count = sum(1 for t in transactions if t["type"] == "BUY")
        sell_count = sum(1 for t in transactions if t["type"] == "SELL")
        
        if buy_count > sell_count:
            return f"POZİTİF - Son dönemde {buy_count} alım, {sell_count} satım"
        elif sell_count > buy_count:
            return f"NEGATİF - Son dönemde {sell_count} satım, {buy_count} alım"
        else:
            return "NÖTR - Alım ve satım dengeli"
    except Exception as e:
        print(f"⚠️ Insider intelligence error: {e}")
        return "Analiz edilemedi"

def get_earnings_info(symbol):
    """Fetch next earnings date and analyst estimates."""
    try:
        normalized_symbol = normalize_symbol(symbol)
        stock = yf.Ticker(normalized_symbol)
        
        # Get earnings calendar
        try:
            calendar = stock.calendar
            if calendar is not None and len(calendar) > 0:
                next_earnings = calendar.iloc[0] if hasattr(calendar, 'iloc') else calendar[0]
                earnings_date = next_earnings.get('Earnings Date', None) if isinstance(next_earnings, dict) else None
                
                if earnings_date:
                    return {
                        "bilanco_tarihi": str(earnings_date),
                        "analyst_estimates": "Mevcut"
                    }
        except:
            pass
        
        # Fallback: Check info
        info = stock.info
        earnings_date = info.get('nextFiscalYearEnd', None) or info.get('exDividendDate', None)
        
        return {
            "bilanco_tarihi": str(earnings_date) if earnings_date else "Bilinmiyor",
            "analyst_estimates": "Mevcut" if info.get('targetMeanPrice') else "Yok"
        }
    except Exception as e:
        print(f"⚠️ Earnings info error: {e}")
        return {
            "bilanco_tarihi": "Bilinmiyor",
            "analyst_estimates": "Yok"
        }

def get_competitor_analysis(symbol):
    """Scan competitors and compare key metrics."""
    try:
        normalized_symbol = normalize_symbol(symbol)
        stock = yf.Ticker(normalized_symbol)
        info = stock.info
        
        # Get sector and industry
        sector = info.get('sector', '')
        industry = info.get('industry', '')
        
        # Common competitor mappings
        competitor_map = {
            'NVDA': ['AMD', 'INTC', 'TSM'],
            'AAPL': ['MSFT', 'GOOGL', 'Samsung'],
            'TSLA': ['F', 'GM', 'RIVN'],
            'MSFT': ['GOOGL', 'AAPL', 'AMZN'],
            'GOOGL': ['MSFT', 'META', 'AAPL'],
            'META': ['GOOGL', 'SNAP', 'TWTR'],
            'AMD': ['NVDA', 'INTC', 'QCOM'],
            'INTC': ['AMD', 'NVDA', 'TSM']
        }
        
        competitors = competitor_map.get(normalized_symbol, [])
        
        if not competitors:
            # Try to get from yfinance
            try:
                competitors_data = stock.recommendations
                if competitors_data is not None:
                    # Fallback: use sector average
                    return f"Sektör: {sector}, Endüstri: {industry}. Detaylı rakip analizi için yeterli veri yok."
            except:
                pass
        
        # Compare with competitors
        current_pe = info.get('trailingPE', None)
        current_margin = info.get('profitMargins', None)
        
        competitor_data = []
        for comp_symbol in competitors[:3]:  # Top 3 competitors
            try:
                comp_stock = yf.Ticker(comp_symbol)
                comp_info = comp_stock.info
                comp_pe = comp_info.get('trailingPE', None)
                comp_margin = comp_info.get('profitMargins', None)
                
                competitor_data.append({
                    'symbol': comp_symbol,
                    'pe': comp_pe,
                    'margin': comp_margin
                })
            except:
                continue
        
        # Create summary
        if competitor_data:
            avg_pe = np.mean([c['pe'] for c in competitor_data if c['pe']])
            avg_margin = np.mean([c['margin'] for c in competitor_data if c['margin']])
            
            comparison = f"Rakip Ortalaması: P/E {round(avg_pe, 2) if avg_pe else 'N/A'}, Kar Marjı {round(avg_margin*100, 2) if avg_margin else 'N/A'}%"
            if current_pe and avg_pe:
                if current_pe < avg_pe:
                    comparison += " - Bu hisse daha ucuz görünüyor."
                else:
                    comparison += " - Bu hisse daha pahalı görünüyor."
            
            return comparison
        
        return f"Sektör: {sector}. Rakip karşılaştırması için yeterli veri yok."
    except Exception as e:
        print(f"⚠️ Competitor analysis error: {e}")
        return "Rakip analizi yapılamadı"

def get_fundamental_data(symbol):
    """
    Fetch FULL fundamental analysis data from yfinance (UNSHACKLED VERSION).
    
    Now fetches comprehensive valuation, financial health, and analyst data:
    - Valuation: PE ratios (forward/trailing), PEG, Price/Book, Price/Sales
    - Financial Health: Market Cap, EBITDA Margins, Debt/Equity, ROE
    - Analyst Data: Target prices, recommendations, number of analysts
    - Sector/Industry context for peer comparison
    - Graham Number (fair value estimate)
    
    Handles both stocks and crypto.
    """
    try:
        normalized_symbol = normalize_symbol(symbol)
        crypto = is_crypto(symbol)
        stock = yf.Ticker(normalized_symbol)
        
        # Add retry logic for .info (can fail intermittently)
        info = None
        for attempt in range(3):  # 3 attempts
            try:
                info = stock.info
                if info and isinstance(info, dict) and len(info) > 5:
                    break
                print(f"⚠️ yfinance .info returned incomplete data for {normalized_symbol} (attempt {attempt + 1}/3)")
            except Exception as e:
                print(f"⚠️ yfinance .info failed for {normalized_symbol} (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(0.5)  # Brief delay before retry
        
        if not info or not isinstance(info, dict):
            info = {}
        
        # For crypto, these metrics don't exist
        if crypto:
            # Crypto-specific metrics (if available)
            market_cap = info.get('marketCap', None)
            volume_24h = info.get('volume24Hr', None)
            circulating_supply = info.get('circulatingSupply', None)
            
            return {
                "f_k_orani": None,  # Crypto doesn't have P/E ratio
                "analist_hedef_fiyat": None,  # Crypto doesn't have analyst targets
                "analist_tavsiyesi": "KRİPTO PARA",  # Crypto indicator
                "market_cap": market_cap,
                "volume_24h": volume_24h,
                "circulating_supply": circulating_supply
            }
        else:
            # ============ COMPREHENSIVE STOCK METRICS (UNSHACKLED) ============
            
            # === VALUATION METRICS ===
            trailing_pe = info.get('trailingPE', None)
            forward_pe = info.get('forwardPE', None)
            peg_ratio = info.get('pegRatio', None)
            price_to_book = info.get('priceToBook', None)
            price_to_sales = info.get('priceToSalesTrailing12Months', None)
            enterprise_value = info.get('enterpriseValue', None)
            ev_to_ebitda = info.get('enterpriseToEbitda', None)
            
            # === ANALYST DATA ===
            target_mean_price = info.get('targetMeanPrice', None)
            target_high_price = info.get('targetHighPrice', None)
            target_low_price = info.get('targetLowPrice', None)
            number_of_analyst_opinions = info.get('numberOfAnalystOpinions', None)
            recommendation_key = info.get('recommendationKey', None)
            
            # Format recommendation
            recommendation_map = {
                'strong_buy': 'GÜÇLÜ AL',
                'buy': 'AL',
                'hold': 'TUT',
                'sell': 'SAT',
                'strong_sell': 'GÜÇLÜ SAT'
            }
            recommendation = recommendation_map.get(recommendation_key, 'BİLİNMİYOR') if recommendation_key else 'BİLİNMİYOR'
            
            # === FINANCIAL HEALTH ===
            market_cap = info.get('marketCap', None)
            ebitda_margins = info.get('ebitdaMargins', None)
            profit_margins = info.get('profitMargins', None)
            debt_to_equity = info.get('debtToEquity', None)
            return_on_equity = info.get('returnOnEquity', None)
            current_ratio = info.get('currentRatio', None)
            
            # === SECTOR/INDUSTRY CONTEXT ===
            sector = info.get('sector', None)
            industry = info.get('industry', None)
            
            # === EARNINGS & BOOK VALUE (for Graham Number) ===
            earnings_per_share = info.get('trailingEps', None)
            book_value_per_share = info.get('bookValue', None)
            
            # === CALCULATE GRAHAM NUMBER (Fair Value Estimate) ===
            # Graham Number = √(22.5 × EPS × Book Value per Share)
            # This is Benjamin Graham's intrinsic value formula
            graham_number = None
            if earnings_per_share and book_value_per_share:
                try:
                    if earnings_per_share > 0 and book_value_per_share > 0:
                        graham_number = round((22.5 * earnings_per_share * book_value_per_share) ** 0.5, 2)
                except Exception:
                    pass
            
            # === DIVIDEND DATA ===
            dividend_yield = info.get('dividendYield', None)
            if dividend_yield:
                dividend_yield = round(dividend_yield * 100, 2)  # Convert to percentage
            
            # === BUILD COMPREHENSIVE RESPONSE ===
            result = {
                # Legacy fields (keep for backward compatibility)
                "f_k_orani": round(trailing_pe, 2) if trailing_pe else None,
                "analist_hedef_fiyat": round(target_mean_price, 2) if target_mean_price else None,
                "analist_tavsiyesi": recommendation,
                
                # === NEW: VALUATION RATIOS ===
                "forward_pe": round(forward_pe, 2) if forward_pe else None,
                "trailing_pe": round(trailing_pe, 2) if trailing_pe else None,
                "peg_ratio": round(peg_ratio, 3) if peg_ratio else None,
                "price_to_book": round(price_to_book, 2) if price_to_book else None,
                "price_to_sales": round(price_to_sales, 2) if price_to_sales else None,
                "ev_to_ebitda": round(ev_to_ebitda, 2) if ev_to_ebitda else None,
                
                # === NEW: ANALYST TARGETS ===
                "target_mean": round(target_mean_price, 2) if target_mean_price else None,
                "target_high": round(target_high_price, 2) if target_high_price else None,
                "target_low": round(target_low_price, 2) if target_low_price else None,
                "analyst_count": number_of_analyst_opinions,
                
                # === NEW: FINANCIAL HEALTH ===
                "market_cap": market_cap,
                "ebitda_margins": round(ebitda_margins * 100, 2) if ebitda_margins else None,
                "profit_margins": round(profit_margins * 100, 2) if profit_margins else None,
                "debt_to_equity": round(debt_to_equity, 2) if debt_to_equity else None,
                "return_on_equity": round(return_on_equity * 100, 2) if return_on_equity else None,
                "current_ratio": round(current_ratio, 2) if current_ratio else None,
                
                # === NEW: SECTOR/INDUSTRY ===
                "sector": sector,
                "industry": industry,
                
                # === NEW: GRAHAM NUMBER (Fair Value) ===
                "graham_number": graham_number,
                "earnings_per_share": round(earnings_per_share, 2) if earnings_per_share else None,
                "book_value_per_share": round(book_value_per_share, 2) if book_value_per_share else None,
                
                # === NEW: DIVIDEND ===
                "dividend_yield_pct": dividend_yield,
                
                # === NEW: ENTERPRISE VALUE ===
                "enterprise_value": enterprise_value,
            }
            
            print(f"✅ Fetched FULL fundamentals for {normalized_symbol}: PE={trailing_pe}, PEG={peg_ratio}, Graham={graham_number}, Sector={sector}")
            return result
            
    except Exception as e:
        print(f"⚠️ Fundamental data error for {symbol}: {e}")
        return {
            "f_k_orani": None,
            "analist_hedef_fiyat": None,
            "analist_tavsiyesi": "BİLİNMİYOR"
        }

def get_news_sentiment(symbol):
    """
    Smart News Interpreter: Process news through AI, return interpreted insights (NO raw headlines).
    Output is ready to display/send to Telegram.
    """
    try:
        normalized_symbol = normalize_symbol(symbol)
        feed = feedparser.parse(f'https://finance.yahoo.com/rss/headline?s={normalized_symbol}')
        
        if not feed.entries:
            return {
                "interpreted_summary": "No significant news",
                "critical_items": [],
                "sentiment": "Neutral"
            }
        
        # Get top 5 news articles
        news_headlines = []
        for entry in feed.entries[:5]:
            title = entry.title
            news_headlines.append(title)
        
        # Process through Gemini API with specific prompt
        try:
            news_prompt = f"""Analyze these news headlines for {normalized_symbol} in depth. Ignore general noise. For each CRITICAL news item, explain: What happened, WHY this is important for the stock, and provide a 2-3 sentence interpretation covering the potential impact on price and investor sentiment. Don't be generic. If no critical news, say "No significant news".

News Headlines:
{chr(10).join([f"{i+1}. {headline}" for i, headline in enumerate(news_headlines)])}

Return in JSON format:
{{
  "critical_items": [
    {{
      "what_happened": "Description of what happened",
      "interpretation": "Bullish/Bearish",
      "summary": "2-3 sentences explaining WHY this is important for the stock and the potential impact on price and investor sentiment. Be specific, not generic."
    }}
  ],
  "overall_sentiment": "Bullish/Bearish/Neutral"
}}

If no critical news items, return:
{{
  "critical_items": [],
  "overall_sentiment": "Neutral",
  "message": "No significant news"
}}"""
            
            # Use safe_gemini_call
            try:
                news_json = safe_gemini_call(news_prompt, response_mode="json", max_retries=1, purpose="news_batch")
            except GeminiCallError:
                news_json = None
            
            if news_json is None:
                print("⚠️ Using fallback data")
                # Fallback: Return simple message without AI interpretation
                return {
                    "interpreted_summary": FALLBACK_AI_MESSAGE,
                    "critical_items": [],
                    "sentiment": "Neutral",
                    "error": "API quota exceeded"
                }
            
            # Extract interpreted data
            critical_items = news_json.get("critical_items", [])
            overall_sentiment = news_json.get("overall_sentiment", "Neutral")
            
            # Build interpreted summary (ready for display/Telegram)
            if critical_items and len(critical_items) > 0:
                interpreted_summary = "\n".join([
                    f"• {item.get('summary', item.get('what_happened', 'N/A'))}"
                    for item in critical_items
                ])
            else:
                interpreted_summary = "No significant news"
            
            return {
                "interpreted_summary": interpreted_summary,
                "critical_items": critical_items,
                "sentiment": overall_sentiment,
                "ticker": normalized_symbol
            }
            
        except Exception as ai_error:
            # Catch ALL exceptions to prevent crashes
            print(f"REAL AI ERROR: {ai_error}")
            print(f"REAL AI ERROR TYPE: {type(ai_error).__name__}")
            print("⚠️ Using fallback data")
            return {
                "interpreted_summary": FALLBACK_AI_MESSAGE,
                "critical_items": [],
                "sentiment": "Neutral",
                "error": "API error"
            }
            
    except Exception as e:
        print(f"⚠️ News sentiment error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "interpreted_summary": "News analysis failed",
            "critical_items": [],
            "sentiment": "Neutral"
        }

def analyze_news_batch_with_llm(news_items: list[dict], symbol: str, mode: str) -> list[dict]:
    """
    Analyze multiple news items in a single batch LLM call.
    
    Args:
        news_items: List of news dicts with keys: title, snippet, source, timestamp (optional)
        symbol: Stock/crypto symbol
        mode: "STOCK" or "CRYPTO"
    
    Returns:
        List of analysis dicts in same order as input:
        [
            {
                "importance_score": int,
                "impact": "bullish" | "bearish" | "neutral",
                "time_horizon": "intraday" | "short" | "long",
                "reasons": [str, ...],
                "key_risks": [str, ...],
                "key_opportunities": [str, ...]
            },
            ...
        ]
    """
    import uuid
    
    # Limit to MAX_NEWS_PER_BATCH
    MAX_NEWS_PER_BATCH = int(os.getenv("MAX_NEWS_PER_BATCH", "10"))
    news_items = news_items[:MAX_NEWS_PER_BATCH]
    
    if not news_items:
        return []
    
    # Build batch prompt
    news_list_str = ""
    for i, item in enumerate(news_items, 1):
        title = item.get("title", "")
        snippet = item.get("snippet", "")[:200]  # Limit snippet length
        source = item.get("source", "Unknown")
        timestamp = item.get("timestamp", item.get("published", "Recent"))
        
        news_list_str += f"""
{i}. TITLE: {title}
   SNIPPET: {snippet}
   SOURCE: {source}
   TIMESTAMP: {timestamp}
"""
    
    prompt = f"""You are a financial news analyst. Analyze the following {len(news_items)} news items for {symbol} ({mode}).

For EACH news item, provide:
- importance_score: 0-100 (how critical/important is this news?)
- impact: "bullish", "bearish", or "neutral" (price impact direction)
- time_horizon: "intraday", "short", or "long" (when will impact be felt?)
- reasons: array of 1-3 short Turkish explanations (max 100 chars each)
- key_risks: array of 1-3 specific risks if bearish/neutral (max 100 chars each, empty if bullish)
- key_opportunities: array of 1-3 specific opportunities if bullish/neutral (max 100 chars each, empty if bearish)

NEWS ITEMS:
{news_list_str}

CRITICAL: Output ONLY valid JSON array. No markdown, no explanations, no comments.
Array must have EXACTLY {len(news_items)} items in the SAME ORDER as input.

Output format (strict JSON):
[
  {{
    "importance_score": 75,
    "impact": "bullish",
    "time_horizon": "short",
    "reasons": ["Kazanç beklentisi aşıldı", "Güçlü büyüme sinyali"],
    "key_risks": [],
    "key_opportunities": ["Fiyat hedefi yükseltildi", "Pozitif momentum"]
  }},
  ...
]
"""
    
    try:
        request_id = str(uuid.uuid4())
        
        result = safe_gemini_call(
            prompt=prompt,
            response_mode="json",
            schema=None,  # Array response, no schema validation
            max_retries=0,
            model_name=None,  # Dynamic model discovery
            temperature=0.2,
            max_output_tokens=2048,
            purpose="news_batch",
            symbol=symbol,
            request_id=request_id
        )
        
        # safe_gemini_call returns parsed JSON (dict or list) in json mode
        # Validate result is a list
        if not isinstance(result, list):
            raise ValueError(f"Expected list, got {type(result).__name__}")
        
        # Ensure same length as input
        if len(result) != len(news_items):
            print(f"⚠️ [news_llm] Warning: LLM returned {len(result)} items, expected {len(news_items)}")
            # Pad or truncate to match input length
            if len(result) < len(news_items):
                # Pad with empty dicts
                for _ in range(len(news_items) - len(result)):
                    result.append({
                        "importance_score": 0,
                        "impact": "neutral",
                        "time_horizon": "short",
                        "reasons": [],
                        "key_risks": [],
                        "key_opportunities": []
                    })
            else:
                # Truncate
                result = result[:len(news_items)]
        
        # Validate each item has required fields
        validated_result = []
        for item in result:
            if not isinstance(item, dict):
                validated_result.append({
                    "importance_score": 0,
                    "impact": "neutral",
                    "time_horizon": "short",
                    "reasons": [],
                    "key_risks": [],
                    "key_opportunities": []
                })
                continue
            
            validated_item = {
                "importance_score": int(item.get("importance_score", 0)),
                "impact": item.get("impact", "neutral").lower(),
                "time_horizon": item.get("time_horizon", "short").lower(),
                "reasons": item.get("reasons", []),
                "key_risks": item.get("key_risks", []),
                "key_opportunities": item.get("key_opportunities", [])
            }
            
            # Ensure impact is valid
            if validated_item["impact"] not in ["bullish", "bearish", "neutral"]:
                validated_item["impact"] = "neutral"
            
            # Ensure time_horizon is valid
            if validated_item["time_horizon"] not in ["intraday", "short", "long"]:
                validated_item["time_horizon"] = "short"
            
            validated_result.append(validated_item)
        
        print(f"[news_llm] batch_call=1 items={len(news_items)}")
        return validated_result
        
    except Exception as e:
        print(f"[news_llm] failed -> fallback_to_local=1 error={type(e).__name__}: {e}")
        # Return empty list - will fallback to local heuristic
        return []


def filter_critical_news_local(news_items: list[dict], limit: int = 3) -> list[dict]:
    """
    Local function to filter critical news without Gemini API calls.
    Uses weighted keyword scoring for better prioritization.
    
    Args:
        news_items: List of news dicts with 'title' key
        limit: Maximum number of items to return
    
    Returns:
        List of filtered news items with impact, reason, and priority
    """
    # Weighted critical keywords (higher weight = more important)
    critical_keywords_weighted = {
        # Macro/Fed related (highest weight)
        "fed": 5, "rate": 4, "rates": 4, "cpi": 5, "inflation": 5,
        "fomc": 5, "powell": 4, "yellen": 4, "treasury": 3,
        # Earnings & guidance
        "earnings": 4, "guidance": 4, "outlook": 3, "forecast": 3,
        "revenue": 3, "profit": 3, "eps": 3, "beat": 3, "miss": 3,
        # Geopolitical/Trade
        "china": 4, "export": 4, "ban": 5, "sanction": 5, "restriction": 4,
        "tariff": 4, "trade war": 5, "huawei": 3, "tsmc": 3,
        # Regulatory/Legal
        "sec": 4, "lawsuit": 4, "antitrust": 4, "investigation": 3,
        "probe": 3, "fine": 3, "penalty": 3, "fraud": 5,
        # M&A
        "merger": 4, "acquisition": 4, "buyout": 4, "takeover": 4,
        # Sector specific (Tech/AI)
        "nvidia": 3, "ai": 3, "chip": 3, "gpu": 3, "semiconductor": 3,
        # Ratings
        "upgrade": 3, "downgrade": 4, "price target": 3,
    }
    
    bullish_keywords = [
        "surge", "surges", "jump", "jumps", "beats", "beat", "record", "growth",
        "upgrade", "strong", "rally", "rallies", "soar", "soars", "gain", "gains",
        "bullish", "outperform", "buy", "positive", "optimistic", "boost",
        "büyüme", "rekor", "artış", "talep", "kazanç", "pozitif", "yükseliş"
    ]
    
    bearish_keywords = [
        "slump", "slumps", "drop", "drops", "falls", "fall", "miss", "misses",
        "downgrade", "selloff", "sell-off", "risk", "warning", "warns",
        "lawsuit", "fraud", "plunge", "plunges", "crash", "crashes", "decline",
        "bearish", "underperform", "sell", "negative", "concern", "weak",
        "düşüş", "kayıp", "baskı", "negatif", "risk", "azalış", "daralma"
    ]
    
    scored_news = []
    for item in news_items:
        title = item.get("title", "")
        title_lower = title.lower()
        
        # Calculate weighted criticality score
        score = 0
        matched_keywords = []
        for keyword, weight in critical_keywords_weighted.items():
            if keyword in title_lower:
                score += weight
                matched_keywords.append(keyword)
        
        # Determine impact
        bullish_count = sum(1 for kw in bullish_keywords if kw in title_lower)
        bearish_count = sum(1 for kw in bearish_keywords if kw in title_lower)
        
        if bullish_count > bearish_count:
            impact = "Positive"
        elif bearish_count > bullish_count:
            impact = "Negative"
        else:
            impact = "Neutral"
        
        # Generate specific reason in Turkish based on matched keywords
        if matched_keywords:
            keyword_str = ", ".join(matched_keywords[:3])
            if impact == "Positive":
                reason = f"Kritik haber ({keyword_str}): Olumlu etki bekleniyor."
            elif impact == "Negative":
                reason = f"Kritik haber ({keyword_str}): Olumsuz etki riski var."
            else:
                reason = f"Kritik haber ({keyword_str}): Dikkatle izlenmeli."
        else:
            if impact == "Positive":
                reason = "Başlık olumlu sinyaller içeriyor."
            elif impact == "Negative":
                reason = "Başlık risk faktörleri içeriyor."
            else:
                reason = "Başlık net yön vermiyor, izleme gerektiriyor."
        
        # Determine priority based on weighted score
        if score >= 8:
            priority = 1  # Very high importance
        elif score >= 4:
            priority = 2  # High importance
        elif score >= 1:
            priority = 3  # Medium importance
        else:
            priority = 4  # Low importance
        
        scored_news.append({
            "title": title,
            "score": score,
            "impact": impact,
            "reason": reason,
            "priority": priority,
            "is_critical": score >= 3,
            "matched_keywords": matched_keywords
        })
    
    # Sort by score (descending) then by priority (ascending)
    scored_news.sort(key=lambda x: (-x["score"], x["priority"]))
    
    # Return top N
    return scored_news[:limit]


def get_news(symbol, use_llm: int = 0, mode: str = "STOCK"):
    """
    Fetch news with local filtering and optional batch LLM analysis.
    
    Args:
        symbol: Stock/crypto symbol
        use_llm: 0 = local heuristic only, 1 = local + batch LLM analysis
        mode: "STOCK" or "CRYPTO" (for LLM context)
    """
    try:
        normalized_symbol = normalize_symbol(symbol)
        feed = feedparser.parse(f'https://finance.yahoo.com/rss/headline?s={normalized_symbol}')
        
        if not feed.entries:
            return {
                "titles": ["Haber yok"],
                "sentiment_score": 50,
                "snippets": [],
                "ai_interpreted": []
            }
        
        # Get top 5 news articles
        raw_news = []
        for entry in feed.entries[:5]:
            title = entry.title
            snippet = entry.summary[:200] if hasattr(entry, 'summary') and entry.summary else title
            # Try to extract source from entry
            source = None
            if hasattr(entry, 'source') and entry.source:
                source = getattr(entry.source, 'title', None) or str(entry.source)
            # Extract timestamp
            timestamp = "Recent"
            if hasattr(entry, 'published'):
                timestamp = entry.published
            elif hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    timestamp = _dt(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass
            
            raw_news.append({
                "title": title,
                "snippet": snippet,
                "source": source,
                "timestamp": timestamp,
                "published": timestamp  # Alias for compatibility
            })
        
        # Use local filtering (NO Gemini API)
        filtered_news = filter_critical_news_local(raw_news, limit=3)
        
        # Step 1: Local heuristic analysis (always runs, free)
        local_analyses = []
        for item in filtered_news:
            title = item["title"]
            source = item.get("source")
            
            # Analyze news item using local analyzer (NO LLM)
            analysis = analyze_news_item(title, source)
            local_analyses.append({
                "item": item,
                "analysis": analysis
            })
        
        # Step 2: Batch LLM analysis (if use_llm=1)
        llm_analyses = []
        if use_llm == 1 and filtered_news:
            # Prepare news items for batch LLM call
            batch_items = []
            for item in filtered_news:
                batch_items.append({
                    "title": item["title"],
                    "snippet": item.get("snippet", item.get("title", "")),
                    "source": item.get("source", "Unknown"),
                    "timestamp": item.get("timestamp", item.get("published", "Recent"))
                })
            
            # Call batch LLM analysis
            llm_analyses = analyze_news_batch_with_llm(batch_items, normalized_symbol, mode.upper())
        
        # Step 3: Merge local and LLM analyses
        ai_interpreted = []
        for i, local_data in enumerate(local_analyses):
            item = local_data["item"]
            local_analysis = local_data["analysis"]
            title = item["title"]
            source = item.get("source")
            
            # Start with local analysis
            importance_score = local_analysis["importance_score"]
            impact = local_analysis["impact"]
            time_horizon = local_analysis["time_horizon"]
            reasons = local_analysis["reasons"]
            
            # If LLM analysis available, merge/enhance with LLM data
            if llm_analyses and i < len(llm_analyses):
                llm_analysis = llm_analyses[i]
                # Use LLM data if available (more detailed)
                if llm_analysis.get("importance_score", 0) > 0:
                    importance_score = llm_analysis["importance_score"]
                if llm_analysis.get("impact"):
                    impact = llm_analysis["impact"]
                if llm_analysis.get("time_horizon"):
                    time_horizon = llm_analysis["time_horizon"]
                if llm_analysis.get("reasons"):
                    reasons = llm_analysis["reasons"]
                
                # Add LLM-specific fields
                key_risks = llm_analysis.get("key_risks", [])
                key_opportunities = llm_analysis.get("key_opportunities", [])
            else:
                key_risks = []
                key_opportunities = []
            
            # Map impact to Turkish
            impact_map = {
                "Positive": "Pozitif",
                "Negative": "Negatif",
                "Neutral": "Nötr",
                "bullish": "Pozitif",
                "bearish": "Negatif",
                "neutral": "Nötr"
            }
            impact_tr = impact_map.get(item.get("impact", impact), "Nötr")
            
            # IMPORTANT: QUICK (use_llm=0) must be deterministic and must not call any LLM.
            # Only allow optional "ai_investor_comment" generation when use_llm=1.
            ai_comment = None
            if use_llm == 1:
                comment_prompt = f'For this stock market news: "{title}"'
                comment_result = gemini_text(comment_prompt)
                ai_comment = comment_result.get("text", "") if not comment_result.get("fallback") else None
            
            priority_map = {1: "CRITICAL", 2: "HIGH", 3: "MEDIUM"}
            priority_str = priority_map.get(item.get("priority", 3), "LOW")
            
            # Mark as low_priority if importance_score < 50
            is_low_priority = importance_score < 50
            
            interpreted_item = {
                "title": title,
                "is_critical": item.get("is_critical", importance_score >= 50),
                "priority": priority_str,
                "impact": impact_tr,
                "explanation": item.get("reason", ". ".join(reasons)),
                # New fields from news analyzer
                "importance_score": importance_score,
                "time_horizon": time_horizon,
                "reasons": reasons,
                "low_priority": is_low_priority
            }
            
            # Add LLM-enhanced fields if available
            if llm_analyses and i < len(llm_analyses):
                interpreted_item["key_risks"] = key_risks
                interpreted_item["key_opportunities"] = key_opportunities
            
            if ai_comment:
                interpreted_item["ai_investor_comment"] = ai_comment.strip()
            
            # Log analysis result
            print(f"[news] analyzed locally, score={importance_score}, impact={impact}")
            
            # Generate stable event_key from title + source + content (for deduplication)
            event_key = generate_event_key(title, source, title[:80] if title else None)
            
            # Get notification configuration from environment variables
            NOTIF_MIN_SCORE = int(os.getenv("NOTIF_MIN_SCORE", "25"))
            NOTIF_COOLDOWN_MINUTES = int(os.getenv("NOTIF_COOLDOWN_MINUTES", "30"))
            NOTIF_MAX_PER_DAY_PER_SYMBOL = os.getenv("NOTIF_MAX_PER_DAY_PER_SYMBOL")
            max_per_day = int(NOTIF_MAX_PER_DAY_PER_SYMBOL) if NOTIF_MAX_PER_DAY_PER_SYMBOL else None
            
            # Check if notification should be sent (score threshold, cooldown, dedupe)
            should_send, reason = should_send_notification(
                normalized_symbol, 
                event_key, 
                importance_score,
                cooldown_minutes=NOTIF_COOLDOWN_MINUTES,
                min_score=NOTIF_MIN_SCORE,
                max_per_day_per_symbol=max_per_day
            )
            
            if should_send:
                # Log notification (actual sending would be done by alert_system)
                log_notification(normalized_symbol, event_key, importance_score, title=title)
                print(f"[notify] sent score={importance_score} key={event_key}")
            else:
                # Suppressed - log reason
                print(f"[notify] suppressed score={importance_score} reason={reason}")
            
            ai_interpreted.append(interpreted_item)
        
        print(f"✅ Local filtering processed {len(ai_interpreted)} critical news items (no API call)")
        
        # Calculate sentiment from AI interpretations
        positive_count = sum(1 for item in ai_interpreted if item.get("impact") == "Pozitif")
        negative_count = sum(1 for item in ai_interpreted if item.get("impact") == "Negatif")
        total_critical = len(ai_interpreted)
        
        if total_critical > 0:
            sentiment_score = 50 + ((positive_count - negative_count) / total_critical) * 50
            sentiment_score = max(0, min(100, int(sentiment_score)))
        else:
            sentiment_score = 50
        
        return {
            "titles": [item.get("title", "") for item in ai_interpreted],
            "sentiment_score": sentiment_score,
            "snippets": [item.get("explanation", "") for item in ai_interpreted],
            "ai_interpreted": ai_interpreted
        }
    except Exception as e:
        print(f"⚠️ News error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "titles": ["Haber çekilemedi"],
            "sentiment_score": 50,
            "snippets": [],
            "ai_interpreted": []
        }


def _map_quick_analysis_to_mentor_card(
    analysis: Dict[str, Any],
    symbol: str,
    title: str,
    source: Optional[str],
    timestamp: str
) -> Dict[str, Any]:
    """
    Map QUICK mode analysis (from analyze_news_item) to MentorNewsCard format.
    
    Args:
        analysis: Output from analyze_news_item()
        symbol: Stock/crypto symbol
        title: Original news title (for event_key generation)
        source: News source name
        timestamp: News timestamp
    
    Returns:
        MentorNewsCard dict
    """
    importance_score = analysis.get("importance_score", 0)
    impact = analysis.get("impact", "neutral")
    time_horizon = analysis.get("time_horizon", "short")
    reasons = analysis.get("reasons", [])
    
    # Map impact to expected_impact
    impact_map = {
        "bullish": "POSITIVE",
        "bearish": "NEGATIVE",
        "neutral": "NEUTRAL"
    }
    expected_impact = impact_map.get(impact, "NEUTRAL")
    
    # Generate mentor_summary from reasons (max 300 chars)
    mentor_summary = ". ".join(reasons[:3])[:300]
    if not mentor_summary:
        mentor_summary = "Haber analiz edildi, önemli sinyal tespit edilmedi."
    
    # Determine action_hint based on impact + importance_score
    if importance_score >= 70:
        if expected_impact == "POSITIVE":
            action_hint = "CONSIDER_BUY"
        elif expected_impact == "NEGATIVE":
            action_hint = "SET_STOP_LOSS"
        else:
            action_hint = "MONITOR"
    elif importance_score >= 50:
        if expected_impact == "POSITIVE":
            action_hint = "HOLD_STRONG"
        elif expected_impact == "NEGATIVE":
            action_hint = "CONSIDER_SELL"
        else:
            action_hint = "HOLD"
    else:
        action_hint = "MONITOR" if importance_score >= 30 else "HOLD"
    
    # Generate ISO timestamp
    try:
        if timestamp and timestamp != "Recent":
            # Try to parse timestamp
            if isinstance(timestamp, str):
                # Try common formats
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%a, %d %b %Y %H:%M:%S %z"]:
                    try:
                        dt = _dt.strptime(timestamp, fmt)
                        iso_timestamp = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                        break
                    except:
                        continue
                else:
                    iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except:
        iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    return {
        "symbol": symbol.upper(),
        "mentor_summary": mentor_summary,
        "expected_impact": expected_impact,
        "action_hint": action_hint,
        "confidence": importance_score,
        "time_horizon": time_horizon,
        "timestamp": iso_timestamp,
        "source": source
    }


def analyze_news_mentor_style_batch(
    news_items: List[Dict[str, Any]],
    relevant_symbols: set
) -> List[Dict[str, Any]]:
    """
    LLM-based mentor reasoning for news batch.
    
    For each news item:
    - Determine if it's relevant to any symbol in relevant_symbols
    - Generate mentor_summary (what happened, why it matters)
    - Predict expected_impact (POSITIVE/NEGATIVE/NEUTRAL)
    - Provide action_hint (BUY/SELL/HOLD/MONITOR with reasoning)
    - Assign confidence (0-100)
    - Estimate time_horizon (intraday/short/long)
    
    Fallback: If LLM fails, return HOLD + explanation with confidence=30
    
    Args:
        news_items: List of news dicts with keys: title, snippet, source, timestamp, symbol
        relevant_symbols: Set of symbols that are relevant (portfolio, trades, analyzed)
    
    Returns:
        List of MentorNewsCard dicts
    """
    if not news_items:
        return []
    
    # Limit batch size
    MAX_NEWS_PER_BATCH = int(os.getenv("MAX_NEWS_PER_BATCH", "10"))
    news_items = news_items[:MAX_NEWS_PER_BATCH]
    
    # Build context for LLM
    symbols_list = sorted(list(relevant_symbols))[:20]  # Limit to 20 symbols
    symbols_context = ", ".join(symbols_list) if symbols_list else "None"
    
    # Build news list for prompt
    news_list_str = ""
    for i, item in enumerate(news_items, 1):
        title = item.get("title", "")
        snippet = item.get("snippet", item.get("title", ""))[:200]
        source = item.get("source", "Unknown")
        timestamp = item.get("timestamp", item.get("published", "Recent"))
        symbol = item.get("symbol", "UNKNOWN")
        
        news_list_str += f"""
{i}. SYMBOL: {symbol}
   TITLE: {title}
   SNIPPET: {snippet}
   SOURCE: {source}
   TIMESTAMP: {timestamp}
"""
    
    prompt = f"""Sen bir finansal mentor ve yatırım danışmanısın. Aşağıdaki haberleri analiz et ve her biri için mentor tarzında yorum yap.

KULLANICI BAĞLAMI:
- Portföydeki/İlgilenilen semboller: {symbols_context}
- Bu semboller için haberler öncelikli olarak değerlendirilmeli.

HER HABER İÇİN ŞUNLARI SAĞLA:
1. mentor_summary: Ne oldu, neden önemli? (max 300 karakter, Türkçe)
2. expected_impact: "POSITIVE", "NEGATIVE", veya "NEUTRAL"
3. action_hint: "BUY", "SELL", "HOLD", "MONITOR", "CONSIDER_BUY", "CONSIDER_SELL", "SET_STOP_LOSS", veya "HOLD_STRONG"
4. confidence: 0-100 arası (haberin önemine ve güvenilirliğine göre)
5. time_horizon: "intraday", "short", veya "long"

HABERLER:
{news_list_str}

KRİTİK: Sadece geçerli JSON array döndür. Markdown, açıklama, yorum yok.
Array tam olarak {len(news_items)} eleman içermeli, giriş sırasıyla aynı.

Çıktı formatı (strict JSON):
[
  {{
    "symbol": "AAPL",
    "mentor_summary": "Kazanç beklentileri aşıldı. Servis segmentinde güçlü büyüme.",
    "expected_impact": "POSITIVE",
    "action_hint": "CONSIDER_BUY",
    "confidence": 75,
    "time_horizon": "short"
  }},
  ...
]
"""
    
    try:
        import uuid
        request_id = str(uuid.uuid4())
        
        result = safe_gemini_call(
            prompt=prompt,
            response_mode="json",
            schema=None,  # Array response, no schema validation
            max_retries=0,
            model_name=None,  # Dynamic model discovery
            temperature=0.2,
            max_output_tokens=2048,
            purpose="news_mentor_batch",
            symbol=None,  # Batch call, no single symbol
            request_id=request_id
        )
        
        # Validate result is a list
        if not isinstance(result, list):
            raise ValueError(f"Expected list, got {type(result).__name__}")
        
        # Ensure same length as input
        if len(result) != len(news_items):
            print(f"⚠️ [mentor_news] Warning: LLM returned {len(result)} items, expected {len(news_items)}")
            # Pad or truncate to match input length
            if len(result) < len(news_items):
                for _ in range(len(news_items) - len(result)):
                    result.append({
                        "symbol": "UNKNOWN",
                        "mentor_summary": "Haber analiz edilemedi, manuel kontrol önerilir",
                        "expected_impact": "NEUTRAL",
                        "action_hint": "HOLD",
                        "confidence": 30,
                        "time_horizon": "short"
                    })
            else:
                result = result[:len(news_items)]
        
        # Validate and enrich each item
        validated_result = []
        for i, item in enumerate(result):
            if not isinstance(item, dict):
                # Fallback card
                validated_result.append({
                    "symbol": news_items[i].get("symbol", "UNKNOWN").upper(),
                    "mentor_summary": "Haber analiz edilemedi, manuel kontrol önerilir",
                    "expected_impact": "NEUTRAL",
                    "action_hint": "HOLD",
                    "confidence": 30,
                    "time_horizon": "short",
                    "timestamp": news_items[i].get("timestamp", _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                    "source": news_items[i].get("source")
                })
                continue
            
            # Get original news item for timestamp/source
            original_item = news_items[i]
            symbol = item.get("symbol", original_item.get("symbol", "UNKNOWN")).upper()
            
            # Validate and set defaults
            mentor_summary = item.get("mentor_summary", "Haber analiz edildi.")
            if len(mentor_summary) > 300:
                mentor_summary = mentor_summary[:300]
            
            expected_impact = item.get("expected_impact", "NEUTRAL").upper()
            if expected_impact not in ["POSITIVE", "NEGATIVE", "NEUTRAL"]:
                expected_impact = "NEUTRAL"
            
            action_hint = item.get("action_hint", "HOLD").upper()
            valid_actions = ["BUY", "SELL", "HOLD", "MONITOR", "CONSIDER_BUY", "CONSIDER_SELL", "SET_STOP_LOSS", "HOLD_STRONG"]
            if action_hint not in valid_actions:
                action_hint = "HOLD"
            
            confidence = int(item.get("confidence", 30))
            confidence = max(0, min(100, confidence))
            
            time_horizon = item.get("time_horizon", "short").lower()
            if time_horizon not in ["intraday", "short", "long"]:
                time_horizon = "short"
            
            # Generate ISO timestamp
            timestamp = original_item.get("timestamp", original_item.get("published", "Recent"))
            try:
                if timestamp and timestamp != "Recent":
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%a, %d %b %Y %H:%M:%S %z"]:
                        try:
                            dt = _dt.strptime(timestamp, fmt)
                            iso_timestamp = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                            break
                        except:
                            continue
                    else:
                        iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                else:
                    iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except:
                iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            validated_result.append({
                "symbol": symbol,
                "mentor_summary": mentor_summary,
                "expected_impact": expected_impact,
                "action_hint": action_hint,
                "confidence": confidence,
                "time_horizon": time_horizon,
                "timestamp": iso_timestamp,
                "source": original_item.get("source")
            })
        
        print(f"[mentor_news] DEEP mode processed {len(validated_result)} news items")
        return validated_result
        
    except Exception as e:
        print(f"[mentor_news] DEEP mode failed -> fallback to HOLD: {type(e).__name__}: {e}")
        # Fallback: Return HOLD cards for all items
        fallback_cards = []
        for item in news_items:
            symbol = item.get("symbol", "UNKNOWN").upper()
            timestamp = item.get("timestamp", item.get("published", "Recent"))
            try:
                if timestamp and timestamp != "Recent":
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%a, %d %b %Y %H:%M:%S %z"]:
                        try:
                            dt = _dt.strptime(timestamp, fmt)
                            iso_timestamp = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                            break
                        except:
                            continue
                    else:
                        iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                else:
                    iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except:
                iso_timestamp = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            fallback_cards.append({
                "symbol": symbol,
                "mentor_summary": "Haber analiz edilemedi, manuel kontrol önerilir",
                "expected_impact": "NEUTRAL",
                "action_hint": "HOLD",
                "confidence": 30,
                "time_horizon": "short",
                "timestamp": iso_timestamp,
                "source": item.get("source")
            })
        return fallback_cards


def get_mentor_news(mode: str = "QUICK", confidence_threshold: int = 50, llm_threshold: int = 60) -> List[Dict[str, Any]]:
    """
    Get mentor-interpreted news for all relevant symbols.
    
    Uses new pipeline: symbol selection → fetch → normalize → dedupe → score → enrich → notify → store
    
    Args:
        mode: "QUICK" (local only) or "DEEP" (LLM enrichment above threshold)
        confidence_threshold: Minimum confidence for inclusion (0-100)
        llm_threshold: Minimum local score to trigger LLM enrichment (0-100, only for DEEP mode)
    
    Returns:
        List of MentorNewsCard dicts with enhanced fields:
        - what_happened (if LLM enriched)
        - why_it_matters (if LLM enriched)
        - mentor_action (if LLM enriched)
        - risk (if LLM enriched)
    """
    try:
        # Use new pipeline module
        from .news_pipeline import process_news_pipeline
        
        return process_news_pipeline(
            mode=mode,
            confidence_threshold=confidence_threshold,
            llm_threshold=llm_threshold
        )
        
    except ImportError:
        # Fallback to old implementation if pipeline module not available
        print("⚠️ [mentor_news] news_pipeline module not available, using fallback")
        return _get_mentor_news_fallback(mode, confidence_threshold)
    except Exception as e:
        print(f"❌ [mentor_news] Error in get_mentor_news: {e}")
        import traceback
        traceback.print_exc()
        return _get_mentor_news_fallback(mode, confidence_threshold)


def _get_mentor_news_fallback(mode: str, confidence_threshold: int) -> List[Dict[str, Any]]:
    """
    Fallback implementation if new pipeline fails.
    """
    try:
        # Get relevant symbols
        relevant_symbols = get_relevant_symbols_for_news()
        
        if not relevant_symbols:
            print("[mentor_news] No relevant symbols found")
            return []
        
        print(f"[mentor_news] Processing {len(relevant_symbols)} relevant symbols in {mode} mode (FALLBACK)")
        
        # Fetch news for all relevant symbols with deduplication
        all_news_items = []
        seen_titles = set()  # Deduplication by normalized title
        
        for symbol in relevant_symbols:
            try:
                normalized_symbol = normalize_symbol(symbol)
                feed = feedparser.parse(f'https://finance.yahoo.com/rss/headline?s={normalized_symbol}')
                
                if not feed.entries:
                    continue
                
                # Get top 5 news articles per symbol
                for entry in feed.entries[:5]:
                    title = entry.title.strip() if entry.title else ""
                    if not title:
                        continue
                    
                    # Normalize title for deduplication (lowercase, remove extra spaces)
                    title_normalized = " ".join(title.lower().split())
                    
                    # Skip if we've seen this title before
                    if title_normalized in seen_titles:
                        continue
                    seen_titles.add(title_normalized)
                    
                    snippet = entry.summary[:200] if hasattr(entry, 'summary') and entry.summary else title
                    source = None
                    if hasattr(entry, 'source') and entry.source:
                        source = getattr(entry.source, 'title', None) or str(entry.source)
                    
                    timestamp = "Recent"
                    if hasattr(entry, 'published'):
                        timestamp = entry.published
                    elif hasattr(entry, 'published_parsed') and entry.published_parsed:
                        try:
                            timestamp = _dt(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            pass
                    
                    all_news_items.append({
                        "title": title,
                        "snippet": snippet,
                        "source": source,
                        "timestamp": timestamp,
                        "published": timestamp,
                        "symbol": normalized_symbol
                    })
                
                # Small delay to avoid rate limiting
                time.sleep(0.5)
                
            except Exception as e:
                print(f"[mentor_news] Error fetching news for {symbol}: {e}")
                continue
        
        if not all_news_items:
            print("[mentor_news] No news items found")
            return []
        
        print(f"[mentor_news] Fetched {len(all_news_items)} total news items")
        
        # Process based on mode
        if mode.upper() == "QUICK":
            # QUICK mode: Deterministic analysis
            mentor_cards = []
            for item in all_news_items:
                title = item["title"]
                source = item.get("source")
                symbol = item.get("symbol", "UNKNOWN")
                
                # Analyze using local heuristic
                analysis = analyze_news_item(title, source)
                
                # Map to MentorNewsCard
                card = _map_quick_analysis_to_mentor_card(
                    analysis=analysis,
                    symbol=symbol,
                    title=title,
                    source=source,
                    timestamp=item.get("timestamp", "Recent")
                )
                
                mentor_cards.append(card)
            
            print(f"[mentor_news] QUICK mode processed {len(mentor_cards)} cards")
            
        elif mode.upper() == "DEEP":
            # DEEP mode: LLM-based analysis
            mentor_cards = analyze_news_mentor_style_batch(all_news_items, relevant_symbols)
            
        else:
            print(f"[mentor_news] Unknown mode: {mode}, defaulting to QUICK")
            # Fallback to QUICK
            mentor_cards = []
            for item in all_news_items:
                title = item["title"]
                source = item.get("source")
                symbol = item.get("symbol", "UNKNOWN")
                analysis = analyze_news_item(title, source)
                card = _map_quick_analysis_to_mentor_card(
                    analysis=analysis,
                    symbol=symbol,
                    title=title,
                    source=source,
                    timestamp=item.get("timestamp", "Recent")
                )
                mentor_cards.append(card)
        
        # Filter by confidence threshold
        filtered_cards = [
            card for card in mentor_cards
            if card.get("confidence", 0) >= confidence_threshold
        ]
        
        # Sort by confidence (descending)
        filtered_cards.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        # Check notifications for each card
        NOTIF_MIN_SCORE = int(os.getenv("NOTIF_MIN_SCORE", "25"))
        NOTIF_COOLDOWN_MINUTES = int(os.getenv("NOTIF_COOLDOWN_MINUTES", "30"))
        NOTIF_MAX_PER_DAY_PER_SYMBOL = os.getenv("NOTIF_MAX_PER_DAY_PER_SYMBOL")
        max_per_day = int(NOTIF_MAX_PER_DAY_PER_SYMBOL) if NOTIF_MAX_PER_DAY_PER_SYMBOL else None
        
        for card in filtered_cards:
            symbol = card.get("symbol", "")
            confidence = card.get("confidence", 0)
            
            # Only send notification if:
            # 1. Confidence >= threshold (already filtered)
            # 2. Symbol is in relevant_symbols (always true here)
            # 3. Cooldown/deduplication rules pass
            
            # Generate event_key from mentor_summary (since we don't have raw title)
            event_key = generate_event_key(
                card.get("mentor_summary", ""),
                card.get("source"),
                card.get("mentor_summary", "")[:80]
            )
            
            should_send, reason = should_send_notification(
                symbol,
                event_key,
                confidence,
                cooldown_minutes=NOTIF_COOLDOWN_MINUTES,
                min_score=confidence_threshold,  # Use confidence_threshold instead of NOTIF_MIN_SCORE
                max_per_day_per_symbol=max_per_day
            )
            
            if should_send:
                log_notification(symbol, event_key, confidence, title=card.get("mentor_summary", "")[:100])
                print(f"[mentor_news] Notification sent: symbol={symbol} confidence={confidence}")
            else:
                print(f"[mentor_news] Notification suppressed: symbol={symbol} reason={reason}")
        
        print(f"[mentor_news] Returning {len(filtered_cards)} mentor cards (confidence >= {confidence_threshold})")
        return filtered_cards
        
    except Exception as e:
        print(f"❌ [mentor_news] Error in fallback: {e}")
        import traceback
        traceback.print_exc()
        return []


def calculate_deep_technicals(symbol):
    """Calculate Golden Cross, MACD, and ATR."""
    try:
        normalized_symbol = normalize_symbol(symbol)
        stock = yf.Ticker(normalized_symbol)
        hist = stock.history(period="6mo")
        
        if len(hist) < 200:
            return {
                "golden_cross": False,
                "macd_signal": "NÖTR",
                "atr": 0,
                "sma50": 0,
                "sma200": 0
            }
        
        # Calculate SMAs
        sma50 = hist['Close'].rolling(window=50).mean()
        sma200 = hist['Close'].rolling(window=200).mean()
        
        # Golden Cross: SMA50 crosses above SMA200
        golden_cross = sma50.iloc[-1] > sma200.iloc[-1] and sma50.iloc[-2] <= sma200.iloc[-2]
        
        # MACD Calculation
        ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
        ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        
        macd_signal = "AL" if histogram.iloc[-1] > 0 and macd_line.iloc[-1] > signal_line.iloc[-1] else "SAT" if histogram.iloc[-1] < 0 else "NÖTR"
        
        # ATR (Average True Range) - Volatility measure
        high_low = hist['High'] - hist['Low']
        high_close = np.abs(hist['High'] - hist['Close'].shift())
        low_close = np.abs(hist['Low'] - hist['Close'].shift())
        
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window=14).mean().iloc[-1]
        
        return {
            "golden_cross": golden_cross,
            "macd_signal": macd_signal,
            "atr": round(atr, 4),
            "sma50": round(sma50.iloc[-1], 2),
            "sma200": round(sma200.iloc[-1], 2)
        }
    except Exception as e:
        print(f"⚠️ Deep technicals error: {e}")
        return {
            "golden_cross": False,
            "macd_signal": "NÖTR",
            "atr": 0,
            "sma50": 0,
            "sma200": 0
        }

def _split_missing_dates_into_segments(missing_dates: List[date]) -> List[tuple]:
    """
    Split a list of missing dates into consecutive segments.
    ARCHITECT FIX: Filters out any future dates before processing.
    
    Args:
        missing_dates: Sorted list of date objects
    
    Returns:
        List of tuples: [(start1, end1), (start2, end2), ...] (both dates inclusive)
    """
    if not missing_dates:
        return []
    
    # ARCHITECT FIX: Filter out any future dates before processing
    today = _dt.now().date()
    filtered_dates = [d for d in missing_dates if d <= today]
    
    if not filtered_dates:
        return []
    
    # Log if we filtered any future dates
    future_count = len(missing_dates) - len(filtered_dates)
    if future_count > 0:
        print(f"⚠️ ARCHITECT BLOCK: Filtered out {future_count} future dates from missing_dates list")
    
    # Sort dates to ensure consecutive check works
    sorted_dates = sorted(filtered_dates)
    segments = []
    segment_start = sorted_dates[0]
    segment_end = sorted_dates[0]
    
    for i in range(1, len(sorted_dates)):
        current_date = sorted_dates[i]
        # Check if consecutive (within 1 day, accounting for weekends)
        days_diff = (current_date - segment_end).days
        if days_diff <= 3:  # Allow up to 3 days gap (weekends/holidays)
            segment_end = current_date
        else:
            # End current segment, start new one
            segments.append((segment_start, segment_end))
            segment_start = current_date
            segment_end = current_date
    
    # Add final segment
    segments.append((segment_start, segment_end))
    
    return segments


def _fetch_ohlcv_yahoo_direct(symbol: str, period: str = "1y") -> List[Dict[str, Any]]:
    """Fetch OHLCV bars from Yahoo Finance v8 chart API directly (no yfinance lib)."""
    try:
        import requests as _req
        from datetime import datetime as _datetime
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={period}"
        r = _req.get(url, headers=headers, timeout=15).json()
        result = r["chart"]["result"][0]
        timestamps = result.get("timestamps") or result.get("timestamp", [])
        q = result["indicators"]["quote"][0]
        opens = q.get("open", [])
        highs = q.get("high", [])
        lows = q.get("low", [])
        closes = q.get("close", [])
        volumes = q.get("volume", [])
        today = _datetime.utcnow().date()
        bars = []
        for i, ts in enumerate(timestamps):
            if ts is None:
                continue
            bar_date = _datetime.utcfromtimestamp(ts).date()
            if bar_date > today:
                continue
            c = closes[i] if i < len(closes) and closes[i] is not None else None
            if c is None:
                continue
            bars.append({
                "date": bar_date.strftime("%Y-%m-%d"),
                "open": round(float(opens[i] or c), 2),
                "high": round(float(highs[i] or c), 2),
                "low": round(float(lows[i] or c), 2),
                "close": round(float(c), 2),
                "volume": int(volumes[i] or 0) if i < len(volumes) else 0,
            })
        return bars
    except Exception as e:
        print(f"⚠️ Yahoo Direct OHLCV failed for {symbol}: {e}")
        return []


def _fetch_remote_bars(symbol: str, mode: str, start_date: Optional[date] = None, end_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """
    Fetch market bars from remote (yfinance) for a given date range.
    
    UNSHACKLED MODE: Default period extended from 6mo to 2y for long-term analysis.
    ARCHITECT FIX: HARD BLOCKS ANY FUTURE DATES (never returns bars > today)
    
    Args:
        symbol: Stock/crypto symbol
        mode: "STOCK" or "CRYPTO"
        start_date: Optional start date (if None, fetches last 2 YEARS - CHANGED FROM 6 MONTHS)
        end_date: Optional end date (if None, uses today)
    
    Returns:
        List of dicts with keys: date, open, high, low, close, volume
    """
    normalized_symbol = normalize_symbol(symbol)
    remote_bars = []
    
    # ARCHITECT FIX: Get today's date as hard ceiling for all bars
    today = _dt.now().date()
    
    # ARCHITECT FIX: Never allow end_date to exceed today
    if end_date and end_date > today:
        print(f"⚠️ ARCHITECT BLOCK: Capping end_date from {end_date} to {today}")
        end_date = today
    
    # ARCHITECT FIX: Skip fetch entirely if start_date is in the future
    if start_date and start_date > today:
        print(f"⚠️ ARCHITECT BLOCK: start_date {start_date} is in the future - skipping fetch")
        return []
    
    try:
        stock = yf.Ticker(normalized_symbol)
        
        if start_date and end_date:
            # Fetch specific date range
            # yfinance accepts date objects or strings (YYYY-MM-DD format)
            # Add 1 day to end_date to include the end date itself (yfinance end is exclusive)
            end_date_inclusive = end_date + timedelta(days=1)
            # Convert to string format for yfinance (more reliable)
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date_inclusive.strftime("%Y-%m-%d")
            hist = stock.history(start=start_str, end=end_str)
        else:
            # CHANGED: Default extended from 6mo to 2y for long-term pattern detection
            hist = stock.history(period="2y")
        
        if hist is None or len(hist) < 1:
            return []
        
        # Convert to bars format
        future_skipped = 0
        for date_idx, row in hist.iterrows():
            # date_idx might be datetime or Timestamp
            if hasattr(date_idx, 'date'):
                bar_date = date_idx.date()
            elif isinstance(date_idx, str):
                bar_date = _dt.strptime(date_idx, "%Y-%m-%d").date()
            else:
                bar_date = date_idx if isinstance(date_idx, date) else _dt.now().date()
            
            # Filter by date range if specified
            if start_date and bar_date < start_date:
                continue
            if end_date and bar_date > end_date:
                continue
            
            # ARCHITECT FIX: HARD BLOCK any bar with date > today
            if bar_date > today:
                future_skipped += 1
                continue  # Skip this bar entirely
            
            remote_bars.append({
                "date": bar_date.strftime("%Y-%m-%d"),
                "open": round(float(row['Open']), 2) if pd.notna(row['Open']) else 0.0,
                "high": round(float(row['High']), 2) if pd.notna(row['High']) else 0.0,
                "low": round(float(row['Low']), 2) if pd.notna(row['Low']) else 0.0,
                "close": round(float(row['Close']), 2) if pd.notna(row['Close']) else 0.0,
                "volume": int(row['Volume']) if pd.notna(row['Volume']) else 0
            })
        
        if future_skipped > 0:
            print(f"⚠️ ARCHITECT BLOCK: Skipped {future_skipped} future bars for {normalized_symbol}")
        
        return remote_bars
        
    except Exception as e:
        print(f"⚠️ Remote fetch (yfinance) error for {normalized_symbol}: {e}")

    # YAHOO DIRECT FALLBACK for OHLCV
    if not remote_bars:
        print(f"[chart] yfinance failed, trying Yahoo Direct for {normalized_symbol}")
        remote_bars = _fetch_ohlcv_yahoo_direct(normalized_symbol, period="1y")
        if remote_bars:
            print(f"✅ Yahoo Direct returned {len(remote_bars)} bars for {normalized_symbol}")

    return remote_bars


def get_chart_data(symbol: str, mode: str = "STOCK") -> List[Dict[str, Any]]:
    """
    Get OHLCV data for interactive chart with cache-first strategy and self-healing.
    Returns list of dicts with date, open, high, low, close, volume.
    
    UNSHACKLED MODE: Extended history requirement from 180 days to 2 YEARS (730 days)
    for long-term pattern analysis (bubble detection, multi-year trends).
    
    Strategy:
    1. Try cache first (DB)
    2. If cache sufficient (>=252 days / 1 year) and recent, check for gaps
    3. If gaps exist, backfill missing dates from remote
    4. If cache insufficient or stale, fetch full range from remote
    5. If remote fails, return cache (if available)
    """
    normalized_symbol = normalize_symbol(symbol)
    mode_upper = mode.upper()
    timeframe = "1d"  # Daily bars
    required_days = 730  # CHANGED FROM 180 TO 730 (2 years of trading days)
    
    # Step 1: Try cache first
    try:
        cached_bars = get_cached_market_bars(normalized_symbol, mode_upper, timeframe, limit=2000)
        
        if cached_bars and len(cached_bars) >= 252:  # ~1 year minimum (CHANGED FROM 126/6mo)
            # Check if cache is recent (last bar within 3 days)
            last_bar_date_str = cached_bars[-1].get("date", "")
            recent_enough = False
            
            if last_bar_date_str:
                try:
                    last_bar_date = _dt.strptime(last_bar_date_str, "%Y-%m-%d").date()
                    today = _dt.now().date()
                    days_old = (today - last_bar_date).days
                    recent_enough = (days_old <= 3)
                except Exception:
                    pass
            
            if recent_enough:
                # Cache hit - but check for gaps in last N days
                today = _dt.now().date()
                start_check_date = today - timedelta(days=required_days)
                
                # Get missing dates (trading days only)
                missing_dates = get_missing_dates(
                    normalized_symbol, mode_upper, timeframe, 
                    start_check_date, today
                )
                
                if missing_dates:
                    # Split missing dates into consecutive segments
                    missing_segments = _split_missing_dates_into_segments(missing_dates)
                    
                    # Log segment info
                    first_seg = missing_segments[0] if missing_segments else None
                    first_seg_str = f"{first_seg[0].strftime('%Y-%m-%d')}..{first_seg[1].strftime('%Y-%m-%d')}" if first_seg else "N/A"
                    print(f"[market] backfill missing_days={len(missing_dates)} segments={len(missing_segments)} first={first_seg_str}")
                    
                    # Fetch each segment separately
                    all_backfill_bars = []
                    missing_dates_set = set(missing_dates)  # For filtering
                    
                    for seg_start, seg_end in missing_segments:
                        # ARCHITECT FIX: STRICTLY FORBID FUTURE DATES
                        today = _dt.now().date()
                        if seg_start > today:
                            print(f"🛑 Skipping future segment: {seg_start} > {today}")
                            continue
                        
                        # Ensure we never request beyond today
                        request_end = seg_end
                        if request_end > today:
                            print(f"⚠️ Clamping end date from {request_end} to {today}")
                            request_end = today
                        
                        segment_bars = _fetch_remote_bars(normalized_symbol, mode_upper, seg_start, request_end)
                        
                        # Filter to only include bars that are actually in missing_dates
                        filtered_bars = []
                        for bar in segment_bars:
                            bar_date_str = bar.get("date", "")
                            if bar_date_str:
                                try:
                                    bar_date = _dt.strptime(bar_date_str, "%Y-%m-%d").date()
                                    if bar_date in missing_dates_set:
                                        filtered_bars.append(bar)
                                except (ValueError, TypeError):
                                    continue
                        
                        all_backfill_bars.extend(filtered_bars)
                    
                    if all_backfill_bars:
                        try:
                            upserted = upsert_market_bars(normalized_symbol, mode_upper, timeframe, all_backfill_bars)
                            print(f"💾 Backfilled {upserted} bars to DB")
                            # Re-fetch to get updated cache
                            cached_bars = get_cached_market_bars(normalized_symbol, mode_upper, timeframe, limit=2000)
                        except Exception as save_err:
                            print(f"⚠️ Failed to save backfill to cache: {save_err}")
                    else:
                        print(f"⚠️ No data returned for backfill segments")
                else:
                    # No missing days - cache hit, zero remote calls
                    print(f"[market] cache_hit points={len(cached_bars)}")
                
                return cached_bars
        
        # Cache exists but may be stale or insufficient
        print(f"[market] cache_miss, fetching_remote... (cached={len(cached_bars) if cached_bars else 0} points)")
    except Exception as cache_err:
        print(f"⚠️ Cache read error: {cache_err}")
        cached_bars = []
    
    # Step 2: Fetch from remote (full range)
    remote_bars = _fetch_remote_bars(normalized_symbol, mode_upper)
    
    if not remote_bars:
        # Remote failed - return cache if available
        if cached_bars:
            print(f"[market] remote_failed, serving_cache points={len(cached_bars)}")
            return cached_bars
        print(f"⚠️ No chart data available (cache={len(cached_bars) if cached_bars else 0}, remote=failed)")
        return []
    
    # Step 3: Save to cache
    try:
        upserted = upsert_market_bars(normalized_symbol, mode_upper, timeframe, remote_bars)
        print(f"💾 Cached {upserted} bars to DB")
    except Exception as save_err:
        print(f"⚠️ Failed to save to cache: {save_err}")
    
    print(f"✅ Got {len(remote_bars)} days of data from remote")
    return remote_bars

def create_chart(symbol):
    """Generate candlestick chart with Bollinger Bands, Volume, and SMAs. Returns Base64 string."""
    try:
        normalized_symbol = normalize_symbol(symbol)
        print(f"📊 Creating chart for {normalized_symbol}...")
        stock = yf.Ticker(normalized_symbol)
        hist = stock.history(period="6mo")
        
        if hist is None or len(hist) < 50:
            print(f"⚠️ Not enough data for chart: {len(hist) if hist is not None else 0} days")
            return None
        
        print(f"✅ Got {len(hist)} days of data")
        
        # Prepare data for mplfinance - ensure proper datetime index
        if not isinstance(hist.index, pd.DatetimeIndex):
            hist.index = pd.to_datetime(hist.index)
        
        # Calculate indicators - only use valid (non-NaN) values
        sma50 = hist['Close'].rolling(window=50).mean()
        sma200 = hist['Close'].rolling(window=200).mean()
        
        # Bollinger Bands
        sma20 = hist['Close'].rolling(window=20).mean()
        std20 = hist['Close'].rolling(window=20).std()
        bb_upper = sma20 + (std20 * 2)
        bb_lower = sma20 - (std20 * 2)
        
        # Create additional plots - be very careful with NaN values
        # mplfinance cannot handle Series with all NaN or empty arrays
        apds = []
        
        # Only add indicators if we have enough data AND valid (non-NaN) values
        # For 128 days: SMA50 works (needs 50), SMA200 doesn't (needs 200), BB works (needs 20)
        
        # SMA50: needs 50 days, we have 128
        if len(hist) >= 50:
            # Get only non-NaN values
            sma50_non_nan = sma50[sma50.notna()]
            if len(sma50_non_nan) > 0:
                # Use the full series but mplfinance should handle NaN automatically
                apds.append(mpf.make_addplot(sma50, color='blue', width=1.5, alpha=0.7))
        
        # Bollinger Bands: needs 20 days, we have 128
        if len(hist) >= 20:
            bb_upper_non_nan = bb_upper[bb_upper.notna()]
            bb_lower_non_nan = bb_lower[bb_lower.notna()]
            if len(bb_upper_non_nan) > 0 and len(bb_lower_non_nan) > 0:
                apds.append(mpf.make_addplot(bb_upper, color='gray', width=1, alpha=0.5, linestyle='--'))
                apds.append(mpf.make_addplot(bb_lower, color='gray', width=1, alpha=0.5, linestyle='--'))
        
        # Skip SMA200 - we don't have 200 days of data
        print(f"📊 Created {len(apds)} additional plots (will show SMA50 and BB)")
        
        # Method 1: Try savefig directly (most reliable)
        print("📈 Generating plot with mplfinance (savefig method)...")
        try:
            buffer = io.BytesIO()
            # Only use addplot if we have valid plots
            plot_kwargs = {
                'type': 'candle',
                'style': 'charles',
                'volume': True,
                'figsize': (12, 8),
                'savefig': dict(
                    fname=buffer,
                    format='png',
                    dpi=100,
                    bbox_inches='tight',
                    facecolor='#0d1117',
                    edgecolor='none'
                ),
                'show_nontrading': False,
                'tight_layout': True,
                'returnfig': False
            }
            # Only add addplot if we have valid plots
            if len(apds) > 0:
                plot_kwargs['addplot'] = apds
            
            mpf.plot(hist, **plot_kwargs)
            buffer.seek(0)
            chart_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            buffer.close()
            print(f"✅ Chart generated successfully with savefig! Base64 length: {len(chart_base64)}")
            return chart_base64
        except Exception as savefig_error:
            print(f"⚠️ savefig method failed: {savefig_error}")
            # Method 2: Try returnfig=True
            try:
                print("📈 Trying returnfig=True method...")
                import matplotlib.pyplot as plt
                fig, axes = mpf.plot(
                    hist,
                    type='candle',
                    style='charles',
                    volume=True,
                    addplot=apds,
                    figsize=(12, 8),
                    show_nontrading=False,
                    tight_layout=True,
                    returnfig=True,
                    closefig=False
                )
                
                # Apply dark theme
                fig.patch.set_facecolor('#0d1117')
                for ax in fig.axes:
                    ax.set_facecolor('#0d1117')
                    ax.tick_params(colors='#c9d1d9')
                    for spine in ax.spines.values():
                        spine.set_color('#30363d')
                
                # Save to buffer
                buffer = io.BytesIO()
                fig.savefig(buffer, format='png', dpi=100, bbox_inches='tight', facecolor='#0d1117', edgecolor='none')
                plt.close(fig)
                
                buffer.seek(0)
                chart_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                buffer.close()
                print(f"✅ Chart generated with returnfig method! Base64 length: {len(chart_base64)}")
                return chart_base64
            except Exception as returnfig_error:
                print(f"❌ returnfig method also failed: {returnfig_error}")
                import traceback
                print(f"❌ Full traceback: {traceback.format_exc()}")
                return None
        
    except Exception as e:
        import traceback
        print(f"❌ Chart generation error: {e}")
        print(f"❌ Full traceback: {traceback.format_exc()}")
        return None

def generate_stock_prompt(normalized_symbol, tech, fundamental, market, news_data, memory_section, cost, deep_tech, fair_value, insider_status, earnings_info, competitor_analysis):
    """Generate prompt for stock analysis with full fundamental intelligence."""
    # FEATURE 2: Get user risk profile from database
    user_profile = get_user_profile()
    risk_profile = user_profile.get("risk_profile", "Defansif/Garantici")
    system_instruction = user_profile.get("system_instruction", "Kullanıcı defansif bir yatırım yaklaşımı tercih ediyor.")
    
    fundamental_str = f"""
    - F/K Oranı (P/E): {fundamental['f_k_orani'] if fundamental['f_k_orani'] else 'N/A'}
    - Analist Hedef Fiyat: ${fundamental['analist_hedef_fiyat'] if fundamental['analist_hedef_fiyat'] else 'N/A'}
    - Analist Tavsiyesi: {fundamental['analist_tavsiyesi']}
    - Adil Değer (Graham): ${fair_value if fair_value else 'Hesaplanamadı'}
    - Insider Durumu: {insider_status}
    - Sonraki Bilanço: {earnings_info.get('bilanco_tarihi', 'Bilinmiyor')}
    - Sektör Karşılaştırması: {competitor_analysis}"""
    
    news_titles = news_data.get('titles', [])
    news_str = '\n    - '.join(news_titles[:5]) if news_titles else "Haber yok"
    
    golden_cross_status = "VAR ✅" if deep_tech['golden_cross'] else "YOK ❌"
    macd_status = deep_tech['macd_signal']
    
    valuation_note = ""
    if fair_value and tech['fiyat']:
        if tech['fiyat'] < fair_value * 0.9:
            valuation_note = f" ⚠️ ÖNEMLİ: Mevcut fiyat (${tech['fiyat']}) adil değerin (%{round((1 - tech['fiyat']/fair_value)*100, 1)}) altında - POTANSİYEL DEĞER FIRSATI!"
        elif tech['fiyat'] > fair_value * 1.1:
            valuation_note = f" ⚠️ ÖNEMLİ: Mevcut fiyat (${tech['fiyat']}) adil değerin (%{round((tech['fiyat']/fair_value - 1)*100, 1)}) üzerinde - AŞIRI DEĞERLENMİŞ OLABİLİR!"
    
    return f"""
    You are a Wall Street Senior Analyst. Analyze the technical and fundamental data for {normalized_symbol}. Do NOT use generic phrases. Provide specific insights on:
    
    KULLANICI RİSK PROFİLİ (USER RISK PROFILE):
    Risk Modu: {risk_profile}
    Sistem Talimatı: {system_instruction}
    
    ÖNEMLİ: Analiz yaparken kullanıcının risk profilini ({risk_profile}) dikkate al. Eğer "Agresif/Büyüme Odaklı" ise daha agresif stratejiler öner. Eğer "Defansif/Garantici" ise daha güvenli stratejiler öner. Eğer "Vur-Kaç (Scalper)" ise kısa vadeli işlemler öner.
    
    Whale Activity: Interpret the insider moves.
    Price Action: Key support/resistance levels.
    Verdict: Why exactly should I Buy, Sell, or Hold?
    Tone: Professional, direct, and critical.
    
    GİRDİLER (DATA INPUTS):
    - Fiyat: ${tech['fiyat']} (Maliyetim: ${cost}){valuation_note}
    - Teknik: RSI {tech['rsi']}, Bollinger Alt: {tech['bb_alt']}, Üst: {tech['bb_ust']}
    - Derin Teknikler: Golden Cross {golden_cross_status}, MACD Sinyali: {macd_status}, ATR (Volatilite): {deep_tech['atr']}, SMA50: ${deep_tech['sma50']}, SMA200: ${deep_tech['sma200']}
    - Temel Analiz:{fundamental_str}
    - Piyasa: VIX {market['vix']}, Durum {market['piyasa_durumu']}
    - Haberler: {news_str}
    {memory_section}

    GÖREV: Aşağıdaki JSON formatında, stratejik ve derinlemesine bir rapor oluştur.
    "ozel_strateji_basligi" kısmına duruma göre (örn: "Maliyet Düşürme", "Kâr Realizasyonu", "Bekle ve Gör") gibi net bir başlık at.
    
    ÖNEMLİ GÖREVLER:
    1. Önceki tahmin varsa, ondan öğren ve daha doğru bir karar ver.
    2. Temel analiz verilerini (F/K oranı, analist hedef fiyat, ADİL DEĞER) mutlaka değerlendir.
    3. Maliyet bazlı strateji geliştir (kâr/zarar durumunu değerlendir).
    4. Golden Cross ve MACD sinyallerini değerlendir.
    5. ADİL DEĞER ANALİZİ: Mevcut fiyat adil değere göre ne durumda? Aşırı değerlenmiş mi, değer fırsatı mı?
    6. INSIDER SİNYALLERİ: Insider alım/satım durumunu değerlendir. Pozitif insider aktivitesi güçlü bir sinyal olabilir.
    7. BİLANÇO TAKVİMİ: Sonraki bilanço tarihini dikkate al. Bilanço öncesi/sonrası stratejisi öner.
    8. SEKTÖR KARŞILAŞTIRMASI: Rakip analizi sonuçlarını değerlendir. Bu hisse sektörde nasıl konumlanmış?
    9. DESEN EŞLEŞTİRME: Mevcut fiyat hareketi geçmişteki hangi piyasa desenine benziyor? (Örn: 2008 kriz sonrası toparlanma, 2020 COVID düşüşü, dot-com balonu patlaması, vb.) Spesifik bir örnek ver.
    10. ANLIK OLAY KONTROLÜ: Verilen haber başlıklarını tarayarak, bu hisse senedini ŞU ANDA etkileyen "Breaking Events" var mı? (Örn: SEC dava, Fed faiz artışı, CEO istifası, büyük sipariş, vb.) Varsa detaylı açıkla.

    {{
        "karar": "AL / SAT / TUT",
        "guven_skoru": "0-100",
        "ana_neden": "Yönetici özetindeki ana gerekçe cümlesi. Adil değer, insider sinyalleri ve sektör karşılaştırmasını dahil et.",
        "ozdenetim_yorum": "Önceki kararları ve makro piyasanın hisseye etkisini yorumla. Önceki tahmin varsa onu da değerlendir.",
        "teknik_derinlik": "RSI momentumu ve Bollinger bantlarına göre fırsat analizi. Temel analiz verilerini de dahil et. Golden Cross ve MACD sinyallerini değerlendir.",
        "stratejik_plan": "Maliyete göre ne yapılmalı? Hedef fiyat ne? Analist hedef fiyatı ve adil değer ile karşılaştır. Bilanço takvimini dikkate al.",
        "ozel_strateji_basligi": "Duruma uygun strateji adı (Örn: Maliyet Düşürme Operasyonu)",
        "ozel_strateji_detayi": "Bu stratejinin mantığı ve nasıl uygulanacağı.",
        "stop_loss": "Net stop fiyatı",
        "risk_uyarisi": "En büyük risk faktörü",
        "benzer_gecmis_senaryo": "Geçmişteki hangi piyasa desenine benziyor? Spesifik örnek ve tarih ver.",
        "anlik_olay_kontrolu": "Şu anda bu hisseyi etkileyen breaking event var mı? Varsa detaylı açıkla, yoksa 'Kritik anlık olay yok' yaz."
    }}
    """

def generate_crypto_prompt(normalized_symbol, tech, fundamental, market, news_data, memory_section, deep_tech):
    """Generate prompt for crypto analysis."""
    fundamental_str = f"""
    - Tip: KRİPTO PARA (24/7 Piyasa)
    - Market Cap: {fundamental.get('market_cap', 'N/A')}
    - 24h Volume: {fundamental.get('volume_24h', 'N/A')}
    - Dolaşımdaki Arz: {fundamental.get('circulating_supply', 'N/A')}"""
    
    news_titles = news_data.get('titles', [])
    news_str = '\n    - '.join(news_titles[:5]) if news_titles else "Haber yok"
    
    golden_cross_status = "VAR ✅" if deep_tech['golden_cross'] else "YOK ❌"
    macd_status = deep_tech['macd_signal']
    
    return f"""
    Sen Kıdemli Kripto Para Trader'ısın. {normalized_symbol} için "MASTER ANALİZ" hazırla (24/7 Piyasa - Sürekli Açık).
    
    GİRDİLER:
    - Fiyat: ${tech['fiyat']}
    - Teknik: RSI {tech['rsi']}, Bollinger Alt: {tech['bb_alt']}, Üst: {tech['bb_ust']}
    - Derin Teknikler: Golden Cross {golden_cross_status}, MACD Sinyali: {macd_status}, ATR (Volatilite): {deep_tech['atr']}, SMA50: ${deep_tech['sma50']}, SMA200: ${deep_tech['sma200']}
    - Temel Analiz:{fundamental_str}
    - Piyasa: VIX {market['vix']}, Durum {market['piyasa_durumu']}
    - Haberler: {news_str}
    {memory_section}

    GÖREV: Aşağıdaki JSON formatında, stratejik ve derinlemesine bir rapor oluştur.
    ÖNEMLİ: Bu bir kripto para analizi. Maliyet/kâr sorma! Bunun yerine:
    - Trend yönü (LONG/SHORT bias) belirle
    - Giriş bölgesi (Entry Zone) belirle
    - Stop-Loss ve Take-Profit seviyeleri belirle
    
    ÖNEMLİ GÖREVLER:
    1. Önceki tahmin varsa, ondan öğren ve daha doğru bir karar ver.
    2. 24/7 piyasa olduğunu unutma, volatilite yüksek olabilir.
    3. Market cap ve volume verilerini değerlendir.
    4. LONG/SHORT bias'ı net belirt.
    5. Golden Cross ve MACD sinyallerini değerlendir.
    6. DESEN EŞLEŞTİRME: Mevcut fiyat hareketi geçmişteki hangi kripto piyasa desenine benziyor? (Örn: 2020 Bitcoin Halving sonrası yükseliş, 2017 ICO balonu, 2021 El Salvador Bitcoin yasası, 2022 Terra Luna çöküşü, vb.) Spesifik bir örnek ver.
    7. ANLIK OLAY KONTROLÜ: Verilen haber başlıklarını tarayarak, bu kripto parayı ŞU ANDA etkileyen "Breaking Events" var mı? (Örn: SEC dava, ETF onayı, büyük exchange hack, whale hareketi, vb.) Varsa detaylı açıkla.

    {{
        "karar": "LONG / SHORT / BEKLE",
        "guven_skoru": "0-100",
        "ana_neden": "Trend yönü ve ana gerekçe cümlesi.",
        "ozdenetim_yorum": "Önceki kararları ve makro piyasanın kripto para üzerindeki etkisini yorumla. Önceki tahmin varsa onu da değerlendir.",
        "teknik_derinlik": "RSI momentumu ve Bollinger bantlarına göre fırsat analizi. Market cap ve volume verilerini de dahil et. Golden Cross ve MACD sinyallerini değerlendir.",
        "stratejik_plan": "Trend yönü (LONG/SHORT), giriş bölgesi, hedef fiyatlar ve zaman çerçevesi.",
        "ozel_strateji_basligi": "Duruma uygun strateji adı (Örn: LONG Pozisyon - Yükseliş Trendi)",
        "ozel_strateji_detayi": "Bu stratejinin mantığı ve nasıl uygulanacağı. Entry zone, stop-loss ve take-profit seviyelerini detaylandır.",
        "stop_loss": "Net stop fiyatı (kripto için kritik)",
        "risk_uyarisi": "En büyük risk faktörü (volatilite, likidite, vb.)",
        "benzer_gecmis_senaryo": "Geçmişteki hangi kripto piyasa desenine benziyor? Spesifik örnek ve tarih ver.",
        "anlik_olay_kontrolu": "Şu anda bu kripto parayı etkileyen breaking event var mı? Varsa detaylı açıkla, yoksa 'Kritik anlık olay yok' yaz."
    }}
    """

def get_market_data_fast(symbol, mode="STOCK"):
    """
    Fast endpoint: Returns price, chart, technicals, fundamentals (no AI).
    Should complete in under 1 second.
    """
    normalized_symbol = normalize_symbol(symbol)
    crypto = (mode.upper() == "CRYPTO") or is_crypto(symbol)
    
    market = get_market_data()
    tech = get_technical_metrics(symbol)
    fundamental = get_fundamental_data(symbol)
    chart_data = get_chart_data(symbol, mode)  # Pass mode for cache
    news_data = get_news(symbol)  # Get AI-interpreted news
    
    # Fundamental Intelligence (only for stocks)
    fair_value = None
    insider_status = ""
    insider_transactions = []
    earnings_info = {"bilanco_tarihi": "Bilinmiyor", "analyst_estimates": "Yok"}
    competitor_analysis = ""
    
    if not crypto:
        fair_value = calculate_fair_value(symbol)
        insider_status = get_insider_intelligence(symbol)
        insider_transactions = get_insider_transactions_detailed(symbol)  # NEW: Detailed transactions
        earnings_info = get_earnings_info(symbol)
        competitor_analysis = get_competitor_analysis(symbol)
    
    response_data = {
        "sembol": normalized_symbol,
        "fiyat_bilgisi": tech,
        "piyasa_bilgisi": market,
        "grafik_verileri": chart_data if chart_data else [],
        "haber_skoru": news_data.get("sentiment_score", 50),
        "ai_interpreted_news": news_data.get("ai_interpreted", [])  # AI-filtered news
    }
    
    # Add fundamental intelligence fields (only for stocks)
    if not crypto:
        response_data["adil_deger"] = fair_value
        response_data["insider_durumu"] = insider_status
        response_data["insider_transactions"] = insider_transactions  # NEW: Detailed transactions list
        response_data["bilanco_tarihi"] = earnings_info.get('bilanco_tarihi', 'Bilinmiyor')
        response_data["sektor_karsilastirmasi"] = competitor_analysis
    else:
        response_data["adil_deger"] = None
        response_data["insider_durumu"] = None
        response_data["insider_transactions"] = []
        response_data["bilanco_tarihi"] = None
        response_data["sektor_karsilastirmasi"] = None
    
    return response_data

def local_decision_engine(
    technical: dict,
    fundamentals: Optional[dict] = None,
    insider: Optional[str] = None,
    volatility: Optional[float] = None,
) -> dict:
    """
    Local decision engine that generates BUY/HOLD/SELL recommendation based on technical indicators,
    fundamentals, insider activity, and volatility. No AI/LLM calls - pure deterministic logic.
    
    Args:
        technical: Technical metrics dict with keys: rsi, bb_alt, bb_ust, fiyat/current_price, trend (optional)
        fundamentals: Optional fundamental data dict (for future use)
        insider: Optional insider intelligence string (e.g., "POZİTİF - Son dönemde 2 alım, 1 satım")
        volatility: Optional volatility value (ATR or std dev percentage)
    
    Returns:
        dict: {"action": "BUY|HOLD|SELL", "confidence_score": int(0-100), "reason_tr": str}
    """
    # Extract technical indicators
    rsi = technical.get("rsi", 50)
    current_price = technical.get("current_price") or technical.get("fiyat", 0)
    bb_alt = technical.get("bb_alt", 0)
    bb_ust = technical.get("bb_ust", 0)
    trend = technical.get("trend", "SIDEWAYS")  # UP, DOWN, SIDEWAYS
    
    # Initialize base score (0-100, 50 = neutral)
    base_score = 50
    
    # 1. RSI Analysis (weight: 30 points)
    if rsi < 30:
        # Oversold - bullish signal
        base_score += 20
    elif rsi < 40:
        base_score += 10
    elif rsi > 70:
        # Overbought - bearish signal
        base_score -= 20
    elif rsi > 60:
        base_score -= 10
    
    # 2. Bollinger Bands Analysis (weight: 25 points)
    if current_price > 0 and bb_alt > 0 and bb_ust > 0:
        bb_mid = (bb_alt + bb_ust) / 2
        bb_range = bb_ust - bb_alt
        
        if bb_range > 0:
            # Position relative to bands
            position_ratio = (current_price - bb_alt) / bb_range
            
            if position_ratio < 0.2:
                # Near lower band - potential bounce
                base_score += 15
            elif position_ratio > 0.8:
                # Near upper band - potential pullback
                base_score -= 15
            elif position_ratio < 0.3:
                base_score += 8
            elif position_ratio > 0.7:
                base_score -= 8
    
    # 3. Trend Analysis (weight: 20 points)
    if trend == "UP":
        base_score += 15
    elif trend == "DOWN":
        base_score -= 15
    
    # 4. Insider Activity Analysis (weight: 15 points)
    if insider:
        insider_lower = insider.lower()
        # Check for positive/negative signals
        if "pozitif" in insider_lower or "alım" in insider_lower:
            # Count buy vs sell mentions
            buy_count = insider_lower.count("alım")
            sell_count = insider_lower.count("satım")
            
            if buy_count > sell_count:
                base_score += 12
            elif sell_count > buy_count * 2:
                # Heavy selling
                base_score -= 15
            elif sell_count > buy_count:
                base_score -= 8
        elif "negatif" in insider_lower or "satım" in insider_lower:
            base_score -= 10
    
    # 5. Volatility Adjustment (weight: 10 points)
    if volatility is not None:
        if volatility > 5.0:  # High volatility (>5%)
            # Reduce confidence but don't change action
            pass  # Will adjust confidence_score later
        elif volatility > 3.0:  # Medium volatility
            pass
    
    # Clamp score to 0-100
    final_score = max(0, min(100, base_score))
    
    # Determine action based on score
    if final_score >= 65:
        action = "BUY"
    elif final_score <= 35:
        action = "SELL"
    else:
        action = "HOLD"
    
    # Calculate confidence score (0-100)
    # Higher confidence when indicators agree, lower when they conflict
    confidence_score = 50  # Base confidence
    
    # Increase confidence if multiple indicators agree
    indicator_agreement = 0
    if rsi < 40 and (current_price <= bb_alt * 1.05 if bb_alt > 0 else False):
        indicator_agreement += 1
    if rsi > 60 and (current_price >= bb_ust * 0.95 if bb_ust > 0 else False):
        indicator_agreement += 1
    if trend == "UP" and rsi < 50:
        indicator_agreement += 1
    if trend == "DOWN" and rsi > 50:
        indicator_agreement += 1
    
    if indicator_agreement >= 2:
        confidence_score = 70
    elif indicator_agreement == 1:
        confidence_score = 55
    else:
        confidence_score = 40
    
    # Reduce confidence if volatility is high
    if volatility is not None and volatility > 5.0:
        confidence_score = max(30, confidence_score - 15)
    elif volatility is not None and volatility > 3.0:
        confidence_score = max(35, confidence_score - 10)
    
    # Build reason string in Turkish
    reasons = []
    
    if rsi < 30:
        reasons.append(f"RSI {rsi:.1f} - Aşırı satım bölgesinde")
    elif rsi > 70:
        reasons.append(f"RSI {rsi:.1f} - Aşırı alım bölgesinde")
    elif rsi < 40:
        reasons.append(f"RSI {rsi:.1f} - Satım bölgesine yakın")
    elif rsi > 60:
        reasons.append(f"RSI {rsi:.1f} - Alım bölgesine yakın")
    
    if current_price > 0 and bb_alt > 0 and bb_ust > 0:
        if current_price < bb_alt * 1.05:
            reasons.append("Bollinger alt bandına yakın - potansiyel destek")
        elif current_price > bb_ust * 0.95:
            reasons.append("Bollinger üst bandına yakın - potansiyel direnç")
    
    if trend == "UP":
        reasons.append("Yükseliş trendi aktif")
    elif trend == "DOWN":
        reasons.append("Düşüş trendi aktif")
    
    if insider:
        if "pozitif" in insider.lower() or ("alım" in insider.lower() and insider.lower().count("alım") > insider.lower().count("satım")):
            reasons.append("Insider alımları pozitif")
        elif "negatif" in insider.lower() or ("satım" in insider.lower() and insider.lower().count("satım") > insider.lower().count("alım") * 1.5):
            reasons.append("Insider satımları risk oluşturuyor")
    
    if volatility is not None and volatility > 5.0:
        reasons.append(f"Yüksek volatilite (%{volatility:.1f}) - dikkatli olunmalı")
    
    if not reasons:
        reasons.append("Teknik göstergeler nötr seviyede")
    
    reason_tr = ". ".join(reasons[:3])  # Max 3 reasons
    if not reason_tr.endswith("."):
        reason_tr += "."
    
    return {
        "action": action,
        "confidence_score": int(confidence_score),
        "reason_tr": reason_tr
    }


def apply_policy_guardrails(analysis: dict, news_items: List[dict]) -> dict:
    """
    Apply policy guardrails based on news impact and importance scores.
    Prevents "context blindness" by enforcing risk-aware decisions.
    
    Rules:
    1. If impact=bearish and importance_score >= 70:
       - Never recommend "BUY" (at least "HOLD" or "SELL")
       - Cap confidence_score at 40
       - Require stop_loss (auto-calculate if missing)
    2. If impact=bullish and importance_score >= 70:
       - Soften "SELL" recommendations (at least "HOLD")
    3. If neutral/low: no changes
    
    Args:
        analysis: Master analysis dict (may be modified in-place)
        news_items: List of news dicts with importance_score and impact fields
    
    Returns:
        Modified analysis dict with policy guardrails applied
    """
    if not news_items:
        return analysis
    
    # Find highest importance_score and impact distribution
    max_score = 0
    impact_counts = {"bearish": 0, "bullish": 0, "neutral": 0}
    
    # Impact mapping: support both English and Turkish values
    impact_map = {
        "bearish": "bearish",
        "negatif": "bearish",
        "negative": "bearish",
        "bullish": "bullish",
        "pozitif": "bullish",
        "positive": "bullish",
        "neutral": "neutral",
        "nötr": "neutral"
    }
    
    for news in news_items:
        score = news.get("importance_score", 0)
        impact_raw = news.get("impact", "neutral")
        impact_normalized = impact_map.get(impact_raw.lower(), "neutral")
        
        if score > max_score:
            max_score = score
        
        if impact_normalized in impact_counts:
            impact_counts[impact_normalized] += 1
    
    # Determine dominant impact
    dominant_impact = max(impact_counts.items(), key=lambda x: x[1])[0] if impact_counts else "neutral"
    
    policy_notes = []
    policy_applied = False
    
    # Rule 1: Bearish high-importance news
    if dominant_impact == "bearish" and max_score >= 70:
        policy_applied = True
        strategy = analysis.get("strategy", {})
        current_stance = strategy.get("stance", "HOLD").upper()
        
        # Never allow BUY or LONG (for crypto)
        if current_stance in ["BUY", "LONG"]:
            strategy["stance"] = "HOLD"
            policy_notes.append("Yüksek önemli bearish haber nedeniyle AL önerisi HOLD'a çevrildi")
            print(f"[policy] triggered impact=bearish score={max_score} action_cap=HOLD")
        
        # Cap confidence score at 40
        confidence_score = analysis.get("confidence_score", {})
        if isinstance(confidence_score, dict):
            current_conf = confidence_score.get("value", 50)
            if current_conf > 40:
                confidence_score["value"] = 40
                if "reasons_tr" not in confidence_score:
                    confidence_score["reasons_tr"] = []
                confidence_score["reasons_tr"].insert(0, "Yüksek önemli bearish haber nedeniyle güven skoru 40 ile sınırlandı")
                policy_notes.append("Güven skoru bearish haber nedeniyle 40'a düşürüldü")
        elif isinstance(confidence_score, (int, float)):
            # Handle case where confidence_score is a number
            if confidence_score > 40:
                analysis["confidence_score"] = {
                    "value": 40,
                    "reasons_tr": ["Yüksek önemli bearish haber nedeniyle güven skoru 40 ile sınırlandı"]
                }
                policy_notes.append("Güven skoru bearish haber nedeniyle 40'a düşürüldü")
        
        # Require stop_loss
        risk_mgmt = strategy.get("risk_management_tr", {})
        if not isinstance(risk_mgmt, dict):
            risk_mgmt = {}
            strategy["risk_management_tr"] = risk_mgmt
        
        if "stop_loss" not in risk_mgmt or risk_mgmt.get("stop_loss") is None or risk_mgmt.get("stop_loss") == 0:
            # Auto-calculate stop_loss (5% below current price)
            price = analysis.get("price_at_analysis", 0)
            if price > 0:
                risk_mgmt["stop_loss"] = round(price * 0.95, 2)
                policy_notes.append("Bearish haber nedeniyle stop_loss otomatik hesaplandı (%5 altı)")
                print(f"[policy] auto-calculated stop_loss={risk_mgmt['stop_loss']:.2f}")
        
        analysis["strategy"] = strategy
        if isinstance(confidence_score, dict):
            analysis["confidence_score"] = confidence_score
    
    # Rule 2: Bullish high-importance news
    elif dominant_impact == "bullish" and max_score >= 70:
        policy_applied = True
        strategy = analysis.get("strategy", {})
        current_stance = strategy.get("stance", "HOLD").upper()
        
        # Soften SELL or SHORT (for crypto) recommendations
        if current_stance in ["SELL", "SHORT"]:
            strategy["stance"] = "HOLD"
            policy_notes.append("Yüksek önemli bullish haber nedeniyle SAT önerisi HOLD'a yumuşatıldı")
            print(f"[policy] triggered impact=bullish score={max_score} action_softened=HOLD")
        
        analysis["strategy"] = strategy
    
    # Add policy metadata
    if policy_applied:
        # Add to data_quality_flags if exists
        if "data_quality_flags" not in analysis:
            analysis["data_quality_flags"] = []
        if "policy_guardrails_applied" not in analysis["data_quality_flags"]:
            analysis["data_quality_flags"].append("policy_guardrails_applied")
        
        # Add policy_notes (optional, won't break frontend)
        if policy_notes:
            analysis["policy_notes"] = policy_notes
    
    return analysis


def _calculate_trend_analysis(price: float, sma50: float, sma200: float, bb_mid: float = None) -> dict:
    """
    Calculate trend analysis based on MA20/MA50 positioning.
    
    Args:
        price: Current price
        sma50: 50-day moving average
        sma200: 200-day moving average
        bb_mid: Bollinger Band middle (MA20), if available
    
    Returns:
        dict with trend_label, ma20_position, ma50_position, trend_description
    """
    # Use BB mid as MA20 approximation if available
    ma20 = bb_mid if bb_mid and bb_mid > 0 else None
    
    trend_label = "SIDEWAYS"
    ma20_position = ""
    ma50_position = ""
    trend_description = ""
    
    if sma50 > 0 and sma200 > 0:
        # Determine trend based on MA50 vs MA200
        if sma50 > sma200:
            trend_label = "UP"
        elif sma50 < sma200:
            trend_label = "DOWN"
        
        # Price position relative to MAs
        if price > sma50:
            ma50_position = f"Fiyat MA50 üzerinde (+{((price/sma50 - 1) * 100):.1f}%)"
        else:
            ma50_position = f"Fiyat MA50 altında ({((price/sma50 - 1) * 100):.1f}%)"
        
        if ma20:
            if price > ma20:
                ma20_position = f"MA20 üzerinde (+{((price/ma20 - 1) * 100):.1f}%)"
            else:
                ma20_position = f"MA20 altında ({((price/ma20 - 1) * 100):.1f}%)"
            trend_description = f"{trend_label} - {ma20_position}, {ma50_position}"
        else:
            trend_description = f"{trend_label} - {ma50_position}"
    
    return {
        "trend_label": trend_label,
        "ma20_position": ma20_position,
        "ma50_position": ma50_position,
        "trend_description": trend_description
    }

def _calculate_momentum_analysis(rsi: float) -> dict:
    """
    Calculate momentum analysis based on RSI.
    
    Args:
        rsi: RSI value (0-100)
    
    Returns:
        dict with rsi_level, momentum_comment
    """
    if rsi >= 70:
        rsi_level = "AŞIRI ALIM"
        momentum_comment = f"RSI {rsi:.1f} - Aşırı alım bölgesinde, düzeltme riski yüksek."
    elif rsi >= 50:
        rsi_level = "GÜÇLÜ"
        momentum_comment = f"RSI {rsi:.1f} - Güçlü momentum, yükseliş eğilimi devam edebilir."
    elif rsi >= 30:
        rsi_level = "ZAYIF"
        momentum_comment = f"RSI {rsi:.1f} - Zayıf momentum, düşüş eğilimi görülüyor."
    else:
        rsi_level = "AŞIRI SATIM"
        momentum_comment = f"RSI {rsi:.1f} - Aşırı satım bölgesinde, toparlanma fırsatı olabilir."
    
    return {
        "rsi_level": rsi_level,
        "momentum_comment": momentum_comment
    }

def _calculate_volatility_analysis(price: float, bb_upper: float, bb_lower: float) -> dict:
    """
    Calculate volatility analysis based on Bollinger Bands.
    
    Args:
        price: Current price
        bb_upper: Bollinger Band upper
        bb_lower: Bollinger Band lower
    
    Returns:
        dict with bb_width_pct, bb_position, volatility_comment
    """
    if bb_upper <= 0 or bb_lower <= 0 or price <= 0:
        return {
            "bb_width_pct": 0,
            "bb_position": "MID",
            "volatility_comment": "Bollinger Bands verisi mevcut değil"
        }
    
    bb_mid = (bb_upper + bb_lower) / 2
    bb_width = bb_upper - bb_lower
    bb_width_pct = (bb_width / bb_mid) * 100 if bb_mid > 0 else 0
    
    # Position relative to bands
    position_ratio = (price - bb_lower) / bb_width if bb_width > 0 else 0.5
    
    if position_ratio >= 0.8:
        bb_position = "ÜST"
        volatility_comment = f"Fiyat üst banda yakın, volatilite {bb_width_pct:.1f}% - yüksek volatilite, düzeltme olasılığı var."
    elif position_ratio <= 0.2:
        bb_position = "ALT"
        volatility_comment = f"Fiyat alt banda yakın, volatilite {bb_width_pct:.1f}% - destek seviyesinde, yükseliş potansiyeli."
    else:
        bb_position = "ORTA"
        volatility_comment = f"Fiyat bantların ortasında, volatilite {bb_width_pct:.1f}% - normal seviyede."
    
    return {
        "bb_width_pct": round(bb_width_pct, 2),
        "bb_position": bb_position,
        "volatility_comment": volatility_comment
    }

def _calculate_risk_metrics(price: float, atr: float) -> dict:
    """
    Calculate risk metrics (stop-loss, take-profit) based on ATR.
    
    Args:
        price: Current price
        atr: Average True Range
    
    Returns:
        dict with stop_loss, take_profit, risk_score, risk_label
    """
    if atr <= 0 or price <= 0:
        # Fallback to percentage-based
        stop_loss = round(price * 0.95, 2)
        take_profit_1 = round(price * 1.10, 2)
        take_profit_2 = round(price * 1.15, 2)
        risk_score = 50
        risk_label = "MEDIUM"
    else:
        # ATR-based calculation
        stop_loss = round(price - (1.5 * atr), 2)
        take_profit_1 = round(price + (2.0 * atr), 2)
        take_profit_2 = round(price + (3.0 * atr), 2)
        
        # Risk score based on ATR relative to price
        atr_pct = (atr / price) * 100
        if atr_pct > 5.0:
            risk_score = 75
            risk_label = "HIGH"
        elif atr_pct > 2.5:
            risk_score = 50
            risk_label = "MEDIUM"
        else:
            risk_score = 25
            risk_label = "LOW"
    
    return {
        "stop_loss": stop_loss,
        "take_profit": [take_profit_1, take_profit_2],
        "risk_score": risk_score,
        "risk_label": risk_label
    }

def _generate_scenarios(price: float, rsi: float, trend: str, bb_position: str, atr: float) -> dict:
    """
    Generate bull/base/bear scenarios based on technical indicators.
    
    Args:
        price: Current price
        rsi: RSI value
        trend: Trend label (UP/DOWN/SIDEWAYS)
        bb_position: Bollinger Band position (ALT/ORTA/ÜST)
        atr: Average True Range
    
    Returns:
        dict with bull_case_tr, base_case_tr, bear_case_tr
    """
    # Bull case
    if trend == "UP" and rsi < 70 and bb_position in ["ALT", "ORTA"]:
        bull_thesis = f"Yükseliş trendi devam ediyor, RSI {rsi:.1f} seviyesinde. Fiyat {bb_position} bölgede, yükseliş potansiyeli var."
        bull_price = round(price * 1.15, 2)
    elif trend == "UP":
        bull_thesis = f"Yükseliş trendi aktif, ancak RSI {rsi:.1f} yüksek seviyede. İhtiyatlı yükseliş beklenebilir."
        bull_price = round(price * 1.10, 2)
    else:
        bull_thesis = f"RSI {rsi:.1f} ve trend {trend}. Teknik iyileşme ile yükseliş senaryosu mümkün."
        bull_price = round(price * 1.12, 2)
    
    # Base case
    if trend == "SIDEWAYS":
        base_thesis = f"Yatay trend devam ediyor. RSI {rsi:.1f} ve {bb_position} bölge - konsolidasyon beklentisi."
        base_price = price
    else:
        base_thesis = f"Trend {trend}, RSI {rsi:.1f}. Mevcut seviyelerde konsolidasyon veya hafif hareket beklenebilir."
        base_price = price
    
    # Bear case
    if trend == "DOWN" and rsi > 30 and bb_position in ["ÜST", "ORTA"]:
        bear_thesis = f"Düşüş trendi devam ediyor, RSI {rsi:.1f} seviyesinde. Fiyat {bb_position} bölgede, düşüş riski var."
        bear_price = round(price * 0.85, 2)
    elif trend == "DOWN":
        bear_thesis = f"Düşüş trendi aktif. RSI {rsi:.1f} düşük seviyede, ancak daha fazla düşüş riski mevcut."
        bear_price = round(price * 0.90, 2)
    else:
        bear_thesis = f"Trend {trend}, RSI {rsi:.1f}. Teknik bozulma ile düşüş senaryosu mümkün."
        bear_price = round(price * 0.88, 2)
    
    return {
        "bull_case_tr": {
            "thesis": bull_thesis,
            "triggers": ["RSI düşüş bölgesine gelir", "Trend yükselişe döner", "Bollinger alt bandına destek bulur"],
            "price_path": f"Hedef: ${bull_price:.2f}"
        },
        "base_case_tr": {
            "thesis": base_thesis,
            "triggers": ["Mevcut trend devam eder", "RSI nötr bölgede kalır"],
            "price_path": f"Konsolidasyon: ${base_price:.2f} civarı"
        },
        "bear_case_tr": {
            "thesis": bear_thesis,
            "triggers": ["RSI yükseliş bölgesine çıkar", "Trend düşüşe döner", "Bollinger üst bandına direnç görür"],
            "price_path": f"Kritik seviye: ${bear_price:.2f}"
        }
    }

def build_template_analysis(
    symbol: str,
    mode: str,
    price: float,
    technical_context: dict,
    news_data: dict,
    news_items: List[dict]
) -> dict:
    """
    Build rich deterministic template-based analysis without LLM.
    Used when use_llm=0.
    
    Args:
        symbol: Stock/crypto symbol
        mode: "STOCK" or "CRYPTO"
        price: Current price
        technical_context: Technical metrics dict (includes tech + deep_tech merged)
        news_data: News data dict
        news_items: List of analyzed news items
    
    Returns:
        Complete master analysis dict matching UI contract
    """
    mode_upper = mode.upper()
    is_crypto = mode_upper == "CRYPTO"
    
    # Extract technical indicators
    rsi = technical_context.get("rsi", 50)
    bb_upper = technical_context.get("bb_ust", 0)
    bb_lower = technical_context.get("bb_alt", 0)
    atr = technical_context.get("atr", 0)
    sma50 = technical_context.get("sma50", 0)
    sma200 = technical_context.get("sma200", 0)
    macd_signal = technical_context.get("macd_signal", "NÖTR")
    golden_cross = technical_context.get("golden_cross", False)
    trend = technical_context.get("trend", "SIDEWAYS")
    
    # Calculate BB middle (MA20 approximation)
    bb_mid = (bb_upper + bb_lower) / 2 if bb_upper > 0 and bb_lower > 0 else None
    
    # Calculate detailed analyses
    trend_analysis = _calculate_trend_analysis(price, sma50, sma200, bb_mid)
    momentum_analysis = _calculate_momentum_analysis(rsi)
    volatility_analysis = _calculate_volatility_analysis(price, bb_upper, bb_lower)
    risk_metrics = _calculate_risk_metrics(price, atr)
    scenarios = _generate_scenarios(price, rsi, trend_analysis["trend_label"], volatility_analysis["bb_position"], atr)
    
    # Analyze news impact
    news_impact_summary = "Nötr"
    if news_items:
        max_score = max((n.get("importance_score", 0) for n in news_items), default=0)
        dominant_impact = "neutral"
        for news in news_items:
            if news.get("importance_score", 0) == max_score:
                dominant_impact = news.get("impact", "neutral").lower()
                break
        
        impact_map = {"bearish": "Olumsuz", "negatif": "Olumsuz", "bullish": "Olumlu", "pozitif": "Olumlu", "neutral": "Nötr", "nötr": "Nötr"}
        news_impact_summary = impact_map.get(dominant_impact, "Nötr")
    
    # Determine stance using local_decision_engine
    try:
        local_decision = local_decision_engine(
            technical=technical_context,
            fundamentals=None,
            insider=None,
            volatility=None
        )
        stance = local_decision.get("action", "HOLD")
        if is_crypto:
            if stance == "BUY":
                stance = "LONG"
            elif stance == "SELL":
                stance = "SHORT"
            else:
                stance = "BEKLE"
    except Exception:
        stance = "HOLD" if not is_crypto else "BEKLE"
    
    # Build rich summary
    headline = f"{symbol.upper()} - Deterministik Teknik Analiz (LLM Kapalı)"
    one_liner = f"{momentum_analysis['momentum_comment']} {trend_analysis['trend_description']}. {volatility_analysis['volatility_comment']}"
    
    key_points = [
        f"RSI: {rsi:.1f} ({momentum_analysis['rsi_level']})",
        trend_analysis['trend_description'] if trend_analysis['trend_description'] else f"Trend: {trend_analysis['trend_label']}",
        volatility_analysis['volatility_comment'],
        f"Risk Seviyesi: {risk_metrics['risk_label']} (Skor: {risk_metrics['risk_score']}/100)"
    ]
    
    if sma50 > 0 and sma200 > 0:
        if golden_cross:
            key_points.append("Golden Cross aktif - Uzun vadeli yükseliş sinyali")
        if macd_signal != "NÖTR":
            key_points.append(f"MACD: {macd_signal} sinyali")
    
    if news_items:
        top_news = max(news_items, key=lambda x: x.get("importance_score", 0), default=None)
        if top_news and top_news.get("importance_score", 0) >= 50:
            key_points.append(f"Önemli haber: {top_news.get('title', 'N/A')[:60]}")
    
    # Build complete analysis structure
    as_of = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    template_analysis = {
        "symbol": symbol.upper(),
        "mode": mode_upper,
        "as_of": as_of,
        "price_at_analysis": price,
        "summary": {
            "headline_tr": headline,
            "one_liner_tr": one_liner,
            "key_points_tr": key_points[:6]  # Max 6
        },
        "technical_analysis": {
            "trend": trend_analysis["trend_label"],
            "support_levels": [
                round(price * 0.95, 2),
                round(price * 0.90, 2),
                round(bb_lower, 2) if bb_lower > 0 else round(price * 0.85, 2)
            ],
            "resistance_levels": [
                round(price * 1.05, 2),
                round(price * 1.10, 2),
                round(bb_upper, 2) if bb_upper > 0 else round(price * 1.15, 2)
            ],
            "indicators": {
                "rsi": {
                    "value": round(rsi, 1),
                    "interpretation_tr": momentum_analysis["momentum_comment"]
                },
                "macd": {
                    "signal": macd_signal.upper() if macd_signal != "NÖTR" else "NEUTRAL",
                    "interpretation_tr": f"MACD: {macd_signal} sinyali" if macd_signal != "NÖTR" else "MACD nötr bölgede"
                },
                "bbands": {
                    "position": volatility_analysis["bb_position"],
                    "interpretation_tr": volatility_analysis["volatility_comment"]
                }
            },
            "notes_tr": [
                momentum_analysis["momentum_comment"],
                trend_analysis["trend_description"] if trend_analysis["trend_description"] else f"Trend: {trend_analysis['trend_label']}",
                volatility_analysis["volatility_comment"],
                f"Volatilite: {volatility_analysis['bb_width_pct']:.2f}% (Bollinger Band genişliği)",
                "⚠️ Deterministik analiz - LLM kapalı, yerel hesaplamalar kullanıldı"
            ]
        },
        "fundamental_analysis": {
            "valuation": {"view": "FAIR", "reason_tr": "Deterministik analiz - LLM kapalı, temel analiz yapılamadı"},
            "growth": {"view": "MODERATE", "reason_tr": "Deterministik analiz - LLM kapalı, büyüme verisi yok"},
            "profitability": {"view": "MODERATE", "reason_tr": "Deterministik analiz - LLM kapalı, karlılık verisi yok"},
            "risks_tr": [
                f"Volatilite riski: {volatility_analysis['bb_width_pct']:.2f}% (Bollinger Band genişliği)",
                f"RSI {rsi:.1f} seviyesi {'yüksek volatilite' if rsi > 70 or rsi < 30 else 'normal'} riski gösteriyor",
                "LLM kapalı - detaylı temel analiz yapılamadı"
            ]
        },
        "sentiment_and_catalysts": {
            "sentiment": "POSITIVE" if rsi > 50 and trend_analysis["trend_label"] == "UP" else "NEGATIVE" if rsi < 50 and trend_analysis["trend_label"] == "DOWN" else "NEUTRAL",
            "drivers_tr": [
                momentum_analysis["momentum_comment"],
                trend_analysis["trend_description"] if trend_analysis["trend_description"] else f"Trend: {trend_analysis['trend_label']}",
                f"Haber etkisi: {news_impact_summary}"
            ],
            "catalysts_tr": [
                f"RSI {rsi:.1f} seviyesi - {'güçlü momentum' if rsi > 50 else 'zayıf momentum'}",
                f"Bollinger {volatility_analysis['bb_position']} bölge - {'destek' if volatility_analysis['bb_position'] == 'ALT' else 'direnç' if volatility_analysis['bb_position'] == 'ÜST' else 'nötr'} sinyali",
                "LLM kapalı - katalizör analizi yerel hesaplamalarla sınırlı"
            ],
            "news_impact_tr": news_impact_summary
        },
        "scenarios": scenarios,
        "strategy": {
            "stance": stance,
            "entry_plan_tr": [
                f"Giriş: Mevcut fiyat ${price:.2f} civarı",
                f"Stop Loss: ${risk_metrics['stop_loss']:.2f} (ATR bazlı: {((price - risk_metrics['stop_loss']) / price * 100):.1f}% altı)" if price > 0 else f"Stop Loss: ${risk_metrics['stop_loss']:.2f}",
                f"Take Profit: ${risk_metrics['take_profit'][0]:.2f} (Hedef 1) veya ${risk_metrics['take_profit'][1]:.2f} (Hedef 2)"
            ],
            "risk_management_tr": {
                "stop_loss": risk_metrics["stop_loss"],
                "take_profit": risk_metrics["take_profit"],
                "position_sizing_tr": f"Risk seviyesi {risk_metrics['risk_label']} - pozisyon boyutu kullanıcı risk profiline göre ayarlanmalı. ATR: ${atr:.2f}, volatilite: {volatility_analysis['bb_width_pct']:.2f}%"
            },
            "time_horizon": "SHORT" if atr > 0 and price > 0 and (atr / price) > 0.03 else "MEDIUM"
        },
        "risk_score": {
            "value": risk_metrics["risk_score"],
            "label": risk_metrics["risk_label"],
            "reasons_tr": [
                f"ATR bazlı risk skoru: {risk_metrics['risk_score']}/100",
                f"Volatilite: {volatility_analysis['bb_width_pct']:.2f}% (Bollinger Band genişliği)",
                f"RSI {rsi:.1f} - {'yüksek' if rsi > 70 or rsi < 30 else 'normal'} risk sinyali"
            ]
        },
        "confidence_score": {
            "value": 55,  # Moderate confidence - rich deterministic analysis
            "reasons_tr": [
                "⚠️ LLM kapalı - Deterministik yerel hesaplamalar kullanıldı",
                "Teknik göstergeler (RSI, MA, Bollinger, ATR) mevcut ve analiz edildi",
                "Temel analiz ve haber yorumu yapılamadı (LLM gerektirir)"
            ]
        },
        "data_quality_flags": ["template_analysis", "llm_disabled"]
    }
    
    # Apply policy guardrails
    template_analysis = apply_policy_guardrails(template_analysis, news_items)
    
    return template_analysis


def build_comparative_context(prev_decision: Optional[Dict[str, Any]], current_price: float, current_technical: dict) -> str:
    """
    Build a comparative context string from previous decision data.
    
    This creates a narrative context that highlights what changed since the last analysis,
    making the AI mentor feel like it remembers past advice.
    
    Args:
        prev_decision: Previous decision dict from get_last_decision_for_symbol()
        current_price: Current market price
        current_technical: Current technical metrics
    
    Returns:
        str: Formatted comparative context string (empty if no previous decision)
    """
    if not prev_decision:
        return ""
    
    # Extract previous data
    prev_price = prev_decision.get("price_at_analysis", 0)
    prev_verdict = prev_decision.get("verdict", "TUT")
    prev_decision_eng = prev_decision.get("decision", "HOLD")
    prev_confidence = prev_decision.get("confidence", 50)
    prev_created = prev_decision.get("created_at", "")
    prev_reasoning = prev_decision.get("key_reasoning", "")
    prev_tech = prev_decision.get("technical_snapshot", {})
    
    # Calculate changes
    price_change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
    price_direction = "yükseldi" if price_change_pct > 0 else "düştü" if price_change_pct < 0 else "sabit kaldı"
    
    # RSI comparison
    prev_rsi = prev_tech.get("rsi", 50)
    current_rsi = current_technical.get("rsi", 50)
    rsi_change = current_rsi - prev_rsi
    rsi_trend = "arttı" if rsi_change > 5 else "azaldı" if rsi_change < -5 else "stabil kaldı"
    
    # Volatility comparison
    prev_vol = prev_tech.get("volatility", "MEDIUM")
    current_vol = current_technical.get("volatility", "MEDIUM")
    vol_change = ""
    if prev_vol != current_vol:
        vol_change = f"Volatilite {prev_vol}'dan {current_vol}'a değişti. "
    
    # Time elapsed
    time_elapsed = ""
    try:
        from datetime import datetime
        if prev_created:
            prev_dt = datetime.fromisoformat(prev_created.replace("Z", "+00:00"))
            now_dt = datetime.now(prev_dt.tzinfo)
            days_ago = (now_dt - prev_dt).days
            if days_ago == 0:
                time_elapsed = "bugün"
            elif days_ago == 1:
                time_elapsed = "dün"
            elif days_ago < 7:
                time_elapsed = f"{days_ago} gün önce"
            else:
                weeks_ago = days_ago // 7
                time_elapsed = f"{weeks_ago} hafta önce"
    except:
        time_elapsed = "geçen analizde"
    
    # Build narrative context
    context = f"""
═══════════════════════════════════════════════════════════════
PREVIOUS DECISION CONTEXT (Context-Aware Memory)
═══════════════════════════════════════════════════════════════
Last Analysis: {time_elapsed}
Previous Decision: {prev_verdict} ({prev_decision_eng}) - Güven: {prev_confidence}%
Previous Price: ${prev_price:.2f}
Current Price: ${current_price:.2f} ({price_direction} %{abs(price_change_pct):.2f})

KEY CHANGES SINCE LAST ANALYSIS:
- Fiyat {price_direction} (${prev_price:.2f} → ${current_price:.2f}, %{price_change_pct:+.2f})
- RSI {prev_rsi:.1f} → {current_rsi:.1f} ({rsi_trend}, {rsi_change:+.1f} puan)
- {vol_change if vol_change else f"Volatilite: {current_vol} (değişmedi)"}

Previous Reasoning Summary:
"{prev_reasoning}"

CRITICAL INSTRUCTION FOR AI:
Your analysis MUST be COMPARATIVE. Don't just describe current state - explain:
1. WHAT CHANGED: Compare current vs previous state with SPECIFIC numbers
2. WHY IT CHANGED: Explain the drivers behind the changes
3. WHAT IT MEANS: How does this affect the previous decision?

Example Format:
"Risk has INCREASED since our last check because volatility jumped from {prev_vol} to {current_vol}, 
and the RSI moved from {prev_rsi:.1f} to {current_rsi:.1f}, indicating overbought conditions."

NOT ACCEPTABLE (generic):
"RSI is high" or "Volatility increased"

ACCEPTABLE (specific & comparative):
"RSI increased from 45 to 72 (+27 points) since last week, crossing into overbought territory. 
This contradicts our previous HOLD stance as momentum risk has significantly elevated."
═══════════════════════════════════════════════════════════════
"""
    
    return context.strip()


def calibrate_confidence_score(
    base_confidence: int,
    technical_indicators: dict,
    news_sentiment: dict,
    decision: str
) -> Tuple[int, List[str]]:
    """
    Calibrate confidence score based on indicator alignment and signal consistency.
    
    Rules:
    1. If trend contradicts news → lower confidence
    2. If technicals + news align → boost confidence > 80%
    3. If volatility is high → reduce confidence
    4. If multiple indicators disagree → reduce confidence
    
    Args:
        base_confidence: Initial confidence score from LLM (0-100)
        technical_indicators: Dict with RSI, trend, volatility, MACD
        news_sentiment: Dict with sentiment score and impact
        decision: Current decision (BUY/HOLD/AVOID)
    
    Returns:
        Tuple of (calibrated_confidence, reasons_list)
    """
    calibrated = base_confidence
    adjustments = []
    
    # Extract key signals (coerce rsi/sentiment_score to float to prevent TypeError on comparison)
    try:
        rsi = float(technical_indicators.get("rsi", 50) or 50)
    except (TypeError, ValueError):
        rsi = 50.0
    trend = technical_indicators.get("trend", "NEUTRAL")
    volatility = technical_indicators.get("volatility", "MEDIUM")
    macd_signal = technical_indicators.get("macd_signal", "NEUTRAL")
    
    sentiment_score = news_sentiment.get("sentiment_score", 50)
    news_impact = news_sentiment.get("impact", "NEUTRAL")
    
    # Determine technical bias
    tech_bullish = (rsi > 50 and trend == "UP") or (rsi > 60)
    tech_bearish = (rsi < 50 and trend == "DOWN") or (rsi < 40)
    tech_neutral = not tech_bullish and not tech_bearish
    
    # Determine news bias
    news_bullish = sentiment_score > 60 or news_impact == "POSITIVE"
    news_bearish = sentiment_score < 40 or news_impact == "NEGATIVE"
    news_neutral = not news_bullish and not news_bearish
    
    # Rule 1: Check alignment between technicals and news
    if (tech_bullish and news_bullish) or (tech_bearish and news_bearish):
        # Strong alignment → boost confidence
        calibrated += 15
        adjustments.append(f"Teknik göstergeler ve haberler aynı yönde ({'+15' if (tech_bullish and news_bullish) else '+15'})")
    elif (tech_bullish and news_bearish) or (tech_bearish and news_bullish):
        # Contradiction → lower confidence
        calibrated -= 20
        adjustments.append(f"Teknik göstergeler ve haberler çelişiyor (-20)")
    
    # Rule 2: High volatility reduces confidence
    if volatility == "HIGH":
        calibrated -= 10
        adjustments.append("Yüksek volatilite belirsizlik yaratıyor (-10)")
    elif volatility == "LOW":
        calibrated += 5
        adjustments.append("Düşük volatilite istikrar sağlıyor (+5)")
    
    # Rule 3: Multiple indicator agreement
    indicators_agree = 0
    
    # Check RSI alignment with decision
    if decision == "BUY" and rsi > 50:
        indicators_agree += 1
    elif decision == "AVOID" and rsi < 50:
        indicators_agree += 1
    elif decision == "HOLD" and 40 <= rsi <= 60:
        indicators_agree += 1
    
    # Check trend alignment with decision
    if decision == "BUY" and trend == "UP":
        indicators_agree += 1
    elif decision == "AVOID" and trend == "DOWN":
        indicators_agree += 1
    elif decision == "HOLD" and trend == "NEUTRAL":
        indicators_agree += 1
    
    # Check MACD alignment
    if macd_signal == "BULLISH" and decision == "BUY":
        indicators_agree += 1
    elif macd_signal == "BEARISH" and decision == "AVOID":
        indicators_agree += 1
    
    if indicators_agree >= 2:
        calibrated += 10
        adjustments.append(f"{indicators_agree} gösterge kararla uyumlu (+10)")
    elif indicators_agree == 0:
        calibrated -= 15
        adjustments.append("Göstergeler kararla uyuşmuyor (-15)")
    
    # Rule 4: Extreme RSI conditions reduce confidence (overbought/oversold unpredictable)
    if rsi > 75 or rsi < 25:
        calibrated -= 10
        adjustments.append(f"RSI aşırı bölgede ({rsi:.1f}) - yön belirsiz (-10)")
    
    # Cap confidence between 20 and 95
    calibrated = max(20, min(95, calibrated))
    
    return calibrated, adjustments


def run_master_analysis(
    symbol: str,
    mode: str,
    price: float,
    technical_context: dict,
    news_context: list[dict],
    memory_summaries: list[str],
    user_profile: Optional[dict] = None,
    detail: str = "medium",
    fundamental_context: Optional[dict] = None,
) -> dict:
    """
    Master analysis function that makes ONE Gemini API call per analysis.
    NOW WITH CONTEXT-AWARE MEMORY: Fetches previous decision and builds comparative narrative.
    
    Args:
        symbol: Stock/crypto symbol
        mode: "STOCK" or "CRYPTO"
        price: Current price
        technical_context: Technical metrics dict (RSI, Bollinger, etc.)
        news_context: List of news dicts with title, source, published_at, link, sentiment_hint
        memory_summaries: List of past analysis summary strings
        user_profile: Optional user profile dict with risk tolerance, etc.
    
    Returns:
        dict: Complete analysis result with all required fields
    """
    # CRITICAL: Initialize variables at function start to prevent UnboundLocalError in except blocks
    top_3_news_fallback = []
    chart_data = []
    
    # Build comprehensive prompt
    mode_upper = mode.upper()
    is_crypto_mode = mode_upper == "CRYPTO"
    
    # STEP 1: Fetch previous decision context (Context-Aware Memory System)
    print(f"🧠 [Context-Aware] Fetching previous decision for {symbol}...")
    prev_decision = get_last_decision_for_symbol(symbol, mode_upper)
    
    if prev_decision:
        print(f"✅ [Context-Aware] Found previous decision: {prev_decision.get('verdict', 'N/A')} at ${prev_decision.get('price_at_analysis', 0):.2f}")
    else:
        print(f"ℹ️ [Context-Aware] No previous decision found - first analysis for {symbol}")
    
    # Format technical context - OPTIMIZED: Only summary metrics, not full OHLCV
    # Extract key indicators only
    tech_summary = {
        "rsi": technical_context.get("rsi", 50),
        "bb_upper": technical_context.get("bb_upper", price * 1.05),
        "bb_lower": technical_context.get("bb_lower", price * 0.95),
        "bb_mid": technical_context.get("bb_mid", price),
        "sma50": technical_context.get("sma50", price),
        "sma200": technical_context.get("sma200", price),
        "atr": technical_context.get("atr", 0),
        "golden_cross": technical_context.get("golden_cross", False),
        "macd_signal": technical_context.get("macd_signal", "NÖTR"),
        "current_price": price
    }
    tech_str = json.dumps(tech_summary, indent=2, ensure_ascii=False)
    
    # Get chart data for key levels (downsampled - last 30 bars only)
    chart_summary = ""
    try:
        chart_list = get_chart_data(symbol, mode_upper)
        if chart_list and isinstance(chart_list, list) and len(chart_list) > 0:
            # Downsample: take last 30 bars only
            recent_bars = chart_list[-30:] if len(chart_list) > 30 else chart_list
            highs = [bar.get("high", 0) for bar in recent_bars if "high" in bar]
            lows = [bar.get("low", 0) for bar in recent_bars if "low" in bar]
            closes = [bar.get("close", 0) for bar in recent_bars if "close" in bar]
            
            if highs and lows and closes:
                recent_high = max(highs)
                recent_low = min(lows)
                current_close = closes[-1] if closes else price
                
                # Calculate key levels
                support_1 = recent_low * 0.98
                support_2 = recent_low * 0.99
                resistance_1 = recent_high * 1.01
                resistance_2 = recent_high * 1.05
                
                chart_summary = f"""
CHART SUMMARY (Last 30 bars):
- Recent High: ${recent_high:.2f}
- Recent Low: ${recent_low:.2f}
- Current Close: ${current_close:.2f}
- Key Support Levels: ${support_1:.2f}, ${support_2:.2f}
- Key Resistance Levels: ${resistance_1:.2f}, ${resistance_2:.2f}
"""
    except Exception as e:
        print(f"⚠️ [run_master_analysis] Failed to get chart summary: {e}")
        chart_summary = ""
    
    # Format news context - Local heuristic selection (max 5 items, no LLM call)
    news_str = ""
    if news_context:
        # Local heuristic: prioritize by sentiment (Positive/Negative > Neutral), then recency
        # Sort: Positive/Negative first, then by published_at (most recent first)
        def news_priority(news):
            sentiment = news.get("sentiment_hint", "Neutral").upper()
            priority = 0
            if sentiment in ["POSITIVE", "NEGATIVE"]:
                priority = 1
            # Use published_at for recency (if available)
            published_at = news.get("published_at", "")
            return (priority, published_at)
        
        sorted_news = sorted(news_context, key=news_priority, reverse=True)
        selected_news = sorted_news[:5]  # Maximum 5 items
        
        news_items = []
        for news in selected_news:
            title = news.get("title", "N/A")
            # Truncate title if too long (max 100 chars)
            if len(title) > 100:
                title = title[:97] + "..."
            source = news.get("source", "Unknown")
            published_at = news.get("published_at", "N/A")
            sentiment = news.get("sentiment_hint", "Neutral")
            # Short format: title, sentiment only
            news_items.append(f"- {title} ({sentiment})")
        news_str = "\n".join(news_items)
    else:
        news_str = "No recent news available."
    
    # Format memory context
    memory_str = ""
    if memory_summaries:
        memory_str = "\n".join([f"- {summary}" for summary in memory_summaries[:20]])
    else:
        memory_str = "No previous analysis history available."
    
    # Format user profile
    user_profile_str = ""
    if user_profile:
        settings = user_profile.get("settings_json", {})
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except:
                settings = {}
        risk_tolerance = settings.get("risk_tolerance", "Moderate")
        time_horizon = settings.get("time_horizon", "Medium-term")
        portfolio_concentration = settings.get("portfolio_concentration", "Diversified")
        user_profile_str = f"""
USER PROFILE:
- Risk Tolerance: {risk_tolerance}
- Time Horizon: {time_horizon}
- Portfolio Concentration: {portfolio_concentration}
"""
    else:
        user_profile_str = "No user profile available. Use moderate risk assumptions."
    
    # Get current timestamp in ISO format
    as_of = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Select top 3 critical news for news_summary
    top_3_news = []
    if news_context:
        sorted_news = sorted(news_context, key=news_priority, reverse=True)
        top_3_news = sorted_news[:3]
    
    # STEP 2: Build comparative context (Context-Aware Memory System)
    comparative_context = build_comparative_context(prev_decision, price, technical_context)
    
    # STEP 3: Build fundamental data section (ARCHITECT MANDATE)
    fundamental_str = ""
    if fundamental_context and isinstance(fundamental_context, dict) and mode_upper == "STOCK":
        trailing_pe = fundamental_context.get("trailingPE") or fundamental_context.get("trailing_pe") or fundamental_context.get("f_k_orani")
        forward_pe = fundamental_context.get("forwardPE") or fundamental_context.get("forward_pe")
        sector = fundamental_context.get("sector", "Unknown")
        analyst_target = fundamental_context.get("targetMeanPrice") or fundamental_context.get("target_mean") or fundamental_context.get("analist_hedef_fiyat")
        analyst_rating = fundamental_context.get("recommendationKey") or fundamental_context.get("analist_tavsiyesi", "BİLİNMİYOR")
        price_to_book = fundamental_context.get("priceToBook") or fundamental_context.get("price_to_book")
        market_cap = fundamental_context.get("marketCap") or fundamental_context.get("market_cap")
        ebitda_margins = fundamental_context.get("ebitdaMargins") or fundamental_context.get("ebitda_margins")
        
        # Format values for display
        trailing_pe_str = f"{trailing_pe:.2f}" if trailing_pe and isinstance(trailing_pe, (int, float)) else "N/A"
        forward_pe_str = f"{forward_pe:.2f}" if forward_pe and isinstance(forward_pe, (int, float)) else "N/A"
        analyst_target_str = f"${analyst_target:.2f}" if analyst_target and isinstance(analyst_target, (int, float)) else "N/A"
        price_to_book_str = f"{price_to_book:.2f}" if price_to_book and isinstance(price_to_book, (int, float)) else "N/A"
        ebitda_margins_str = f"{ebitda_margins:.1f}%" if ebitda_margins and isinstance(ebitda_margins, (int, float)) else "N/A"
        market_cap_str = f"${market_cap/1e9:.2f}B" if market_cap and isinstance(market_cap, (int, float)) else "N/A"
        
        fundamental_str = f"""
═══════════════════════════════════════════════════════════════
[FUNDAMENTAL DATA - USE THIS FOR VALUATION SECTION]
═══════════════════════════════════════════════════════════════
P/E Ratio (Trailing): {trailing_pe_str}
Forward P/E: {forward_pe_str}
Sector: {sector}
Analyst Target: {analyst_target_str}
Analyst Rating: {analyst_rating}
Price to Book: {price_to_book_str}
Market Cap: {market_cap_str}
EBITDA Margins: {ebitda_margins_str}

**CRITICAL**: Use these metrics in your DEĞERLEME commentary. Compare P/E to sector average, 
discuss whether the stock is undervalued/overvalued, reference analyst targets.
═══════════════════════════════════════════════════════════════
"""
    
    # Build NEW optimized prompt with comparative narrative emphasis and MENTOR PERSONA
    prompt = f"""CRITICAL JSON OUTPUT RULES (MANDATORY):
1. Output ONLY valid JSON. No markdown, no explanations, no comments, no trailing text.
2. Output must start with '{{' and end with '}}'.
3. String fields: Use double quotes. Do NOT use newlines (\\n) inside strings.
4. If data is missing, use empty string "" or empty list [] but NEVER skip required keys.
5. All required keys from schema MUST be present in output.
6. MINIMUM 400 WORDS TOTAL in Turkish content across all fields. NO short writing. Provide detailed, concrete analysis.

═══════════════════════════════════════════════════════════════
**YOUR IDENTITY: SENIOR INVESTMENT MENTOR & HEDGE FUND STRATEGIST**
═══════════════════════════════════════════════════════════════

You are NOT a simple analyst. You are a **SENIOR HEDGE FUND PORTFOLIO MANAGER & INVESTMENT MENTOR** with 25+ years of battle-tested experience at elite firms like Bridgewater Associates, Renaissance Technologies, and Citadel. You've navigated the dot-com crash, 2008 financial crisis, COVID black swan, and multiple market cycles.

**YOUR MANDATE:**
- Provide NARRATIVE-RICH analysis with clear investment thesis
- Name your STRATEGY (e.g., "Kademeli Toplama Stratejisi", "Momentum Sörfü", "Değer Avı")
- Give specific GAME PLANS with entry/exit levels and position sizing
- Comment on VALUATION using Graham Number, P/E ratios, sector comps
- Use SCENARIO THINKING with probabilities (Bull/Base/Bear cases)
- Connect CAUSAL RELATIONSHIPS (don't just list - explain WHY it matters)

**FORBIDDEN: Generic Phrases**
❌ "RSI yüksek" → ✅ "RSI 78'de aşırı alım + MACD histogramı daralıyor = momentum yorgunluğu sinyali"
❌ "Fiyat arttı" → ✅ "Fiyat 3 seansta %8 yükseldi ancak SMA200'ün %18 üzerinde - tarihi olarak ortalamaya dönüş riski"
❌ "Haber olumlu" → ✅ "Q4 earnings beat %12 - EPS $2.85 (beklenti $2.55) ancak guidance zayıf, premarket %3 düştü"

═══════════════════════════════════════════════════════════════
ASSET METADATA
═══════════════════════════════════════════════════════════════
- Symbol: {symbol}
- Mode: {mode_upper}
- Last Price: ${price}
- Analysis Time: {as_of}

═══════════════════════════════════════════════════════════════
TECHNICAL INDICATORS SUMMARY
═══════════════════════════════════════════════════════════════
{tech_str}
{chart_summary}
{fundamental_str}
═══════════════════════════════════════════════════════════════
NEWS CONTEXT (Top 3 Critical)
═══════════════════════════════════════════════════════════════
{news_str}

═══════════════════════════════════════════════════════════════
PAST ANALYSIS MEMORY
═══════════════════════════════════════════════════════════════
{memory_str}

{comparative_context}

═══════════════════════════════════════════════════════════════
{user_profile_str}
═══════════════════════════════════════════════════════════════
OUTPUT FORMAT - STRICT JSON SCHEMA
═══════════════════════════════════════════════════════════════

You MUST respond ONLY with the following exact JSON structure. No markdown, no explanations, no text outside the JSON object. All string values must be in Turkish.

Respond with ONLY the following JSON. Fill every field. Complete all strings. No text outside the braces.

Output this JSON and nothing else:

{{
  "headline_tr": "Tek cümlelik Türkçe yönetici özeti başlığı",
  "verdict": "AL veya TUT veya SAT",
  "confidence": 75,
  "strategy_name": "Stratejinin ismi (örn: Momentum Sörfü, Kademeli Toplama)",
  "main_thesis": "Ana yatırım tezi: mevcut teknik ve temel verilere dayanarak neden bu karar verildi, en az 3 cümle Türkçe",
  "thesis_bullets": [
    "Giriş planı: ${price:.2f} yakınında pozisyon, kademeli alım önerilir",
    "Teknik görünüm: RSI/MACD/SMA sinyallerinin özeti ve anlamı",
    "Katalist: Fiyatı tetikleyecek olay veya seviye"
  ],
  "risk_bullets": [
    "Stop-loss seviyesi ve yüzde kaybı",
    "En kötü senaryo: destek kırılırsa beklenen hareket",
    "Makro risk: sektör veya piyasa geneli risk faktörü"
  ],
  "levels": {{
    "entry_zone": "${price:.2f} civarı",
    "stop_loss": "0.00",
    "take_profit_1": "0.00",
    "take_profit_2": "0.00"
  }},
  "scenarios": [
    {{
      "type": "bull",
      "trigger": "Boğa senaryosunu tetikleyecek olay veya seviye",
      "expected_move": "Hedef fiyat ve yüzde artış",
      "timeframe": "1-2 hafta"
    }},
    {{
      "type": "base",
      "trigger": "Baz senaryo: mevcut trendin devamı",
      "expected_move": "Beklenen fiyat aralığı",
      "timeframe": "2-4 hafta"
    }},
    {{
      "type": "bear",
      "trigger": "Ayı senaryosu: bozulma sinyali",
      "expected_move": "Destek seviyeleri ve olası düşüş",
      "timeframe": "1-3 hafta"
    }}
  ],
  "news_summary": "Son haberlerin fiyata etkisi ve önemli katalitler - Türkçe özet",
  "what_to_watch": [
    "Takip edilecek teknik seviye veya olay 1",
    "Takip edilecek teknik seviye veya olay 2",
    "Takip edilecek teknik seviye veya olay 3"
  ]
}}

CRITICAL RULES:
1. Output ONLY valid JSON. No markdown. No text before or after the braces.
2. verdict MUST be exactly: "AL", "TUT", or "SAT".
3. confidence MUST be an integer 0-100.
4. levels.stop_loss and levels.take_profit_1/2 MUST be numeric strings like "185.50".
5. All string values MUST be in Turkish. Minimum 3 sentences in main_thesis.
6. Do NOT use newlines inside JSON string values.
7. thesis_bullets and risk_bullets must have 3-5 items each, concrete and specific.
"""
    
    # Get chart data for fallback (if needed)
    chart_data = None
    try:
        chart_list = get_chart_data(symbol, mode_upper)
        if chart_list and isinstance(chart_list, list) and len(chart_list) > 0:
            # Convert list format to dict format for fallback
            chart_data = {
                "high": [item.get("high", 0) for item in chart_list if "high" in item],
                "low": [item.get("low", 0) for item in chart_list if "low" in item],
                "close": [item.get("close", 0) for item in chart_list if "close" in item],
                "open": [item.get("open", 0) for item in chart_list if "open" in item],
            }
    except Exception as e:
        print(f"⚠️ [run_master_analysis] Failed to get chart data: {e}")
    
    # Make single Gemini call with strict JSON + schema (1 analysis = 1 Gemini call)
    model_name_used = None  # Use dynamic model discovery (prefers flash models)
    
    # Set max_output_tokens based on detail level
    # ARCHITECT FIX: Increased all limits to prevent JSON cut-off (Unterminated string errors)
    detail_lower = detail.lower()
    if detail_lower == "short":
        max_output_tokens = 2048  # Increased from 1024
    elif detail_lower == "full":
        max_output_tokens = 8192  # Maximum for Flash
    else:  # medium (default)
        max_output_tokens = 4096  # Increased from 2048
    
    try:
        # Use safe_gemini_call with schema validation (NO retry, NO JSON repair, NO second LLM calls)
        import uuid
        request_id = str(uuid.uuid4())
        
        # Estimate input tokens before call
        input_tokens_est = estimate_token_count(prompt)
        
        result = safe_gemini_call(
            prompt=prompt,
            response_mode="json",
            schema=NEW_ANALYSIS_SCHEMA,
            max_retries=0,  # Ignored - always 0 for quota protection
            model_name=model_name_used,
            temperature=0.2,  # Fixed in safe_gemini_call
            max_output_tokens=max_output_tokens,
            purpose="ai_insight",
            symbol=symbol,
            request_id=request_id
        )
        
        # Estimate output tokens after call
        output_json_str = json.dumps(result, ensure_ascii=False)
        output_tokens_est = estimate_token_count(output_json_str)
        
        # Logging: gemini_call_count, input_tokens_est, output_tokens_est, reason
        print(f"[llm] gemini_call_count=1 input_tokens_est={input_tokens_est} output_tokens_est={output_tokens_est} reason=success schema=NEW_ANALYSIS_SCHEMA")
        
        # SCHEMA NORMALIZATION: prompt now returns NEW_ANALYSIS_SCHEMA directly.
        # If Gemini returned old format (with sections/targets), remap to flat schema.
        if isinstance(result, dict):
            sections = result.get("sections", {})
            verdict_raw = result.get("verdict", "TUT")
            targets = result.get("targets", {})

            # Remap old nested format to flat NEW_ANALYSIS_SCHEMA
            if sections and isinstance(sections, dict):
                yonetici = sections.get("yonetici_ozeti", {}) or {}
                stratejik = sections.get("stratejik_oyun_plani", {}) or {}
                risk_nota = sections.get("risk_notu", {}) or {}
                verdict_obj = verdict_raw if isinstance(verdict_raw, dict) else {}
                verdict_str = verdict_obj.get("decision", "TUT") if isinstance(verdict_obj, dict) else str(verdict_raw)
                confidence_val = verdict_obj.get("confidence", 50) if isinstance(verdict_obj, dict) else result.get("confidence", 50)
                steps = stratejik.get("steps", []) if isinstance(stratejik, dict) else []
                main_t = stratejik.get("main_thesis", "") if isinstance(stratejik, dict) else ""
                thesis = ([main_t] if main_t else []) + (steps if isinstance(steps, list) else [])
                warnings = risk_nota.get("warnings", []) if isinstance(risk_nota, dict) else []
                sl = targets.get("stop_loss", 0) if isinstance(targets, dict) else 0
                tp = targets.get("take_profit", 0) if isinstance(targets, dict) else 0
                result["headline_tr"] = yonetici.get("headline", "") if isinstance(yonetici, dict) else result.get("headline_tr", "")
                result["verdict"] = verdict_str
                result["confidence"] = confidence_val
                if thesis: result["thesis_bullets"] = thesis
                if warnings: result["risk_bullets"] = warnings
                result["levels"] = {
                    "entry_zone": f"${price:.2f} civarı",
                    "stop_loss": f"{sl:.2f}" if sl else "N/A",
                    "take_profit_1": f"{tp:.2f}" if tp else "N/A",
                    "take_profit_2": f"{tp * 1.05:.2f}" if tp else "N/A",
                }

            # Normalize verdict to string
            if isinstance(result.get("verdict"), dict):
                result["verdict"] = result["verdict"].get("decision", "TUT")

            # Fill missing keys with safe defaults
            defaults = {
                "headline_tr": f"{symbol} Teknik Analiz",
                "verdict": "TUT", "confidence": 50, "strategy_name": "Bekle ve Gör",
                "main_thesis": "Teknik göstergeler nötr seviyede.",
                "thesis_bullets": ["Teknik göstergeler nötr", "Piyasa izleniyor"],
                "risk_bullets": ["Volatilite riski mevcut", "Stop-loss kullanın"],
                "levels": {"entry_zone": f"${price:.2f}", "stop_loss": "N/A", "take_profit_1": "N/A", "take_profit_2": "N/A"},
                "scenarios": [
                    {"type": "bull", "trigger": "Direnç kırılması", "expected_move": "+5%", "timeframe": "1-2 hafta"},
                    {"type": "base", "trigger": "Mevcut trend devam", "expected_move": "Yatay", "timeframe": "2-4 hafta"},
                    {"type": "bear", "trigger": "Destek kırılması", "expected_move": "-5%", "timeframe": "1-3 hafta"},
                ],
                "news_summary": "Haber analizi mevcut değil.",
                "what_to_watch": ["RSI 70 üstü aşırı alım", "Destek/direnç seviyeleri"],
            }
            for k, v in defaults.items():
                if k not in result or not result[k]:
                    result[k] = v
        else:
            print(f"⚠️ [SCHEMA] Result was not a dict")
            result = default_template.copy()
        
        # Auto-fix levels object
        if "levels" not in result or not isinstance(result.get("levels"), dict):
            result["levels"] = default_template["levels"]
        else:
            levels = result["levels"]
            for level_key in ["entry_zone", "stop_loss", "take_profit_1", "take_profit_2"]:
                if level_key not in levels or levels[level_key] is None:
                    levels[level_key] = "N/A"
        
        # Auto-fix scenarios array
        if "scenarios" not in result or not isinstance(result.get("scenarios"), list) or len(result.get("scenarios", [])) < 3:
            result["scenarios"] = default_template["scenarios"]
        
        # Extract summary for database (use headline_tr)
        summary_text = result.get("headline_tr", "") or "Analysis completed"
        
        # Extract confidence for risk_score (use confidence field)
        base_confidence = result.get("confidence", 50)
        if not isinstance(base_confidence, (int, float)):
            try:
                base_confidence = int(base_confidence)
            except:
                base_confidence = 50
        
        # STEP 3: Calibrate confidence based on indicator alignment (Context-Aware Confidence Calibration)
        print(f"🎯 [Confidence Calibration] Base confidence from LLM: {base_confidence}%")
        
        # Prepare news sentiment dict
        news_sentiment = {
            "sentiment_score": 50,  # Default neutral
            "impact": "NEUTRAL"
        }
        
        if news_context:
            # Calculate average sentiment from news
            positive_count = sum(1 for n in news_context if n.get("sentiment_hint", "").upper() in ["POSITIVE", "BULLISH"])
            negative_count = sum(1 for n in news_context if n.get("sentiment_hint", "").upper() in ["NEGATIVE", "BEARISH"])
            total_news = len(news_context)
            
            if total_news > 0:
                sentiment_score = 50 + ((positive_count - negative_count) / total_news) * 50
                news_sentiment["sentiment_score"] = max(0, min(100, int(sentiment_score)))
                
                if sentiment_score > 60:
                    news_sentiment["impact"] = "POSITIVE"
                elif sentiment_score < 40:
                    news_sentiment["impact"] = "NEGATIVE"
        
        # Get verdict for calibration
        # LLM new schema returns verdict as dict {"decision": "AL", ...}; old schema returns string
        verdict_raw = result.get("verdict", "TUT")
        if isinstance(verdict_raw, dict):
            verdict = verdict_raw.get("decision", "TUT")
        else:
            verdict = verdict_raw if isinstance(verdict_raw, str) else "TUT"
        decision_map = {"AL": "BUY", "TUT": "HOLD", "SAT": "AVOID", "KAÇIN": "AVOID",
                        "BUY": "BUY", "HOLD": "HOLD", "SELL": "AVOID", "AVOID": "AVOID"}
        decision = decision_map.get(str(verdict).upper(), "HOLD")
        
        # Calibrate confidence
        calibrated_confidence, calibration_reasons = calibrate_confidence_score(
            base_confidence=base_confidence,
            technical_indicators=technical_context,
            news_sentiment=news_sentiment,
            decision=decision
        )
        
        # Update confidence in result
        result["confidence"] = calibrated_confidence
        confidence = calibrated_confidence
        
        print(f"✅ [Confidence Calibration] Calibrated confidence: {calibrated_confidence}% (Δ{calibrated_confidence - base_confidence:+d})")
        print(f"📊 [Confidence Calibration] Adjustments: {', '.join(calibration_reasons)}")
        
        # Save to database
        try:
            save_analysis(
                symbol=symbol,
                mode=mode_upper,
                raw_prompt=prompt,
                raw_response=json.dumps(result, ensure_ascii=False),
                summary=summary_text,
                risk_level=int(confidence),  # Use confidence as risk_level for backward compatibility
                full_analysis_json=result,
                price_at_analysis=price
            )
        except Exception as db_error:
            print(f"⚠️ [run_master_analysis] Failed to save to database: {db_error}")
        
        return result
        
    except GeminiCallError as gemini_err:
        # Gemini API call failed - use deterministic fallback (MANDATORY)
        reason = gemini_err.reason
        
        # Estimate input tokens for logging
        input_tokens_est = estimate_token_count(prompt)
        
        # Map error reason to flags
        if reason == "gemini_schema_error":
            reason_flags = ["fallback_used", "gemini_schema_error"]
            log_reason = "gemini_schema_error"
        elif reason == "gemini_error_429":
            reason_flags = ["fallback_used", "gemini_error_429"]
            log_reason = "gemini_error_429"
        elif reason == "gemini_invalid_json":
            reason_flags = ["fallback_used", "gemini_invalid_json"]
            log_reason = "gemini_invalid_json"
        elif reason == "gemini_timeout":
            reason_flags = ["fallback_used", "gemini_timeout"]
            log_reason = "gemini_timeout"
        elif reason == "schema_validation_failed":
            reason_flags = ["fallback_used", "schema_validation_failed"]
            log_reason = "schema_validation_failed"
        elif reason == "empty_response":
            reason_flags = ["fallback_used", "gemini_error_unknown"]
            log_reason = "gemini_error_unknown"
        else:
            reason_flags = ["fallback_used", "gemini_error_unknown"]
            log_reason = "gemini_error_unknown"
        
        # Get additional data for local_decision_engine
        insider_data = None
        volatility_data = None
        try:
            # Get insider intelligence (only for stocks)
            if mode_upper != "CRYPTO":
                insider_data = get_insider_intelligence(symbol)
            
            # Get volatility from technical_context (ATR if available)
            if "atr" in technical_context:
                volatility_data = technical_context["atr"]
            elif chart_data and chart_data.get("close"):
                # Calculate simple volatility from chart data
                try:
                    closes = chart_data["close"]
                    if len(closes) >= 10:
                        returns = np.diff(closes) / closes[:-1]
                        volatility_data = np.std(returns) * 100
                except:
                    pass
        except Exception as e:
            print(f"⚠️ [run_master_analysis] Failed to get insider/volatility data: {e}")
        
        # Call local_decision_engine
        try:
            local_decision = local_decision_engine(
                technical=technical_context,
                fundamentals=None,  # Can be enhanced later
                insider=insider_data,
                volatility=volatility_data
            )
        except Exception as e:
            print(f"⚠️ [run_master_analysis] local_decision_engine failed: {e}")
            local_decision = {"action": "HOLD", "confidence_score": 40, "reason_tr": "Teknik analiz yapılamadı"}
        
        # Always use build_level0_fallback_analysis for complete UI contract compliance
        # Pass local_decision to enhance fallback with local engine results
        fallback_result = build_level0_fallback_analysis(
            symbol, mode_upper, as_of, price, chart_data, news_context, reason_flags, local_decision
        )
        
        # Save fallback to DB
        try:
            save_analysis(
                symbol=symbol,
                mode=mode_upper,
                raw_prompt=prompt,
                raw_response=json.dumps(fallback_result, ensure_ascii=False),
                summary=fallback_result["summary"]["headline_tr"],
                risk_level=fallback_result["risk_score"]["value"],
                full_analysis_json=fallback_result,
                price_at_analysis=price
            )
        except:
            pass
        
        # Logging: gemini_call_count, input_tokens_est, output_tokens_est, reason
        print(f"[llm] gemini_call_count=1 input_tokens_est={input_tokens_est} output_tokens_est=0 reason={log_reason} schema=NEW_ANALYSIS_SCHEMA")
        
        # CRITICAL FIX: Wrap fallback conversion in try/except to prevent 500 errors
        try:
            # CRITICAL FIX: Normalize top_3_news_fallback to dict to prevent AttributeError
            fallback_new_schema = _convert_fallback_to_new_schema(fallback_result, symbol, price, ensure_dict(top_3_news_fallback) if not isinstance(top_3_news_fallback, list) else top_3_news_fallback)
        except Exception as conv_err:
            print(f"❌ [run_master_analysis] Fallback conversion failed: {conv_err}")
            # Emergency hardcoded fallback (last resort)
            fallback_new_schema = {
                "headline_tr": "Sistem hatası - Analiz tamamlanamadı",
                "verdict": "TUT",
                "confidence": 10,
                "thesis_bullets": [
                    "AI servisi şu anda kullanılamıyor",
                    "Sistem hatası nedeniyle analiz tamamlanamadı",
                    "Lütfen daha sonra tekrar deneyin",
                    "Manuel analiz önerilir",
                    "Belirsizlik nedeniyle bekleme önerilir"
                ],
                "risk_bullets": [
                    "Veri yetersizliği nedeniyle yüksek belirsizlik",
                    "AI analizi yapılamadı",
                    "Risk değerlendirmesi sınırlı",
                    "Dikkatli olunmalı",
                    "Pozisyon alınmamalı"
                ],
                "levels": {
                    "entry_zone": f"${price * 0.98:.2f} - ${price * 1.02:.2f}",
                    "stop_loss": f"${price * 0.95:.2f}",
                    "take_profit_1": f"${price * 1.05:.2f}",
                    "take_profit_2": f"${price * 1.10:.2f}"
                },
                "scenarios": [
                    {"type": "bull", "trigger": "Sistem hatası", "expected_move": "Bilinmiyor", "timeframe": "Bilinmiyor"},
                    {"type": "base", "trigger": "Sistem hatası", "expected_move": "Bilinmiyor", "timeframe": "Bilinmiyor"},
                    {"type": "bear", "trigger": "Sistem hatası", "expected_move": "Bilinmiyor", "timeframe": "Bilinmiyor"}
                ],
                "news_summary": "Haber analizi yapılamadı - Sistem hatası",
                "what_to_watch": ["Sistem durumu", "Manuel analiz", "Tekrar deneme"]
            }
        
        return fallback_new_schema
        
    except Exception as e:
        import traceback
        error_type = type(e).__name__
        
        # Estimate input tokens for logging
        input_tokens_est = estimate_token_count(prompt)
        
        # Use deterministic fallback for any unexpected errors
        reason_flags = ["fallback_used", "gemini_error_unknown"]
        log_reason = f"exception_{error_type}"
        
        # Get top_3_news for fallback conversion
        top_3_news_fallback = []
        if news_context:
            def news_priority_fallback(news):
                sentiment = news.get("sentiment_hint", "Neutral").upper()
                priority = 0
                if sentiment in ["POSITIVE", "NEGATIVE"]:
                    priority = 1
                published_at = news.get("published_at", "")
                return (priority, published_at)
            sorted_news_fallback = sorted(news_context, key=news_priority_fallback, reverse=True)
            top_3_news_fallback = sorted_news_fallback[:3]
        
        # Get additional data for local_decision_engine
        insider_data = None
        volatility_data = None
        try:
            # Get insider intelligence (only for stocks)
            if mode_upper != "CRYPTO":
                insider_data = get_insider_intelligence(symbol)
            
            # Get volatility from technical_context (ATR if available)
            if "atr" in technical_context:
                volatility_data = technical_context["atr"]
            elif chart_data and chart_data.get("close"):
                # Calculate simple volatility from chart data
                try:
                    closes = chart_data["close"]
                    if len(closes) >= 10:
                        returns = np.diff(closes) / closes[:-1]
                        volatility_data = np.std(returns) * 100
                except:
                    pass
        except Exception as e2:
            print(f"⚠️ [run_master_analysis] Failed to get insider/volatility data: {e2}")
        
        # Call local_decision_engine
        try:
            local_decision = local_decision_engine(
                technical=technical_context,
                fundamentals=None,
                insider=insider_data,
                volatility=volatility_data
            )
        except Exception as e3:
            print(f"⚠️ [run_master_analysis] local_decision_engine failed: {e3}")
            local_decision = {"action": "HOLD", "confidence_score": 40, "reason_tr": "Teknik analiz yapılamadı"}
        
        fallback_result = build_level0_fallback_analysis(
            symbol, mode_upper, as_of, price, chart_data, news_context, reason_flags, local_decision
        )
        
        # CRITICAL FIX: Wrap fallback conversion in try/except to prevent 500 errors
        try:
            # CRITICAL FIX: Normalize top_3_news_fallback to dict to prevent AttributeError
            fallback_new_schema = _convert_fallback_to_new_schema(fallback_result, symbol, price, ensure_dict(top_3_news_fallback) if not isinstance(top_3_news_fallback, list) else top_3_news_fallback)
        except Exception as conv_err:
            print(f"❌ [run_master_analysis] Fallback conversion failed (except block): {conv_err}")
            import traceback
            traceback.print_exc()
            # Emergency hardcoded fallback (last resort)
            fallback_new_schema = {
                "headline_tr": "Sistem hatası - Analiz tamamlanamadı",
                "verdict": "TUT",
                "confidence": 10,
                "thesis_bullets": [
                    "AI servisi şu anda kullanılamıyor",
                    "Sistem hatası nedeniyle analiz tamamlanamadı",
                    "Lütfen daha sonra tekrar deneyin",
                    "Manuel analiz önerilir",
                    "Belirsizlik nedeniyle bekleme önerilir"
                ],
                "risk_bullets": [
                    "Veri yetersizliği nedeniyle yüksek belirsizlik",
                    "AI analizi yapılamadı",
                    "Risk değerlendirmesi sınırlı",
                    "Dikkatli olunmalı",
                    "Pozisyon alınmamalı"
                ],
                "levels": {
                    "entry_zone": f"${price * 0.98:.2f} - ${price * 1.02:.2f}",
                    "stop_loss": f"${price * 0.95:.2f}",
                    "take_profit_1": f"${price * 1.05:.2f}",
                    "take_profit_2": f"${price * 1.10:.2f}"
                },
                "scenarios": [
                    {"type": "bull", "trigger": "Sistem hatası", "expected_move": "Bilinmiyor", "timeframe": "Bilinmiyor"},
                    {"type": "base", "trigger": "Sistem hatası", "expected_move": "Bilinmiyor", "timeframe": "Bilinmiyor"},
                    {"type": "bear", "trigger": "Sistem hatası", "expected_move": "Bilinmiyor", "timeframe": "Bilinmiyor"}
                ],
                "news_summary": "Haber analizi yapılamadı - Sistem hatası",
                "what_to_watch": ["Sistem durumu", "Manuel analiz", "Tekrar deneme"]
            }
        
        # Logging: gemini_call_count, input_tokens_est, output_tokens_est, reason
        print(f"[llm] gemini_call_count=1 input_tokens_est={input_tokens_est} output_tokens_est=0 reason={log_reason} schema=NEW_ANALYSIS_SCHEMA")
        
        # Save fallback to DB
        try:
            save_analysis(
                symbol=symbol,
                mode=mode_upper,
                raw_prompt=prompt,
                raw_response=json.dumps(fallback_new_schema, ensure_ascii=False),
                summary=fallback_new_schema.get("headline_tr", "Fallback analysis"),
                risk_level=fallback_new_schema.get("confidence", 20),
                full_analysis_json=fallback_new_schema,
                price_at_analysis=price
            )
        except:
            pass
        
        return fallback_new_schema


def build_level0_fallback_analysis(
    symbol: str,
    mode: str,
    as_of: str,
    price_at_analysis: float,
    chart_data: Optional[dict] = None,
    critical_news: Optional[List[dict]] = None,
    reason_flags: List[str] = None,
    local_decision: Optional[dict] = None
) -> dict:
    """
    Build deterministic fallback analysis with all UI contract fields filled.
    
    This function generates a complete analysis structure without AI, using:
    - Chart data for technical levels (high/low/close)
    - Deterministic risk/strategy calculations
    - All mandatory fields from MASTER_ANALYSIS_SCHEMA
    
    Args:
        symbol: Stock/crypto symbol
        mode: "STOCK" or "CRYPTO"
        as_of: ISO 8601 timestamp
        price_at_analysis: Current price
        chart_data: Optional chart data dict with high/low/close arrays
        critical_news: Optional list of news items
        reason_flags: List of quality flags (e.g., ["fallback_used", "gemini_invalid_json"])
    
    Returns:
        dict: Complete analysis structure matching UI contract
    """
    if reason_flags is None:
        reason_flags = ["fallback_used"]
    
    mode_upper = mode.upper()
    is_crypto = mode_upper == "CRYPTO"
    
    # Extract technical levels from chart_data if available
    support_levels = []
    resistance_levels = []
    trend = "SIDEWAYS"
    
    if chart_data:
        try:
            highs = chart_data.get("high", [])
            lows = chart_data.get("low", [])
            closes = chart_data.get("close", [])
            
            if highs and lows and closes:
                # Calculate support/resistance from recent data
                recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs) if highs else price_at_analysis
                recent_low = min(lows[-20:]) if len(lows) >= 20 else min(lows) if lows else price_at_analysis
                current_close = closes[-1] if closes else price_at_analysis
                
                # Support levels (below current price)
                support_levels = [
                    recent_low * 0.98,  # Strong support
                    recent_low * 0.99,  # Medium support
                    current_close * 0.97  # Near support
                ]
                
                # Resistance levels (above current price)
                resistance_levels = [
                    current_close * 1.03,  # Near resistance
                    recent_high * 1.01,  # Medium resistance
                    recent_high * 1.05  # Strong resistance
                ]
                
                # Determine trend
                if current_close > recent_high * 0.95:
                    trend = "UP"
                elif current_close < recent_low * 1.05:
                    trend = "DOWN"
                else:
                    trend = "SIDEWAYS"
        except:
            pass
    
    # Default levels if chart_data not available
    if not support_levels:
        support_levels = [price_at_analysis * 0.95, price_at_analysis * 0.90, price_at_analysis * 0.85]
    if not resistance_levels:
        resistance_levels = [price_at_analysis * 1.05, price_at_analysis * 1.10, price_at_analysis * 1.15]
    
    # Calculate volatility approximation (simple std dev if available)
    volatility_note = "Veri yetersiz"
    if chart_data and chart_data.get("close"):
        try:
            closes = chart_data["close"]
            if len(closes) >= 10:
                import numpy as np
                returns = np.diff(closes) / closes[:-1]
                vol = np.std(returns) * 100
                volatility_note = f"Volatilite yaklaşık %{vol:.1f}"
        except:
            pass
    
    # Determine stance based on local_decision_engine if available, otherwise use trend
    if local_decision and isinstance(local_decision, dict):
        local_action = local_decision.get("action", "HOLD")
        if is_crypto:
            # Map BUY/SELL to LONG/SHORT for crypto
            if local_action == "BUY":
                stance = "LONG"
            elif local_action == "SELL":
                stance = "SHORT"
            else:
                stance = "BEKLE"
        else:
            stance = local_action
    else:
        # Fallback to trend-based decision
        if trend == "UP":
            stance = "BUY" if not is_crypto else "LONG"
        elif trend == "DOWN":
            stance = "SELL" if not is_crypto else "SHORT"
        else:
            stance = "HOLD" if not is_crypto else "BEKLE"
    
    # Build complete fallback structure
    fallback = {
        "symbol": symbol.upper(),
        "mode": mode_upper,
        "as_of": as_of,
        "price_at_analysis": price_at_analysis,
        "summary": {
            "headline_tr": f"{symbol.upper()} için yerel karar motoru analizi",
            "one_liner_tr": local_decision.get("reason_tr", "Teknik veriler mevcut ancak AI analizi geçici olarak devre dışı. Bekle ve gör stratejisi önerilir.") if local_decision else "Teknik veriler mevcut ancak AI analizi geçici olarak devre dışı. Bekle ve gör stratejisi önerilir.",
            "key_points_tr": [
                "Yerel karar motoru kullanıldı (AI servisi geçici olarak kullanılamıyor)" if local_decision else "AI servisi geçici olarak kullanılamıyor",
                "Teknik seviyeler chart verilerinden hesaplandı",
                f"Trend: {trend}",
                f"Önerilen aksiyon: {stance}",
                local_decision.get("reason_tr", "Bekle ve gör stratejisi önerilir") if local_decision else "Bekle ve gör stratejisi önerilir"
            ]
        },
        "technical_analysis": {
            "trend": trend,
            "support_levels": support_levels,
            "resistance_levels": resistance_levels,
            "indicators": {
                "rsi": {
                    "value": 50,
                    "interpretation_tr": "RSI verisi mevcut değil, nötr kabul edildi"
                },
                "macd": {
                    "signal": "NEUTRAL",
                    "interpretation_tr": "MACD verisi mevcut değil"
                },
                "bbands": {
                    "position": "MID",
                    "interpretation_tr": "Bollinger Bands verisi mevcut değil"
                }
            },
            "notes_tr": [
                f"Destek seviyeleri: {support_levels[0]:.2f}, {support_levels[1]:.2f}, {support_levels[2]:.2f}",
                f"Direnç seviyeleri: {resistance_levels[0]:.2f}, {resistance_levels[1]:.2f}, {resistance_levels[2]:.2f}",
                volatility_note
            ]
        },
        "fundamental_analysis": {
            "valuation": {
                "view": "FAIR",
                "reason_tr": "AI analizi mevcut olmadığı için değerleme yapılamadı"
            },
            "growth": {
                "view": "MODERATE",
                "reason_tr": "Büyüme verisi mevcut değil"
            },
            "profitability": {
                "view": "MODERATE",
                "reason_tr": "Karlılık verisi mevcut değil"
            },
            "risks_tr": [
                "AI analizi mevcut olmadığı için risk değerlendirmesi sınırlı",
                "Teknik seviyeler chart verilerine dayanıyor",
                "Temel analiz yapılamadı"
            ]
        },
        "sentiment_and_catalysts": {
            "sentiment": "NEUTRAL",
            "drivers_tr": [
                "AI analizi mevcut değil",
                "Haber analizi yapılamadı"
            ],
            "catalysts_tr": [
                "Katalizör analizi yapılamadı"
            ],
            "news_impact_tr": "Haber analizi yapılamadı"
        },
        "scenarios": {
            "bull_case_tr": {
                "thesis": "Yükseliş senaryosu için AI analizi mevcut değil. Teknik seviyeler yukarı yönlü hareket için destek sağlayabilir.",
                "triggers": [
                    "Direnç seviyelerinin aşılması",
                    "Piyasa genelinde olumlu momentum"
                ],
                "price_path": f"Potansiyel hedef: {resistance_levels[2]:.2f}"
            },
            "bear_case_tr": {
                "thesis": "Düşüş senaryosu için AI analizi mevcut değil. Destek seviyelerinin kırılması aşağı yönlü hareketi tetikleyebilir.",
                "triggers": [
                    "Destek seviyelerinin kırılması",
                    "Piyasa genelinde olumsuz momentum"
                ],
                "price_path": f"Kritik seviye: {support_levels[2]:.2f}"
            }
        },
        "strategy": {
            "stance": stance,
            "entry_plan_tr": [
                f"Giriş: Mevcut fiyat ({price_at_analysis:.2f}) civarı",
                f"Stop Loss: {support_levels[0]:.2f}",
                f"Take Profit: {resistance_levels[0]:.2f}, {resistance_levels[1]:.2f}"
            ],
            "risk_management_tr": {
                "stop_loss": support_levels[0],
                "take_profit": [resistance_levels[0], resistance_levels[1]],
                "position_sizing_tr": "Bekle ve gör stratejisi önerilir. Pozisyon boyutu düşük tutulmalı."
            },
            "time_horizon": "SHORT"
        },
        "risk_score": {
            "value": 75,  # High risk when fallback
            "label": "HIGH",
            "reasons_tr": [
                "AI analizi mevcut olmadığı için risk değerlendirmesi sınırlı",
                "Eksik veri nedeniyle yüksek belirsizlik",
                "Bekle ve gör stratejisi önerilir"
            ]
        },
        "confidence_score": {
            "value": local_decision.get("confidence_score", 20) if local_decision else 20,  # Use local_decision confidence if available
            "reasons_tr": [
                local_decision.get("reason_tr", "AI analizi mevcut değil") if local_decision else "AI analizi mevcut değil",
                "Yerel karar motoru kullanıldı" if local_decision else "Deterministik fallback kullanıldı"
            ]
        },
        "data_quality_flags": reason_flags
    }
    
    return fallback


def _convert_fallback_to_new_schema(fallback_old: dict, symbol: str, price: float, top_3_news) -> dict:
    """
    Convert old schema fallback to new compact schema format.
    
    **CRITICAL FIX**: Handle top_3_news as both list and dict to prevent AttributeError.
    """
    # Extract data from old schema
    summary = fallback_old.get("summary", {})
    strategy = fallback_old.get("strategy", {})
    scenarios = fallback_old.get("scenarios", {})
    technical = fallback_old.get("technical_analysis", {})
    confidence_score = fallback_old.get("confidence_score", {})
    
    # Map stance to verdict
    stance = strategy.get("stance", "HOLD")
    if stance == "BUY" or stance == "LONG":
        verdict = "AL"
    elif stance == "SELL" or stance == "SHORT":
        verdict = "SAT"
    else:
        verdict = "TUT"
    
    # Extract levels from risk_management
    risk_mgmt = strategy.get("risk_management_tr", {})
    stop_loss_val = risk_mgmt.get("stop_loss", price * 0.95)
    take_profit_vals = risk_mgmt.get("take_profit", [price * 1.05, price * 1.10])
    
    # CRITICAL FIX: Handle top_3_news as both list and dict using ensure_dict
    news_items = []
    if isinstance(top_3_news, list):
        # Already a list - use directly
        news_items = top_3_news
    elif isinstance(top_3_news, dict):
        # Dict - try to extract list from common keys
        news_items = top_3_news.get("news", []) or top_3_news.get("items", []) or []
    else:
        # Other types (None, str, etc.) - normalize to dict and try to extract
        news_dict = ensure_dict(top_3_news)
        news_items = news_dict.get("news", []) or news_dict.get("items", []) or []
    
    # Build news summary from news_items
    news_summary_text = "Haber analizi yapılamadı. AI servisi geçici olarak kullanılamıyor."
    if news_items:
        news_titles = [
            news.get("title", "N/A") if isinstance(news, dict) else str(news) 
            for news in news_items[:3]
        ]
        news_summary_text = f"Son 3 kritik haber: {', '.join(news_titles)}. Bu haberlerin toplu etkisi değerlendirilemedi çünkü AI servisi geçici olarak kullanılamıyor."
    
    # Build scenarios array
    bull_case = scenarios.get("bull_case_tr", {})
    bear_case = scenarios.get("bear_case_tr", {})
    base_case = scenarios.get("base_case_tr", {})
    
    scenarios_array = [
        {
            "type": "bull",
            "trigger": ", ".join(bull_case.get("triggers", ["Teknik seviyelerin aşılması"])),
            "expected_move": bull_case.get("price_path", f"Potansiyel hedef: ${price * 1.10:.2f}"),
            "timeframe": "2-4 hafta"
        },
        {
            "type": "base",
            "trigger": "Mevcut trend devam ederse",
            "expected_move": base_case.get("price_path", f"Yatay hareket: ${price * 0.98:.2f} - ${price * 1.02:.2f}") if base_case else f"Yatay hareket: ${price * 0.98:.2f} - ${price * 1.02:.2f}",
            "timeframe": "1-2 ay"
        },
        {
            "type": "bear",
            "trigger": ", ".join(bear_case.get("triggers", ["Destek seviyelerinin kırılması"])),
            "expected_move": bear_case.get("price_path", f"Kritik seviye: ${price * 0.90:.2f}"),
            "timeframe": "3-6 hafta"
        }
    ]
    
    # Build thesis and risk bullets from old schema
    thesis_bullets = summary.get("key_points_tr", [])
    if len(thesis_bullets) < 5:
        thesis_bullets.extend([
            "Teknik analiz yapılamadı - AI servisi geçici olarak kullanılamıyor",
            "Temel analiz yapılamadı - AI servisi geçici olarak kullanılamıyor",
            "Haber analizi yapılamadı - AI servisi geçici olarak kullanılamıyor"
        ])
    
    risk_bullets = fallback_old.get("fundamental_analysis", {}).get("risks_tr", [])
    if len(risk_bullets) < 5:
        risk_bullets.extend([
            "AI analizi mevcut olmadığı için risk değerlendirmesi sınırlı",
            "Eksik veri nedeniyle yüksek belirsizlik",
            "Bekle ve gör stratejisi önerilir"
        ])
    
    # Build what_to_watch
    what_to_watch = [
        f"RSI seviyesi: {technical.get('indicators', {}).get('rsi', {}).get('value', 'N/A')}",
        f"Destek seviyeleri: {', '.join([f'${s:.2f}' for s in technical.get('support_levels', [])[:3]])}",
        f"Direnç seviyeleri: {', '.join([f'${r:.2f}' for r in technical.get('resistance_levels', [])[:3]])}",
        "Yeni haberler ve piyasa güncellemeleri",
        f"Fiyat hareketi: ${price:.2f} seviyesi"
    ]
    
    # Build new schema result
    return {
        "headline_tr": summary.get("headline_tr", f"{symbol} için yerel karar motoru analizi"),
        "verdict": verdict,
        "confidence": confidence_score.get("value", 20),
        "thesis_bullets": thesis_bullets[:8],
        "risk_bullets": risk_bullets[:8],
        "levels": {
            "entry_zone": f"${price:.2f} civarı",
            "stop_loss": f"${stop_loss_val:.2f}",
            "take_profit_1": f"${take_profit_vals[0]:.2f}" if len(take_profit_vals) > 0 else f"${price * 1.05:.2f}",
            "take_profit_2": f"${take_profit_vals[1]:.2f}" if len(take_profit_vals) > 1 else f"${price * 1.10:.2f}"
        },
        "scenarios": scenarios_array,
        "news_summary": news_summary_text,
        "what_to_watch": what_to_watch
    }


def _create_fallback_analysis(symbol: str, mode: str, price: float) -> dict:
    """Create a fallback analysis when Gemini fails."""
    as_of = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    is_crypto = mode == "CRYPTO"
    stance = "HOLD" if not is_crypto else "BEKLE"
    
    fallback = {
        "symbol": symbol,
        "mode": mode,
        "as_of": as_of,
        "price_at_analysis": price,
        "fallback": True,
        "summary": {
            "headline_tr": "AI analizi geçici olarak kullanılamıyor",
            "one_liner_tr": "AI servisi şu anda kullanılamıyor, bekle ve gör stratejisi önerilir",
            "key_points_tr": [
                "AI servisi geçici olarak kullanılamıyor",
                "Teknik veriler kontrol edilemedi",
                "Bekle ve gör stratejisi önerilir"
            ]
        },
        "technical_analysis": {
            "trend": "SIDEWAYS",
            "support_levels": [],
            "resistance_levels": [],
            "indicators": {
                "rsi": {"value": 50, "interpretation_tr": "Veri yetersiz"},
                "macd": {"signal": "NEUTRAL", "interpretation_tr": "Veri yetersiz"},
                "bbands": {"position": "MID", "interpretation_tr": "Veri yetersiz"}
            },
            "notes_tr": ["AI analizi geçici olarak kullanılamıyor"]
        },
        "fundamental_analysis": {
            "valuation": {"view": "FAIR", "reason_tr": "Veri yetersiz"},
            "growth": {"view": "MODERATE", "reason_tr": "Veri yetersiz"},
            "profitability": {"view": "MODERATE", "reason_tr": "Veri yetersiz"},
            "risks_tr": ["AI analizi geçici olarak kullanılamıyor"]
        },
        "sentiment_and_catalysts": {
            "sentiment": "NEUTRAL",
            "drivers_tr": ["Veri yetersiz"],
            "catalysts_tr": ["Veri yetersiz"],
            "news_impact_tr": "Haber analizi yapılamadı"
        },
        "scenarios": {
            "bull_case_tr": {
                "thesis": "Veri yetersiz",
                "triggers": [],
                "price_path": "N/A"
            },
            "bear_case_tr": {
                "thesis": "Veri yetersiz",
                "triggers": [],
                "price_path": "N/A"
            }
        },
        "strategy": {
            "stance": stance,
            "entry_plan_tr": ["Bekle ve gör stratejisi önerilir"],
            "risk_management_tr": {
                "stop_loss": price * 0.95,
                "take_profit": [price * 1.05, price * 1.10],
                "position_sizing_tr": "Bekle ve gör stratejisi önerilir"
            },
            "time_horizon": "SHORT"
        },
        "risk_score": {
            "value": 85,
            "label": "HIGH",
            "reasons_tr": ["AI analizi geçici olarak kullanılamıyor"]
        },
        "confidence_score": {
            "value": 10,
            "reasons_tr": ["Veri yetersiz"]
        }
    }
    
    # Save fallback to database
    try:
            save_analysis(
            symbol=symbol,
            mode=mode,
            raw_prompt="Fallback analysis - AI unavailable",
            raw_response=json.dumps(fallback, ensure_ascii=False),
            summary=fallback["summary"]["headline"],
            risk_level=75,
            full_analysis_json=fallback,
            price_at_analysis=price
        )
    except:
        pass  # Ignore DB errors in fallback
    
    return fallback


def _validate_and_fill_analysis(result: dict, symbol: str, mode: str, price: float) -> dict:
    """Validate and fill missing fields in analysis result (new strict schema)."""
    # Ensure all required top-level keys exist
    if "symbol" not in result:
        result["symbol"] = symbol
    if "mode" not in result:
        result["mode"] = mode
    if "as_of" not in result:
        result["as_of"] = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if "price_at_analysis" not in result:
        result["price_at_analysis"] = price
    
    # Fill summary (new schema)
    if "summary" not in result or not isinstance(result["summary"], dict):
        result["summary"] = {
            "headline_tr": "",
            "one_liner_tr": "",
            "key_points_tr": []
        }
    else:
        if "headline_tr" not in result["summary"]:
            result["summary"]["headline_tr"] = result["summary"].get("headline", "")
        if "one_liner_tr" not in result["summary"]:
            result["summary"]["one_liner_tr"] = ""
        if "key_points_tr" not in result["summary"]:
            result["summary"]["key_points_tr"] = result["summary"].get("bullets_tr", [])
    
    # Fill technical_analysis (new schema)
    if "technical_analysis" not in result or not isinstance(result["technical_analysis"], dict):
        result["technical_analysis"] = {
            "trend": "SIDEWAYS",
            "support_levels": [],
            "resistance_levels": [],
            "indicators": {},
            "notes_tr": []
        }
    else:
        tech = result["technical_analysis"]
        if "trend" not in tech:
            tech["trend"] = "SIDEWAYS"
        if "support_levels" not in tech:
            tech["support_levels"] = []
        if "resistance_levels" not in tech:
            tech["resistance_levels"] = []
        if "indicators" not in tech:
            tech["indicators"] = {}
        if "notes_tr" not in tech:
            tech["notes_tr"] = []
    
    # Fill fundamental_analysis (new schema)
    if "fundamental_analysis" not in result or not isinstance(result["fundamental_analysis"], dict):
        result["fundamental_analysis"] = {
            "valuation": {"view": "FAIR", "reason_tr": ""},
            "growth": {"view": "MODERATE", "reason_tr": ""},
            "profitability": {"view": "MODERATE", "reason_tr": ""},
            "risks_tr": []
        }
    
    # Fill sentiment_and_catalysts (new schema)
    if "sentiment_and_catalysts" not in result:
        # Try legacy field name
        if "sentiment_and_news" in result:
            old = result["sentiment_and_news"]
            result["sentiment_and_catalysts"] = {
                "sentiment": old.get("overall_sentiment", "NEUTRAL"),
                "drivers_tr": [],
                "catalysts_tr": [],
                "news_impact_tr": old.get("news_impact_summary", "")
            }
        else:
            result["sentiment_and_catalysts"] = {
                "sentiment": "NEUTRAL",
                "drivers_tr": [],
                "catalysts_tr": [],
                "news_impact_tr": ""
            }
    
    # Fill scenarios (new schema)
    if "scenarios" not in result or not isinstance(result["scenarios"], dict):
        result["scenarios"] = {
            "bull_case_tr": {"thesis": "", "triggers": [], "price_path": ""},
            "bear_case_tr": {"thesis": "", "triggers": [], "price_path": ""}
        }
    
    # Fill strategy (new schema)
    if "strategy" not in result or not isinstance(result["strategy"], dict):
        result["strategy"] = {
            "stance": "HOLD",
            "entry_plan_tr": [],
            "risk_management_tr": {
                "stop_loss": price * 0.95,  # Default 5% stop loss
                "take_profit": [price * 1.10, price * 1.20],  # Default 10-20% take profit
                "position_sizing_tr": ""
            },
            "time_horizon": "SWING"
        }
    else:
        strat = result["strategy"]
        if "stance" not in strat:
            strat["stance"] = "HOLD"
        if "entry_plan_tr" not in strat:
            strat["entry_plan_tr"] = []
        if "risk_management_tr" not in strat:
            strat["risk_management_tr"] = {
                "stop_loss": price * 0.95,
                "take_profit": [price * 1.10, price * 1.20],
                "position_sizing_tr": ""
            }
        if "time_horizon" not in strat:
            strat["time_horizon"] = "SWING"
    
    # Fill risk_score and confidence_score (new schema)
    if "risk_score" not in result:
        # Try legacy numeric_scores
        if "numeric_scores" in result:
            risk_val = result["numeric_scores"].get("risk_score", 50)
        else:
            risk_val = 50
        result["risk_score"] = {
            "value": int(risk_val) if isinstance(risk_val, (int, float)) else 50,
            "label": "HIGH" if risk_val >= 70 else "MEDIUM" if risk_val >= 40 else "LOW",
            "reasons_tr": []
        }
    else:
        if not isinstance(result["risk_score"], dict):
            result["risk_score"] = {"value": int(result["risk_score"]), "label": "MEDIUM", "reasons_tr": []}
        if "value" not in result["risk_score"]:
            result["risk_score"]["value"] = 50
        if "label" not in result["risk_score"]:
            val = result["risk_score"]["value"]
            result["risk_score"]["label"] = "HIGH" if val >= 70 else "MEDIUM" if val >= 40 else "LOW"
        if "reasons_tr" not in result["risk_score"]:
            result["risk_score"]["reasons_tr"] = []
    
    if "confidence_score" not in result:
        # Try legacy numeric_scores
        if "numeric_scores" in result:
            conf_val = result["numeric_scores"].get("confidence_score", 50)
        else:
            conf_val = 50
        result["confidence_score"] = {
            "value": int(conf_val) if isinstance(conf_val, (int, float)) else 50,
            "reasons_tr": []
        }
    else:
        if not isinstance(result["confidence_score"], dict):
            result["confidence_score"] = {"value": int(result["confidence_score"]), "reasons_tr": []}
        if "value" not in result["confidence_score"]:
            result["confidence_score"]["value"] = 50
        if "reasons_tr" not in result["confidence_score"]:
            result["confidence_score"]["reasons_tr"] = []
    
    # Ensure quality_guards
    if "quality_guards" not in result:
        result["quality_guards"] = {
            "no_repeated_sentences": True,
            "min_detail_level": True
        }
    
    return result


def _transform_master_to_legacy_format(master_analysis: dict, news_sentiment_score: int = 50) -> dict:
    """Transform NEW_ANALYSIS_SCHEMA format to legacy analiz format for frontend."""
    ma = master_analysis if isinstance(master_analysis, dict) else {}

    # verdict → karar
    verdict_raw = ma.get("verdict", "TUT")
    if isinstance(verdict_raw, dict):
        verdict_str = verdict_raw.get("decision", "TUT")
    else:
        verdict_str = str(verdict_raw).upper()
    if verdict_str in ("AL", "BUY"): karar = "AL"
    elif verdict_str in ("SAT", "SELL"): karar = "SAT"
    else: karar = "TUT"

    confidence = ma.get("confidence", 50)
    try: confidence = int(confidence)
    except: confidence = 50

    headline_tr = ma.get("headline_tr", "")
    main_thesis = ma.get("main_thesis", "")
    thesis_bullets = ma.get("thesis_bullets", [])
    risk_bullets = ma.get("risk_bullets", [])
    news_summary = ma.get("news_summary", "")
    what_to_watch = ma.get("what_to_watch", [])
    strategy_name = ma.get("strategy_name", "")
    levels = ma.get("levels", {}) if isinstance(ma.get("levels"), dict) else {}

    # Build rich strings for legacy fields
    ana_neden = headline_tr or main_thesis or "Analiz tamamlandı"
    teknik_str = ". ".join(thesis_bullets[:3]) if thesis_bullets else "Teknik analiz yapılamadı"
    stratejik_str = main_thesis or ". ".join(thesis_bullets) or "Stratejik plan yapılamadı"
    risk_str = " | ".join(risk_bullets[:2]) if risk_bullets else "Risk analizi yapılamadı"
    stop_loss = levels.get("stop_loss", "N/A")

    # Bear scenario from scenarios list
    scenarios = ma.get("scenarios", [])
    bear = next((s for s in scenarios if isinstance(s, dict) and s.get("type") == "bear"), {})
    benzer_gecmis = bear.get("trigger", "") + " " + bear.get("expected_move", "") if bear else news_summary or "Analiz edilemedi"

    anlik_olay = news_summary or ". ".join(what_to_watch[:2]) or "Kontrol edilemedi"

    return {
        "karar": karar,
        "guven_skoru": str(confidence),
        "ana_neden": ana_neden,
        "ozdenetim_yorum": anlik_olay,
        "teknik_derinlik": teknik_str,
        "stratejik_plan": stratejik_str,
        "ozel_strateji_basligi": strategy_name or karar,
        "ozel_strateji_detayi": ". ".join(thesis_bullets) or stratejik_str,
        "stop_loss": stop_loss,
        "risk_uyarisi": risk_str,
        "benzer_gecmis_senaryo": benzer_gecmis,
        "anlik_olay_kontrolu": anlik_olay,
    }


def _iso_utc_now() -> str:
    return _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_reason_to_bullets(reason_tr: str) -> List[str]:
    if not reason_tr or not isinstance(reason_tr, str):
        return []
    parts = [p.strip() for p in reason_tr.replace("\n", " ").split(".") if p.strip()]
    return parts[:3]


def _map_news_impact(value: str) -> str:
    if not value:
        return "neutral"
    v = str(value).strip().lower()
    if v in ["bearish", "negatif", "negative", "down"]:
        return "bearish"
    if v in ["bullish", "pozitif", "positive", "up"]:
        return "bullish"
    return "neutral"


def _canonical_decision_from_local_action(local_action: str, has_position: bool) -> str:
    a = (local_action or "HOLD").upper()
    if a == "BUY":
        return "BUY"
    if a == "SELL":
        return "REDUCE" if has_position else "AVOID"
    return "HOLD"


def _default_glossary_terms() -> Dict[str, str]:
    return {
        "RSI": "Göreli Güç Endeksi; aşırı alım/satım bölgelerini işaret eder.",
        "Bollinger Bands": "Fiyatın oynaklık bandı; alt bant destek, üst bant direnç gibi davranabilir.",
        "Stop-loss": "Zarar büyümeden çıkış için önceden belirlenen seviye.",
        "Take-profit": "Kârı kilitlemek için önceden belirlenen hedef seviye.",
        "Horizon": "Planın geçerli olacağı tahmini süre (gün).",
    }


def _build_action_plan(
    decision: str,
    technical: Dict[str, Any],
    has_position: bool,
) -> List[Dict[str, Any]]:
    price = float(technical.get("current_price") or technical.get("fiyat") or 0) if technical else 0.0
    bb_alt = float(technical.get("bb_alt") or 0) if technical else 0.0
    bb_ust = float(technical.get("bb_ust") or 0) if technical else 0.0

    plan: List[Dict[str, Any]] = []

    if decision == "BUY":
        plan.append(
            {
                "type": "BUY",
                "amount_percent_of_position_value": 10,
                "timeframe": "1-3 gün",
                "rationale_short": "Kademeli giriş; tek seferde yüklenme yerine adım adım ilerle.",
            }
        )
        if bb_alt > 0:
            plan.append(
                {
                    "type": "SET_SL",
                    "price_level": bb_alt,
                    "timeframe": "hemen",
                    "rationale_short": "Alt banda yakın stop ile riskini sınırlamaya çalış.",
                }
            )
        if bb_ust > 0:
            plan.append(
                {
                    "type": "SET_TP",
                    "price_level": bb_ust,
                    "timeframe": "3-14 gün",
                    "rationale_short": "Üst banda yaklaşırken kârı kademeli kilitle.",
                }
            )
        plan.append(
            {
                "type": "RECHECK",
                "timeframe": "24 saat",
                "rationale_short": "RSI ve trend teyidi için 1 gün sonra yeniden değerlendir.",
            }
        )

    elif decision == "REDUCE":
        plan.append(
            {
                "type": "SELL",
                "amount_percent_of_position_value": 20,
                "timeframe": "1-3 gün",
                "rationale_short": "Risk azalt; özellikle aşırı alım/olumsuz haber varsa küçült.",
            }
        )
        if bb_alt > 0:
            plan.append(
                {
                    "type": "SET_SL",
                    "price_level": bb_alt,
                    "timeframe": "hemen",
                    "rationale_short": "Zarar kontrolü için stop seviyesini netleştir.",
                }
            )
        plan.append(
            {
                "type": "RECHECK",
                "timeframe": "24-48 saat",
                "rationale_short": "Haber akışı ve RSI normalleşirse planı güncelle.",
            }
        )

    elif decision == "AVOID":
        plan.append(
            {
                "type": "NO_ACTION",
                "timeframe": "şimdi",
                "rationale_short": "Yeni pozisyon açma; şartlar netleşene kadar bekle.",
            }
        )
        plan.append(
            {
                "type": "RECHECK",
                "timeframe": "24-72 saat",
                "rationale_short": "Trend dönüşü veya risk azalınca tekrar değerlendir.",
            }
        )

    else:  # HOLD
        plan.append(
            {
                "type": "WAIT",
                "timeframe": "1-3 gün",
                "rationale_short": "Kararı değiştirecek net bir sinyal oluşana kadar izle.",
            }
        )
        if has_position and bb_alt > 0:
            plan.append(
                {
                    "type": "SET_SL",
                    "price_level": bb_alt,
                    "timeframe": "hemen",
                    "rationale_short": "Mevcut pozisyon için zarar kes planını hazır tut.",
                }
            )
        if has_position and bb_ust > 0 and price > 0:
            plan.append(
                {
                    "type": "SET_TP",
                    "price_level": bb_ust,
                    "timeframe": "3-14 gün",
                    "rationale_short": "Direnç/üst bantta kârı kilitlemeyi planla.",
                }
            )
        plan.append(
            {
                "type": "RECHECK",
                "timeframe": "24 saat",
                "rationale_short": "Yeni kapanış ve haber akışı ile yeniden değerlendir.",
            }
        )

    return plan[:4]


def _compute_quick_features_hash(features: Dict[str, Any]) -> str:
    try:
        payload = json_lib.dumps(features, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.sha256(str(features).encode("utf-8")).hexdigest()


def get_canonical_quick_analysis(
    symbol: str,
    cost: Optional[float] = None,
    qty: float = 1,
    mode: str = "STOCK",
    as_of: Optional[str] = None,
    include_evidence: bool = False,
) -> Dict[str, Any]:
    """
    QUICK (deterministic) canonical decision endpoint helper.
    Produces the full canonical JSON without any LLM calls.
    """
    # Use robust normalization
    from .data_provider import normalize_symbol as robust_normalize, validate_symbol
    
    try:
        normalized_symbol, detected_mode = robust_normalize(symbol, mode)
        mode_upper = detected_mode
    except ValueError as e:
        # Invalid symbol - return HOLD with explanation
        return {
            "symbol": symbol.upper().strip(),
            "decision": "HOLD",
            "confidence": 20,
            "why_bullets": [
                f"Sembol normalleştirme hatası: {str(e)}",
                "Geçersiz sembol formatı nedeniyle analiz yapılamadı",
                "Lütfen sembolü kontrol edin"
            ],
            "action_plan": [
                {"type": "WAIT", "rationale_short": "Geçersiz sembol, işlem yapmayın"}
            ],
            "missing_data": {
                "sections": ["all"],
                "errors": [f"Symbol normalization failed: {str(e)}"],
                "symbol": symbol,
            },
            "risk_note": "Sembol doğrulama hatası nedeniyle analiz yapılamadı",
            "errors": [f"Invalid symbol: {str(e)}"],
            "flags": {"missing_data": True, "validation_failed": True}
        }

    analysis_ts = as_of or _iso_utc_now()

    # Data fetch via MarketSnapshot (single interface; explicit availability/errors)
    # NOTE: import inside function to avoid circular imports (market_snapshot uses logic helpers).
    from .market_snapshot import get_market_snapshot

    snapshot = get_market_snapshot(
        symbol=normalized_symbol,
        mode=mode_upper,
        as_of=analysis_ts,
        include_ohlc=True,  # Use provider cache+fallback; enables meaningful as_of.ohlc for UI/debug
    )

    # Check for missing data and return HOLD if critical data is missing
    tech = snapshot.quote or {}
    fundamentals = snapshot.fundamentals if mode_upper == "STOCK" else {}
    news_data = snapshot.news or {}
    
    # If quote data is missing, return HOLD with explanation
    if not snapshot.data_availability.get("quote", {}).available:
        missing_sections = []
        if not snapshot.data_availability.get("quote", {}).available:
            missing_sections.append("quote")
        if not snapshot.data_availability.get("ohlc", {}).available:
            missing_sections.append("ohlc")
        if mode_upper == "STOCK" and not snapshot.data_availability.get("fundamentals", {}).available:
            missing_sections.append("fundamentals")
        
        error_messages = [e.message for e in snapshot.errors[:3]]
        
        return {
            "symbol": normalized_symbol,
            "decision": "HOLD",
            "confidence": 20,
            "why_bullets": [
                f"Veri sağlayıcıdan {', '.join(missing_sections)} alınamadı",
                f"Hata: {error_messages[0] if error_messages else 'Bilinmeyen hata'}",
                "Eksik veri nedeniyle güvenli karar: HOLD"
            ],
            "action_plan": [
                {"type": "WAIT", "rationale_short": "Veri eksikliği nedeniyle işlem yapmayın"},
                {"type": "SET_ALERT", "rationale_short": "Veri geldiğinde bildirim alın"}
            ],
            "missing_data": {
                "sections": missing_sections,
                "errors": error_messages,
                "symbol": normalized_symbol,
            },
            "risk_note": f"Veri eksikliği riski: {', '.join(missing_sections)} bölümleri mevcut değil",
            "errors": error_messages,
            "flags": {"missing_data": True, "provider_failed": True}
        }

    # Normalize news items into canonical shape (top 3 by importance)
    raw_news_items = []
    for item in (news_data.get("ai_interpreted") or [])[:10]:
        raw_news_items.append(
            {
                "title": item.get("title", ""),
                "importance_score": int(item.get("importance_score", 0) or 0),
                "impact": _map_news_impact(item.get("impact", "")),
                "reasons": item.get("reasons") or [],
            }
        )
    raw_news_items.sort(key=lambda x: x.get("importance_score", 0), reverse=True)
    top_news_items = raw_news_items[:3]

    news_impact = []
    for n in top_news_items:
        title = (n.get("title") or "").strip()
        importance = int(n.get("importance_score", 0) or 0)
        impact = n.get("impact", "neutral")
        reasons = n.get("reasons") or []
        why = reasons[0] if reasons else f"Önem skoru {importance}/100; kısa vadede fiyatı etkileyebilir."
        news_impact.append(
            {
                "event_summary": title[:140] if title else "Haber başlığı yok",
                "impact": impact,
                "why_it_matters": str(why)[:160],
                "confidence": max(0, min(100, importance)),
            }
        )

    # Decision engine (deterministic)
    has_position = (cost is not None) and (qty is not None) and float(qty) > 0
    insider_hint = None
    try:
        insider_hint = get_insider_intelligence(normalized_symbol) if mode_upper == "STOCK" else None
    except Exception:
        insider_hint = None

    local_decision = local_decision_engine(technical=tech, fundamentals=fundamentals, insider=insider_hint)
    base_decision = _canonical_decision_from_local_action(local_decision.get("action"), has_position)
    confidence = int(local_decision.get("confidence_score", 50) or 50)

    # News guardrails (deterministic)
    max_bearish = max((n["confidence"] for n in news_impact if n.get("impact") == "bearish"), default=0)
    max_bullish = max((n["confidence"] for n in news_impact if n.get("impact") == "bullish"), default=0)

    why_bullets = _split_reason_to_bullets(local_decision.get("reason_tr", ""))[:2]
    if not why_bullets:
        # Ensure canonical contract stays non-empty/deterministic even if upstream reason is blank.
        why_bullets = ["Veri/sinyal seti sınırlı; karar temkinli kurallarla oluşturuldu."]

    decision = base_decision
    if max_bearish >= 70 and decision == "BUY":
        decision = "HOLD" if has_position else "AVOID"
        confidence = min(confidence, 40)
        why_bullets.append("Kritik olumsuz haber riski: yeni alım yerine beklemek daha güvenli olabilir.")
    elif max_bullish >= 70 and decision in ["AVOID", "REDUCE"]:
        decision = "HOLD"
        why_bullets.append("Kritik olumlu haber: agresif satış/kaçınma yerine nötr duruş daha mantıklı olabilir.")

    why_bullets = why_bullets[:3]

    # Horizon heuristic (deterministic)
    rsi = float(tech.get("rsi", 50) or 50)
    trend = str(tech.get("trend", "SIDEWAYS") or "SIDEWAYS").upper()
    horizon_days = 7
    if decision == "BUY" and trend == "UP" and 35 <= rsi <= 65:
        horizon_days = 14
    elif decision in ["AVOID", "REDUCE"] and (rsi >= 70 or trend == "DOWN"):
        horizon_days = 3

    action_plan = _build_action_plan(decision=decision, technical=tech, has_position=has_position)

    # Data freshness stamps (best-effort, from snapshot)
    freshness = {
        "analysis": snapshot.analysis_as_of or analysis_ts,
        "quote": snapshot.quote_as_of or analysis_ts,
        "ohlc": snapshot.ohlc_as_of or analysis_ts,
        "fundamentals": snapshot.fundamentals_as_of or analysis_ts,
        "news": snapshot.news_as_of or analysis_ts,
    }

    # Features hash for caching DEEP
    quick_features = {
        "symbol": normalized_symbol,
        "mode": mode_upper,
        "price": tech.get("current_price") or tech.get("fiyat"),
        "rsi": tech.get("rsi"),
        "bb_alt": tech.get("bb_alt"),
        "bb_ust": tech.get("bb_ust"),
        "trend": tech.get("trend"),
        "has_position": has_position,
        "top_news": [
            {"impact": n.get("impact"), "confidence": n.get("confidence"), "event_summary": n.get("event_summary")}
            for n in news_impact
        ],
        "decision": decision,
        "confidence": confidence,
        "horizon_days": horizon_days,
    }
    quick_hash = _compute_quick_features_hash(quick_features)

    result: Dict[str, Any] = {
        "symbol": normalized_symbol,
        "mode": "quick",
        "as_of": freshness,
        "decision": decision,
        "confidence": max(0, min(100, int(confidence))),
        "horizon_days": max(1, min(365, int(horizon_days))),
        "why_bullets": why_bullets,
        "action_plan": action_plan,
        "news_impact": news_impact[:3],
        "glossary_terms": _default_glossary_terms(),
        "mentor_scenario": "Planını uygula, duygusal karar yerine kurallara sadık kal. Gelişmelerle birlikte 24-72 saat içinde yeniden değerlendir.",
        "quick_features_hash": quick_hash,
    }

    if include_evidence:
        result["evidence"] = {
            "technical": {
                "price": tech.get("current_price") or tech.get("fiyat"),
                "rsi": tech.get("rsi"),
                "bb_alt": tech.get("bb_alt"),
                "bb_ust": tech.get("bb_ust"),
                "trend": tech.get("trend"),
            },
            "news_raw": (news_data.get("ai_interpreted") or [])[:3],
            "snapshot": {
                "data_availability": _json_safe(
                    {k: v.model_dump() for k, v in (snapshot.data_availability or {}).items()}
                ),
                "errors": [e.model_dump() for e in (snapshot.errors or [])],
                "as_of": {
                    "analysis_as_of": snapshot.analysis_as_of,
                    "quote_as_of": snapshot.quote_as_of,
                    "ohlc_as_of": snapshot.ohlc_as_of,
                    "fundamentals_as_of": snapshot.fundamentals_as_of,
                    "news_as_of": snapshot.news_as_of,
                },
            },
        }

    # Strict validation + normalization (max items, etc.)
    validated = CanonicalDecisionResponse.model_validate(result)
    return _json_safe(validated.model_dump())


def _compute_deep_cache_key(symbol: str, as_of_analysis: str, quick_features_hash: str) -> str:
    raw = f"{symbol}|{as_of_analysis}|{quick_features_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _apply_deep_patch_with_guards(quick_json: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge DEEP narrative patch into QUICK canonical output, enforcing divergence rules."""
    deep = dict(quick_json)
    deep["mode"] = "deep"

    quick_decision = quick_json.get("decision")

    # Wording only
    why_bullets = patch.get("why_bullets") if isinstance(patch, dict) else None
    if isinstance(why_bullets, list) and why_bullets:
        deep["why_bullets"] = [str(x) for x in why_bullets][:3]

    rationales = patch.get("action_plan_rationales") if isinstance(patch, dict) else None
    if isinstance(rationales, list) and isinstance(deep.get("action_plan"), list):
        for i, item in enumerate(deep["action_plan"]):
            if i < len(rationales) and isinstance(item, dict):
                item["rationale_short"] = str(rationales[i])[:220]

    mentor_scenario = patch.get("mentor_scenario") if isinstance(patch, dict) else None
    if isinstance(mentor_scenario, str) and mentor_scenario.strip():
        deep["mentor_scenario"] = mentor_scenario.strip()

    # OVERRIDE contract (rare)
    override = patch.get("override") if isinstance(patch, dict) else None
    if isinstance(override, dict) and override.get("override_applied") is True:
        proposed = str(override.get("decision") or "").upper()
        proposed_reason = str(override.get("override_reason") or "").strip()
        proposed_conf = override.get("override_confidence")
        proposed_ts = str(override.get("data_change_timestamp") or "").strip() or _iso_utc_now()

        news_events = [
            str(n.get("event_summary", ""))
            for n in (quick_json.get("news_impact") or [])
            if isinstance(n, dict)
        ]
        reason_has_event = any(ev and ev.lower() in proposed_reason.lower() for ev in news_events)
        has_critical_news = any(
            isinstance(n, dict)
            and int(n.get("confidence", 0) or 0) >= 80
            and n.get("impact") in ["bullish", "bearish"]
            for n in (quick_json.get("news_impact") or [])
        )
        conf_ok = isinstance(proposed_conf, (int, float)) and int(proposed_conf) >= 60

        if (
            proposed in ["BUY", "HOLD", "REDUCE", "AVOID"]
            and proposed != quick_decision
            and proposed_reason
            and reason_has_event
            and has_critical_news
            and conf_ok
        ):
            deep["decision"] = proposed
            deep["override"] = {
                "override_applied": True,
                "override_reason": proposed_reason,
                "override_confidence": int(proposed_conf),
                "data_change_hash": hashlib.sha256("|".join(news_events).encode("utf-8")).hexdigest(),
                "data_change_timestamp": proposed_ts,
            }
            print("[deep_override_applied]", {"from": quick_decision, "to": proposed, "reason": proposed_reason[:120]})
        else:
            print("[deep_override_rejected]", {"from": quick_decision, "to": proposed, "reason": proposed_reason[:120]})

    deep_decision = deep.get("decision")
    override_applied = bool(isinstance(deep.get("override"), dict) and deep["override"].get("override_applied") is True)
    if deep_decision != quick_decision and not override_applied:
        deep["decision"] = quick_decision
        deep.pop("override", None)
        print("deep_divergence_blocked")

    return deep

def _deep_quality_gate_required_fields(payload: Dict[str, Any]) -> Optional[str]:
    """
    Quality gate for DEEP responses.

    Requirement: before returning DEEP, ensure required fields are present and not empty:
    - decision
    - why_bullets
    - action_plan
    - glossary_terms
    """
    try:
        decision = (payload.get("decision") or "").strip()
        if decision not in ["BUY", "HOLD", "REDUCE", "AVOID"]:
            return "missing_or_invalid_decision"

        why = payload.get("why_bullets")
        if not isinstance(why, list) or not any(isinstance(x, str) and x.strip() for x in why):
            return "missing_why_bullets"

        action_plan = payload.get("action_plan")
        if not isinstance(action_plan, list) or len(action_plan) < 1:
            return "missing_action_plan"

        glossary = payload.get("glossary_terms")
        if not isinstance(glossary, dict) or len(glossary) < 1:
            return "missing_glossary_terms"

        for k, v in glossary.items():
            if not isinstance(k, str) or not k.strip():
                return "invalid_glossary_terms"
            if not isinstance(v, str) or not v.strip():
                return "invalid_glossary_terms"

        return None
    except Exception as e:
        return f"deep_quality_gate_exception:{type(e).__name__}"


def get_canonical_deep_analysis(
    symbol: str,
    cost: Optional[float] = None,
    qty: float = 1,
    mode: str = "STOCK",
    as_of: Optional[str] = None,
    force: bool = False,
    include_evidence: bool = False,
) -> Dict[str, Any]:
    """
    DEEP canonical decision endpoint helper.
    - Always computes QUICK first (or uses cached DEEP by hash key).
    - Calls LLM ONLY to polish wording + mentor scenario, never to rescore.
    - Enforces divergence/override rules.
    """
    quick = get_canonical_quick_analysis(
        symbol=symbol, cost=cost, qty=qty, mode=mode, as_of=as_of, include_evidence=include_evidence
    )
    as_of_analysis = quick.get("as_of", {}).get("analysis") or (as_of or _iso_utc_now())
    quick_hash = quick.get("quick_features_hash") or ""
    cache_key = _compute_deep_cache_key(quick.get("symbol", symbol), as_of_analysis, quick_hash)

    if not force:
        cached = get_deep_decision_cache(cache_key)
        if isinstance(cached, dict) and cached.get("symbol") == quick.get("symbol"):
            # Even cached DEEP must obey divergence rule
            cached_fixed = dict(cached)
            if cached_fixed.get("decision") != quick.get("decision"):
                cached_fixed["decision"] = quick.get("decision")
                cached_fixed.pop("override", None)
                print("deep_divergence_blocked")
            cached_fixed["mode"] = "deep"
            validated = CanonicalDecisionResponse.model_validate(cached_fixed)
            deep_cached_out = _json_safe(validated.model_dump())

            gate_reason = _deep_quality_gate_required_fields(deep_cached_out)
            if gate_reason:
                print("[deep_quality_gate_failed]", {"reason": gate_reason, "cache_hit": 1})
                quick_fallback = dict(quick)
                quick_fallback["mode"] = "quick"
                quick_fallback["deep_failed_reason"] = gate_reason
                validated_quick = CanonicalDecisionResponse.model_validate(quick_fallback)
                return _json_safe(validated_quick.model_dump())

            print(f"[deep] cache_hit=1 force=0 key={cache_key[:10]}...")
            return deep_cached_out

    # Build narrative-only patch via LLM (best-effort)
    prompt = f"""You are an investment mentor writing in Turkish.

ROOT RULE:
- QUICK is the deterministic decision engine.
- You may ONLY improve wording/clarity. Do NOT add new numeric indicators.
- Do NOT contradict QUICK decision/confidence/horizon or any numbers.

QUICK canonical decision JSON (ground truth):
{json_lib.dumps(quick, ensure_ascii=False)}

Do:
- Polish why_bullets (max 3) without changing meaning.
- Provide action_plan_rationales: one rationale per existing action_plan item (same order).
- Write mentor_scenario as exactly 2 sentences.

Optional OVERRIDE (rare):
If (and only if) a concrete critical news event in news_impact forces a different decision, include override with:
- override_applied=true
- decision
- override_reason (must mention the exact event_summary)
- override_confidence
- data_change_timestamp
Otherwise omit override or set override_applied=false.
"""

    patch: Dict[str, Any] = {}
    try:
        patch = safe_gemini_call(
            prompt,
            response_mode="json",
            schema=DEEP_NARRATIVE_PATCH_SCHEMA,
            max_retries=1,
            purpose="decision_deep",
        )
        if not isinstance(patch, dict):
            patch = {}
    except Exception as e:
        print(f"[deep] llm_failed: {type(e).__name__}: {e}")
        patch = {}

    deep = _apply_deep_patch_with_guards(quick_json=quick, patch=patch)
    deep["mode"] = "deep"

    validated = CanonicalDecisionResponse.model_validate(deep)
    deep_out = _json_safe(validated.model_dump())

    gate_reason = _deep_quality_gate_required_fields(deep_out)
    if gate_reason:
        print("[deep_quality_gate_failed]", {"reason": gate_reason, "cache_hit": 0, "llm_used": 1 if patch else 0})
        quick_fallback = dict(quick)
        quick_fallback["mode"] = "quick"
        quick_fallback["deep_failed_reason"] = gate_reason
        validated_quick = CanonicalDecisionResponse.model_validate(quick_fallback)
        return _json_safe(validated_quick.model_dump())

    # Save cache (best-effort)
    set_deep_decision_cache(
        cache_key=cache_key,
        symbol=deep_out.get("symbol", symbol),
        as_of_analysis=as_of_analysis,
        quick_features_hash=quick_hash,
        deep_json=deep_out,
    )
    print(f"[deep] cache_hit=0 llm_used={1 if patch else 0} force={1 if force else 0} key={cache_key[:10]}...")

    return deep_out

def get_ai_insight(symbol, cost=None, qty=1, mode="STOCK", use_llm: int = 1, detail: str = "medium"):
    """
    Slow endpoint: Returns ONLY AI analysis.
    
    **DEEP MODE ENFORCED**: Always uses LLM for quality analysis (Gemini 1.5 Flash, 15 RPM).
    
    Args:
        symbol: Stock/crypto symbol
        cost: Optional cost basis
        qty: Optional quantity
        mode: "STOCK" or "CRYPTO"
        use_llm: FORCED TO 1 (always use LLM for deep analysis)
        detail: "short" | "medium" | "full" (default: "medium")
    
    Returns:
        dict: Analysis result with legacy and master format
    """
    # ULTIMATE SAFETY NET: Wrap entire function in try/except to prevent 500 errors
    try:
        # FORCE DEEP MODE: Override use_llm to always use LLM
        use_llm = 1
        print(f"🔥 [DEEP MODE ENFORCED] Using LLM for {symbol} analysis (Quality over Speed)")
        
        normalized_symbol = normalize_symbol(symbol)
        crypto = (mode.upper() == "CRYPTO") or is_crypto(symbol)
        mode_upper = mode.upper()
        
        # Get data needed for analysis via MarketSnapshot (single interface)
        # NOTE: import inside function to avoid circular imports.
        from .market_snapshot import get_market_snapshot

        snapshot = get_market_snapshot(
            symbol=normalized_symbol,
            mode=mode_upper,
            as_of=_iso_utc_now(),
            include_ohlc=True,
        )

        tech = snapshot.quote or {}
        fundamentals = snapshot.fundamentals if mode_upper == "STOCK" else {}
        # IMPORTANT: /ai-insight should not trigger extra LLM calls inside news fetching.
        # The only LLM call (when enabled) should be run_master_analysis below.
        news_data = snapshot.news or {}

        llm_skipped_reason = None
        if use_llm == 1:
            # Non-degradation gate: if required market data is missing, skip LLM and serve template output.
            quote_ok = bool(snapshot.data_availability.get("quote") and snapshot.data_availability["quote"].available)
            ohlc_ok = bool(snapshot.data_availability.get("ohlc") and snapshot.data_availability["ohlc"].available)
            news_ok = bool(snapshot.data_availability.get("news") and snapshot.data_availability["news"].available)
            needs_news = str(detail or "").lower() == "full"

            if not quote_ok:
                llm_skipped_reason = "missing_snapshot_quote"
                use_llm = 0
            elif not ohlc_ok:
                llm_skipped_reason = "missing_snapshot_ohlc"
                use_llm = 0
            elif needs_news and not news_ok:
                llm_skipped_reason = "missing_snapshot_news_for_full_detail"
                use_llm = 0

        deep_tech = calculate_deep_technicals(symbol)
        
        # Build technical context (combine tech and deep_tech)
        technical_context = {
            **tech,
            **deep_tech
        }
        
        # Extract news items with importance_score and impact
        news_items = []
        if news_data.get("ai_interpreted"):
            for item in news_data["ai_interpreted"]:
                news_items.append({
                    "title": item.get("title", ""),
                    "importance_score": item.get("importance_score", 0),
                    "impact": item.get("impact", "neutral").lower()
                })
        
        # Format news context as list of dicts (for LLM if used)
        news_context = []
        if news_data.get("titles"):
            for i, title in enumerate(news_data.get("titles", [])[:10]):
                news_item = {
                    "title": title,
                    "source": "Yahoo Finance",
                    "published_at": "Recent",
                    "link": "",
                    "sentiment_hint": "Neutral"
                }
                # Try to get from ai_interpreted if available
                if news_data.get("ai_interpreted") and i < len(news_data["ai_interpreted"]):
                    interpreted = news_data["ai_interpreted"][i]
                    news_item["sentiment_hint"] = interpreted.get("impact", "Neutral")
                    news_item["link"] = interpreted.get("link", "")
                news_context.append(news_item)
        
        price = tech.get("fiyat", tech.get("current_price", 0))
        
        # Step 1: Apply policy guardrails BEFORE LLM call (or template generation)
        # This ensures risk-aware decisions regardless of LLM usage
        
        # Step 2: Generate analysis (LLM or template)
        if use_llm == 0:
            # Template-based analysis (NO LLM)
            print(f"[ai] llm_disabled serving_template=1")
            if llm_skipped_reason:
                print("[ai] llm_skipped", {"reason": llm_skipped_reason})
            
            master_analysis = build_template_analysis(
                symbol=normalized_symbol,
                mode=mode_upper,
                price=price,
                technical_context=technical_context,
                news_data=news_data,
                news_items=news_items
            )
            
            # Apply policy guardrails to template analysis
            master_analysis = apply_policy_guardrails(master_analysis, news_items)
            
        else:
            # LLM-based analysis (use_llm=1)
            # Get memory summaries using database helper
            memory_summaries = get_memory_context(normalized_symbol, mode_upper, limit=20)
            
            # Get user profile
            user_profile = get_user_profile()
            
            # Call master analysis (ONE Gemini call, retry 0)
            try:
                master_analysis = run_master_analysis(
                    symbol=normalized_symbol,
                    mode=mode_upper,
                    price=price,
                    technical_context=technical_context,
                    news_context=news_context,
                    memory_summaries=memory_summaries,
                    user_profile=user_profile,
                    detail=detail,
                    fundamental_context=fundamentals
                )
                
                # Apply policy guardrails AFTER LLM call
                master_analysis = apply_policy_guardrails(master_analysis, news_items)
                
            except Exception as e:
                import traceback
                error_type = type(e).__name__
                error_str = str(e).lower()
                
                # Check if it's a budget limit error
                is_budget_error = (
                    "budget" in error_str or
                    "GeminiCallError" in error_type and "budget" in error_str
                )
                
                if is_budget_error:
                    print(f"[llm] blocked budget daily_calls=... monthly_usd=... purpose=ai_insight")
                else:
                    print(f"❌ [get_ai_insight] LLM error: {error_type}: {e}")
                    traceback.print_exc()
                
                # Fallback to template analysis on LLM failure (including budget limit)
                print(f"[ai] llm_failed, falling_back_to_template")
                master_analysis = build_template_analysis(
                    symbol=normalized_symbol,
                    mode=mode_upper,
                    price=price,
                    technical_context=technical_context,
                    news_data=news_data,
                    news_items=news_items
                )
                master_analysis = apply_policy_guardrails(master_analysis, news_items)
    
        # CRITICAL FIX: Ensure master_analysis is a dict before transformation
        master_analysis = ensure_dict(master_analysis)
        
        # Transform to legacy format for backward compatibility
        legacy_analysis = _transform_master_to_legacy_format(master_analysis, news_data.get('sentiment_score', 50))
        
        response_data = {
            "sembol": normalized_symbol,
            "analiz": [legacy_analysis],
            "benzer_gecmis_senaryo": legacy_analysis.get('benzer_gecmis_senaryo', 'Analiz edilemedi'),
            "anlik_olay_kontrolu": legacy_analysis.get('anlik_olay_kontrolu', 'Kontrol edilemedi'),
            "haber_skoru": news_data.get('sentiment_score', 50),
            "master_analysis": master_analysis,  # Include new format for future use
            "meta": {
                "llm_used": 1 if use_llm == 1 else 0,
                "llm_skipped_reason": llm_skipped_reason,
                "snapshot_availability": {k: v.model_dump() for k, v in (snapshot.data_availability or {}).items()},
                "snapshot_errors": [e.model_dump() for e in (snapshot.errors or [])],
            },
        }
        
        return response_data
    
    except Exception as e:
        # ULTIMATE SAFETY NET: Return valid error card to prevent 500 errors
        import traceback
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"❌ [ULTIMATE SAFETY NET] get_ai_insight crashed: {error_type}: {error_msg}")
        traceback.print_exc()
        
        # Normalize symbol for error response (try to get normalized_symbol, fallback to input symbol)
        try:
            normalized_symbol = normalize_symbol(symbol)
        except:
            normalized_symbol = symbol
        
        # Return safe error card in master_analysis format
        error_master_analysis = {
            "headline_tr": f"Sistem hatası düzeliyor: {error_type}",
            "verdict": "TUT",
            "confidence": 0,
            "thesis_bullets": [
                "Veri işleme hatası oluştu",
                "Sistem otomatik koruma modunda",
                "Analiz tamamlanamadı",
                "Manuel inceleme önerilir",
                "Lütfen tekrar deneyin"
            ],
            "risk_bullets": [
                "Otomatik koruma devrede",
                "Belirsizlik çok yüksek",
                "Pozisyon alınmamalı",
                "Risk yönetimi yapılamadı",
                "Sistem hatası"
            ],
            "news_summary_tr": "Haber analizi yapılamadı - sistem hatası",
            "next_levels": {
                "stop_loss": 0,
                "take_profit_1": 0,
                "take_profit_2": 0,
                "trailing_stop_distance": 0
            },
            "scenarios": [],
            "context_memory": "",
            "raw_score": 0,
            "meta": {
                "model": "emergency_fallback",
                "purpose": "error_recovery",
                "timestamp": _iso_utc_now(),
                "llm_used": 0,
                "error": error_msg[:200]
            }
        }
        
        # Build legacy format from error master analysis
        error_legacy_analysis = {
            "karar": "TUT",
            "güven_skoru": 0,
            "açıklama": f"Sistem hatası düzeliyor: {str(e)[:100]}",
            "nedenler": ["Veri işleme hatası"],
            "önerilen_işlemler": ["Bekle"],
            "risk_uyarısı": "Otomatik koruma devrede.",
            "benzer_gecmis_senaryo": "Analiz edilemedi - sistem hatası",
            "anlik_olay_kontrolu": "Kontrol edilemedi - sistem hatası"
        }
        
        return {
            "sembol": normalized_symbol,
            "analiz": [error_legacy_analysis],
            "benzer_gecmis_senaryo": "Analiz edilemedi - sistem hatası",
            "anlik_olay_kontrolu": "Kontrol edilemedi - sistem hatası",
            "haber_skoru": 50,
            "master_analysis": error_master_analysis,
            "meta": {
                "llm_used": 0,
                "llm_skipped_reason": "fatal_error",
                "error_type": error_type,
                "error_message": error_msg[:200],
                "snapshot_availability": {},
                "snapshot_errors": [],
            },
        }

def generate_ai_report(symbol, cost=None, qty=1, mode="STOCK"):
    """
    Legacy endpoint: Combines fast market data + slow AI insight.
    Kept for backward compatibility.
    Now uses run_master_analysis for single Gemini call.
    """
    # Normalize symbol for crypto (BTC -> BTC-USD)
    normalized_symbol = normalize_symbol(symbol)
    crypto = (mode.upper() == "CRYPTO") or is_crypto(symbol)
    mode_upper = mode.upper()
    
    # Get market data and chart data (these don't require AI)
    market = get_market_data()
    tech = get_technical_metrics(symbol)
    fundamental = get_fundamental_data(symbol)
    fundamentals = fundamental  # Alias for consistency with other functions
    news_data = get_news(symbol)
    deep_tech = calculate_deep_technicals(symbol)
    chart_data = get_chart_data(symbol, mode_upper)
    
    # Fundamental Intelligence (only for stocks)
    fair_value = None
    insider_status = ""
    earnings_info = {"bilanco_tarihi": "Bilinmiyor", "analyst_estimates": "Yok"}
    competitor_analysis = ""
    
    if not crypto:
        fair_value = calculate_fair_value(symbol)
        insider_status = get_insider_intelligence(symbol)
        earnings_info = get_earnings_info(symbol)
        competitor_analysis = get_competitor_analysis(symbol)
    
    # Build technical context (combine tech and deep_tech)
    technical_context = {
        **tech,
        **deep_tech
    }
    
    # Format news context as list of dicts
    news_context = []
    if news_data.get("titles"):
        for i, title in enumerate(news_data.get("titles", [])[:10]):
            news_item = {
                "title": title,
                "source": "Yahoo Finance",
                "published_at": "Recent",
                "link": "",
                "sentiment_hint": "Neutral"
            }
            # Try to get from ai_interpreted if available
            if news_data.get("ai_interpreted") and i < len(news_data["ai_interpreted"]):
                interpreted = news_data["ai_interpreted"][i]
                news_item["sentiment_hint"] = interpreted.get("impact", "Neutral")
                news_item["link"] = interpreted.get("link", "")
            news_context.append(news_item)
    
    # Get memory summaries using database helper
    memory_summaries = get_memory_context(normalized_symbol, mode_upper, limit=20)
    
    # Get user profile
    user_profile = get_user_profile()
    
    # Call master analysis (ONE Gemini call)
    try:
        master_analysis = run_master_analysis(
                symbol=normalized_symbol,
            mode=mode_upper,
            price=tech.get("fiyat", tech.get("current_price", 0)),
            technical_context=technical_context,
            news_context=news_context,
            memory_summaries=memory_summaries,
            user_profile=user_profile,
            fundamental_context=fundamentals
        )
        
        # CRITICAL FIX: Ensure master_analysis is a dict before transformation
        master_analysis = ensure_dict(master_analysis)
        
        # Transform to legacy format for backward compatibility
        legacy_analysis = _transform_master_to_legacy_format(master_analysis, news_data.get('sentiment_score', 50))
        
        response_data = {
            "sembol": normalized_symbol,
            "fiyat_bilgisi": tech,
            "piyasa_bilgisi": market,
            "analiz": [legacy_analysis],
            "grafik_verileri": chart_data if chart_data else [],
            "benzer_gecmis_senaryo": legacy_analysis.get('benzer_gecmis_senaryo', 'Analiz edilemedi'),
            "anlik_olay_kontrolu": legacy_analysis.get('anlik_olay_kontrolu', 'Kontrol edilemedi'),
            "haber_skoru": news_data.get('sentiment_score', 50),
            "master_analysis": master_analysis  # Include new format for future use
        }
        
        if not crypto:
            response_data["adil_deger"] = fair_value
            response_data["insider_durumu"] = insider_status
            response_data["bilanco_tarihi"] = earnings_info.get('bilanco_tarihi', 'Bilinmiyor')
            response_data["sektor_karsilastirmasi"] = competitor_analysis
        else:
            response_data["adil_deger"] = None
            response_data["insider_durumu"] = None
            response_data["bilanco_tarihi"] = None
            response_data["sektor_karsilastirmasi"] = None
        
        return response_data
        
    except Exception as e:
        import traceback
        print(f"❌ [generate_ai_report] Error: {type(e).__name__}: {e}")
        traceback.print_exc()
        
        # Fallback response
        return {
            "sembol": normalized_symbol,
            "fiyat_bilgisi": tech,
            "piyasa_bilgisi": market,
            "analiz": [{
                "karar": "TUT" if not crypto else "BEKLE",
                "guven_skoru": "50",
                "ana_neden": FALLBACK_AI_MESSAGE,
                "ozdenetim_yorum": FALLBACK_AI_MESSAGE,
                "teknik_derinlik": FALLBACK_AI_MESSAGE,
                "stratejik_plan": FALLBACK_AI_MESSAGE,
                "ozel_strateji_basligi": "Bekle ve Gör",
                "ozel_strateji_detayi": FALLBACK_AI_MESSAGE,
                "stop_loss": "N/A",
                "risk_uyarisi": "AI analizi geçici olarak kullanılamıyor",
                "benzer_gecmis_senaryo": "N/A",
                "anlik_olay_kontrolu": "N/A"
            }],
            "grafik_verileri": chart_data if chart_data else [],
            "benzer_gecmis_senaryo": "N/A",
            "anlik_olay_kontrolu": "N/A",
            "haber_skoru": news_data.get('sentiment_score', 50)
        }

# ========== PORTFOLIO ANALYSIS FUNCTIONS ==========

def get_daily_briefing(user_portfolio_list: list) -> dict:
    """
    Personalized Portfolio Briefing: Generate AI-powered morning brief.
    Fetches generic market data (SPY, VIX, BTC) and creates personalized summary
    explaining how market conditions impact the users specific stocks.

    Args:
        user_portfolio_list: List of stock symbols in users portfolio (e.g., ['AAPL', 'NVDA', 'TSLA'])

    Returns:
        dict with market_data, ai_briefing, and timestamp
    """
    
    try:
        # Fetch generic market data (SPY, VIX, BTC)
        market_data = {}
        
        # SPY (S&P 500)
        try:
            spy = yf.Ticker("SPY")
            spy_hist = spy.history(period="2d")
            if not spy_hist.empty:
                spy_current = spy_hist['Close'].iloc[-1]
                spy_previous = spy_hist['Close'].iloc[-2]
                spy_change = spy_current - spy_previous
                spy_change_pct = (spy_change / spy_previous) * 100
                market_data["SPY"] = {
                    "current": round(spy_current, 2),
                    "change": round(spy_change, 2),
                    "change_pct": round(spy_change_pct, 2)
                }
        except Exception as e:
            print(f"⚠️ Error fetching SPY: {e}")
            market_data["SPY"] = {"current": 0, "change": 0, "change_pct": 0}
        
        # VIX (Volatility Index)
        try:
            vix = yf.Ticker("^VIX")
            vix_hist = vix.history(period="1d")
            if not vix_hist.empty:
                vix_value = vix_hist['Close'].iloc[-1]
                market_data["VIX"] = round(vix_value, 2)
            else:
                market_data["VIX"] = 0
        except Exception as e:
            print(f"⚠️ Error fetching VIX: {e}")
            market_data["VIX"] = 0
        
        # BTC (Bitcoin)
        try:
            btc = yf.Ticker("BTC-USD")
            btc_hist = btc.history(period="2d")
            if not btc_hist.empty:
                btc_current = btc_hist['Close'].iloc[-1]
                btc_previous = btc_hist['Close'].iloc[-2]
                btc_change = btc_current - btc_previous
                btc_change_pct = (btc_change / btc_previous) * 100
                market_data["BTC"] = {
                    "current": round(btc_current, 2),
                    "change": round(btc_change, 2),
                    "change_pct": round(btc_change_pct, 2)
                }
            else:
                market_data["BTC"] = {"current": 0, "change": 0, "change_pct": 0}
        except Exception as e:
            print(f"⚠️ Error fetching BTC: {e}")
            market_data["BTC"] = {"current": 0, "change": 0, "change_pct": 0}
        
        # Format portfolio list for prompt
        if user_portfolio_list and len(user_portfolio_list) > 0:
            portfolio_str = ", ".join([str(s).upper() for s in user_portfolio_list])
        else:
            portfolio_str = "No stocks in portfolio"
        
        # Build market overview string
        market_overview = f"""MARKET OVERVIEW:
- SPY (S&P 500): ${market_data.get('SPY', {}).get('current', 0):.2f} ({market_data.get('SPY', {}).get('change_pct', 0):+.2f}%)
- VIX (Volatility Index): {market_data.get('VIX', 0):.2f}
- BTC (Bitcoin): ${market_data.get('BTC', {}).get('current', 0):.2f} ({market_data.get('BTC', {}).get('change_pct', 0):+.2f}%)"""
        
        # Generate AI-powered personalized briefing
        try:
            briefing_prompt = f"""Here is the market overview. The user holds: {portfolio_str}. Write a short morning brief explaining how the general market specifically impacts HIS stocks today.

{market_overview}

USER'S PORTFOLIO: {portfolio_str}

Instructions:
- Write a concise morning brief (2-3 paragraphs, max 200 words)
- Focus on how SPY, VIX, and BTC movements specifically affect the user's stocks ({portfolio_str})
- Be realistic and specific - mention actual stock symbols
- If portfolio is empty, provide general market commentary
- Use clear, actionable language
- Format: Plain text, ready to send to Telegram/display"""
            
            # Use unified gemini_text function
            result = gemini_text(briefing_prompt)
            
            if result["fallback"] or not result.get("text"):
                print("⚠️ Using fallback data")
                # Fallback: Return basic market summary without AI
                ai_briefing = f"""Piyasa Özeti:
- SPY: ${market_data.get('SPY', {}).get('current', 0):.2f} ({market_data.get('SPY', {}).get('change_pct', 0):+.2f}%)
- VIX: {market_data.get('VIX', 0):.2f}
- BTC: ${market_data.get('BTC', {}).get('current', 0):.2f} ({market_data.get('BTC', {}).get('change_pct', 0):+.2f}%)

Portföy: {portfolio_str}

{FALLBACK_AI_MESSAGE}"""
            else:
                ai_briefing = result["text"]
            
            return {
                "success": True,
                "market_data": market_data,
                "portfolio_symbols": user_portfolio_list,
                "ai_briefing": ai_briefing,
                "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
        except Exception as e:
            # Catch ALL exceptions to prevent crashes
            print("⚠️ Using fallback data")
            return {
                "success": False,
                "market_data": market_data,
                "portfolio_symbols": user_portfolio_list,
                "ai_briefing": FALLBACK_AI_MESSAGE,
                "error": "API error",
                "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
    except Exception as e:
        print(f"❌ Error in get_daily_briefing: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "market_data": {},
            "portfolio_symbols": user_portfolio_list if 'user_portfolio_list' in locals() else [],
            "ai_briefing": "Error generating briefing",
            "error": str(e),
            "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        }

def compute_portfolio_features(portfolio_data: list, sorted_by_weight: list, risk: dict, news: list, portfolio_summary: dict) -> dict:
    """
    Compute deterministic feature vector for portfolio analysis.
    Used for similarity search and recommendation generation.
    """
    try:
        # Top 3 weight percentage
        top3_weight_pct = sum(item["weight_percent"] for item in sorted_by_weight[:3]) if len(sorted_by_weight) >= 3 else 0
        
        # Concentration score (0-100, higher = more concentrated)
        concentration_score = min(100, top3_weight_pct * 1.2)  # Scale to 0-100
        
        # Average RSI
        if portfolio_data:
            avg_rsi = sum(item.get("rsi", 50) for item in portfolio_data) / len(portfolio_data)
        else:
            avg_rsi = 50
        
        # Average volatility level (LOW=0, MED=1, HIGH=2)
        vol_levels = {"LOW": 0, "MED": 1, "HIGH": 2}
        avg_vol_level = 0
        if portfolio_data:
            vol_sum = 0
            for item in portfolio_data:
                # Determine vol level for each holding
                weight = item.get("weight_percent", 0)
                pnl = abs(item.get("pnl_percent", 0))
                rsi = item.get("rsi", 50)
                vol = 0
                if weight >= 30 or pnl >= 20:
                    vol = 2
                elif weight >= 15 or pnl >= 10 or (rsi >= 70 or rsi <= 30):
                    vol = 1
                vol_sum += vol
            avg_vol_level = vol_sum / len(portfolio_data)
        
        # Bearish news count
        bearish_count = 0
        avg_news_score = 0
        if news:
            bearish_count = sum(1 for item in news if item.get("impact", "").lower() in ["negative", "bearish", "bear"])
            scores = [item.get("importance_score", 0) for item in news if item.get("importance_score")]
            avg_news_score = sum(scores) / len(scores) if scores else 0
        
        # PnL dispersion (best - worst)
        if portfolio_data:
            pnls = [item.get("pnl_percent", 0) for item in portfolio_data]
            pnl_dispersion = max(pnls) - min(pnls) if pnls else 0
        else:
            pnl_dispersion = 0
        
        # Portfolio return recent (use total_pnl_percent)
        portfolio_return_recent = portfolio_summary.get("total_pnl_percent", 0)
        
        return {
            "top3_weight_pct": round(top3_weight_pct, 2),
            "concentration_score": round(concentration_score, 2),
            "avg_rsi": round(avg_rsi, 2),
            "avg_vol_level": round(avg_vol_level, 2),
            "bearish_news_count": bearish_count,
            "avg_news_score": round(avg_news_score, 2),
            "pnl_dispersion": round(pnl_dispersion, 2),
            "portfolio_return_recent": round(portfolio_return_recent, 2)
        }
    except Exception as e:
        print(f"⚠️ Error computing portfolio features: {e}")
        return {}


def generate_portfolio_recommendation(features: dict, risk: dict, similar_cases: list) -> dict:
    """
    Generate deterministic BUY/SELL/HOLD recommendation based on features and similar cases.
    Returns recommendation object with action, confidence, and reasoning.
    """
    try:
        # Initialize recommendation
        action = "HOLD"
        confidence = 50
        horizon_days = 7
        why_tr = []
        if_then_tr = []
        
        # Extract key metrics
        concentration_score = features.get("concentration_score", 50)
        top3_weight = features.get("top3_weight_pct", 0)
        avg_rsi = features.get("avg_rsi", 50)
        avg_vol_level = features.get("avg_vol_level", 1)
        bearish_news_count = features.get("bearish_news_count", 0)
        avg_news_score = features.get("avg_news_score", 0)
        pnl_dispersion = features.get("pnl_dispersion", 0)
        portfolio_return = features.get("portfolio_return_recent", 0)
        
        # Base confidence adjustments
        confidence_adjustments = []
        
        # 1. Concentration risk (high concentration -> reduce BUY confidence, bias to HOLD/REDUCE)
        if top3_weight >= 70:
            confidence_adjustments.append(-20)
            why_tr.append(f"Yüksek konsantrasyon riski (Top 3: %{top3_weight:.1f}) - Tek hisse riski yüksek")
            if_then_tr.append("Eğer konsantrasyon %70'in üzerindeyse, kademeli dengeleme düşün")
            action = "HOLD"  # Bias away from BUY
        elif top3_weight >= 50:
            confidence_adjustments.append(-10)
            why_tr.append(f"Orta konsantrasyon (Top 3: %{top3_weight:.1f})")
        
        # 2. RSI momentum proxy
        if avg_rsi >= 70:
            confidence_adjustments.append(-15)
            why_tr.append(f"Ortalama RSI aşırı alım bölgesinde ({avg_rsi:.1f}) - Düzeltme riski var")
            if_then_tr.append("Eğer RSI 70'in üzerindeyse, kısa vadede düzeltme olasılığı yüksek")
            if action == "BUY":
                action = "HOLD"
        elif avg_rsi <= 30:
            confidence_adjustments.append(+15)
            why_tr.append(f"Ortalama RSI aşırı satım bölgesinde ({avg_rsi:.1f}) - Alım fırsatı olabilir")
            if_then_tr.append("Eğer RSI 30'un altındaysa, toparlanma potansiyeli var")
            if action == "HOLD":
                action = "BUY"
        
        # 3. Volatility level
        if avg_vol_level >= 1.5:
            confidence_adjustments.append(-10)
            why_tr.append("Yüksek volatilite seviyesi - Risk yönetimi kritik")
            if_then_tr.append("Eğer volatilite yüksekse, pozisyon boyutlarını küçült")
        elif avg_vol_level <= 0.5:
            confidence_adjustments.append(+5)
            why_tr.append("Düşük volatilite - Stabil portföy")
        
        # 4. Bearish news impact (high bearish news -> reduce BUY confidence)
        if bearish_news_count >= 3:
            confidence_adjustments.append(-20)
            why_tr.append(f"{bearish_news_count} adet olumsuz haber - Piyasa riski yüksek")
            if_then_tr.append("Eğer olumsuz haber sayısı 3'ten fazlaysa, yeni alımları ertele")
            if action == "BUY":
                action = "HOLD"
        elif bearish_news_count >= 1:
            confidence_adjustments.append(-5)
            why_tr.append(f"{bearish_news_count} adet olumsuz haber tespit edildi")
        
        # 5. Portfolio return momentum
        if portfolio_return >= 10:
            confidence_adjustments.append(+10)
            why_tr.append(f"Portföy performansı güçlü (%{portfolio_return:.1f})")
            if action == "HOLD" and concentration_score < 60:
                action = "BUY"
        elif portfolio_return <= -10:
            confidence_adjustments.append(-15)
            why_tr.append(f"Portföy performansı zayıf (%{portfolio_return:.1f}) - Zarar kontrolü gerekli")
            if_then_tr.append("Eğer portföy %10'dan fazla zarardaysa, stop-loss planını gözden geçir")
            if action == "BUY":
                action = "HOLD"
        
        # 6. PnL dispersion (high dispersion = mixed signals)
        if pnl_dispersion >= 30:
            confidence_adjustments.append(-5)
            why_tr.append("Yüksek PnL dağılımı - Pozisyonlar farklı performans gösteriyor")
        
        # Calculate final confidence
        base_confidence = 50
        for adj in confidence_adjustments:
            base_confidence += adj
        
        confidence = max(0, min(100, base_confidence))
        
        # Adjust action based on confidence
        # IMPORTANT: Use only BUY/HOLD/REDUCE (never SELL)
        if confidence >= 65 and action != "REDUCE":
            action = "BUY"
            horizon_days = 7
        elif confidence <= 35:
            action = "REDUCE"  # Changed from SELL to REDUCE
            horizon_days = 3
        else:
            action = "HOLD"
            horizon_days = 7
        
        # Add default if-then if empty
        if not if_then_tr:
            if_then_tr.append("Eğer portföy hedeflerinle uyumluysa, mevcut pozisyonları koru")
            if_then_tr.append("Eğer risk toleransını aşıyorsa, pozisyon boyutlarını gözden geçir")
        
        # Process similar cases for history-based stats
        based_on_history = {
            "similar_cases": len(similar_cases),
            "avg_return_3d": None,
            "avg_return_7d": None,
            "win_rate_3d": None,
            "win_rate_7d": None,
            "note_tr": "Yeterli geçmiş veri yok"
        }
        
        if similar_cases:
            returns_3d = []
            returns_7d = []
            wins_3d = 0
            wins_7d = 0
            
            for case in similar_cases:
                outcomes = case.get("outcomes", {})
                if 3 in outcomes:
                    ret_3d = outcomes[3].get("return_pct")
                    if ret_3d is not None:
                        returns_3d.append(ret_3d)
                        if ret_3d > 0:
                            wins_3d += 1
                if 7 in outcomes:
                    ret_7d = outcomes[7].get("return_pct")
                    if ret_7d is not None:
                        returns_7d.append(ret_7d)
                        if ret_7d > 0:
                            wins_7d += 1
            
            if returns_3d:
                based_on_history["avg_return_3d"] = round(sum(returns_3d) / len(returns_3d), 2)
                based_on_history["win_rate_3d"] = round((wins_3d / len(returns_3d)) * 100, 1)
            
            if returns_7d:
                based_on_history["avg_return_7d"] = round(sum(returns_7d) / len(returns_7d), 2)
                based_on_history["win_rate_7d"] = round((wins_7d / len(returns_7d)) * 100, 1)
            
            if based_on_history["avg_return_3d"] is not None or based_on_history["avg_return_7d"] is not None:
                based_on_history["note_tr"] = f"Benzer geçmiş durumlarda {len(similar_cases)} analiz bulundu. Ortalama getiri: 3gün=%{based_on_history.get('avg_return_3d', 'N/A')}, 7gün=%{based_on_history.get('avg_return_7d', 'N/A')}. Kazanma oranı: 3gün=%{based_on_history.get('win_rate_3d', 'N/A')}, 7gün=%{based_on_history.get('win_rate_7d', 'N/A')} (geçmiş performans geleceği garanti etmez)."
        
        return {
            "action": action,
            "confidence": confidence,
            "horizon_days": horizon_days,
            "why_tr": why_tr[:5],  # Limit to 5 bullets
            "if_then_tr": if_then_tr[:4],  # Limit to 4 conditionals
            "based_on_history": based_on_history
        }
        
    except Exception as e:
        print(f"⚠️ Error generating recommendation: {e}")
        import traceback
        traceback.print_exc()
        return {
            "action": "HOLD",
            "confidence": 50,
            "horizon_days": 7,
            "why_tr": ["Analiz sırasında hata oluştu"],
            "if_then_tr": ["Veri eksikliği nedeniyle genel tavsiye: mevcut pozisyonları koru"],
            "based_on_history": {"similar_cases": 0, "note_tr": "Veri yetersiz"}
        }


def analyze_portfolio(portfolio: list, use_llm: bool = False, force: bool = False, detail_level: str = "detailed") -> dict:
    """
    Analyze entire portfolio with Quick (deterministic) or Deep (LLM) mode.
    
    Args:
        portfolio: List of portfolio items with symbol, avg_cost, quantity
        use_llm: False = Quick mode (no LLM), True = Deep mode (single LLM call, daily cache)
        force: True = Force new LLM call (ignore cache), False = Use cache if available
        detail_level: "basic" = Basic output, "detailed" = Enhanced output with scenarios (only for quick mode)
    
    Returns:
        dict: Portfolio analysis result
    """
    try:
        if not portfolio:
            result = {"success": False, "message": "Portfolio is empty"}
            return _json_safe(result)
        
        # ========================================================================
        # STEP 1: Fetch portfolio data (always needed for both modes)
        # ========================================================================
        portfolio_data = []
        total_value = 0
        total_cost = 0
        
        for item in portfolio:
            symbol = item["symbol"]
            avg_cost = item["avg_cost"]
            quantity = item["quantity"]
            
            try:
                # Get current price and analysis
                tech = get_technical_metrics(symbol)
                current_price = tech.get("fiyat", 0)
                current_value = current_price * quantity
                cost_basis = avg_cost * quantity
                pnl = current_value - cost_basis
                pnl_percent = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
                
                # Get RSI
                rsi = tech.get("rsi", 50)
                
                portfolio_data.append({
                    "symbol": symbol,
                    "quantity": quantity,
                    "avg_cost": avg_cost,
                    "current_price": current_price,
                    "current_value": current_value,
                    "cost_basis": cost_basis,
                    "pnl": pnl,
                    "pnl_percent": pnl_percent,
                    "rsi": rsi,
                    "weight_percent": 0  # Will be calculated below
                })
                
                total_value += current_value
                total_cost += cost_basis
            except Exception as e:
                print(f"⚠️ Error fetching data for {symbol}: {e}")
                continue
        
        if not portfolio_data:
            result = {"success": False, "message": "Failed to fetch portfolio data"}
            return _json_safe(result)
        
        # Calculate allocation percentages
        for item in portfolio_data:
            item["weight_percent"] = (item["current_value"] / total_value * 100) if total_value > 0 else 0
        
        total_pnl = total_value - total_cost
        total_pnl_percent = ((total_pnl / total_cost * 100) if total_cost > 0 else 0)
        holdings_count = len(portfolio_data)
        
        # Sort by weight for largest positions
        sorted_by_weight = sorted(portfolio_data, key=lambda x: x["weight_percent"], reverse=True)
        largest_positions = [
            {
                "symbol": item["symbol"],
                "weight_percent": round(item["weight_percent"], 1),
                "pnl_percent": round(item["pnl_percent"], 1)
            }
            for item in sorted_by_weight[:3]
        ]
        
        # ========================================================================
        # PER-HOLDING ACTIONABLE MENTOR ADVICE: Generate entry zones, stop/tp, sizing
        # ========================================================================
        position_mentor_advice = []
        
        # For EACH holding in the portfolio (iterate all items, no truncation)
        for idx, item in enumerate(portfolio_data):
            symbol = item["symbol"]
            current_price = item["current_price"]
            avg_cost = item["avg_cost"]
            pnl_percent = item["pnl_percent"]
            weight_pct = item["weight_percent"]
            rsi = item.get("rsi", 50)
            
            # Get technical metrics for actionable levels
            try:
                tech = get_technical_metrics(symbol)
                bb_alt = tech.get("bb_alt", 0) or 0
                bb_ust = tech.get("bb_ust", 0) or 0
                trend = tech.get("trend", "SIDEWAYS")
            except Exception:
                bb_alt = 0
                bb_ust = 0
                trend = "SIDEWAYS"
            
            # Determine action recommendation
            action = "HOLD"
            if pnl_percent >= 20 and rsi >= 70:
                action = "REDUCE"  # Take profit on overbought winners
            elif pnl_percent <= -10:
                action = "REDUCE"  # Cut losses
            elif pnl_percent >= 15:
                action = "CONSIDER_REDUCE"  # Consider taking some profit
            elif rsi < 30 and pnl_percent < 5:
                action = "CONSIDER_BUY"  # Oversold, could add
            
            # Calculate entry zone (for new positions or adding)
            entry_zone_low = current_price * 0.95 if current_price > 0 else 0
            entry_zone_high = current_price * 1.02 if current_price > 0 else 0
            if bb_alt > 0:
                entry_zone_low = min(entry_zone_low, bb_alt * 0.98)
            
            # Calculate stop loss
            stop_loss = 0
            if bb_alt > 0:
                stop_loss = bb_alt * 0.97  # 3% below lower Bollinger Band
            elif current_price > 0:
                stop_loss = current_price * 0.92  # 8% below current price
            
            # Calculate take profit levels
            take_profit_1 = 0
            take_profit_2 = 0
            if bb_ust > 0:
                take_profit_1 = bb_ust * 0.98  # Near upper Bollinger Band
                take_profit_2 = bb_ust * 1.05  # Extended target
            elif current_price > 0:
                take_profit_1 = current_price * 1.08  # 8% gain
                take_profit_2 = current_price * 1.15  # 15% gain
            
            # Calculate position sizing recommendation (% of portfolio)
            position_sizing_pct = 0
            if action == "CONSIDER_BUY":
                # Conservative sizing: 5-10% max per position
                position_sizing_pct = min(10, max(5, 100 / holdings_count))
            elif action == "REDUCE":
                # Reduce by 20-30% of current position
                position_sizing_pct = -25
            elif action == "CONSIDER_REDUCE":
                # Reduce by 10-15% of current position
                position_sizing_pct = -15
            
            # Invalidation condition (when to change the recommendation)
            invalidation = ""
            if action == "REDUCE":
                invalidation = f"Eğer {symbol} fiyatı ${stop_loss:.2f}'nin altına düşerse veya RSI 30'un altına inerse, pozisyonu tamamen kapatmayı düşünün."
            elif action == "CONSIDER_BUY":
                invalidation = f"Eğer {symbol} fiyatı ${entry_zone_high:.2f}'nin üzerine çıkarsa veya RSI 50'nin üzerine çıkarsa, alımı erteleyin."
            else:
                invalidation = f"Eğer {symbol} fiyatı ${stop_loss:.2f}'nin altına düşerse veya RSI 70'in üzerine çıkarsa, pozisyonu yeniden değerlendirin."
            
            # Wait/no-action condition
            wait_condition = ""
            if action == "HOLD":
                wait_condition = "Net bir sinyal oluşana kadar mevcut pozisyonu koruyun."
            elif action == "CONSIDER_REDUCE":
                wait_condition = "Kâr kilitleme için uygun bir fiyat seviyesi bekleyin."
            elif action == "CONSIDER_BUY":
                wait_condition = "Daha iyi bir giriş fırsatı için fiyatın düşmesini bekleyin."
            
            position_mentor_advice.append({
                "symbol": symbol,
                "action": action,
                "entry_zone": {
                    "low": round(entry_zone_low, 2),
                    "high": round(entry_zone_high, 2),
                    "current_price": round(current_price, 2)
                },
                "stop_loss": round(stop_loss, 2),
                "take_profit": {
                    "level_1": round(take_profit_1, 2),
                    "level_2": round(take_profit_2, 2)
                },
                "position_sizing_pct": position_sizing_pct,
                "invalidation": invalidation,
                "wait_condition": wait_condition,
                "reasoning": f"RSI: {rsi:.1f}, PnL: {pnl_percent:.1f}%, Ağırlık: {weight_pct:.1f}%"
            })
        
        # ========================================================================
        # PER-HOLDING MINI-SUMMARY: Generate position_notes_tr for ALL holdings (QUICK mode)
        # ========================================================================
        position_notes_tr = []
        
        # For EACH holding in the portfolio (iterate all items, no truncation)
        for item in portfolio_data:
            symbol = item["symbol"]
            weight_pct = round(item["weight_percent"], 1)
            pnl_percent = round(item["pnl_percent"], 1)
            rsi = round(item["rsi"], 1) if item.get("rsi") is not None else None
            
            # Determine volatility_level (LOW/MED/HIGH) based on deterministic thresholds
            volatility_level = "LOW"
            if weight_pct >= 30 or abs(pnl_percent) >= 20:
                volatility_level = "HIGH"
            elif weight_pct >= 15 or abs(pnl_percent) >= 10 or (rsi is not None and (rsi >= 70 or rsi <= 30)):
                volatility_level = "MED"
            
            # Generate deterministic Turkish note (1-2 sentences)
            note_parts = []
            
            # Rule 1: If weight_pct >= 25: mention concentration risk
            if weight_pct >= 25:
                note_parts.append(f"{symbol} portföyün %{weight_pct}'ini oluşturuyor - Konsantrasyon riski yüksek")
            
            # Rule 2: If pnl_percent >= 15: mention "kârı kilitleme / kısmi realizasyon"
            if pnl_percent >= 15:
                note_parts.append(f"%{pnl_percent:.1f} karda - Kârı kilitleme / kısmi realizasyon düşünün")
            
            # Rule 3: If pnl_percent <= -10: mention "zarar kontrolü / stop-loss planı"
            if pnl_percent <= -10:
                note_parts.append(f"%{abs(pnl_percent):.1f} zararda - Zarar kontrolü / stop-loss planı yapın")
            
            # Rule 4: If rsi >= 70: mention "aşırı alım" caution
            if rsi is not None and rsi >= 70:
                note_parts.append(f"Aşırı alım bölgesinde (RSI {rsi:.1f}) - Dikkatli olun")
            
            # Rule 5: If rsi <= 30: mention "aşırı satım" caution
            if rsi is not None and rsi <= 30:
                note_parts.append(f"Aşırı satım bölgesinde (RSI {rsi:.1f}) - Alım fırsatı olabilir")
            
            # Rule 6: If none triggered: give neutral maintenance note
            if not note_parts:
                note_parts.append("Düzenli takip, ağırlık ve risk uyumu")
            
            # Combine into 1-2 sentence note
            note_tr = ". ".join(note_parts) + "."
            
            position_notes_tr.append({
                "symbol": symbol,
                "weight_pct": weight_pct,
                "pnl_percent": pnl_percent,
                "rsi": rsi if rsi is not None else None,
                "volatility_level": volatility_level,
                "note_tr": note_tr
            })
        
        # ========================================================================
        # STEP 2: Calculate risk metrics (deterministic, no LLM)
        # ========================================================================
        # Concentration risk: Check if top 3 positions > 70% of portfolio
        top3_weight = sum(item["weight_percent"] for item in sorted_by_weight[:3])
        concentration_risk = {
            "flag": top3_weight > 70,
            "note_tr": f"Top 3 pozisyon portföyün %{top3_weight:.1f}'ini oluşturuyor. {'Yüksek konsantrasyon riski var.' if top3_weight > 70 else 'Konsantrasyon seviyesi kabul edilebilir.'}"
        }
        
        # Volatility risk: Calculate weighted average RSI
        weighted_rsi = sum(item["rsi"] * item["weight_percent"] / 100 for item in portfolio_data)
        volatility_risk = {
            "flag": weighted_rsi > 70 or weighted_rsi < 30,
            "note_tr": f"Ortalama RSI: {weighted_rsi:.1f}. {'Aşırı alım bölgesinde - düzeltme riski yüksek.' if weighted_rsi > 70 else 'Aşırı satım bölgesinde - toparlanma potansiyeli var.' if weighted_rsi < 30 else 'RSI seviyesi normal aralıkta.'}"
        }
        
        # ========================================================================
        # STEP 3: News risk summary (deterministic, using local analyzer)
        # ========================================================================
        all_news_items = []
        for item in portfolio:
            try:
                news = get_news(item["symbol"], use_llm=0)  # No LLM for news in Quick mode
                if news and news.get("ai_interpreted"):
                    for news_item in news["ai_interpreted"][:2]:  # Top 2 per stock
                        all_news_items.append(news_item)
            except:
                continue
        
        # Sort by importance score
        all_news_items.sort(key=lambda x: x.get("importance_score", 0), reverse=True)
        top_events = [
            {
                "title": item.get("title", "N/A"),
                "importance_score": item.get("importance_score", 0),
                "impact": item.get("impact", "neutral")
            }
            for item in all_news_items[:5]
        ]
        
        # Calculate overall news score (average of top 3)
        overall_score = int(sum(event["importance_score"] for event in top_events[:3]) / 3) if top_events else 0
        
        news_risk_summary = {
            "top_events": top_events,
            "overall_score": overall_score,
            "note_tr": f"Portföy için {len(top_events)} önemli haber tespit edildi. Ortalama önem skoru: {overall_score}/100."
        }
        
        # ========================================================================
        # STEP 4: QUICK MODE (no LLM) - Always generated
        # ========================================================================
        as_of = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        
        # Generate action bullets (deterministic) - Enhanced to cover multiple holdings
        action_bullets_tr = []
        
        # 1. Top 3 concentration summary
        if len(sorted_by_weight) >= 3:
            top3_symbols = [item["symbol"] for item in sorted_by_weight[:3]]
            top3_weights = [item["weight_percent"] for item in sorted_by_weight[:3]]
            top3_total = sum(top3_weights)
            action_bullets_tr.append(f"En büyük 3 pozisyon ({', '.join(top3_symbols)}): Toplam ağırlık %{top3_total:.1f} - {'Yüksek konsantrasyon riski var' if top3_total >= 70 else 'Konsantrasyon seviyesi kabul edilebilir'}")
        
        # 2. Largest weight holding (if >= 30%)
        if len(sorted_by_weight) > 0:
            largest = sorted_by_weight[0]
            if largest["weight_percent"] >= 30:
                action_bullets_tr.append(f"{largest['symbol']} portföyün %{largest['weight_percent']:.1f}'ini oluşturuyor - Tek hisse riski nedeniyle ağırlığı izleyin")
        
        # 3. Worst PnL holding (if <= -10%)
        worst_pnl = min(portfolio_data, key=lambda x: x["pnl_percent"])
        if worst_pnl["pnl_percent"] <= -10:
            action_bullets_tr.append(f"{worst_pnl['symbol']}: %{worst_pnl['pnl_percent']:.1f} zararda - Stop-loss seviyesini kontrol edin ve pozisyonu gözden geçirin")
        
        # 4. Best PnL holding (if >= +10%)
        best_pnl = max(portfolio_data, key=lambda x: x["pnl_percent"])
        if best_pnl["pnl_percent"] >= 10:
            action_bullets_tr.append(f"{best_pnl['symbol']}: %{best_pnl['pnl_percent']:.1f} karda - Kısmi kar realizasyonu düşünün")
        
        # 5. RSI warnings for top positions (limit to avoid too many bullets)
        rsi_warnings = []
        for item in sorted_by_weight[:3]:
            if item["rsi"] > 70:
                rsi_warnings.append(f"{item['symbol']} aşırı alım bölgesinde (RSI {item['rsi']:.1f})")
            elif item["rsi"] < 30:
                rsi_warnings.append(f"{item['symbol']} aşırı satım bölgesinde (RSI {item['rsi']:.1f})")
        if rsi_warnings:
            action_bullets_tr.append("RSI Uyarıları: " + ", ".join(rsi_warnings))
        
        # 6. Overall risk/discipline
        if concentration_risk["flag"]:
            action_bullets_tr.append("Yüksek konsantrasyon riski: Portföyü çeşitlendirmeyi düşünün")
        if volatility_risk["flag"]:
            action_bullets_tr.append("Volatilite riski: Piyasa koşullarını yakından takip edin")
        
        # 7. General discipline reminder
        action_bullets_tr.append("Portföy performansını düzenli olarak gözden geçirin ve risk yönetimi kurallarınıza uyun")
        
        # Limit to max 10 bullets
        action_bullets_tr = action_bullets_tr[:10]
        
        # ========================================================================
        # PER-HOLDING ANALYSIS: Generate position_risk_rows_tr for ALL holdings (QUICK mode always)
        # ========================================================================
        position_risk_rows_tr = []
        
        if not use_llm:  # QUICK mode only
            # Process ALL holdings in descending weight order
            for item in sorted_by_weight:
                symbol = item["symbol"]
                weight_pct = round(item["weight_percent"], 1)
                pnl_pct = round(item["pnl_percent"], 1)
                rsi = round(item["rsi"], 1) if item.get("rsi") is not None else None
                
                # Determine volatility level
                vol_level = "LOW"
                if weight_pct >= 30 or abs(pnl_pct) >= 20:
                    vol_level = "HIGH"
                elif weight_pct >= 15 or abs(pnl_pct) >= 10 or (rsi and (rsi > 70 or rsi < 30)):
                    vol_level = "MED"
                
                # Generate deterministic Turkish note
                note_parts = []
                
                # Concentration risk
                if weight_pct >= 30:
                    note_parts.append(f"{symbol} portföyün %{weight_pct}'ini oluşturuyor")
                    note_parts.append("Tek hisse riski nedeniyle ağırlığı izleyin")
                
                # PnL-based notes
                if pnl_pct <= -10:
                    note_parts.append(f"%{abs(pnl_pct):.1f} zararda - Stop-loss seviyesini kontrol edin")
                elif pnl_pct >= 20:
                    note_parts.append(f"%{pnl_pct:.1f} karda - Kısmi kar realizasyonu düşünün")
                
                # RSI-based notes
                if rsi is not None:
                    if rsi >= 70:
                        note_parts.append("Aşırı alım bölgesinde (RSI yüksek) - Dikkatli olun")
                    elif rsi <= 30:
                        note_parts.append("Aşırı satım bölgesinde (RSI düşük) - Alım fırsatı olabilir")
                
                # Volatility note
                if vol_level == "HIGH":
                    note_parts.append("Volatilite yüksek")
                
                # Default note if nothing specific
                if not note_parts:
                    note_parts.append(f"Portföy ağırlığı %{weight_pct} - Durumu izleyin")
                
                note_tr = ". ".join(note_parts) + "."
                
                position_risk_rows_tr.append({
                    "symbol": symbol,
                    "weight_pct": weight_pct,
                    "pnl_pct": pnl_pct,
                    "rsi": rsi if rsi is not None else "n/a",
                    "vol_level": vol_level,
                    "note_tr": note_tr
                })
        
        # ========================================================================
        # ENHANCED QUICK MODE: Scenarios (detailed only)
        # ========================================================================
        scenarios = []
        position_risk_rows = []  # Keep for backward compatibility (detailed mode)
        
        if detail_level == "detailed" and not use_llm:
            # Calculate scenario analysis for top 3 positions
            for item in sorted_by_weight[:3]:
                symbol = item["symbol"]
                weight_pct = item["weight_percent"]
                current_value = item["current_value"]
                
                # Scenario 1: -5% shock
                shock_5pct = -0.05
                portfolio_impact_usd_5 = current_value * shock_5pct
                portfolio_impact_pct_5 = (portfolio_impact_usd_5 / total_value * 100) if total_value > 0 else 0
                
                scenarios.append({
                    "symbol": symbol,
                    "shock": shock_5pct,
                    "portfolio_impact_usd": round(portfolio_impact_usd_5, 2),
                    "portfolio_impact_pct": round(portfolio_impact_pct_5, 2)
                })
                
                # Scenario 2: -10% shock
                shock_10pct = -0.10
                portfolio_impact_usd_10 = current_value * shock_10pct
                portfolio_impact_pct_10 = (portfolio_impact_usd_10 / total_value * 100) if total_value > 0 else 0
                
                scenarios.append({
                    "symbol": symbol,
                    "shock": shock_10pct,
                    "portfolio_impact_usd": round(portfolio_impact_usd_10, 2),
                    "portfolio_impact_pct": round(portfolio_impact_pct_10, 2)
                })
            
            # Build position risk rows (for backward compatibility, detailed mode)
            for item in portfolio_data:
                risk_level = "low"
                if item["rsi"] > 70 or item["rsi"] < 30:
                    risk_level = "medium"
                if item["pnl_percent"] < -15 or item["weight_percent"] > 40:
                    risk_level = "high"
                
                position_risk_rows.append({
                    "symbol": item["symbol"],
                    "weight_percent": round(item["weight_percent"], 1),
                    "pnl_percent": round(item["pnl_percent"], 1),
                    "rsi": round(item["rsi"], 1),
                    "risk_level": risk_level
                })
        
        # Build base portfolio summary (used in all modes)
        portfolio_summary = {
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_percent": round(total_pnl_percent, 2),
            "holdings_count": holdings_count
        }
        
        # Build holdings array (per-holding breakdown)
        holdings = [
            {
                "symbol": item["symbol"],
                "quantity": item["quantity"],
                "avg_cost": item["avg_cost"],
                "current_price": item["current_price"],
                "current_value": item["current_value"],
                "cost_basis": item["cost_basis"],
                "pnl": item["pnl"],
                "pnl_percent": item["pnl_percent"],
                "weight_percent": item["weight_percent"],
                "rsi": item["rsi"]
            }
            for item in portfolio_data
        ]
        
        # Build risk object
        risk = {
            "concentration": concentration_risk,
            "volatility": volatility_risk,
            "news": news_risk_summary
        }
        
        # Build quick result with consistent structure
        quick_result = {
            "success": True,
            "mode": "quick",
            "detail_level": detail_level,
            "as_of": as_of,
            "portfolio": portfolio_summary,
            "holdings": holdings,
            "risk": risk,
            "news": top_events[:5] if top_events else [],
            "action_bullets_tr": action_bullets_tr,
            "position_risk_rows_tr": position_risk_rows_tr,  # Always included for QUICK mode (ALL holdings)
            "position_notes_tr": position_notes_tr,  # NEW: Mini-summary for EVERY holding
            "position_mentor_advice": position_mentor_advice,  # NEW: Actionable entry/exit zones, stop/tp, sizing
            "deep_summary_tr": None,  # Only in DEEP mode
            "meta": {
                "llm_used": 0,
                "cache_hit": 0,
                "force": 1 if force else 0
            }
        }
        
        # Add detailed enhancements only if detail_level == "detailed"
        if detail_level == "detailed":
            quick_result["scenarios"] = scenarios
            quick_result["position_risk_rows"] = position_risk_rows  # Backward compatibility
        else:
            quick_result["scenarios"] = []
            quick_result["position_risk_rows"] = []
        
        # ========================================================================
        # STEP 5: MENTOR SYSTEM - Compute features and recommendation (QUICK mode)
        # ========================================================================
        features = {}
        recommendation = {}
        
        if not use_llm:  # Only for QUICK mode
            try:
                # Compute feature vector
                features = compute_portfolio_features(
                    portfolio_data, sorted_by_weight, risk, top_events, portfolio_summary
                )
                
                # Find similar cases
                similar_cases = []
                if features:
                    try:
                        similar_cases = find_similar_analyses(features, k=5, limit_recent=100)
                    except Exception as sim_err:
                        print(f"⚠️ Error finding similar analyses: {sim_err}")
                
                # Generate recommendation
                recommendation = generate_portfolio_recommendation(features, risk, similar_cases)
                
                # Add to quick_result
                quick_result["recommendation"] = recommendation
                
                # ========================================================================
                # NEW STANDARD FIELDS: mentor, quick_actions, portfolio_commentary_tr, stress_test, positions
                # ========================================================================
                
                # 1. MENTOR object (from recommendation, standardized format)
                mentor_action = recommendation.get("action", "HOLD")
                # Ensure action is BUY/HOLD/REDUCE (never SELL)
                if mentor_action == "SELL":
                    mentor_action = "REDUCE"
                
                # Calculate allocation_pct based on action and concentration
                top3_weight_pct = features.get("top3_weight_pct", 0)
                max_single_weight = sorted_by_weight[0]["weight_percent"] if sorted_by_weight else 0
                allocation_pct = 0
                if mentor_action == "REDUCE":
                    # If high concentration, suggest reducing by 20-30%
                    if top3_weight_pct > 70 or max_single_weight > 30:
                        allocation_pct = 25
                    elif top3_weight_pct > 50:
                        allocation_pct = 20
                    elif top3_weight_pct > 40:
                        allocation_pct = 15
                    else:
                        allocation_pct = 10  # Default minimum for REDUCE
                elif mentor_action == "BUY":
                    # Conservative buy allocation
                    allocation_pct = 10
                
                # Generate mentor title and main goal (aligned with action)
                if mentor_action == "REDUCE":
                    mentor_title = "Risk düşür, kârı kilitle"
                    main_goal = "Konsantrasyon riskini azaltmak ve kâr pozisyonlarında kısmi realizasyon yapmak"
                elif mentor_action == "BUY":
                    mentor_title = "Fırsat değerlendir, kademeli ekle"
                    main_goal = "Uygun fırsatlarda kademeli pozisyon artırımı yapmak"
                else:
                    mentor_title = "Mevcut pozisyonları koru, izle"
                    main_goal = "Mevcut portföy yapısını koruyarak düzenli takip yapmak"
                
                # Filter why_tr and plan_tr to align with mentor action (no contradictions)
                why_tr_filtered = []
                plan_tr_filtered = []
                
                for why_item in recommendation.get("why_tr", [])[:5]:
                    why_lower = why_item.lower() if isinstance(why_item, str) else ""
                    # Remove contradictory messages
                    if mentor_action == "REDUCE":
                        # Remove "koru", "izle" messages that contradict REDUCE
                        if "koru" not in why_lower and "izle" not in why_lower or "konsantrasyon" in why_lower or "risk" in why_lower:
                            why_tr_filtered.append(why_item)
                    elif mentor_action == "BUY":
                        # Keep buy-related or neutral messages
                        if "azalt" not in why_lower or "risk" in why_lower:
                            why_tr_filtered.append(why_item)
                    else:  # HOLD
                        # Keep neutral or hold-related messages
                        why_tr_filtered.append(why_item)
                
                for plan_item in recommendation.get("if_then_tr", [])[:5]:
                    plan_lower = plan_item.lower() if isinstance(plan_item, str) else ""
                    # Align with mentor action
                    if mentor_action == "REDUCE":
                        # Keep reduce-related or risk management messages
                        if "azalt" in plan_lower or "dengele" in plan_lower or "realizasyon" in plan_lower or "risk" in plan_lower:
                            plan_tr_filtered.append(plan_item)
                    elif mentor_action == "BUY":
                        # Keep buy-related or opportunity messages
                        if "ekle" in plan_lower or "fırsat" in plan_lower or "artır" in plan_lower:
                            plan_tr_filtered.append(plan_item)
                    else:  # HOLD
                        # Keep hold-related or neutral messages
                        if "koru" in plan_lower or "izle" in plan_lower or "takip" in plan_lower:
                            plan_tr_filtered.append(plan_item)
                
                # Ensure at least 1 item in each list
                if not why_tr_filtered:
                    if mentor_action == "REDUCE":
                        why_tr_filtered = ["Yüksek konsantrasyon riski var"]
                    elif mentor_action == "BUY":
                        why_tr_filtered = ["Fırsat değerlendirme zamanı"]
                    else:
                        why_tr_filtered = ["Portföy dengeli durumda"]
                
                if not plan_tr_filtered:
                    if mentor_action == "REDUCE":
                        plan_tr_filtered = ["Kademeli dengeleme yapın"]
                    elif mentor_action == "BUY":
                        plan_tr_filtered = ["Kademeli pozisyon artırımı yapın"]
                    else:
                        plan_tr_filtered = ["Mevcut pozisyonları izleyin"]
                
                # Generate summary_tr (1 sentence net summary)
                if mentor_action == "REDUCE":
                    summary_tr = f"Konsantrasyon riskini azaltmak ve kâr pozisyonlarında kısmi realizasyon yapmak için {allocation_pct}% oranında pozisyon azaltımı önerilir."
                elif mentor_action == "BUY":
                    summary_tr = f"Uygun fırsatlarda kademeli pozisyon artırımı yapmak için {allocation_pct}% oranında ekleme önerilir."
                else:
                    summary_tr = "Mevcut portföy yapısını koruyarak düzenli takip yapmak önerilir."
                
                # Generate triggers_tr (conditions that would change the decision)
                # Calculate weighted_rsi and bearish_news_count
                weighted_rsi_calc = sum(item["rsi"] * item["weight_percent"] / 100 for item in portfolio_data) if portfolio_data else 50
                bearish_news_count_val = sum(1 for event in top_events if event.get("impact", "").lower() in ["negative", "bearish", "bear"]) if top_events else 0
                
                triggers_tr = []
                if top3_weight_pct > 70:
                    triggers_tr.append(f"Eğer konsantrasyon %{top3_weight_pct:.1f}'den %50'nin altına düşerse, HOLD'a geçilebilir")
                if weighted_rsi_calc > 70:
                    triggers_tr.append(f"Eğer RSI {weighted_rsi_calc:.1f}'den 50'nin altına düşerse, pozisyon artırımı düşünülebilir")
                elif weighted_rsi_calc < 30:
                    triggers_tr.append(f"Eğer RSI {weighted_rsi_calc:.1f}'den 50'nin üzerine çıkarsa, kâr kilitleme düşünülebilir")
                if bearish_news_count_val >= 3:
                    triggers_tr.append(f"Eğer olumsuz haber sayısı {bearish_news_count_val}'ten 1'in altına düşerse, risk azaltılabilir")
                
                # Limit to max 3
                triggers_tr = triggers_tr[:3]
                
                # Generate invalidates_tr (conditions that invalidate the decision)
                invalidates_tr = []
                if mentor_action == "REDUCE":
                    invalidates_tr.append("Eğer portföy %10'dan fazla zarara girerse, REDUCE yerine zarar kontrolü yapılmalı")
                    invalidates_tr.append("Eğer tüm pozisyonlar %5'in altında ağırlığa düşerse, REDUCE kararı geçersiz olur")
                elif mentor_action == "BUY":
                    invalidates_tr.append("Eğer portföy %15'ten fazla zarara girerse, BUY kararı geçersiz olur")
                    invalidates_tr.append("Eğer konsantrasyon %80'in üzerine çıkarsa, BUY yerine HOLD yapılmalı")
                else:  # HOLD
                    invalidates_tr.append("Eğer portföy %20'den fazla zarara girerse, HOLD yerine zarar kontrolü yapılmalı")
                
                # Limit to max 2
                invalidates_tr = invalidates_tr[:2]
                
                # Generate from_history_tr (similar cases from history)
                from_history_tr = []
                if similar_cases:
                    based_on_history = recommendation.get("based_on_history", {})
                    similar_count = based_on_history.get("similar_cases", 0)
                    avg_return_7d = based_on_history.get("avg_return_7d")
                    if similar_count > 0 and avg_return_7d is not None:
                        # Get first similar case for example
                        first_case = similar_cases[0] if similar_cases else None
                        if first_case:
                            case_id = first_case.get("analysis_id", "N/A")
                            from_history_tr.append(f"Benzer durum: analiz_id={case_id} -> 7gün getiri: %{avg_return_7d:.1f} (benzer {similar_count} durum)")
                
                # Limit to max 2
                from_history_tr = from_history_tr[:2]
                
                # Generate reason_types (specific reasons with evidence)
                reason_types = []
                reason_weights = {}
                
                # 1. PROFIT_TAKE: High PnL positions
                best_pnl = max(portfolio_data, key=lambda x: x["pnl_percent"]) if portfolio_data else None
                if best_pnl and best_pnl["pnl_percent"] >= 15:
                    symbol_best = best_pnl["symbol"]
                    pnl_best = best_pnl["pnl_percent"]
                    reason_weights["PROFIT_TAKE"] = min(1.0, (pnl_best - 10) / 20)  # Scale 10-30% to 0-1
                    reason_types.append({
                        "code": "PROFIT_TAKE",
                        "weight": reason_weights["PROFIT_TAKE"],
                        "label_tr": "Kâr Kilitleme",
                        "evidence_tr": f"{symbol_best} %{pnl_best:.1f} kârda; konsantrasyon yüksek." if top3_weight_pct > 50 else f"{symbol_best} %{pnl_best:.1f} kârda."
                    })
                
                # 2. CONCENTRATION: High concentration risk
                if top3_weight_pct > 70:
                    reason_weights["CONCENTRATION"] = min(1.0, (top3_weight_pct - 50) / 30)  # Scale 50-80% to 0-1
                    reason_types.append({
                        "code": "CONCENTRATION",
                        "weight": reason_weights["CONCENTRATION"],
                        "label_tr": "Konsantrasyon",
                        "evidence_tr": f"Top 3 pozisyon portföyün %{top3_weight_pct:.1f}'ini oluşturuyor."
                    })
                elif top3_weight_pct > 50:
                    reason_weights["CONCENTRATION"] = 0.5
                    reason_types.append({
                        "code": "CONCENTRATION",
                        "weight": reason_weights["CONCENTRATION"],
                        "label_tr": "Konsantrasyon",
                        "evidence_tr": f"Top 3 pozisyon portföyün %{top3_weight_pct:.1f}'ini oluşturuyor."
                    })
                
                # 3. VOLATILITY: High volatility
                high_vol_count = sum(1 for item in portfolio_data if item.get("weight_percent", 0) >= 15 or abs(item.get("pnl_percent", 0)) >= 10)
                if weighted_rsi_calc > 70 or weighted_rsi_calc < 30 or high_vol_count >= 2:
                    reason_weights["VOLATILITY"] = 0.6 if (weighted_rsi_calc > 70 or weighted_rsi_calc < 30) else 0.4
                    rsi_desc = "aşırı alım" if weighted_rsi_calc > 70 else "aşırı satım" if weighted_rsi_calc < 30 else "yüksek"
                    reason_types.append({
                        "code": "VOLATILITY",
                        "weight": reason_weights["VOLATILITY"],
                        "label_tr": "Volatilite",
                        "evidence_tr": f"Ortalama RSI {weighted_rsi_calc:.1f} ({rsi_desc} bölgesi); {high_vol_count} pozisyon yüksek volatilite."
                    })
                
                # 4. NEWS_RISK: High news risk
                if bearish_news_count_val >= 3:
                    reason_weights["NEWS_RISK"] = min(1.0, bearish_news_count_val / 5)
                    reason_types.append({
                        "code": "NEWS_RISK",
                        "weight": reason_weights["NEWS_RISK"],
                        "label_tr": "Haber Riski",
                        "evidence_tr": f"{bearish_news_count_val} adet olumsuz haber; ortalama önem skoru {overall_score}/100."
                    })
                elif bearish_news_count_val >= 1 and overall_score >= 70:
                    reason_weights["NEWS_RISK"] = 0.5
                    reason_types.append({
                        "code": "NEWS_RISK",
                        "weight": reason_weights["NEWS_RISK"],
                        "label_tr": "Haber Riski",
                        "evidence_tr": f"{bearish_news_count_val} adet olumsuz haber; yüksek önem skoru."
                    })
                
                # 5. MOMENTUM_WEAK: Weak momentum (if applicable)
                if mentor_action == "REDUCE" and total_pnl_percent < 5 and weighted_rsi_calc < 50:
                    reason_weights["MOMENTUM_WEAK"] = 0.4
                    reason_types.append({
                        "code": "MOMENTUM_WEAK",
                        "weight": reason_weights["MOMENTUM_WEAK"],
                        "label_tr": "Momentum Zayıf",
                        "evidence_tr": f"Portföy momentumu zayıf (RSI {weighted_rsi_calc:.1f}, P/L %{total_pnl_percent:.1f})."
                    })
                
                # 6. DRAWDOWN: Recent drawdown (if applicable)
                if total_pnl_percent < -5:
                    reason_weights["DRAWDOWN"] = min(1.0, abs(total_pnl_percent) / 20)
                    reason_types.append({
                        "code": "DRAWDOWN",
                        "weight": reason_weights["DRAWDOWN"],
                        "label_tr": "Düşüş",
                        "evidence_tr": f"Portföy %{abs(total_pnl_percent):.1f} zararda; zarar kontrolü gerekli."
                    })
                
                # 7. EVENT_RISK: Upcoming events risk (will be added after events are generated)
                # This will be handled after events list is populated
                
                # 8. VALUATION_RICH: Overvalued positions (P/E, fair value check)
                # Simple heuristic: if portfolio has high PnL and high RSI, might be overvalued
                if total_pnl_percent > 20 and weighted_rsi_calc > 70:
                    avg_pnl = sum(item.get("pnl_percent", 0) for item in portfolio_data) / len(portfolio_data) if portfolio_data else 0
                    if avg_pnl > 15:
                        reason_weights["VALUATION_RICH"] = min(1.0, (total_pnl_percent - 15) / 30)
                        reason_types.append({
                            "code": "VALUATION_RICH",
                            "weight": reason_weights["VALUATION_RICH"],
                            "label_tr": "Değerleme Yüksek",
                            "evidence_tr": f"Ortalama P/L %{avg_pnl:.1f}, RSI {weighted_rsi_calc:.1f} (aşırı alım) - değerleme riski."
                        })
                
                # 9. RISK_BUDGET: Risk budget exceeded (concentration + volatility)
                risk_budget_score = (top3_weight_pct / 100) * 0.6 + (min(weighted_rsi_calc, 100 - weighted_rsi_calc) / 50) * 0.4 if weighted_rsi_calc > 50 else (top3_weight_pct / 100) * 0.6 + (weighted_rsi_calc / 50) * 0.4
                if risk_budget_score > 0.75 and (top3_weight_pct > 60 or abs(weighted_rsi_calc - 50) > 25):
                    reason_weights["RISK_BUDGET"] = min(1.0, (risk_budget_score - 0.5) * 2)
                    reason_types.append({
                        "code": "RISK_BUDGET",
                        "weight": reason_weights["RISK_BUDGET"],
                        "label_tr": "Risk Bütçesi Aşıldı",
                        "evidence_tr": f"Konsantrasyon %{top3_weight_pct:.1f}, RSI {weighted_rsi_calc:.1f} - risk bütçesi aşıldı."
                    })
                
                # 10. REBALANCE: Target weight deviation (high concentration suggests rebalancing needed)
                if top3_weight_pct > 65 and mentor_action in ["REDUCE", "HOLD"]:
                    # Ideal target would be more balanced (e.g., top 3 should be < 50%)
                    deviation = top3_weight_pct - 50
                    if deviation > 15:
                        reason_weights["REBALANCE"] = min(1.0, (deviation - 10) / 25)
                        reason_types.append({
                            "code": "REBALANCE",
                            "weight": reason_weights["REBALANCE"],
                            "label_tr": "Yeniden Dengeleme",
                            "evidence_tr": f"Hedef ağırlık sapması: Top 3 %{top3_weight_pct:.1f} (hedef < %50) - yeniden dengeleme gerekli."
                        })
                
                # Normalize weights (sum to ~1)
                total_weight = sum(r.get("weight", 0) for r in reason_types)
                if total_weight > 0:
                    for r in reason_types:
                        r["weight"] = round(r["weight"] / total_weight, 2)
                
                # Sort by weight descending and limit to max 4
                reason_types.sort(key=lambda x: x.get("weight", 0), reverse=True)
                reason_types = reason_types[:4]
                
                # Generate events (upcoming earnings, FED, etc.)
                events = []
                try:
                    # Check for upcoming earnings in top positions
                    for item in sorted_by_weight[:3]:  # Top 3 positions
                        symbol = item["symbol"]
                        try:
                            earnings_info = get_earnings_info(symbol)
                            earnings_date_str = earnings_info.get("bilanco_tarihi", "")
                            
                            if earnings_date_str and earnings_date_str != "Bilinmiyor":
                                try:
                                    # Parse earnings date
                                    earnings_date = _dt.strptime(earnings_date_str.split()[0], "%Y-%m-%d").date() if " " in earnings_date_str else _dt.strptime(earnings_date_str, "%Y-%m-%d").date()
                                    today = _dt.now().date()
                                    days_until = (earnings_date - today).days
                                    
                                    # Only include events within horizon_days
                                    if 0 <= days_until <= mentor_horizon:
                                        # Determine impact based on current volatility
                                        impact = "VOLATILE"
                                        if weighted_rsi_calc > 70:
                                            impact = "DOWN"
                                        elif weighted_rsi_calc < 30:
                                            impact = "UP"
                                        
                                        events.append({
                                            "kind": "EARNINGS",
                                            "date_utc": earnings_date.strftime("%Y-%m-%dT00:00:00Z"),
                                            "title_tr": f"{symbol} {days_until} gün sonra açıklama",
                                            "impact": impact,
                                            "confidence": 60 if days_until <= 3 else 40,
                                            "plan_tr": "Açıklama öncesi pozisyonu küçült, sonrası yeniden giriş için tetik bekle." if mentor_action == "REDUCE" else "Açıklama sonrası trendi izle."
                                        })
                                except:
                                    pass
                        except:
                            continue
                except:
                    pass
                
                # Limit events to max 2
                events = events[:2]
                
                # Add EVENT_RISK to reason_types if events exist
                if events and not any(r.get("code") == "EVENT_RISK" for r in reason_types):
                    # Calculate event risk weight based on proximity and impact
                    event_risk_weight = 0.0
                    for event in events:
                        try:
                            event_date = datetime.fromisoformat(event["date_utc"].replace("Z", "+00:00")).date()
                            days_until = (event_date - _dt.now().date()).days
                            # Closer events = higher risk weight
                            proximity_weight = max(0.3, 1.0 - (days_until / 14))  # Max weight for today, decays over 14 days
                            impact_weight = 0.5 if event.get("impact") == "VOLATILE" else 0.3 if event.get("impact") in ["DOWN", "UP"] else 0.1
                            event_risk_weight += proximity_weight * impact_weight
                        except:
                            event_risk_weight += 0.3  # Default if parsing fails
                    
                    event_risk_weight = min(1.0, event_risk_weight / len(events))  # Average and cap at 1.0
                    if event_risk_weight > 0.2:  # Only add if significant
                        reason_types.append({
                            "code": "EVENT_RISK",
                            "weight": event_risk_weight,
                            "label_tr": "Olay Riski",
                            "evidence_tr": f"{len(events)} yaklaşan olay tespit edildi ({', '.join([e.get('title_tr', '')[:20] for e in events[:2]])})."
                        })
                        # Re-normalize after adding EVENT_RISK
                        total_weight = sum(r.get("weight", 0) for r in reason_types)
                        if total_weight > 0:
                            for r in reason_types:
                                r["weight"] = round(r["weight"] / total_weight, 2)
                        # Re-sort and limit to max 4
                        reason_types.sort(key=lambda x: x.get("weight", 0), reverse=True)
                        reason_types = reason_types[:4]
                
                # Generate timing_tr (timing plan)
                timing_parts = []
                if events:
                    nearest_event = min(events, key=lambda x: x.get("date_utc", ""))
                    days_until_event = (datetime.fromisoformat(nearest_event["date_utc"].replace("Z", "+00:00")).date() - _dt.now().date()).days
                    if days_until_event <= 3:
                        timing_parts.append(f"Bugün/yarın: {nearest_event['title_tr']} - pozisyonu küçült")
                    else:
                        timing_parts.append(f"{days_until_event} gün sonra: {nearest_event['title_tr']} - hazırlık yap")
                
                if mentor_action == "REDUCE":
                    timing_parts.append("Bu hafta: REDUCE verilen pozisyonlardan başla")
                elif mentor_action == "BUY":
                    timing_parts.append("Bu hafta: Kademeli pozisyon artırımı yap")
                else:
                    timing_parts.append("Bu hafta: Mevcut pozisyonları izle")
                
                timing_tr = " | ".join(timing_parts[:2]) if timing_parts else ""
                
                # Generate entry_reentry_tr (re-entry conditions)
                entry_conditions = []
                if mentor_action == "REDUCE":
                    entry_conditions.append("Tekrar alım için: RSI < 50, konsantrasyon < %50")
                    if weighted_rsi_calc > 70:
                        entry_conditions.append("Trend dönüşü: RSI 50'nin altına düşerse")
                elif mentor_action == "BUY":
                    entry_conditions.append("Pozisyon artırımı için: RSI 30-70 arası, trend güçlü")
                else:
                    entry_conditions.append("Pozisyon değişikliği için: RSI aşırı uçlarda veya konsantrasyon riski")
                
                entry_reentry_tr = " | ".join(entry_conditions[:2]) if entry_conditions else ""
                
                # Adjust horizon_days if events are near
                mentor_horizon = recommendation.get("horizon_days", 7)
                final_horizon = mentor_horizon
                if events:
                    try:
                        nearest_event_days = min([
                            (_dt.fromisoformat(e["date_utc"].replace("Z", "+00:00")).date() - _dt.now().date()).days
                            for e in events
                        ])
                        if nearest_event_days <= 7:
                            final_horizon = nearest_event_days + 2  # Event + 2 days buffer
                    except:
                        pass
                
                # Ensure reduce_pct is always set for REDUCE (default 10/15/20)
                if mentor_action == "REDUCE" and allocation_pct == 0:
                    allocation_pct = 15  # Default if somehow still 0
                
                # Build mentor object (new standardized format with reason_types and events)
                mentor = {
                    "decision": mentor_action,  # Changed from "action" to "decision"
                    "confidence": recommendation.get("confidence", 50),
                    "horizon_days": final_horizon,
                    "scope": "portfolio",
                    "title_tr": mentor_title[:50] if len(mentor_title) > 50 else mentor_title,  # Max 8 words ≈ 50 chars
                    "summary_tr": summary_tr,
                    "why_tr": why_tr_filtered[:3],  # Max 3
                    "plan_tr": plan_tr_filtered[:3],  # Max 3
                    "triggers_tr": triggers_tr,
                    "invalidates_tr": invalidates_tr,
                    "from_history_tr": from_history_tr,
                    "reduce_pct": allocation_pct if mentor_action == "REDUCE" else None,
                    "reason_types": reason_types,
                    "events": events,
                    "timing_tr": timing_tr,
                    "entry_reentry_tr": entry_reentry_tr
                }
                quick_result["mentor"] = mentor
                
                # 2. QUICK_ACTIONS (max 4, prioritized by weight/pnl/risk with priority field)
                quick_actions = []
                seen_symbols = set()
                priority_counter = 1
                
                # Priority 1: REDUCE actions (highest priority)
                # 1a: Highest weight positions requiring REDUCE
                for item in sorted_by_weight:
                    if len(quick_actions) >= 4:
                        break
                    symbol = item["symbol"]
                    if symbol in seen_symbols:
                        continue
                    weight_pct = item["weight_percent"]
                    pnl_pct = item["pnl_percent"]
                    if weight_pct >= 30:
                        quick_actions.append({
                            "symbol": symbol,
                            "action": "REDUCE",
                            "allocation_pct": 25,
                            "horizon_days": 3,
                            "reason_tr": f"Konsantrasyon yüksek (%{weight_pct:.1f})",
                            "priority": priority_counter
                        })
                        priority_counter += 1
                        seen_symbols.add(symbol)
                    elif weight_pct >= 25 and pnl_pct >= 15:
                        quick_actions.append({
                            "symbol": symbol,
                            "action": "REDUCE",
                            "allocation_pct": 20,
                            "horizon_days": 3,
                            "reason_tr": f"Kâr kilitle (%{pnl_pct:.1f})",
                            "priority": priority_counter
                        })
                        priority_counter += 1
                        seen_symbols.add(symbol)
                
                # 1b: High PnL positions for profit locking
                sorted_by_pnl = sorted(portfolio_data, key=lambda x: x["pnl_percent"], reverse=True)
                for item in sorted_by_pnl:
                    if len(quick_actions) >= 4:
                        break
                    symbol = item["symbol"]
                    if symbol in seen_symbols:
                        continue
                    pnl_pct = item["pnl_percent"]
                    if pnl_pct >= 15:
                        quick_actions.append({
                            "symbol": symbol,
                            "action": "REDUCE",
                            "allocation_pct": 20,
                            "horizon_days": 3,
                            "reason_tr": f"Kâr kilitle (%{pnl_pct:.1f})",
                            "priority": priority_counter
                        })
                        priority_counter += 1
                        seen_symbols.add(symbol)
                
                # Priority 2: BUY actions (if mentor says BUY)
                if mentor_action == "BUY":
                    for item in sorted_by_weight:
                        if len(quick_actions) >= 4:
                            break
                        symbol = item["symbol"]
                        if symbol in seen_symbols:
                            continue
                        weight_pct = item["weight_percent"]
                        pnl_pct = item["pnl_percent"]
                        rsi = item.get("rsi", 50)
                        # Look for opportunities (low weight, good RSI, positive PnL)
                        if weight_pct < 15 and pnl_pct > 0 and 30 < rsi < 70:
                            quick_actions.append({
                                "symbol": symbol,
                                "action": "BUY",
                                "allocation_pct": 10,
                                "horizon_days": 7,
                                "reason_tr": f"Fırsat değerlendir (%{pnl_pct:.1f} kâr)",
                                "priority": priority_counter
                            })
                            priority_counter += 1
                            seen_symbols.add(symbol)
                
                # Priority 3: HOLD actions (monitoring)
                for item in sorted_by_weight:
                    if len(quick_actions) >= 4:
                        break
                    symbol = item["symbol"]
                    if symbol in seen_symbols:
                        continue
                    weight_pct = item["weight_percent"]
                    pnl_pct = item["pnl_percent"]
                    rsi = item.get("rsi", 50)
                    
                    # Determine hold reason
                    if weight_pct >= 15:
                        reason = f"Trend korunuyor"
                    elif abs(pnl_pct) >= 10:
                        reason = f"Volatilite yüksek"
                    else:
                        reason = f"Risk dengeli"
                    
                    quick_actions.append({
                        "symbol": symbol,
                        "action": "HOLD",
                        "allocation_pct": 0,
                        "horizon_days": 7,
                        "reason_tr": reason,
                        "priority": priority_counter
                    })
                    priority_counter += 1
                    seen_symbols.add(symbol)
                
                # Sort by priority and limit to 4
                quick_actions.sort(key=lambda x: x.get("priority", 999))
                quick_result["quick_actions"] = quick_actions[:4]
                
                # 3. PORTFOLIO_COMMENTARY_TR (2-3 sentences, aligned with mentor action)
                commentary_sentences = []
                
                # Sentence 1: What happened (P/L, general status)
                if total_pnl_percent > 10:
                    commentary_sentences.append(f"Portföy şu anda kârlı (%{total_pnl_percent:.1f})")
                elif total_pnl_percent < -10:
                    commentary_sentences.append(f"Portföy zararda (%{abs(total_pnl_percent):.1f})")
                elif total_pnl_percent > 0:
                    commentary_sentences.append(f"Portföy hafif kârlı (%{total_pnl_percent:.1f})")
                else:
                    commentary_sentences.append(f"Portföy dengeli durumda")
                
                # Sentence 2: Why it matters (concentration/volatility/news)
                if top3_weight_pct > 70:
                    commentary_sentences.append(f"ancak kazançların büyük kısmı birkaç pozisyonda yoğunlaşıyor (Top 3: %{top3_weight_pct:.1f})")
                elif top3_weight_pct > 50:
                    commentary_sentences.append(f"ve pozisyonlar orta seviyede konsantre (Top 3: %{top3_weight_pct:.1f})")
                
                # Check volatility
                weighted_rsi = sum(item["rsi"] * item["weight_percent"] / 100 for item in portfolio_data) if portfolio_data else 50
                if weighted_rsi > 70:
                    commentary_sentences.append("Aşırı alım bölgesinde - düzeltme riski yüksek")
                elif weighted_rsi < 30:
                    commentary_sentences.append("Aşırı satım bölgesinde - toparlanma potansiyeli var")
                
                # Sentence 3: What to do (aligned with mentor action, non-command tone)
                if mentor_action == "REDUCE":
                    commentary_sentences.append("Kâr kilitleme ve ağırlık dengeleme ile riski disipline etmek mantıklı")
                elif mentor_action == "BUY":
                    commentary_sentences.append("Uygun fırsatlarda kademeli pozisyon artırımı düşünülebilir")
                else:  # HOLD
                    commentary_sentences.append("Mevcut pozisyonları izlemek ve disiplinli takip yapmak önemli")
                
                # Combine into 2-3 sentences
                portfolio_commentary_tr = ". ".join(commentary_sentences[:3]) + "."
                quick_result["portfolio_commentary_tr"] = portfolio_commentary_tr
                
                # 4. STRESS_TEST (from scenarios, mentorized - new format)
                stress_test = {
                    "rows": [],
                    "worst_case": None,
                    "mentor_take_tr": [],
                    "action_tr": ""
                }
                
                if detail_level == "detailed" and scenarios:
                    # Transform scenarios to new format (rows)
                    for scenario in scenarios[:6]:  # Max 6 scenarios (top 3 positions, 2 shocks each)
                        symbol = scenario.get("symbol", "")
                        shock = scenario.get("shock", 0)
                        impact_usd = scenario.get("portfolio_impact_usd", 0)
                        impact_pct = scenario.get("portfolio_impact_pct", 0)
                        
                        # Create scenario name
                        shock_pct = abs(shock * 100)
                        scenario_name = f"{symbol} -{shock_pct:.0f}%"
                        
                        stress_test["rows"].append({
                            "scenario": scenario_name,
                            "impact_usd": round(impact_usd, 2),
                            "impact_pct": round(impact_pct, 2)
                        })
                    
                    # Find worst case
                    if stress_test["rows"]:
                        worst_row = min(stress_test["rows"], key=lambda x: x["impact_usd"])
                        worst_scenario_name = worst_row["scenario"]
                        
                        # Find the symbol from worst scenario
                        worst_driver = worst_scenario_name.split(" -")[0] if " -" in worst_scenario_name else worst_scenario_name
                        
                        stress_test["worst_case"] = {
                            "impact_usd": worst_row["impact_usd"],
                            "impact_pct": worst_row["impact_pct"],
                            "driver": worst_scenario_name
                        }
                        
                        # Generate mentor take (aligned with mentor action)
                        worst_pct = worst_row["impact_pct"]
                        stress_test["mentor_take_tr"] = [
                            f"En kötü senaryoda ~%{abs(worst_pct):.1f} kayıp mümkün.",
                            f"Şok etkisi ilk 3 pozisyonda yoğunlaşıyor."
                        ]
                        
                        # Action must align with mentor decision
                        if mentor_action == "REDUCE":
                            stress_test["action_tr"] = f"Bu hafta risk azalt: REDUCE verilen pozisyonlardan başla."
                        elif mentor_action == "BUY":
                            stress_test["action_tr"] = f"Şok etkisi düşük - BUY kararı ile dikkatli kademeli ekleme yap."
                        else:  # HOLD
                            stress_test["action_tr"] = f"Şok etkisi orta - HOLD kararı ile pozisyonları izle ve gerekirse ayarla."
                
                quick_result["stress_test"] = stress_test
                
                # 5. POSITIONS (unified table - single source, new format)
                positions = []
                # Create a map from position_notes_tr for easy lookup
                notes_map = {note["symbol"]: note for note in position_notes_tr}
                
                for row in position_risk_rows_tr:
                    symbol = row["symbol"]
                    note_data = notes_map.get(symbol, {})
                    
                    weight_pct = row.get("weight_pct", 0)
                    pnl_pct = row.get("pnl_pct", 0)
                    
                    # Get RSI
                    rsi_val = row.get("rsi", "n/a")
                    if isinstance(rsi_val, str) and rsi_val == "n/a":
                        rsi_val = None
                    rsi_final = round(rsi_val, 1) if rsi_val is not None else None
                    
                    # Determine vol_tag (LOW/MED/HIGH)
                    vol_level = row.get("vol_level", "LOW")
                    vol_tag = vol_level  # Already LOW/MED/HIGH
                    
                    # Determine risk_tag (LOW/MED/HIGH)
                    risk_tag = "LOW"
                    if weight_pct >= 30 or abs(pnl_pct) >= 20:
                        risk_tag = "HIGH"
                    elif weight_pct >= 15 or abs(pnl_pct) >= 10 or (rsi_final is not None and (rsi_final >= 70 or rsi_final <= 30)):
                        risk_tag = "MED"
                    
                    # Determine action (BUY/HOLD/REDUCE)
                    pos_action = "HOLD"
                    pos_action_pct = 0
                    pos_horizon_days = 7
                    
                    if weight_pct >= 30 or (weight_pct >= 25 and pnl_pct >= 15):
                        pos_action = "REDUCE"
                        pos_action_pct = 25 if weight_pct >= 30 else 20
                        pos_horizon_days = 3
                    elif pnl_pct >= 15:
                        pos_action = "REDUCE"
                        pos_action_pct = 15
                        pos_horizon_days = 3
                    elif pnl_pct <= -10:
                        pos_action = "HOLD"  # Don't reduce losses, just hold and monitor
                        pos_horizon_days = 7
                    elif mentor_action == "BUY" and weight_pct < 15 and pnl_pct > 0 and rsi_final is not None and 30 < rsi_final < 70:
                        pos_action = "BUY"
                        pos_action_pct = 10
                        pos_horizon_days = 7
                    
                    # Generate mentor note (1 sentence)
                    mentor_note_parts = []
                    if weight_pct >= 30:
                        mentor_note_parts.append(f"Yüksek konsantrasyon (%{weight_pct:.1f})")
                    if pnl_pct >= 15:
                        mentor_note_parts.append(f"Kâr kilitleme fırsatı (%{pnl_pct:.1f})")
                    elif pnl_pct <= -10:
                        mentor_note_parts.append(f"Zarar kontrolü gerekli (%{abs(pnl_pct):.1f})")
                    if rsi_final is not None and rsi_final >= 70:
                        mentor_note_parts.append("Aşırı alım bölgesi")
                    elif rsi_final is not None and rsi_final <= 30:
                        mentor_note_parts.append("Aşırı satım bölgesi")
                    
                    if not mentor_note_parts:
                        mentor_note_parts.append("Düzenli takip")
                    
                    mentor_note_tr = ". ".join(mentor_note_parts[:2]) + "."  # Max 2 parts, 1 sentence
                    
                    # Generate position-level reason_types
                    pos_reason_types = []
                    if weight_pct >= 30:
                        pos_reason_types.append({
                            "code": "CONCENTRATION",
                            "label_tr": "Konsantrasyon",
                            "evidence_tr": f"Ağırlık %{weight_pct:.1f}"
                        })
                    if pnl_pct >= 15:
                        pos_reason_types.append({
                            "code": "PROFIT_TAKE",
                            "label_tr": "Kâr Kilitleme",
                            "evidence_tr": f"P/L %{pnl_pct:.1f}"
                        })
                    elif pnl_pct <= -10:
                        pos_reason_types.append({
                            "code": "DRAWDOWN",
                            "label_tr": "Düşüş",
                            "evidence_tr": f"P/L %{pnl_pct:.1f}"
                        })
                    if vol_tag == "HIGH":
                        pos_reason_types.append({
                            "code": "VOLATILITY",
                            "label_tr": "Volatilite",
                            "evidence_tr": "Yüksek volatilite"
                        })
                    
                    # Limit to max 2
                    pos_reason_types = pos_reason_types[:2]
                    
                    # Check for position-specific events (earnings)
                    pos_events = []
                    try:
                        earnings_info = get_earnings_info(symbol)
                        earnings_date_str = earnings_info.get("bilanco_tarihi", "")
                        
                        if earnings_date_str and earnings_date_str != "Bilinmiyor":
                            try:
                                earnings_date = _dt.strptime(earnings_date_str.split()[0], "%Y-%m-%d").date() if " " in earnings_date_str else _dt.strptime(earnings_date_str, "%Y-%m-%d").date()
                                today = _dt.now().date()
                                days_until = (earnings_date - today).days
                                
                                if 0 <= days_until <= 14:  # Within 2 weeks
                                    impact = "VOLATILE"
                                    if rsi_final is not None and rsi_final > 70:
                                        impact = "DOWN"
                                    elif rsi_final is not None and rsi_final < 30:
                                        impact = "UP"
                                    
                                    pos_events.append({
                                        "kind": "EARNINGS",
                                        "date_utc": earnings_date.strftime("%Y-%m-%dT00:00:00Z"),
                                        "title_tr": f"{days_until} gün sonra açıklama",
                                        "impact": impact,
                                        "confidence": 60 if days_until <= 3 else 40,
                                        "plan_tr": "Açıklama öncesi pozisyonu küçült" if pos_action == "REDUCE" else "Açıklama sonrası trendi izle"
                                    })
                            except:
                                pass
                    except:
                        pass
                    
                    positions.append({
                        "symbol": symbol,
                        "weight_pct": round(weight_pct, 1),
                        "pnl_pct": round(pnl_pct, 1),
                        "rsi": rsi_final,
                        "vol_tag": vol_tag,
                        "risk_tag": risk_tag,
                        "action": pos_action,
                        "action_pct": pos_action_pct,
                        "horizon_days": pos_horizon_days,
                        "mentor_note_tr": mentor_note_tr,
                        "reason_types": pos_reason_types if pos_reason_types else [],
                        "events": pos_events
                    })
                
                quick_result["positions"] = positions
                
            except Exception as mentor_err:
                print(f"⚠️ Error in mentor system: {mentor_err}")
                import traceback
                traceback.print_exc()
                # Fallback: Create minimal mentor structure
                recommendation = {
                    "action": "HOLD",
                    "confidence": 50,
                    "horizon_days": 7,
                    "why_tr": ["Analiz sırasında hata oluştu"],
                    "if_then_tr": ["Mevcut pozisyonları koru"]
                }
            
            # Always create standard fields (even if recommendation failed)
            if recommendation:
                # Build mentor and other standard fields (code continues below)
                mentor_action = recommendation.get("action", "HOLD")
                if mentor_action == "SELL":
                    mentor_action = "REDUCE"
                
                top3_weight_pct = features.get("top3_weight_pct", 0) if features else sum(item["weight_percent"] for item in sorted_by_weight[:3]) if len(sorted_by_weight) >= 3 else 0
                max_single_weight = sorted_by_weight[0]["weight_percent"] if sorted_by_weight else 0
                allocation_pct = 0
                if mentor_action == "REDUCE":
                    if top3_weight_pct > 70 or max_single_weight > 30:
                        allocation_pct = 25
                    elif top3_weight_pct > 50:
                        allocation_pct = 15
                elif mentor_action == "BUY":
                    allocation_pct = 10
                
                if mentor_action == "REDUCE":
                    mentor_title = "Risk düşür, kârı kilitle"
                elif mentor_action == "BUY":
                    mentor_title = "Fırsat değerlendir, kademeli ekle"
                else:
                    mentor_title = "Mevcut pozisyonları koru, izle"
                
                mentor = {
                    "scope": {"type": "portfolio", "symbol": None},
                    "action": mentor_action,
                    "allocation_pct": allocation_pct,
                    "horizon_days": recommendation.get("horizon_days", 7),
                    "confidence": recommendation.get("confidence", 50),
                    "title_tr": mentor_title,
                    "why_tr": recommendation.get("why_tr", [])[:3],
                    "plan_tr": recommendation.get("if_then_tr", [])[:3],
                    "rules_tr": [
                        "Konsantrasyon riski yüksekse (%70+), kademeli dengeleme yap",
                        "Kâr pozisyonlarında (%15+), kısmi realizasyon düşün",
                        "Zarar pozisyonlarında (%-10+), stop-loss planı yap"
                    ]
                }
                quick_result["mentor"] = mentor
                
                # Quick actions (max 4)
                quick_actions = []
                seen_symbols = set()
                
                for item in sorted_by_weight:
                    if len(quick_actions) >= 4:
                        break
                    symbol = item["symbol"]
                    if symbol in seen_symbols:
                        continue
                    weight_pct = item["weight_percent"]
                    if weight_pct >= 25:
                        pnl_pct = item["pnl_percent"]
                        if weight_pct >= 30:
                            action = "REDUCE"
                            allocation_pct = 25
                            reason = f"Yüksek konsantrasyon (%{weight_pct:.1f}) - Risk azaltma önerilir"
                        elif pnl_pct >= 15:
                            action = "REDUCE"
                            allocation_pct = 20
                            reason = f"Kâr pozisyonu (%{pnl_pct:.1f}) - Kısmi realizasyon düşün"
                        else:
                            action = "HOLD"
                            allocation_pct = 0
                            reason = f"Ağırlık yüksek (%{weight_pct:.1f}) - İzle"
                        
                        quick_actions.append({
                            "symbol": symbol,
                            "action": action,
                            "allocation_pct": allocation_pct,
                            "horizon_days": 3 if action == "REDUCE" else 7,
                            "reason_tr": reason
                        })
                        seen_symbols.add(symbol)
                
                sorted_by_pnl = sorted(portfolio_data, key=lambda x: x["pnl_percent"], reverse=True)
                for item in sorted_by_pnl:
                    if len(quick_actions) >= 4:
                        break
                    symbol = item["symbol"]
                    if symbol in seen_symbols:
                        continue
                    pnl_pct = item["pnl_percent"]
                    if pnl_pct >= 15:
                        quick_actions.append({
                            "symbol": symbol,
                            "action": "REDUCE",
                            "allocation_pct": 20,
                            "horizon_days": 3,
                            "reason_tr": f"Kâr pozisyonu (%{pnl_pct:.1f}) - Kârı kilitle"
                        })
                        seen_symbols.add(symbol)
                
                for item in sorted_by_weight:
                    if len(quick_actions) >= 4:
                        break
                    symbol = item["symbol"]
                    if symbol in seen_symbols:
                        continue
                    weight_pct = item["weight_percent"]
                    pnl_pct = abs(item["pnl_percent"])
                    rsi = item.get("rsi", 50)
                    if weight_pct >= 15 or pnl_pct >= 10 or (rsi >= 70 or rsi <= 30):
                        quick_actions.append({
                            "symbol": symbol,
                            "action": "HOLD",
                            "allocation_pct": 0,
                            "horizon_days": 7,
                            "reason_tr": f"Yüksek volatilite - Dikkatli izle"
                        })
                        seen_symbols.add(symbol)
                
                for item in sorted_by_weight:
                    if len(quick_actions) >= 4:
                        break
                    symbol = item["symbol"]
                    if symbol in seen_symbols:
                        continue
                    quick_actions.append({
                        "symbol": symbol,
                        "action": "HOLD",
                        "allocation_pct": 0,
                        "horizon_days": 7,
                        "reason_tr": "Düzenli takip"
                    })
                    seen_symbols.add(symbol)
                
                quick_result["quick_actions"] = quick_actions[:4]
                
                # Portfolio commentary
                commentary_parts = []
                if top3_weight_pct > 70:
                    commentary_parts.append(f"Portföy yüksek konsantrasyon riski taşıyor (Top 3: %{top3_weight_pct:.1f}).")
                if total_pnl_percent > 10:
                    commentary_parts.append(f"Genel performans güçlü (%{total_pnl_percent:.1f} kâr).")
                elif total_pnl_percent < -10:
                    commentary_parts.append(f"Portföy zararda (%{abs(total_pnl_percent):.1f}).")
                
                if not commentary_parts:
                    commentary_parts.append("Portföy dengeli durumda.")
                
                quick_result["portfolio_commentary_tr"] = " ".join(commentary_parts[:3])
                
                # Stress test
                stress_test = {
                    "scenarios": [],
                    "mentor_take_tr": [],
                    "action_link_tr": ""
                }
                
                if detail_level == "detailed" and scenarios:
                    for scenario in scenarios[:6]:
                        symbol = scenario.get("symbol", "")
                        shock = scenario.get("shock", 0)
                        impact_usd = scenario.get("portfolio_impact_usd", 0)
                        impact_pct = scenario.get("portfolio_impact_pct", 0)
                        
                        shock_pct = abs(shock * 100)
                        scenario_name = f"{symbol} -{shock_pct:.0f}%"
                        
                        stress_test["scenarios"].append({
                            "name_tr": scenario_name,
                            "estimated_pnl_usd": round(impact_usd, 2),
                            "estimated_portfolio_pct": round(impact_pct, 2)
                        })
                    
                    if stress_test["scenarios"]:
                        worst_scenario = min(stress_test["scenarios"], key=lambda x: x["estimated_pnl_usd"])
                        worst_pct = worst_scenario["estimated_portfolio_pct"]
                        
                        stress_test["mentor_take_tr"] = [
                            f"En kötü senaryoda portföy %{abs(worst_pct):.1f} değer kaybedebilir.",
                            f"Top 3 pozisyonun şok etkisi yüksek - Risk yönetimi kritik."
                        ]
                        
                        if worst_pct < -10:
                            stress_test["action_link_tr"] = "Yüksek risk: Pozisyon boyutlarını gözden geçirin ve stop-loss planı yapın."
                        elif worst_pct < -5:
                            stress_test["action_link_tr"] = "Orta risk: Pozisyonları izleyin ve gerekirse kademeli dengeleme yapın."
                        else:
                            stress_test["action_link_tr"] = "Düşük risk: Mevcut pozisyonları koruyun."
                
                quick_result["stress_test"] = stress_test
                
                # Positions (unified table)
                positions = []
                notes_map = {note["symbol"]: note for note in position_notes_tr}
                
                for row in position_risk_rows_tr:
                    symbol = row["symbol"]
                    note_data = notes_map.get(symbol, {})
                    
                    pos_action = "HOLD"
                    pos_allocation_pct = 0
                    weight_pct = row.get("weight_pct", 0)
                    pnl_pct = row.get("pnl_pct", 0)
                    
                    if weight_pct >= 30 or (weight_pct >= 25 and pnl_pct >= 15):
                        pos_action = "REDUCE"
                        pos_allocation_pct = 20
                    elif pnl_pct >= 15:
                        pos_action = "REDUCE"
                        pos_allocation_pct = 15
                    elif pnl_pct <= -10:
                        pos_action = "HOLD"
                    
                    vol_level = row.get("vol_level", "LOW")
                    risk_label = "DÜŞÜK"
                    if vol_level == "HIGH":
                        risk_label = "YÜKSEK"
                    elif vol_level == "MED":
                        risk_label = "ORTA"
                    
                    rsi_val = row.get("rsi", "n/a")
                    if isinstance(rsi_val, str) and rsi_val == "n/a":
                        rsi_val = None
                    
                    positions.append({
                        "symbol": symbol,
                        "weight_pct": weight_pct,
                        "pnl_pct": pnl_pct,
                        "rsi": round(rsi_val, 1) if rsi_val is not None else None,
                        "vol_flag": vol_level,
                        "risk_label_tr": risk_label,
                        "mentor_action": pos_action,
                        "mentor_allocation_pct": pos_allocation_pct,
                        "mentor_note_tr": note_data.get("note_tr", row.get("note_tr", "Düzenli takip"))
                    })
                
                quick_result["positions"] = positions
            else:
                # Minimal fallback if everything failed
                quick_result["mentor"] = {
                    "scope": {"type": "portfolio", "symbol": None},
                    "action": "HOLD",
                    "allocation_pct": 0,
                    "horizon_days": 7,
                    "confidence": 50,
                    "title_tr": "Analiz tamamlanamadı",
                    "why_tr": ["Veri eksikliği"],
                    "plan_tr": ["Mevcut pozisyonları koru"],
                    "rules_tr": []
                }
                quick_result["quick_actions"] = []
                quick_result["portfolio_commentary_tr"] = "Portföy analizi tamamlanamadı."
                quick_result["stress_test"] = {"scenarios": [], "mentor_take_tr": [], "action_link_tr": ""}
                quick_result["positions"] = []
        
        # ========================================================================
        # STEP 6: If use_llm=False, return Quick mode immediately (but save to DB first)
        # ========================================================================
        if not use_llm:
            # Save QUICK mode result to database (legacy table)
            try:
                portfolio_json_str = json.dumps(portfolio_data, ensure_ascii=False)
                save_portfolio_analysis(
                    portfolio_json=portfolio_json_str,
                    summary="Quick mode analysis - Deterministic portfolio summary",
                    risk_level=50,  # Default risk level for quick mode
                    full_json=quick_result
                )
            except Exception as save_err:
                print(f"⚠️ Error saving QUICK portfolio analysis: {save_err}")
            
            # Save to mentor system tables
            try:
                summary_json = {
                    "total_value": portfolio_summary.get("total_value", 0),
                    "total_pnl_percent": portfolio_summary.get("total_pnl_percent", 0),
                    "holdings_count": portfolio_summary.get("holdings_count", 0)
                }
                analysis_id = save_portfolio_analysis_mentor(
                    as_of=as_of,
                    mode="quick",
                    summary_json=summary_json,
                    full_json=quick_result,
                    feature_json=features
                )
                print(f"✅ Saved to mentor system (analysis_id={analysis_id})")
            except Exception as mentor_save_err:
                print(f"⚠️ Error saving to mentor system: {mentor_save_err}")
            
            print(f"[portfolio] mode=quick llm_used=0 cache_hit=0 force={1 if force else 0}")
            return _json_safe(quick_result)
        
        # ========================================================================
        # STEP 6: DEEP MODE - Check cache first (unless force=True)
        # ========================================================================
        cache_hit = 0
        llm_used = 0
        
        if not force:
            latest_analysis = get_latest_portfolio_analysis()
            if latest_analysis and latest_analysis.get("created_at"):
                try:
                    # Parse created_at date
                    created_at_str = latest_analysis["created_at"]
                    if isinstance(created_at_str, str):
                        # Try to parse as ISO format or SQLite datetime
                        try:
                            created_date = _dt.fromisoformat(created_at_str.replace("Z", "+00:00")).date()
                        except:
                            # Try SQLite format
                            created_date = _dt.strptime(created_at_str.split()[0], "%Y-%m-%d").date()
                        
                        today = _dt.now().date()
                        
                        # If cache is from today, use it
                        if created_date == today and latest_analysis.get("full_json"):
                            cached_json = latest_analysis["full_json"]
                            if isinstance(cached_json, dict):
                                # Ensure consistent structure for cached result
                                result = {
                                    "success": True,
                                    "mode": "deep",
                                    "detail_level": "detailed",  # DEEP mode always detailed
                                    "as_of": cached_json.get("as_of", as_of),
                                    "portfolio": cached_json.get("portfolio", portfolio_summary),
                                    "holdings": cached_json.get("holdings", holdings),
                                    "risk": cached_json.get("risk", risk),
                                    "news": cached_json.get("news", top_events[:5] if top_events else []),
                                    "action_bullets_tr": cached_json.get("action_bullets_tr", action_bullets_tr[:8]),
                                    "position_risk_rows_tr": [],  # DEEP mode doesn't include position risk rows tr
                                    "deep_summary_tr": cached_json.get("deep_summary_tr") or cached_json.get("portfolio_summary_tr"),
                                    "scenarios": [],  # DEEP mode doesn't include scenarios
                                    "position_risk_rows": [],  # DEEP mode doesn't include position risk rows
                                    "meta": {
                                        "llm_used": 0,
                                        "cache_hit": 1,
                                        "force": 0
                                    }
                                }
                                
                                # Save cached result to DB (for history tracking)
                                try:
                                    portfolio_json_str = json.dumps(portfolio_data, ensure_ascii=False)
                                    save_portfolio_analysis(
                                        portfolio_json=portfolio_json_str,
                                        summary=result.get("deep_summary_tr") or "Deep mode analysis (cached)",
                                        risk_level=cached_json.get("risk_score", 50),
                                        full_json=result
                                    )
                                except Exception as save_err:
                                    print(f"⚠️ Error saving CACHED portfolio analysis: {save_err}")
                                
                                print(f"[portfolio] mode=deep llm_used=0 cache_hit=1 force=0")
                                return _json_safe(result)
                except Exception as cache_err:
                    print(f"⚠️ Cache check error: {cache_err}")
                    # Continue to generate new analysis
        
        # ========================================================================
        # STEP 7: DEEP MODE - Generate LLM analysis (single call)
        # ========================================================================
        # Prepare holdings summary for LLM prompt
        holdings_summary = "\n".join([
            f"- {item['symbol']}: {item['quantity']} adet, Ortalama maliyet: ${item['avg_cost']:.2f}, "
            f"Güncel fiyat: ${item['current_price']:.2f}, P/L: %{item['pnl_percent']:.1f}, "
            f"Ağırlık: %{item['weight_percent']:.1f}"
            for item in portfolio_data
        ])
        
        # Prepare news summary for LLM prompt
        news_summary_text = "\n".join([
            f"- {event['title']} (Önem: {event['importance_score']}/100, Etki: {event['impact']})"
            for event in top_events[:5]
        ]) if top_events else "Önemli haber bulunamadı."
        
        # Build LLM prompt
        prompt = f"""Sen gerçekçi bir hedge fund yöneticisisin. Portföy analizi yap ve somut, uygulanabilir tavsiyeler ver.

PORTFÖY ÖZETİ (QUICK MODE):
- Toplam Değer: ${total_value:.2f}
- Toplam Maliyet: ${total_cost:.2f}
- Toplam P/L: ${total_pnl:.2f} (%{total_pnl_percent:.2f})
- Pozisyon Sayısı: {holdings_count}
- En Büyük 3 Pozisyon: {', '.join([f"{p['symbol']} (%{p['weight_percent']:.1f})" for p in largest_positions])}
- Konsantrasyon Riski: {'YÜKSEK' if concentration_risk['flag'] else 'DÜŞÜK'}
- Volatilite Riski: {'YÜKSEK' if volatility_risk['flag'] else 'DÜŞÜK'}

HOLDINGS DETAYLARI:
{holdings_summary}

HABERLER (Top Events):
{news_summary_text}

GÖREV:
1. portfolio_summary_tr: Portföyün genel durumunu 1 paragrafta özetle (Türkçe)
2. top_actions_tr: En önemli 5 aksiyonu belirt (her biri somut: "NVDA ağırlığını %X'e indir, gerekçe: ...")
3. risk_reduction_plan_tr: Risk azaltma planı (3-6 madde)
4. catalyst_summary_tr: Katalizörler ve fırsatlar (3-6 madde)
5. watchlist_tr: İzlenmesi gereken 5 madde
6. risk_score: 0-100 arası risk skoru (integer)
7. confidence_score: 0-100 arası güven skoru (integer)

ÖNEMLİ: 
- Generic tavsiyeler VERME
- Her aksiyon için SPESİFİK sembol, yüzde ve gerekçe ver
- Türkçe yaz"""
        
        try:
            deep_json = safe_gemini_call(
                prompt,
                response_mode="json",
                schema=PORTFOLIO_DEEP_SCHEMA,
                max_retries=0,  # No retries for free tier
                purpose="portfolio_analysis",
                max_output_tokens=2000
            )
            
            if deep_json:
                # Build consistent DEEP mode result structure
                result = {
                    "success": True,
                    "mode": "deep",
                    "detail_level": "detailed",  # DEEP mode always detailed
                    "as_of": as_of,
                    "portfolio": portfolio_summary,
                    "holdings": holdings,
                    "risk": risk,
                    "news": top_events[:5] if top_events else [],
                    "action_bullets_tr": deep_json.get("top_actions_tr", action_bullets_tr[:8]),
                    "position_risk_rows_tr": [],  # DEEP mode doesn't include position risk rows tr
                    "deep_summary_tr": deep_json.get("portfolio_summary_tr", ""),
                    "scenarios": [],  # DEEP mode doesn't include scenarios
                    "position_risk_rows": [],  # DEEP mode doesn't include position risk rows
                    "meta": {
                        "llm_used": 1,
                        "cache_hit": 0,
                        "force": 1 if force else 0
                    }
                }
                
                # Add optional DEEP mode fields if present
                if "risk_reduction_plan_tr" in deep_json:
                    result["risk_reduction_plan_tr"] = deep_json["risk_reduction_plan_tr"]
                if "catalyst_summary_tr" in deep_json:
                    result["catalyst_summary_tr"] = deep_json["catalyst_summary_tr"]
                if "watchlist_tr" in deep_json:
                    result["watchlist_tr"] = deep_json["watchlist_tr"]
                if "risk_score" in deep_json:
                    result["risk_score"] = deep_json["risk_score"]
                if "confidence_score" in deep_json:
                    result["confidence_score"] = deep_json["confidence_score"]
                
                llm_used = 1
                
                # Save to database
                try:
                    portfolio_json_str = json.dumps(portfolio_data, ensure_ascii=False)
                    save_portfolio_analysis(
                        portfolio_json=portfolio_json_str,
                        summary=result.get("deep_summary_tr", ""),
                        risk_level=deep_json.get("risk_score", 50),
                        full_json=result
                    )
                except Exception as save_err:
                    print(f"⚠️ Error saving DEEP portfolio analysis: {save_err}")
                
                print(f"[portfolio] mode=deep llm_used=1 cache_hit=0 force={1 if force else 0}")
                return _json_safe(result)
            else:
                raise Exception("LLM returned empty response")
                
        except Exception as llm_err:
            print(f"⚠️ LLM call failed: {llm_err}")
            # Fallback to Quick mode
            quick_result["meta"]["llm_used"] = 0
            quick_result["meta"]["force"] = 1 if force else 0
            if "data_quality_flags" not in quick_result:
                quick_result["data_quality_flags"] = []
            quick_result["data_quality_flags"].append("llm_failed")
            # Ensure detail_level, position_risk_rows_tr, and position_notes_tr are set even in fallback
            if "detail_level" not in quick_result:
                quick_result["detail_level"] = detail_level
            if "position_risk_rows_tr" not in quick_result:
                quick_result["position_risk_rows_tr"] = position_risk_rows_tr
            if "position_notes_tr" not in quick_result:
                quick_result["position_notes_tr"] = position_notes_tr
            
            # Save fallback result to database
            try:
                portfolio_json_str = json.dumps(portfolio_data, ensure_ascii=False)
                save_portfolio_analysis(
                    portfolio_json=portfolio_json_str,
                    summary="Quick mode analysis (LLM fallback) - Deterministic portfolio summary",
                    risk_level=50,
                    full_json=quick_result
                )
            except Exception as save_err:
                print(f"⚠️ Error saving FALLBACK portfolio analysis: {save_err}")
            
            print(f"[portfolio] mode=quick llm_used=0 cache_hit=0 force={1 if force else 0} (llm_failed)")
            return _json_safe(quick_result)
        
    except Exception as e:
        print(f"❌ Error analyzing portfolio: {e}")
        import traceback
        traceback.print_exc()
        result = {"success": False, "error": str(e), "mode": "error"}
        return _json_safe(result)

def backtest_lite(portfolio: list) -> dict:
    """Backtest: If bought portfolio 1 month ago, return vs S&P500 with per-stock breakdown."""
    try:
        one_month_ago = _dt.now() - timedelta(days=30)
        
        # Get S&P500 performance
        sp500 = yf.Ticker("^GSPC")
        sp500_hist = sp500.history(period="1mo")
        if len(sp500_hist) > 0:
            sp500_start = sp500_hist.iloc[0]["Close"]
            sp500_end = sp500_hist.iloc[-1]["Close"]
            sp500_return = ((sp500_end - sp500_start) / sp500_start * 100)
        else:
            sp500_return = 0
            sp500_start = 0
            sp500_end = 0
        
        # Calculate portfolio performance with per-stock breakdown
        portfolio_start_value = 0
        portfolio_end_value = 0
        stock_breakdown = []
        
        for item in portfolio:
            symbol = item["symbol"]
            quantity = item["quantity"]
            
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1mo")
                
                if len(hist) > 0:
                    start_price = hist.iloc[0]["Close"]
                    end_price = hist.iloc[-1]["Close"]
                    change_percent = ((end_price - start_price) / start_price * 100) if start_price > 0 else 0
                    
                    portfolio_start_value += start_price * quantity
                    portfolio_end_value += end_price * quantity
                    
                    stock_breakdown.append({
                        "symbol": symbol,
                        "quantity": quantity,
                        "start_price": float(start_price),
                        "current_price": float(end_price),
                        "change_percent": change_percent,
                        "start_value": float(start_price * quantity),
                        "current_value": float(end_price * quantity),
                        "pnl": float((end_price - start_price) * quantity)
                    })
            except Exception as e:
                print(f"⚠️ Error fetching backtest data for {symbol}: {e}")
                continue
        
        portfolio_return = ((portfolio_end_value - portfolio_start_value) / portfolio_start_value * 100) if portfolio_start_value > 0 else 0
        
        # Generate AI commentary on performance
        breakdown_summary = "\n".join([
            f"- {item['symbol']}: {item['change_percent']:.1f}% change (${item['start_price']:.2f} → ${item['current_price']:.2f})"
            for item in stock_breakdown
        ])
        
        prompt = f"""Sen bir finansal analistsin. Aşağıdaki backtest sonuçlarını analiz et ve kısa, net bir yorum yap.

PORTFÖY PERFORMANSI:
- Portföy Getirisi: {portfolio_return:.2f}%
- S&P 500 Getirisi: {sp500_return:.2f}%
- Outperformance: {portfolio_return - sp500_return:.2f}%

HİSSE BAZLI DETAYLAR:
{breakdown_summary}

ÖNEMLİ: Hangi hissenin portföyü aşağı çektiğini veya yukarı taşıdığını spesifik olarak belirt. Örneğin: "TSLA portföyü %15 aşağı çekti çünkü 1 ay önce $250'dan $200'a düştü."

Lütfen şu formatta JSON döndür:
{{
    "yorum": "Kısa genel yorum (örn: Portföy S&P500'ü 2.5% geride bıraktı)",
    "en_iyi_performans": "Hangi hisse en iyi performans gösterdi ve neden (örn: NVDA +12% - AI haberleri pozitif)",
    "en_kotu_performans": "Hangi hisse portföyü aşağı çekti ve ne kadar etkiledi (örn: TSLA -15% - portföyü %3 aşağı çekti)",
    "oneri": "Portföy iyileştirme önerisi (hangi hisse azaltılmalı/artırılmalı)"
}}"""
        
        try:
            # Use unified gemini_json function
            try:
                ai_commentary = safe_gemini_call(prompt, response_mode="json", max_retries=1, purpose="backtest_commentary")
            except GeminiCallError:
                ai_commentary = None
            
            if ai_commentary is None:
                print("⚠️ Using fallback data")
                ai_commentary = {
                    "yorum": FALLBACK_AI_MESSAGE,
                    "en_iyi_performans": "N/A",
                    "en_kotu_performans": "N/A",
                    "oneri": "Lütfen daha sonra tekrar deneyin"
                }
        except Exception as e:
            # Catch ALL exceptions to prevent crashes
            print("⚠️ Using fallback data")
            ai_commentary = {
                "yorum": FALLBACK_AI_MESSAGE,
                "en_iyi_performans": "N/A",
                "en_kotu_performans": "N/A",
                "oneri": "N/A"
            }
        
        return {
            "success": True,
            "period": "1 month",
            "portfolio_return": portfolio_return,
            "sp500_return": sp500_return,
            "outperformance": portfolio_return - sp500_return,
            "portfolio_start_value": portfolio_start_value,
            "portfolio_end_value": portfolio_end_value,
            "sp500_start": sp500_start,
            "sp500_end": sp500_end,
            "stock_breakdown": stock_breakdown,
            "ai_commentary": ai_commentary
        }
    except Exception as e:
        print(f"❌ Error in backtest: {e}")
        return {"success": False, "error": str(e)}

def generate_mentor_drawdown_response(user_message: str) -> dict:
    """
    Deterministic mentor response generator for portfolio drawdown questions.
    Uses ONLY QUICK data (no LLM). Returns None if not triggered.
    """
    try:
        # Check for drawdown keywords
        drawdown_keywords = ["düşüş", "zarar", "neden", "niye", "2 gündür", "kayıp", "down", "drawdown", 
                            "düştü", "düşüyor", "kaybediyorum", "kaybediyor", "negatif", "eksi"]
        user_lower = user_message.lower()
        
        # Check if message contains drawdown-related keywords
        has_drawdown_keyword = any(keyword in user_lower for keyword in drawdown_keywords)
        if not has_drawdown_keyword:
            return None  # Not a drawdown question, return None to continue with normal flow
        
        print(f"📊 Drawdown question detected, generating QUICK mentor response...")
        
        # Get portfolio data
        from database import get_portfolio
        portfolio = get_portfolio()
        
        if not portfolio or len(portfolio) == 0:
            return {
                "success": True,
                "response": "Portföyünüzde henüz pozisyon yok. Portföy analizi yapmak için önce pozisyon ekleyin.",
                "use_llm": False
            }
        
        # Run QUICK portfolio analysis (no LLM)
        portfolio_analysis = analyze_portfolio(portfolio, use_llm=False, force=False, detail_level="detailed")
        
        if not portfolio_analysis.get("success"):
            return {
                "success": True,
                "response": "Portföy verileri alınamadı. Lütfen daha sonra tekrar deneyin.",
                "use_llm": False
            }
        
        # Extract data from analysis
        holdings = portfolio_analysis.get("holdings", [])
        risk = portfolio_analysis.get("risk", {})
        news = portfolio_analysis.get("news", [])
        portfolio_summary = portfolio_analysis.get("portfolio", {})
        
        if not holdings:
            return {
                "success": True,
                "response": "Portföy verileri bulunamadı.",
                "use_llm": False
            }
        
        # A) Quick diagnosis: Find worst contributors
        # Sort by PnL (worst first)
        sorted_by_pnl = sorted(holdings, key=lambda x: x.get("pnl_percent", 0))
        worst_contributors = sorted_by_pnl[:2]  # Top 1-2 worst
        
        # Calculate contribution (weight * pnl_percent)
        for holding in holdings:
            weight = holding.get("weight_percent", 0)
            pnl = holding.get("pnl_percent", 0)
            holding["contribution"] = weight * abs(pnl) / 100  # Contribution to portfolio change
        
        sorted_by_contribution = sorted(holdings, key=lambda x: x.get("contribution", 0), reverse=True)
        top_contributors = sorted_by_contribution[:2]
        
        # B) Concentration analysis
        concentration = risk.get("concentration", {})
        top3_weight = 0
        if holdings:
            sorted_by_weight = sorted(holdings, key=lambda x: x.get("weight_percent", 0), reverse=True)
            top3_weight = sum(h.get("weight_percent", 0) for h in sorted_by_weight[:3])
        
        concentration_level = "yüksek" if top3_weight >= 70 else "orta" if top3_weight >= 50 else "düşük"
        
        # C) Volatility/RSI analysis
        volatility = risk.get("volatility", {})
        volatility_note = volatility.get("note_tr", "Volatilite verisi mevcut değil")
        
        # Calculate weighted RSI
        weighted_rsi = 50  # Default
        total_weight = 0
        rsi_sum = 0
        for holding in holdings:
            weight = holding.get("weight_percent", 0)
            rsi = holding.get("rsi", 50)
            if rsi and rsi > 0:
                rsi_sum += rsi * weight
                total_weight += weight
        
        if total_weight > 0:
            weighted_rsi = rsi_sum / total_weight
        
        rsi_status = "Aşırı alım" if weighted_rsi >= 70 else "Aşırı satım" if weighted_rsi <= 30 else "Normal"
        volatility_signal = "HIGH" if weighted_rsi >= 70 or weighted_rsi <= 30 else "MED" if abs(weighted_rsi - 50) >= 10 else "LOW"
        
        # D) News impact analysis
        bearish_count = 0
        news_matches_holdings = False
        portfolio_symbols = [h.get("symbol", "").upper() for h in holdings]
        
        for news_item in news[:10]:  # Check top 10 news items
            title = news_item.get("title", "").upper()
            impact = news_item.get("impact", "neutral").lower()
            
            # Check if news mentions any portfolio symbol
            for symbol in portfolio_symbols:
                if symbol in title or title.find(symbol) >= 0:
                    news_matches_holdings = True
                    break
            
            # Count bearish news
            if impact in ["negative", "bearish", "bear"]:
                bearish_count += 1
        
        # E) Market-wide risk (try to get QQQ/SPY if available)
        market_risk_note = "Genel piyasa verisi mevcut değil"
        try:
            # Try to get SPY or QQQ data as market proxy using yfinance directly
            for market_symbol in ["SPY", "QQQ"]:
                try:
                    ticker = yf.Ticker(market_symbol)
                    hist = ticker.history(period="2d")
                    if not hist.empty and len(hist) >= 2:
                        current_price = hist['Close'].iloc[-1]
                        prev_price = hist['Close'].iloc[-2]
                        change_pct = ((current_price - prev_price) / prev_price) * 100
                        
                        if change_pct < -1:
                            market_risk_note = f"{market_symbol} son dönemde %{abs(change_pct):.1f} düşüş gösteriyor - Genel piyasa riski yüksek"
                        elif change_pct < 0:
                            market_risk_note = f"{market_symbol} hafif düşüşte (%{abs(change_pct):.1f}) - Genel piyasa riski orta"
                        else:
                            market_risk_note = f"{market_symbol} pozitif (%{change_pct:.1f}%) - Genel piyasa riski düşük"
                        break
                except Exception as e:
                    print(f"⚠️ Could not get {market_symbol} data: {e}")
                    continue
        except Exception as e:
            print(f"⚠️ Market data fetch error: {e}")
            pass
        
        # F) Sector/tech concentration check
        tech_symbols = ["AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "AMD", "INTC", "QQQ"]
        tech_holdings = [h for h in holdings if h.get("symbol", "").upper() in tech_symbols]
        tech_weight = sum(h.get("weight_percent", 0) for h in tech_holdings)
        sector_note = ""
        if tech_weight >= 50:
            sector_note = f"Teknoloji sektörü konsantrasyonu yüksek (%{tech_weight:.1f}) - Sektörel risk var"
        elif tech_weight >= 30:
            sector_note = f"Teknoloji sektörü ağırlığı orta (%{tech_weight:.1f})"
        
        # Build response
        response_parts = []
        
        # A) Quick diagnosis
        response_parts.append("📌 Hızlı Teşhis")
        if worst_contributors:
            worst_symbols = [h.get("symbol", "?") for h in worst_contributors]
            worst_pnls = [h.get("pnl_percent", 0) for h in worst_contributors]
            if len(worst_symbols) >= 2:
                response_parts.append(f"• Son dönem düşüşte en büyük katkı: {worst_symbols[0]} (%{worst_pnls[0]:.1f}) ve {worst_symbols[1]} (%{worst_pnls[1]:.1f})")
            else:
                response_parts.append(f"• Son dönem düşüşte en büyük katkı: {worst_symbols[0]} (%{worst_pnls[0]:.1f})")
        else:
            response_parts.append("• Düşüş katkısı analizi için yeterli veri yok")
        
        response_parts.append(f"• Konsantrasyon: Top 3 ağırlık = %{top3_weight:.1f} ({concentration_level})")
        response_parts.append(f"• Volatilite/RSI sinyali: {volatility_signal} - {rsi_status} (Ortalama RSI: {weighted_rsi:.1f})")
        
        # B) Likely drivers
        response_parts.append("")
        response_parts.append("🔎 Olası Nedenler")
        
        # Market-wide risk
        response_parts.append(f"1. {market_risk_note}")
        
        # Sector concentration
        if sector_note:
            response_parts.append(f"2. {sector_note}")
        
        # News impact
        if bearish_count > 0:
            news_note = f"3. {bearish_count} adet olumsuz haber tespit edildi"
            if news_matches_holdings:
                news_note += " - Bu haberler portföy pozisyonlarınızla ilgili"
            response_parts.append(news_note)
        else:
            response_parts.append("3. Haber etkisi: Önemli olumsuz haber tespit edilmedi")
        
        # C) Decision frames (NOT advice)
        response_parts.append("")
        response_parts.append("🧭 Disiplinli Sonraki Adımlar")
        response_parts.append("• Panik yerine: Zarar sınırın/planın var mı? Her pozisyon için stop-loss seviyesi belirledin mi?")
        response_parts.append("• Yeni alım düşünüyorsan: Portföy ağırlık hedefin bozuluyor mu? Konsantrasyon riski artıyor mu?")
        
        if top3_weight >= 70:
            response_parts.append("• Tek hisse riski yüksek: Kademeli dengeleme opsiyonlarını değerlendir. Top 3 pozisyon %70'i aşıyor.")
        elif top3_weight >= 50:
            response_parts.append("• Konsantrasyon orta seviyede: Tek hisse riski artmadan önce dengeleme düşünebilirsin.")
        
        response_parts.append("• Bugün için: Sadece izleme + alarm koşulları (eşik) belirle. Örnek: 'X sembolü %Y'nin altına düşerse bildirim al'")
        
        # D) Follow-up question
        response_parts.append("")
        if len(holdings) > 1:
            response_parts.append("💭 Bu düşüşte en çok rahatsız eden pozisyon hangisi?")
        else:
            response_parts.append("💭 Bu pozisyon kısa/orta/uzun vade mi?")
        
        final_response = "\n".join(response_parts)
        
        return {
            "success": True,
            "response": final_response,
            "use_llm": False,
            "mentor_mode": "drawdown_quick"
        }
        
    except Exception as e:
        print(f"⚠️ Error in generate_mentor_drawdown_response: {e}")
        import traceback
        traceback.print_exc()
        return None  # Return None to fall back to normal LLM flow

def chat_with_mentor(user_message: str, context_data: dict = None) -> dict:
    """AI Investment Mentor: Answer user questions with context awareness."""
    try:
        if not user_message or len(user_message.strip()) == 0:
            return {
                "success": False,
                "response": "Lütfen bir soru yazın.",
                "error": "Empty message"
            }
        
        print(f"💬 Chat request received: {user_message[:50]}...")
        print(f"📊 Context data: {context_data}")
        
        # ========================================================================
        # CHECK FOR DRAWDOWN QUESTIONS FIRST (QUICK mode, no LLM)
        # ========================================================================
        mentor_drawdown_response = generate_mentor_drawdown_response(user_message)
        if mentor_drawdown_response is not None:
            print(f"✅ Mentor drawdown response generated (QUICK mode, no LLM)")
            return mentor_drawdown_response
        
        # Build context string from provided data
        context_str = ""
        if context_data and isinstance(context_data, dict):
            if "type" in context_data:
                if context_data["type"] == "stock":
                    # Stock context: Price, RSI, News, etc.
                    symbol = context_data.get("symbol", "Unknown")
                    price = context_data.get("price", 0) or 0
                    rsi = context_data.get("rsi", 0) or 0
                    fair_value = context_data.get("fair_value")
                    news_summary = context_data.get("news_summary", "") or ""
                    mode = context_data.get("mode", "STOCK")
                    
                    fair_value_str = f"${fair_value:.2f}" if fair_value and fair_value > 0 else "Hesaplanamadı"
                    
                    # CONTEXT-AWARE: Fetch last mentor decision for this symbol
                    last_decision_context = ""
                    try:
                        last_decision = get_last_decision_for_symbol(symbol, mode)
                        if last_decision:
                            decision = last_decision.get("decision", "HOLD")
                            verdict = last_decision.get("verdict", "TUT")
                            price_at_analysis = last_decision.get("price_at_analysis", 0)
                            confidence = last_decision.get("confidence", 50)
                            created_at = last_decision.get("created_at", "")
                            key_reasoning = last_decision.get("key_reasoning", "")
                            
                            # Calculate price change since last decision
                            price_change_pct = 0
                            if price_at_analysis and price_at_analysis > 0:
                                price_change_pct = ((price - price_at_analysis) / price_at_analysis) * 100
                            
                            last_decision_context = f"""
- Son Mentor Kararı: {verdict} ({decision}) - Güven: {confidence}%
- Karar Zamanı: {created_at}
- Karar Fiyatı: ${price_at_analysis:.2f} → Şimdi: ${price:.2f} ({price_change_pct:+.1f}%)
- Gerekçe: {key_reasoning[:150]}"""
                    except Exception as e:
                        print(f"⚠️ Could not fetch last decision for {symbol}: {e}")
                    
                    context_str = f"""
MEVCUT HİSSE BİLGİLERİ:
- Sembol: {symbol}
- Mevcut Fiyat: ${price:.2f}
- RSI: {rsi:.1f}
- Adil Değer: {fair_value_str}
- Son Haberler: {news_summary[:200] if news_summary else 'Yok'}{last_decision_context}
"""
                elif context_data["type"] == "portfolio":
                    # Portfolio context: Summary, holdings, etc.
                    total_value = context_data.get("total_value", 0) or 0
                    total_pnl = context_data.get("total_pnl", 0) or 0
                    holdings_count = context_data.get("holdings_count", 0) or 0
                    
                    # Try to get latest portfolio analysis for mentor context
                    latest_mentor_decision = ""
                    try:
                        from .database import get_latest_portfolio_analysis
                        latest_analysis = get_latest_portfolio_analysis()
                        if latest_analysis and isinstance(latest_analysis, dict):
                            mentor = latest_analysis.get("mentor", {})
                            if mentor:
                                decision = mentor.get("decision", "")
                                confidence = mentor.get("confidence", 0)
                                summary = mentor.get("summary_tr", "")
                                if decision and summary:
                                    latest_mentor_decision = f"\n- Son Mentor Kararı: {decision} (Güven: {confidence}%) - {summary}"
                    except Exception as e:
                        print(f"⚠️ Could not fetch latest mentor decision: {e}")
                    
                    context_str = f"""
PORTFÖY ÖZETİ:
- Toplam Değer: ${total_value:.2f}
- Toplam P/L: ${total_pnl:.2f}
- Hisse Sayısı: {holdings_count}{latest_mentor_decision}
"""
        
        # Check for transaction extraction first
        transaction_extracted = None
        transaction_prompt = f"""Kullanıcının mesajında bir portföy işlemi (alım/satım) var mı? Mesaj: "{user_message}"

Eğer alım/satım varsa, şu JSON formatında döndür:
{{
    "has_transaction": true,
    "symbol": "NVDA",
    "quantity": 10,
    "price": 180.0,
    "type": "BUY" veya "SELL"
}}

Eğer yoksa:
{{
    "has_transaction": false
}}

Örnekler:
- "10 adet NVDA aldım 180'den" -> {{"has_transaction": true, "symbol": "NVDA", "quantity": 10, "price": 180, "type": "BUY"}}
- "5 TSLA sattım" -> {{"has_transaction": true, "symbol": "TSLA", "quantity": 5, "type": "SELL"}}
- "NVDA almayı düşünüyorum" -> {{"has_transaction": false}}
"""
        
        try:
            # Use unified gemini_json function
            try:
                extract_json = safe_gemini_call(transaction_prompt, response_mode="json", max_retries=1, purpose="chat_transaction_extraction")
            except GeminiCallError:
                extract_json = None
            
            if extract_json is None:
                extract_json = {"has_transaction": False}
            
            if extract_json.get("has_transaction"):
                transaction_extracted = {
                    "symbol": extract_json.get("symbol", "").upper(),
                    "quantity": float(extract_json.get("quantity", 0)),
                    "price": float(extract_json.get("price", 0)),
                    "type": extract_json.get("type", "BUY").upper()
                }
                print(f"✅ Transaction extracted: {transaction_extracted}")
        except Exception as e:
            print(f"⚠️ Transaction extraction failed: {e}")
            transaction_extracted = None
        
        # If transaction extracted, add it to portfolio
        transaction_message = ""
        if transaction_extracted:
            try:
                from .database import add_portfolio_transaction
                result = add_portfolio_transaction(
                    transaction_extracted["symbol"],
                    transaction_extracted["quantity"],
                    transaction_extracted["price"],
                    transaction_extracted["type"]
                )
                if result.get("success"):
                    if transaction_extracted["type"] == "BUY":
                        transaction_message = f"✅ Tamamdır, {transaction_extracted['quantity']} adet {transaction_extracted['symbol']} portföyüne eklendi. Yeni durumunu analiz etmemi ister misin?"
                    else:
                        transaction_message = f"✅ Tamamdır, {transaction_extracted['quantity']} adet {transaction_extracted['symbol']} portföyünden çıkarıldı."
                else:
                    transaction_message = f"⚠️ İşlem kaydedilirken hata: {result.get('message', 'Bilinmeyen hata')}"
            except Exception as e:
                print(f"❌ Error adding transaction: {e}")
                transaction_message = f"⚠️ İşlem kaydedilemedi: {str(e)}"
        
        # System prompt for Investment Mentor
        system_prompt = """You are an AI Investment Mentor, not a chatbot.

Your role:
- Act as a disciplined, risk-first investment mentor.
- Do NOT hype, do NOT guess, do NOT overtrade.
- Capital preservation > profit.

Core rules:
1. Every response must start with a clear stance:
   EXECUTE | WAIT | REDUCE | AVOID
2. Never give advice without stating WHY.
3. If data is insufficient, say WAIT and request exactly what is missing.
4. Prefer not acting over acting.
5. **CONTEXT-AWARE**: Use past mentor decisions to improve future advice.
   - If "Son Mentor Kararı" is provided, ALWAYS reference it in your response.
   - Compare current situation with the last decision (price change, RSI change, etc.)
   - Explain if your stance has changed and WHY.
   - Example: "Geçen sefer AL dedik $150'den. Şimdi $165'te (+10%). RSI 75'e yükseldi, kar kilitleme zamanı."

When user asks:
- "buy/sell/add" → simulate first, then advise
- "analyze" → use QUICK unless explicitly DEEP
- "advice" → give mentor-style decision, not generic analysis
- "what if" → run scenario logic

Response format (STRICTLY FOLLOW THIS):
- Decision (1 word: EXECUTE | WAIT | REDUCE | AVOID)
- 1-sentence summary
- 2–3 bullet reasons (WHY) - MUST include comparison with last decision if available
- 1–3 action steps (if any)
- Risk note (1 sentence)

Tone:
- Calm
- Mentor-like
- Clear
- No emojis
- No financial hype

Goal:
User should trust you more than charts."""
        
        # Build full prompt with enhanced instructions
        user_intent = ""
        user_message_lower = user_message.lower()
        if any(word in user_message_lower for word in ["al", "buy", "sat", "sell", "ekle", "add"]):
            user_intent = "\n\nÖNEMLİ: Kullanıcı bir işlem (alım/satım) yapmak istiyor. Önce bu işlemin portföy üzerindeki etkisini simüle et, sonra tavsiye ver."
        elif "analiz" in user_message_lower and "deep" not in user_message_lower and "derin" not in user_message_lower:
            user_intent = "\n\nNOT: Kullanıcı analiz istiyor. QUICK analiz modunu kullan (DEEP değil)."
        elif "tavsiye" in user_message_lower or "advice" in user_message_lower:
            user_intent = "\n\nNOT: Kullanıcı mentor tavsiyesi istiyor. Generic analiz değil, net bir karar (EXECUTE/WAIT/REDUCE/AVOID) ve gerekçeler ver."
        elif "what if" in user_message_lower or "ya" in user_message_lower or "eğer" in user_message_lower:
            user_intent = "\n\nNOT: Kullanıcı senaryo analizi istiyor. Senaryo mantığını çalıştır ve farklı sonuçları değerlendir."
        
        # Build full prompt
        full_prompt = f"""{system_prompt}

{context_str}

KULLANICI SORUSU: {user_message}
{('İŞLEM: ' + transaction_message) if transaction_message else ''}{user_intent}

YANIT FORMATI (BU FORMAT'A UYGUN CEVAP VER):
1. Decision (tek kelime): EXECUTE | WAIT | REDUCE | AVOID
2. Özet (1 cümle)
3. Gerekçeler (2-3 madde, WHY)
4. Aksiyonlar (1-3 adım, eğer varsa)
5. Risk Notu (1 cümle)

Eğer yeterli veri yoksa WAIT de ve tam olarak ne eksik olduğunu belirt. Context'teki bilgileri kullanarak spesifik tavsiyeler ver. {('Kullanıcı bir işlem yaptı, bunu değerlendir ve portföy durumunu analiz et.' if transaction_message else '')}"""
        
        print(f"📝 Sending prompt to Gemini...")
        
        # Use unified gemini_text function
        result = gemini_text(full_prompt)
        
        if result["fallback"] or not result.get("text"):
            response_text = "Üzgünüm, şu anda AI servisi kullanılamıyor (API kotası aşıldı). Lütfen birkaç dakika sonra tekrar deneyin."
            print(f"⚠️ API quota exceeded, using fallback message")
        else:
            response_text = result["text"]
            print(f"✅ Got response: {response_text[:100]}...")
        
        # Combine transaction message with AI response
        final_response = response_text
        if transaction_message:
            final_response = f"{transaction_message}\n\n{response_text}"
        
        return {
            "success": True,
            "response": final_response,
            "context_used": context_data is not None,
            "transaction_processed": transaction_extracted is not None
        }
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Error in chat_with_mentor: {e}")
        print(f"📋 Traceback: {error_trace}")
        return {
            "success": False,
            "response": f"Üzgünüm, bir hata oluştu: {str(e)}. Lütfen tekrar deneyin.",
            "error": str(e)
        }

def whale_watch(symbols: list) -> dict:
    """Monitor institutional holders (whales) and insider transactions for given symbols.
    Uses services/whale_service.py for comprehensive BUY/SELL transaction data."""
    try:
        # Use the dedicated whale service for better organization
        from services.whale_service import get_whale_activity
        return get_whale_activity(symbols)
    except ImportError:
        # Fallback to inline implementation if service not available
        whale_funds = ["Vanguard", "BlackRock", "State Street", "Fidelity", "Berkshire", "T. Rowe Price"]
        whale_activity = []
        insider_transactions = []
        
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                
                # Get institutional holders
                institutional_holders = ticker.institutional_holders
                
                if institutional_holders is not None and len(institutional_holders) > 0:
                    for _, holder in institutional_holders.iterrows():
                        holder_name = holder.get("Holder", "")
                        shares = holder.get("Shares", 0)
                        value = holder.get("Value", 0)
                        
                        # Check if it's a whale fund
                        is_whale = any(whale in holder_name for whale in whale_funds)
                        
                        if is_whale:
                            whale_activity.append({
                                "symbol": symbol,
                                "holder": holder_name,
                                "shares": int(shares) if pd.notna(shares) else 0,
                                "value": float(value) if pd.notna(value) else 0,
                                "is_whale": True
                            })
                
                # Get insider transactions (NEW)
                try:
                    insider_data = ticker.insider_transactions
                    if insider_data is not None and len(insider_data) > 0:
                        # Get most recent 10 transactions
                        for _, transaction in insider_data.head(10).iterrows():
                            person = transaction.get("Name", "N/A")
                            transaction_type = transaction.get("Transaction", "")
                            transaction_code = transaction.get("TransactionCode", "")
                            shares = transaction.get("Shares", 0)
                            date = transaction.get("Date", "")
                            
                            # Determine if it's BUY or SELL
                            is_buy = False
                            if transaction_type:
                                transaction_lower = transaction_type.lower()
                                if any(word in transaction_lower for word in ["purchase", "buy", "acquisition", "option"]):
                                    is_buy = True
                                elif any(word in transaction_lower for word in ["sale", "sell", "disposition"]):
                                    is_buy = False
                            
                            # Transaction code interpretation
                            if transaction_code:
                                code_str = str(transaction_code).upper()
                                if "P" in code_str or "A" in code_str:
                                    is_buy = True
                                elif "S" in code_str or "D" in code_str:
                                    is_buy = False
                            
                            insider_transactions.append({
                                "symbol": symbol,
                                "person": person,
                                "type": "BUY" if is_buy else "SELL",
                                "shares": int(shares) if pd.notna(shares) else 0,
                                "date": str(date) if pd.notna(date) else "N/A",
                                "transaction_code": str(transaction_code) if pd.notna(transaction_code) else ""
                            })
                except Exception as insider_error:
                    print(f"⚠️ Insider transactions not available for {symbol}: {insider_error}")
                    # Continue even if insider data is not available
                    
            except Exception as e:
                print(f"⚠️ Error fetching whale data for {symbol}: {e}")
                continue
        
        return {
            "success": True,
            "whale_activity": whale_activity,
            "insider_transactions": insider_transactions,
            "whale_count": len(whale_activity),
            "insider_count": len(insider_transactions),
            "message": f"Found {len(whale_activity)} whale positions and {len(insider_transactions)} insider transactions"
        }
    except Exception as e:
        print(f"❌ Error in whale watch: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
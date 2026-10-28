# Playground/BR/agent/main.py
import os
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types
from google.cloud import firestore
from google.oauth2 import service_account

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("global_report_two_step")

# ---------- Env / Clients ----------
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
FIREBASE_SERVICE_ACCOUNT = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
PROJECT_ID = os.environ.get("PROJECT_ID")
FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "br-prod-db")
MODEL = os.environ.get("GLOBAL_REPORT_MODEL", "gemini-2.5-flash")

if not GOOGLE_API_KEY:
    raise RuntimeError("GOOGLE_API_KEY is required")

client = genai.Client(api_key=GOOGLE_API_KEY)
# Step 1 uses tools (Google Search); Step 2 does not
grounding_tool = types.Tool(google_search=types.GoogleSearch())

def get_firestore_client():
    """Service-account JSON if provided, else Application Default Credentials (Cloud Run identity)."""
    if not PROJECT_ID:
        raise RuntimeError("PROJECT_ID is required")
    if FIREBASE_SERVICE_ACCOUNT:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(FIREBASE_SERVICE_ACCOUNT)
        )
        return firestore.Client(credentials=creds, project=PROJECT_ID, database=FIRESTORE_DATABASE)
    return firestore.Client(project=PROJECT_ID, database=FIRESTORE_DATABASE)

# ---------- Utils ----------
def _extract_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise RuntimeError("Model did not return valid JSON")

def hour_doc_id(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d-%H")

def _sentence_count(text: str) -> int:
    # Split on sentence punctuation, but ignore decimals (e.g., 0.3)
    parts = [p.strip() for p in re.split(r'(?<!\d)[.!?]+(?!\d)', text) if p.strip()]
    return len(parts)

def _has_digits(text: str) -> bool:
    return any(ch.isdigit() for ch in text)

def _mentions_indexes(text: str) -> bool:
    t = text.lower()
    has_spx = ("s&p 500" in t) or ("s&p" in t) or ("spx" in t)
    has_dow = ("dow jones" in t) or ("dow" in t) or ("djia" in t)
    has_nasdaq = ("nasdaq" in t) or ("ndx" in t)
    return has_spx and has_dow and has_nasdaq

# ---------- Prompts ----------
def build_fact_pack_prompt(now_iso: str) -> str:
    return f"""
You are a markets researcher. Use web search to collect verifiable, RECENT facts as of {now_iso} (UTC).

Rules:
- Only include facts from credible sources (major financial media, exchanges, data providers, tech companies stock partnerships).
- Prefer last 24h. If you cannot verify a number, omit it (do not guess).
- Focus on equities first; then rates, FX, and commodities for context.
- Output ONLY JSON. No extra text.

Return EXACTLY this JSON schema:
{{
  "as_of_utc": "{now_iso}",
  "top_indexes": [
    {{
      "name": "S&P 500",
      "last": "numeric level if available, else empty string",
      "change_points": "e.g., +39.13 or -12.4, else empty string",
      "change_percent": "e.g., +0.58% or -0.3%, else empty string",
      "session_context": "close|midday|futures",
      "source_url": "credible source URL"
    }},
    {{
      "name": "Dow Jones Industrial Average",
      "last": "numeric level if available, else empty string",
      "change_points": "e.g., +120.5 or -80.2, else empty string",
      "change_percent": "e.g., +0.3% or -0.2%, else empty string",
      "session_context": "close|midday|futures",
      "source_url": "credible source URL"
    }},
    {{
      "name": "Nasdaq Composite",
      "last": "numeric level if available, else empty string",
      "change_points": "e.g., +255.0 or -90.3, else empty string",
      "change_percent": "e.g., +1.1% or -0.4%, else empty string",
      "session_context": "close|midday|futures",
      "source_url": "credible source URL"
    }}
  ],
  "notable_movers": [
    {{
      "ticker_or_asset": "AAPL|NVDA|WTI|Gold|DXY|etc.",
      "direction": "up|down|flat",
      "magnitude": "optional number/percent if verified, else empty",
      "driver": "earnings|guidance|macro|regulation|geopolitics",
      "source_url": "credible source URL"
    }}
  ],
  "macro_events": [
    {{
      "title": "CPI|Fed|Payrolls|Earnings|PMIs|etc.",
      "timing": "date/time window if applicable",
      "summary": "1–2 sentence factual summary",
      "source_url": "credible source URL"
    }}
  ],
  "upcoming_watch": [
    {{
      "item": "event or catalyst to watch (e.g., Fed remarks, CPI release, earnings)",
      "why_it_matters": "short reason",
      "timing": "expected timing",
      "source_url": "credible source URL"
    }}
  ]
}}

Constraints:
- Keep arrays concise (3 items in top_indexes as defined; 2–4 items for others).
- JSON only.
""".strip()

def build_composition_prompt(facts: Dict[str, Any], now_iso: str) -> str:
    style_example = {
      "headline": "Stocks Edge Lower as Yields Firm; Nasdaq Lags on Chip Weakness",
      "headline_summary": "U.S. equities trade mixed as higher long-end yields pressure growth while defensives stabilize. Energy outperforms on supply concerns and a softer dollar. Investors focus on Fed remarks and a busy earnings slate.",
      "key_movements": "S&P 500 slips 0.3% to 6,742 as breadth narrows and rates weigh on multiples. Dow Jones Industrial Average dips 0.2% to 41,120 with financials mixed. Nasdaq Composite falls 0.8% to 23,010 as semiconductors underperform on inventory and export headlines.",
      "implications": "Firmer yields keep duration-sensitive pockets choppy and cap multiple expansion. Commodity strength and a softer dollar favor energy and exporters at the margin. Fed tone and incoming earnings remain decisive for rates, the dollar, and cross-asset volatility.",
      "watch_points": "Fed Chair remarks later today guide the near-term rates path and risk tone. CPI print on Thursday shapes real-yield expectations and equity risk premia. Mega-cap earnings will test AI spend efficiency and margin durability."
    }
    facts_json = json.dumps(facts, ensure_ascii=False)

    return f"""
You are a professional financial news writer. Compose a concise, wire-style global market report using ONLY the verified facts below.

Facts (verbatim JSON):
{facts_json}

Hard requirements:
- Present tense, newswire tone (concise, factual; no politics/gossip).
- Equities-first focus; Key Movements must mention S&P 500, Dow, and Nasdaq.
- Output ONLY valid JSON with EXACT fields: headline, headline_summary, key_movements, implications, watch_points.
- headline: ≤25 words; no date in headline.
- headline_summary: 3-5 sentences; straight news, no opinion.
- key_movements: 3-5 sentences in this order:
  1) S&P 500 — include level and/or points/percent if present in facts.
  2) Dow Jones Industrial Average — include level and/or points/percent if present in facts.
  3) Nasdaq Composite — include level and/or points/percent if present in facts.
  4) Any Major Market Movers — include level and/or points/percent if present in facts.
  If a verified number is missing for an index, write a directional sentence without numbers (do not invent).
- implications: 3-4 sentences; tie to verified rates/FX/commodity or macro context from facts.
- watch_points: 3-4 sentences; near-term catalysts and why they matter.
- No bullet points; sentences only. No extra fields.

Style guidance (format only, do not copy content):
{json.dumps(style_example, ensure_ascii=False, indent=2)}

Return ONLY the JSON object with the five fields.
""".strip()

# ---------- LLM Calls ----------
def generate_fact_pack(model: str = MODEL) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    prompt = build_fact_pack_prompt(now_iso)
    # Step 1: WITH tools, NO response_mime_type (tools + JSON mime not allowed together)
    config = types.GenerateContentConfig(tools=[grounding_tool])
    resp = client.models.generate_content(model=model, contents=prompt, config=config)
    raw = getattr(resp, "text", "") or ""
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Fact pack must be a JSON object")
    data["as_of_utc"] = now_iso
    return data

# --- Add this helper (no tools; JSON-only) ---
def repair_headline_summary(facts: Dict[str, Any], current_text: str, model: str = MODEL) -> str:
    """
    Rewrites headline_summary into 2–4 present-tense sentences using ONLY facts.
    """
    facts_json = json.dumps({
        "top_indexes": facts.get("top_indexes", []),
        "notable_movers": facts.get("notable_movers", []),
        "macro_events": facts.get("macro_events", []),
    }, ensure_ascii=False)
    prompt = f"""
You are a formatter. Using ONLY the verifiable facts in the JSON below, rewrite the headline_summary into 2–4 sentences (prefer 3), present-tense, wire-style, no speculation.

Facts:
{facts_json}

Return ONLY JSON:
{{"headline_summary": "..."}}.
""".strip()
    config = types.GenerateContentConfig(response_mime_type="application/json")
    resp = client.models.generate_content(model=model, contents=prompt, config=config)
    raw = getattr(resp, "text", "") or ""
    data = _extract_json(raw)
    out = (data.get("headline_summary") or "").strip()
    if not out:
        raise RuntimeError("Failed to repair headline_summary")
    return out

def force_format_key_movements(facts: Dict[str, Any], model: str = MODEL) -> str:
    """
    Rewrites key_movements into exactly 3 sentences, one per index (S&P 500, Dow, Nasdaq),
    using ONLY numbers present in facts.top_indexes. Returns the corrected string.
    """
    facts_json = json.dumps({"top_indexes": facts.get("top_indexes", [])}, ensure_ascii=False)
    prompt = f"""
You are a formatter. Using ONLY the numeric data in the JSON facts below, produce a single string with 3-5 sentences in this order:
1) S&P 500 sentence, including any verified level and/or points/percent from facts.
2) Dow Jones Industrial Average sentence, including any verified level and/or points/percent from facts.
3) Nasdaq Composite sentence, including any verified level and/or points/percent from facts.
4) Any Major Market Movers sentence, including any verified level and/or points/percent from facts.

Facts:
{facts_json}

Rules:
- Present tense, newswire tone.
- Do NOT invent numbers; if a number is missing for an index, write a directional sentence without numbers.
- No bullet points; sentences only.
- Return ONLY JSON: {{"key_movements": "..."}}.
""".strip()

    config = types.GenerateContentConfig(response_mime_type="application/json")
    resp = client.models.generate_content(model=model, contents=prompt, config=config)
    raw = getattr(resp, "text", "") or ""
    data = _extract_json(raw)
    km = (data.get("key_movements") or "").strip()
    if not km:
        raise RuntimeError("Failed to repair key_movements")
    return km

# --- Replace your compose_report with this version (only the try/except block changed) ---
def compose_report(facts: Dict[str, Any], model: str = MODEL) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    prompt = build_composition_prompt(facts, now_iso)

    def _call(prompt_text: str) -> Dict[str, Any]:
        config = types.GenerateContentConfig(response_mime_type="application/json")
        resp = client.models.generate_content(model=model, contents=prompt_text, config=config)
        raw = getattr(resp, "text", "") or ""
        return _extract_json(raw)

    data = _call(prompt)

    return {
        "headline": data["headline"].strip(),
        "headline_summary": data["headline_summary"].strip(),
        "key_movements": data["key_movements"].strip(),
        "implications": data["implications"].strip(),
        "watch_points": data["watch_points"].strip(),
        "generated_at": now_iso,
        "model": model,
    }
    
# ---------- Firestore ----------
def write_report(db: firestore.Client, doc_id: str, payload: Dict[str, Any]) -> None:
    db.collection("reports").document(doc_id).set(payload, merge=True)

# ---------- Runner ----------
def run_once(dry_run: bool = False, model: str = MODEL) -> Dict[str, Any]:
    logger.info("Step 1: collecting verifiable facts via search...")
    facts = generate_fact_pack(model=model)

    logger.info("Step 2: composing final JSON report from facts...")
    report = compose_report(facts=facts, model=model)

    doc_id = hour_doc_id()
    payload = {
        "generated_at": report["generated_at"],
        "headline": report["headline"],
        "headline_summary": report["headline_summary"],
        "key_movements": report["key_movements"],
        "implications": report["implications"],
        "watch_points": report["watch_points"],
        "model": report["model"],
        "facts": facts,  # stored for traceability
    }

    if dry_run:
        logger.info(f"[DRY RUN] Would write to br-prod-db/reports/{doc_id}")
        return {"doc_id": doc_id, "report": payload}

    db = get_firestore_client()
    write_report(db, doc_id, payload)
    logger.info(f"Saved global report to br-prod-db/reports/{doc_id}")
    return {"doc_id": doc_id, "ok": True}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Global market report (two-step; hourly doc)")
    parser.add_argument("--dry-run", action="store_true", help="Generate but do not write to Firestore")
    parser.add_argument("--model", default=MODEL, help="Override model (default: gemini-2.5-flash)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    result = run_once(dry_run=args.dry_run, model=args.model)
    print(json.dumps(result, indent=2))
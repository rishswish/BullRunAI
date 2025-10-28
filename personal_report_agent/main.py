# Playground/BR/personal_report_agent/main.py
import os
import json
import logging
import re
import requests
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, List

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types
from google.cloud import firestore
from google.oauth2 import service_account
from snaptrade_client import SnapTrade

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("personal_report_agent")

# ---------- Env / Clients ----------
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
FIREBASE_SERVICE_ACCOUNT = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
PROJECT_ID = os.environ.get("PROJECT_ID")
MODEL = os.environ.get("PERSONAL_REPORT_MODEL", "gemini-2.5-flash")
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY")
SNAPTRADE_CONSUMER_KEY = os.environ.get("SNAPTRADE_CONSUMER_KEY")
SNAPTRADE_CLIENT_ID = os.environ.get("SNAPTRADE_CLIENT_ID")

if not GOOGLE_API_KEY:
    raise RuntimeError("GOOGLE_API_KEY is required")

client = genai.Client(api_key=GOOGLE_API_KEY)
# Add grounding tool for web search
grounding_tool = types.Tool(google_search=types.GoogleSearch())

def get_firestore_client():
    if not FIREBASE_SERVICE_ACCOUNT or not PROJECT_ID:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT and PROJECT_ID are required")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(FIREBASE_SERVICE_ACCOUNT)
    )
    # Target 'br-prod-db' database (same as global agent)
    return firestore.Client(credentials=creds, project=PROJECT_ID, database="br-prod-db")

def get_snaptrade_client():
    if not SNAPTRADE_CONSUMER_KEY or not SNAPTRADE_CLIENT_ID:
        raise RuntimeError("Missing SNAPTRADE_CONSUMER_KEY or SNAPTRADE_CLIENT_ID")
    return SnapTrade(
        consumer_key=SNAPTRADE_CONSUMER_KEY,
        client_id=SNAPTRADE_CLIENT_ID,
    )

# ---------- Utils ----------
def _extract_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise RuntimeError("Model did not return valid JSON")

def date_doc_id(dt: Optional[datetime] = None) -> str:
    """Generate date-based document ID (YYYY-MM-DD)"""
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")

def _get_snaptrade_info(doc_dict: dict):
    """Extract SnapTrade credentials from user document"""
    d = doc_dict or {}
    uid = d.get("snaptrade_user_id")
    sec = d.get("snaptrade_user_secret")
    if uid and sec:
        return {"userId": uid, "userSecret": sec}
    return None

def _extract_symbol_and_name(position: dict):
    """Helper to extract symbol and name from SnapTrade position data"""
    sym_field = position.get('symbol')
    ticker = None
    name = None

    if isinstance(sym_field, dict):
        inner = sym_field.get('symbol') or sym_field.get('ticker')
        if isinstance(inner, dict):
            ticker = inner.get('symbol') or inner.get('ticker')
            name = inner.get('description') or inner.get('name')
        else:
            ticker = inner
            name = sym_field.get('description') or sym_field.get('name')
    else:
        ticker = sym_field

    if not ticker:
        ticker = position.get('ticker')
    if not ticker:
        uni = position.get('universal_symbol') or {}
        if isinstance(uni, dict):
            ticker = uni.get('symbol')
            if not name:
                name = uni.get('description') or uni.get('name')

    if not name:
        name = position.get('description') or position.get('name')

    if isinstance(ticker, dict):
        ticker = ticker.get('symbol') or ticker.get('ticker') or ''
    if isinstance(name, dict):
        name = name.get('description') or name.get('name') or ''

    return str(ticker or ''), str(name or '')

def get_portfolio_data(user_email: str, snaptrade_info: Dict[str, str]) -> Dict[str, Any]:
    """Fetch portfolio data from SnapTrade API"""
    if not snaptrade_info:
        return {
            "hasConnectedAccounts": False,
            "totals": {"totalBalance": 0.0, "totalInvestments": 0.0},
            "positions": [],
            "topHoldings": []
        }

    try:
        st_client = get_snaptrade_client()
        uid = snaptrade_info["userId"]
        sec = snaptrade_info["userSecret"]

        # Get accounts
        accounts_resp = st_client.account_information.list_user_accounts(
            user_id=uid, user_secret=sec
        )
        accounts = (accounts_resp.body or [])

        total_balance = 0.0
        total_investments = 0.0
        all_positions = []

        for acct in accounts:
            account_id = acct.get('id') or acct.get('account_id') or acct.get('accountId')
            
            # Get balances
            try:
                bal_resp = st_client.account_information.get_user_account_balance(
                    user_id=uid, user_secret=sec, account_id=account_id
                )
                for b in (bal_resp.body or []):
                    amount = b.get('cash') or b.get('amount') or b.get('balance') or 0.0
                    total_balance += float(amount or 0)
            except Exception:
                pass

            # Get positions
            try:
                pos_resp = st_client.account_information.get_user_account_positions(
                    user_id=uid, user_secret=sec, account_id=account_id
                )
                for p in (pos_resp.body or []):
                    qty = p.get('units') or p.get('quantity') or 0
                    price = p.get('price') or p.get('unit_price') or p.get('average_purchase_price') or 0
                    mv = p.get('market_value') or p.get('current_market_value') or (qty or 0) * (price or 0)
                    sym, name = _extract_symbol_and_name(p)
                    if mv:
                        total_investments += float(mv)
                    all_positions.append({
                        "accountId": account_id,
                        "symbol": sym,
                        "name": name,
                        "quantity": qty,
                        "marketValue": mv,
                    })
            except Exception:
                pass

        # Top holdings
        top = sorted(all_positions, key=lambda x: float(x.get('marketValue') or 0), reverse=True)[:5]
        grand = float(total_investments or 0) or 1.0
        top = [
            {**t, "weight": round(100.0 * float(t.get('marketValue') or 0) / grand, 2)}
            for t in top
        ]

        return {
            "hasConnectedAccounts": len(accounts) > 0,
            "totals": {
                "totalBalance": round(float(total_balance), 2),
                "totalInvestments": round(float(total_investments), 2),
            },
            "positions": all_positions,
            "topHoldings": top,
        }
    except Exception as e:
        logger.error(f"Failed to fetch portfolio data for {user_email}: {e}")
        return {
            "hasConnectedAccounts": False,
            "totals": {"totalBalance": 0.0, "totalInvestments": 0.0},
            "positions": [],
            "topHoldings": []
        }

def get_watchlist_data(watchlist: List[str]) -> Dict[str, Any]:
    """Fetch current market data for watchlist symbols"""
    if not watchlist or not POLYGON_API_KEY:
        return {"stocks": [], "news": []}

    def _get(url, params=None):
        q = dict(params or {})
        q["apiKey"] = POLYGON_API_KEY
        r = requests.get(url, params=q, timeout=10)
        r.raise_for_status()
        return r.json()

    def _fmt_price(p):
        try:
            return f"{float(p):.2f}"
        except Exception:
            return "-"
    
    def _fmt_signed(n):
        try:
            return f"{float(n):+0.2f}"
        except Exception:
            return "+0.00"
    
    def _fmt_signed_pct(n):
        try:
            return f"{float(n):+0.2f}%"
        except Exception:
            return "+0.00%"

    stocks = []
    news = []
    seen_news_urls = set()

    for sym in watchlist[:10]:  # Limit to 10 symbols
        try:
            # Get stock data
            s = _get(f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{sym}") or {}
            t = s.get("ticker") or {}
            last_price = (t.get("lastTrade") or {}).get("p") or (t.get("day") or {}).get("c")
            prev_c = (t.get("prevDay") or {}).get("c")
            ch = None
            chp = None
            if isinstance(last_price, (int, float)) and isinstance(prev_c, (int, float)) and prev_c not in (0, 0.0):
                ch = float(last_price) - float(prev_c)
                chp = (ch / float(prev_c)) * 100.0
            
            stocks.append({
                "symbol": sym,
                "name": sym,
                "price": _fmt_price(last_price),
                "change": _fmt_signed(ch),
                "changePercent": _fmt_signed_pct(chp),
            })

            # Get news for this symbol
            try:
                ticker_news = _get(
                    "https://api.polygon.io/v2/reference/news",
                    params={"ticker": sym, "order": "desc", "limit": 2, "sort": "published_utc"},
                ) or {}
                news_results = ticker_news.get("results") or []
                for item in news_results:
                    news_url = item.get("article_url") or item.get("url")
                    if news_url and news_url not in seen_news_urls:
                        seen_news_urls.add(news_url)
                        img = item.get("image_url")
                        if not img:
                            imgs = item.get("images") or []
                            if isinstance(imgs, list) and imgs:
                                img = imgs[0].get("url")
                        news.append({
                            "ticker": sym,
                            "title": item.get("title"),
                            "date": item.get("published_utc"),
                            "summary": item.get("description"),
                            "url": news_url,
                            "image": img,
                            "publisher": item.get("publisher")
                        })
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Failed to fetch data for {sym}: {e}")
            continue

    return {"stocks": stocks, "news": news}

# ---------- Enhanced Prompts for Global Report Style ----------
def build_personal_fact_pack_prompt(user_data: Dict[str, Any], portfolio_data: Dict[str, Any], 
                                  watchlist_data: Dict[str, Any], now_iso: str) -> str:
    """Build prompt for collecting personalized market facts via search"""
    
    user_name = user_data.get("name", "Investor")
    experience = user_data.get("onboarding", {}).get("experience", "intermediate")
    goal = user_data.get("onboarding", {}).get("goal", "growth")
    interests = user_data.get("onboarding", {}).get("interests", [])
    watchlist_symbols = user_data.get("onboarding", {}).get("watchlist", [])
    
    # Determine focus stocks
    focus_stocks = []
    if portfolio_data.get("hasConnectedAccounts") and portfolio_data.get("topHoldings"):
        focus_stocks = [h["symbol"] for h in portfolio_data["topHoldings"][:5]]
    elif watchlist_symbols:
        focus_stocks = watchlist_symbols[:5]
    else:
        focus_stocks = ["TSLA", "MSFT", "GOOGL", "NVDA"]  # Default stocks
    
    focus_stocks_str = ", ".join(focus_stocks)
    
    return f"""
You are a personalized markets researcher for {user_name}. Use web search to collect verifiable, RECENT facts as of {now_iso} (UTC) focusing on their specific holdings and interests.

User Profile:
- Experience Level: {experience}
- Investment Goal: {goal}
- Interests: {', '.join(interests) if interests else 'General investing'}
- Focus Stocks: {focus_stocks_str}

Rules:
- Only include facts from credible sources (major financial media, exchanges, data providers).
- Prefer last 24h. If you cannot verify a number, omit it (do not guess).
- Focus on the user's specific stocks first, then broader market context.
- Highlight major moves (>3%), earnings announcements, analyst upgrades/downgrades.
- Output ONLY JSON. No extra text.

Return EXACTLY this JSON schema:
{{
  "as_of_utc": "{now_iso}",
  "user_focus": {{
    "name": "{user_name}",
    "experience": "{experience}",
    "goal": "{goal}",
    "interests": {json.dumps(interests) if interests else '["General investing"]'},
    "focus_stocks": {json.dumps(focus_stocks)}
  }},
  "personal_holdings": [
    {{
      "symbol": "AAPL|TSLA|MSFT|etc.",
      "last": "numeric level if available, else empty string",
      "change_points": "e.g., +2.50 or -1.20, else empty string",
      "change_percent": "e.g., +1.5% or -0.8%, else empty string",
      "session_context": "close|midday|futures",
      "news_driver": "earnings|guidance|analyst|regulatory|etc. if available",
      "source_url": "credible source URL"
    }}
  ],
  "market_context": [
    {{
      "name": "S&P 500|Dow Jones|Nasdaq",
      "last": "numeric level if available, else empty string",
      "change_points": "e.g., +39.13 or -12.4, else empty string",
      "change_percent": "e.g., +0.58% or -0.3%, else empty string",
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
  "upcoming_events": [
    {{
      "item": "earnings|Fed|CPI|Payrolls|PMIs|etc.",
      "timing": "date/time window if applicable",
      "relevance": "why this matters to the user's holdings/interests",
      "source_url": "credible source URL"
    }}
  ]
}}

Constraints:
- Keep arrays concise (3-5 items for personal_holdings, 3 for market_context, 2-4 for others).
- JSON only.
""".strip()

def build_personal_composition_prompt(facts: Dict[str, Any], user_data: Dict[str, Any], 
                                    portfolio_data: Dict[str, Any], now_iso: str) -> str:
    """Build prompt for composing personalized report in global report style"""
    
    user_name = user_data.get("name", "Investor")
    experience = user_data.get("onboarding", {}).get("experience", "intermediate")
    goal = user_data.get("onboarding", {}).get("goal", "growth")
    interests = user_data.get("onboarding", {}).get("interests", [])
    
    # Portfolio context
    portfolio_context = ""
    if portfolio_data.get("hasConnectedAccounts"):
        total_inv = portfolio_data.get("totals", {}).get("totalInvestments", 0)
        total_bal = portfolio_data.get("totals", {}).get("totalBalance", 0)
        top_holdings = portfolio_data.get("topHoldings", [])
        
        portfolio_context = f"Portfolio: ${total_inv:,.2f} invested, ${total_bal:,.2f} cash. "
        if top_holdings:
            top_3 = top_holdings[:3]
            holdings_text = ", ".join([f"{h['symbol']} ({h['weight']:.1f}%)" for h in top_3])
            portfolio_context += f"Top holdings: {holdings_text}."
    else:
        portfolio_context = "No connected portfolio accounts."
    
    style_example = {
      "headline": "Tech Stocks Lead Gains as AI Optimism Drives Microsoft and Nvidia Higher",
      "headline_summary": "Technology stocks outperform as Microsoft gains 2.1% on AI infrastructure demand while Nvidia rises 3.4% on data center strength. Broader market advances with S&P 500 up 0.8% as investors focus on earnings season and Fed policy outlook.",
      "key_movements": "Microsoft climbs 2.1% to $445.20 on strong Azure growth and AI adoption trends. Nvidia advances 3.4% to $875.50 as data center revenue exceeds expectations. S&P 500 gains 0.8% to 5,420 with technology sector leading. Tesla trades flat at $180.30 as EV demand concerns persist.",
      "implications": "AI infrastructure spending continues to drive technology valuations higher, benefiting growth-oriented portfolios. Strong earnings from mega-cap tech names support broader market sentiment. Energy sector weakness suggests rotation into growth stocks as rates stabilize.",
      "watch_points": "Microsoft earnings on Thursday will test AI revenue growth expectations and cloud margins. Fed Chair Powell's remarks Friday could impact rate-sensitive technology valuations. Tesla's delivery numbers next week will clarify EV demand trends and production capacity."
    }
    
    facts_json = json.dumps(facts, ensure_ascii=False)

    return f"""
You are a personal financial advisor creating a professional market report for {user_name}.

User Profile:
- Experience Level: {experience}
- Investment Goal: {goal}
- Interests: {', '.join(interests) if interests else 'General investing'}
- Portfolio Context: {portfolio_context}

Facts (verbatim JSON):
{facts_json}

Hard requirements:
- Present tense, professional tone appropriate for {experience} level.
- Personal holdings-first focus; mention specific stocks from their portfolio/watchlist.
- Output ONLY valid JSON with EXACT fields: headline, headline_summary, key_movements, implications, watch_points.
- headline: ≤25 words; focus on what matters most to this investor.
- headline_summary: 3-5 sentences; personalized news focusing on their holdings/interests.
- key_movements: 3-5 sentences covering:
  1) Their top holdings with specific prices/changes if available
  2) Broader market context (S&P 500, Dow, Nasdaq)
  3) Any major movers relevant to their interests
  If verified numbers are missing, write directional sentences without inventing numbers.
- implications: 3-4 sentences; how market conditions affect their specific portfolio and investment goals.
- watch_points: 3-4 sentences; personalized near-term catalysts relevant to their holdings and interests.
- No bullet points; sentences only. No extra fields.

Style guidance (format only, do not copy content):
{json.dumps(style_example, ensure_ascii=False, indent=2)}

Return ONLY the JSON object with the five fields.
""".strip()

# ---------- Enhanced LLM Calls ----------
def generate_personal_fact_pack(user_data: Dict[str, Any], portfolio_data: Dict[str, Any], 
                              watchlist_data: Dict[str, Any], model: str = MODEL) -> Dict[str, Any]:
    """Generate personalized fact pack using web search"""
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    prompt = build_personal_fact_pack_prompt(user_data, portfolio_data, watchlist_data, now_iso)
    
    # Step 1: WITH tools for web search
    config = types.GenerateContentConfig(tools=[grounding_tool])
    resp = client.models.generate_content(model=model, contents=prompt, config=config)
    raw = getattr(resp, "text", "") or ""
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Personal fact pack must be a JSON object")
    data["as_of_utc"] = now_iso
    return data

def compose_personal_report(facts: Dict[str, Any], user_data: Dict[str, Any], 
                          portfolio_data: Dict[str, Any], model: str = MODEL) -> Dict[str, Any]:
    """Compose personalized report from facts"""
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    prompt = build_personal_composition_prompt(facts, user_data, portfolio_data, now_iso)

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
        "user_email": user_data.get("email", ""),
    }

# ---------- Firestore ----------
def write_personal_report(db: firestore.Client, user_email: str, doc_id: str, payload: Dict[str, Any]) -> None:
    """Write personal report to user's reports subcollection"""
    user_ref = db.collection('users').document(user_email.lower())
    reports_ref = user_ref.collection('reports').document(doc_id)
    reports_ref.set(payload, merge=True)

def get_all_users(db: firestore.Client) -> List[Dict[str, Any]]:
    """Get all users from the database"""
    users = []
    try:
        users_ref = db.collection('users')
        docs = users_ref.stream()
        
        for doc in docs:
            user_data = doc.to_dict()
            user_data['email'] = doc.id  # Add email as document ID
            users.append(user_data)
            
        logger.info(f"Retrieved {len(users)} users from database")
        return users
    except Exception as e:
        logger.error(f"Failed to retrieve users: {e}")
        return []

# ---------- Enhanced Runner ----------
def run_personal_reports(dry_run: bool = False, model: str = MODEL, limit_users: Optional[int] = None) -> Dict[str, Any]:
    """Generate personalized reports for all users using global report style"""
    logger.info("Starting personalized report generation...")
    
    db = get_firestore_client()
    users = get_all_users(db)
    
    if limit_users:
        users = users[:limit_users]
        logger.info(f"Limited to {limit_users} users for processing")
    
    results = {
        "processed": 0,
        "successful": 0,
        "failed": 0,
        "errors": []
    }
    
    doc_id = date_doc_id()
    
    for user in users:
        try:
            user_email = user.get("email", "")
            if not user_email:
                logger.warning("Skipping user with no email")
                continue
                
            logger.info(f"Processing user: {user_email}")
            results["processed"] += 1
            
            # Skip users who haven't onboarded
            if not user.get("hasUserOnboarded", False):
                logger.info(f"Skipping non-onboarded user: {user_email}")
                continue
            
            # Get SnapTrade info
            snaptrade_info = _get_snaptrade_info(user)
            
            # Fetch portfolio data
            portfolio_data = get_portfolio_data(user_email, snaptrade_info)
            
            # Fetch watchlist data
            watchlist = user.get("onboarding", {}).get("watchlist", [])
            watchlist_data = get_watchlist_data(watchlist)
            
            logger.info(f"Step 1: Collecting personalized facts via search for {user_email}...")
            facts = generate_personal_fact_pack(user_data=user, portfolio_data=portfolio_data, 
                                              watchlist_data=watchlist_data, model=model)
            
            logger.info(f"Step 2: Composing personalized report from facts for {user_email}...")
            report = compose_personal_report(facts=facts, user_data=user, 
                                          portfolio_data=portfolio_data, model=model)
            
            # Prepare payload
            payload = {
                "generated_at": report["generated_at"],
                "headline": report["headline"],
                "headline_summary": report["headline_summary"],
                "key_movements": report["key_movements"],
                "implications": report["implications"],
                "watch_points": report["watch_points"],
                "model": report["model"],
                "user_email": user_email,
                "facts": facts,  # Store for traceability
                "portfolio_data": portfolio_data,  # Store for traceability
                "watchlist_data": watchlist_data,  # Store for traceability
            }
            
            if dry_run:
                logger.info(f"[DRY RUN] Would write personal report for {user_email} to users/{user_email}/reports/{doc_id}")
                results["successful"] += 1
            else:
                write_personal_report(db, user_email, doc_id, payload)
                logger.info(f"Saved personal report for {user_email} to users/{user_email}/reports/{doc_id}")
                results["successful"] += 1
                
        except Exception as e:
            logger.error(f"Failed to process user {user_email}: {e}")
            results["failed"] += 1
            results["errors"].append({"user": user_email, "error": str(e)})
    
    logger.info(f"Personal report generation complete. Processed: {results['processed']}, Successful: {results['successful']}, Failed: {results['failed']}")
    return results

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Personal report agent (daily per user)")
    parser.add_argument("--dry-run", action="store_true", help="Generate but do not write to Firestore")
    parser.add_argument("--model", default=MODEL, help="Override model (default: gemini-2.5-flash)")
    parser.add_argument("--limit", type=int, help="Limit number of users to process (for testing)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    result = run_personal_reports(dry_run=args.dry_run, model=args.model, limit_users=args.limit)
    print(json.dumps(result, indent=2))
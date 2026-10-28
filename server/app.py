from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
from functools import wraps
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google.cloud import firestore
from google.oauth2 import service_account
import json
import os
import uuid
import re
import requests
import time
# Forcing IPv4
import socket

# Forcing IPv4
import socket
_original_getaddrinfo = socket.getaddrinfo
# Override it to only use AF_INET (IPv4)
def force_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
# Apply patch early, before imports that use requests or urllib3
socket.getaddrinfo = force_ipv4_getaddrinfo


# SnapTrade SDK
from snaptrade_client import SnapTrade

app = Flask(__name__)
CORS(app)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID")
FIREBASE_SERVICE_ACCOUNT = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
PROJECT_ID = os.environ.get("PROJECT_ID")
FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "br-prod-db")

# SnapTrade env config
SNAPTRADE_CONSUMER_KEY = os.environ.get("SNAPTRADE_CONSUMER_KEY")
SNAPTRADE_CLIENT_ID = os.environ.get("SNAPTRADE_CLIENT_ID")
SNAPTRADE_REDIRECT_BASE = os.environ.get("SNAPTRADE_REDIRECT_BASE", "http://localhost:5173/portfolio")

def get_snaptrade_client():
    if not SNAPTRADE_CONSUMER_KEY or not SNAPTRADE_CLIENT_ID:
        raise RuntimeError("Missing SNAPTRADE_CONSUMER_KEY or SNAPTRADE_CLIENT_ID")
    return SnapTrade(
        consumer_key=SNAPTRADE_CONSUMER_KEY,
        client_id=SNAPTRADE_CLIENT_ID,
    )

def get_firestore_client():
    """Firestore client. Uses FIREBASE_SERVICE_ACCOUNT JSON if set, otherwise the runtime's
    own identity (Application Default Credentials, i.e. the Cloud Run service account)."""
    if not PROJECT_ID:
        raise RuntimeError("PROJECT_ID env var not set")
    if FIREBASE_SERVICE_ACCOUNT:
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(FIREBASE_SERVICE_ACCOUNT)
        )
        return firestore.Client(credentials=credentials, project=PROJECT_ID, database=FIRESTORE_DATABASE)
    return firestore.Client(project=PROJECT_ID, database=FIRESTORE_DATABASE)

# Token verification decorator
def require_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            print(f"[AUTH] Missing or invalid Authorization header from {request.remote_addr}")
            return jsonify({"error": "Missing or invalid token"}), 401
        
        token = auth_header.split(' ')[1]
        
        try:
            idinfo = id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                GOOGLE_CLIENT_ID,
                clock_skew_in_seconds=10
            )
            request.user_email = idinfo.get('email')
            request.user_info = {
                "email": idinfo.get('email'),
                "name": idinfo.get('name'),
                "avatar": idinfo.get('picture')
            }
            print(f"[AUTH] Token verified successfully for user: {request.user_email}")
            return f(*args, **kwargs)
        except Exception as e:
            print(f"[AUTH] Token verification failed: {e}")
            return jsonify({"error": "Invalid token"}), 401
    
    return decorated_function

def _get_user_doc_ref(client: firestore.Client, email: str):
    """Users are keyed by email as document ID within 'users' collection."""
    return client.collection('users').document((email or '').strip().lower())

def _safe_user_out(doc_dict: dict):
    d = doc_dict or {}
    ob = d.get("onboarding") or {}
    ints = ob.get("interests")
    wlst = ob.get("watchlist")
    if not isinstance(ints, list):
        ints = []
    if not isinstance(wlst, list):
        wlst = []
    return {
        "email": d.get("email"),
        "name": d.get("name", ""),
        "avatar": d.get("avatar", ""),
        "hasUserOnboarded": bool(d.get("hasUserOnboarded", False)),
        "onboarding": {
            "goal": (ob or {}).get("goal", ""),
            "experience": (ob or {}).get("experience", ""),
            "interests": ints,
            "watchlist": wlst,
        }
    }
    
def _get_snaptrade_info(doc_dict: dict):
    d = doc_dict or {}
    # Prefer top-level fields (BR_October convention)
    uid = d.get("snaptrade_user_id")
    sec = d.get("snaptrade_user_secret")
    if uid and sec:
        return {"userId": uid, "userSecret": sec}

    # Fallback to nested map if present
    st = d.get("snaptrade") or {}
    uid = st.get("userId")
    sec = st.get("userSecret")
    if uid and sec:
        return {"userId": uid, "userSecret": sec}
    return None

def _ensure_snaptrade_user(client: firestore.Client, email: str):
    """Ensure a SnapTrade userId/secret exists for this app user; create and persist if absent."""
    print(f"[SNAPTRADE] Ensuring SnapTrade user for: {email}")
    ref = _get_user_doc_ref(client, email)
    snap = ref.get()
    if not snap.exists:
        # create minimal user shell
        print(f"[SNAPTRADE] Creating minimal user doc for: {email}")
        now = datetime.utcnow()
        ref.set({
            "email": email,
            "name": (getattr(request, 'user_info', {}) or {}).get("name", ""),
            "avatar": (getattr(request, 'user_info', {}) or {}).get("avatar", ""),
            "hasUserOnboarded": False,
            "onboarding": {},
            "created_at": now,
            "updated_at": now,
        })
        doc = {}
    else:
        doc = snap.to_dict() or {}

    st = _get_snaptrade_info(doc)
    if st:
        print(f"[SNAPTRADE] Found existing SnapTrade credentials for: {email}")
        # If nested exists but top-level missing, promote to top-level and remove nested to avoid duplication
        if not doc.get("snaptrade_user_id") and not doc.get("snaptrade_user_secret"):
            print(f"[SNAPTRADE] Promoting nested SnapTrade data to top-level for: {email}")
            ref.update({
                "snaptrade_user_id": st["userId"],
                "snaptrade_user_secret": st["userSecret"],
                "updated_at": datetime.utcnow(),
            })
            try:
                ref.update({"snaptrade": firestore.DELETE_FIELD})
            except Exception:
                pass
        return st

    # Register SnapTrade user
    print(f"[SNAPTRADE] Registering new SnapTrade user for: {email}")
    st_client = get_snaptrade_client()
    user_id = f"br-{uuid.uuid4()}"
    try:
        register_response = st_client.authentication.register_snap_trade_user(
            user_id=user_id
        )
    except Exception:
        register_response = st_client.authentication.register_snap_trade_user(
            body={"userId": user_id}
        )
    body = getattr(register_response, "body", {}) or {}
    user_secret = body.get("userSecret") or body.get("user_secret")
    if not user_secret:
        print(f"[SNAPTRADE] ERROR: Failed to obtain userSecret for: {email}")
        raise RuntimeError("Failed to obtain SnapTrade userSecret")

    # Persist mapping on user doc (top-level only)
    print(f"[SNAPTRADE] Successfully registered SnapTrade user: {user_id} for: {email}")
    update_doc = {
        "snaptrade_user_id": user_id,
        "snaptrade_user_secret": user_secret,
        "updated_at": datetime.utcnow(),
    }
    # Remove nested field if present to avoid duplication
    try:
        update_doc["snaptrade"] = firestore.DELETE_FIELD
    except Exception:
        pass
    ref.update(update_doc)
    return {"userId": user_id, "userSecret": user_secret}

@app.route('/api/user', methods=['GET'])
@require_token
def get_or_create_user():
    """Fetch user by email; create if not exists with minimal profile.
    Doc key = email (lowercase). Database = 'br-prod-db', collection = 'users'.
    """
    try:
        email = request.user_email
        print(f"[GET /api/user] Request from user: {email}")
        info = getattr(request, 'user_info', {})
        client = get_firestore_client()
        ref = _get_user_doc_ref(client, email)
        snap = ref.get()

        if not snap.exists:
            print(f"[GET /api/user] Creating new user document for: {email}")
            # Create minimal user record
            now = datetime.utcnow()
            new_doc = {
                "email": email,
                "name": info.get("name", ""),
                "avatar": info.get("avatar", ""),
                "hasUserOnboarded": False,
                "onboarding": {},
                "created_at": now,
                "updated_at": now,
            }
            ref.set(new_doc)
            print(f"[GET /api/user] Successfully created user: {email}")
            return jsonify(_safe_user_out(new_doc)), 201

        data = snap.to_dict() or {}
        print(f"[GET /api/user] Found existing user: {email}")
        # Backfill missing basics if needed
        update = {}
        if not data.get("name") and info.get("name"):
            update["name"] = info.get("name")
        if not data.get("avatar") and info.get("avatar"):
            update["avatar"] = info.get("avatar")
        if update:
            print(f"[GET /api/user] Backfilling user data for: {email}")
            update["updated_at"] = datetime.utcnow()
            ref.update(update)
            data.update(update)
        print(f"[GET /api/user] Successfully fetched user: {email}")
        return jsonify(_safe_user_out(data)), 200
    except Exception as e:
        print(f"[GET /api/user] ERROR: {e}")
        return jsonify({"error": "Failed to fetch user"}), 500


@app.route('/api/register', methods=['POST'])
def register_user():
    """Unauthenticated register: accepts email and onboarding details.
       Body: { email, name?, avatar?, answers?: { goal, experience, interests[], watchlist[] } }
       409 if email already exists; 201 with user payload otherwise.
    """
    try:
        payload = request.get_json() or {}
        raw_email = str(payload.get('email') or '').strip()
        if not raw_email:
            return jsonify({"error": "Email is required"}), 400

        # Basic email sanity check (lightweight)
        email = raw_email.lower()
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({"error": "Invalid email"}), 400

        # Optional identity hints
        name = str(payload.get('name') or '').strip()
        avatar = str(payload.get('avatar') or '').strip()

        # Normalize onboarding answers (reuse save_onboarding shape)
        raw = payload.get('answers') or {}
        goal = str(raw.get('goal', '')).strip()
        experience = str(raw.get('experience', '')).strip()

        interests = raw.get('interests') or []
        if not isinstance(interests, list):
            interests = []
        interests = [str(x).strip() for x in interests if str(x).strip()]

        watchlist_in = raw.get('watchlist') or []
        if not isinstance(watchlist_in, list):
            watchlist_in = []
        wl = []
        for x in watchlist_in:
            t = str(x).strip().upper()
            if t and t not in wl:
                wl.append(t)

        payload_onboarding = {
            "goal": goal,
            "experience": experience,
            "interests": interests,
            "watchlist": wl,
        }

        client = get_firestore_client()
        ref = _get_user_doc_ref(client, email)
        snap = ref.get()

        if snap.exists:
            # Email already registered
            return jsonify({"error": "Email already exists"}), 409

        now = datetime.utcnow()
        new_doc = {
            "email": email,
            "name": name,
            "avatar": avatar,
            "hasUserOnboarded": True,
            "onboarding": payload_onboarding,
            "created_at": now,
            "updated_at": now,
        }

        ref.set(new_doc)
        return jsonify(_safe_user_out(new_doc)), 201

    except Exception as e:
        print(f"[POST /api/register] ERROR: {e}")
        return jsonify({"error": "Failed to register user"}), 500

        
@app.route('/api/user/onboarding', methods=['POST'])
@require_token
def save_onboarding():
    """Save simple onboarding answers and mark user onboarded."""
    try:
        email = request.user_email
        payload = request.get_json() or {}
        raw = payload.get('answers') or {}
        print(f"[POST /api/user/onboarding] Request from user: {email}, answers: {raw}")

        # sanitize
        goal = str(raw.get('goal', '')).strip()
        experience = str(raw.get('experience', '')).strip()

        interests = raw.get('interests') or []
        if not isinstance(interests, list):
            interests = []
        interests = [str(x).strip() for x in interests if str(x).strip()]

        watchlist_in = raw.get('watchlist') or []
        if not isinstance(watchlist_in, list):
            watchlist_in = []
        wl = []
        for x in watchlist_in:
            t = str(x).strip().upper()
            if t and t not in wl:
                wl.append(t)

        client = get_firestore_client()
        ref = _get_user_doc_ref(client, email)
        snap = ref.get()

        payload_onboarding = {
            "goal": goal,
            "experience": experience,
            "interests": interests,
            "watchlist": wl,
        }

        if not snap.exists:
            print(f"[POST /api/user/onboarding] Creating new user with onboarding data: {email}")
            ref.set({
                "email": email,
                "name": (getattr(request, 'user_info', {}) or {}).get("name", ""),
                "avatar": (getattr(request, 'user_info', {}) or {}).get("avatar", ""),
                "hasUserOnboarded": True,
                "onboarding": payload_onboarding,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            })
        else:
            print(f"[POST /api/user/onboarding] Updating existing user: {email}")
            ref.update({
                "hasUserOnboarded": True,
                "onboarding": payload_onboarding,
                "updated_at": datetime.utcnow(),
            })

        doc = ref.get().to_dict() or {}
        print(f"[POST /api/user/onboarding] Successfully saved onboarding for: {email}")
        return jsonify(_safe_user_out(doc)), 200
    except Exception as e:
        print(f"[POST /api/user/onboarding] ERROR: {e}")
        return jsonify({"error": "Failed to save onboarding"}), 500

@app.route('/api/user/watchlist', methods=['POST'])
@require_token
def add_to_watchlist():
    """Append symbols to the user's onboarding.watchlist (deduped, uppercase)."""
    try:
        email = request.user_email
        payload = request.get_json() or {}
        symbols = payload.get('symbols') or payload.get('symbol') or []
        if isinstance(symbols, str):
            symbols = [symbols]
        if not isinstance(symbols, list):
            symbols = []

        # sanitize and dedupe
        to_add = []
        for x in symbols:
            t = str(x or '').strip().upper()
            if t and t not in to_add:
                to_add.append(t)

        client = get_firestore_client()
        ref = _get_user_doc_ref(client, email)
        snap = ref.get()

        if not snap.exists:
            now = datetime.utcnow()
            ref.set({
                "email": email,
                "name": (getattr(request, 'user_info', {}) or {}).get("name", ""),
                "avatar": (getattr(request, 'user_info', {}) or {}).get("avatar", ""),
                "hasUserOnboarded": False,
                "onboarding": {"watchlist": to_add},
                "created_at": now,
                "updated_at": now,
            })
            merged = to_add
        else:
            doc = snap.to_dict() or {}
            ob = doc.get("onboarding") or {}
            wl = ob.get("watchlist") or []
            if not isinstance(wl, list):
                wl = []
            current = [str(x).strip().upper() for x in wl if str(x).strip()]
            merged = current[:]
            for t in to_add:
                if t not in merged:
                    merged.append(t)
            ref.update({
                "onboarding": {**ob, "watchlist": merged},
                "updated_at": datetime.utcnow(),
            })

        return jsonify({"watchlist": merged}), 200
    except Exception as e:
        print(f"[POST /api/user/watchlist] ERROR: {e}")
        return jsonify({"error": "Failed to update watchlist"}), 500


@app.route('/api/user/watchlist/update', methods=['POST'])
@require_token
def replace_watchlist():
    """Replace the user's onboarding.watchlist with the provided list (deduped, uppercase)."""
    try:
        email = request.user_email
        payload = request.get_json() or {}
        symbols = payload.get('symbols')

        if symbols is None:
            symbols = []
        if isinstance(symbols, str):
            symbols = [symbols]
        if not isinstance(symbols, list):
            symbols = []

        # sanitize, uppercase, preserve order, dedupe
        sanitized = []
        for x in symbols:
            t = str(x or '').strip().upper()
            if t and t not in sanitized:
                sanitized.append(t)

        client = get_firestore_client()
        ref = _get_user_doc_ref(client, email)
        snap = ref.get()
        now = datetime.utcnow()

        if not snap.exists:
            print(f"[POST /api/user/watchlist/update] Creating new user shell for: {email}")
            ref.set({
                "email": email,
                "name": (getattr(request, 'user_info', {}) or {}).get("name", ""),
                "avatar": (getattr(request, 'user_info', {}) or {}).get("avatar", ""),
                "hasUserOnboarded": False,
                "onboarding": {"watchlist": sanitized},
                "created_at": now,
                "updated_at": now,
            })
        else:
            doc = snap.to_dict() or {}
            ob = doc.get("onboarding") or {}
            print(f"[POST /api/user/watchlist/update] Replacing watchlist for: {email} with {sanitized}")
            ref.update({
                "onboarding": {**ob, "watchlist": sanitized},
                "updated_at": now,
            })

        return jsonify({"watchlist": sanitized}), 200
    except Exception as e:
        print(f"[POST /api/user/watchlist/update] ERROR: {e}")
        return jsonify({"error": "Failed to replace watchlist"}), 500

@app.route('/api/market-summary', methods=['GET'])
@require_token
def get_market_summary():
    try:
        email = request.user_email
        print(f"[GET /api/market-summary] Request from user: {email}")
        client = get_firestore_client()

        # First try to get personal report for the user
        personal_reports_ref = client.collection('users').document(email).collection('reports')
        personal_query = personal_reports_ref.order_by('generated_at', direction=firestore.Query.DESCENDING).limit(1)
        personal_docs = list(personal_query.stream())
        
        if personal_docs:
            # Use personal report
            report = personal_docs[0].to_dict() or {}
            print(f"[GET /api/market-summary] Found personal report for: {email}")
        else:
            # Fall back to global report
            global_query = (
                client.collection('reports')
                .order_by('generated_at', direction=firestore.Query.DESCENDING)
                .limit(1)
            )
            global_docs = list(global_query.stream())
            report = (global_docs[0].to_dict() if global_docs else {}) or {}
            print(f"[GET /api/market-summary] Using global report fallback for: {email}")

        # Extract data from the report (personal or global)
        headline = (report.get('headline') or '').strip()
        headline_summary = (report.get('headline_summary') or report.get('summary') or '').strip()

        def split_sentences(val):
            # Split on '.' followed by space (avoids decimals like 5.1, 23.04)
            if not val:
                return []
            if isinstance(val, list):
                out = []
                for x in val:
                    out.extend(split_sentences(x))
                return out
            s = str(val).strip()
            if not s:
                return []
            # Split on sentence boundaries while preserving:
            # - Abbreviations like U.S., U.K., U.N. (capital letter + period + capital letter)
            # - Decimals like 5.1, 23.04 (already handled by requiring space after period)
            # Pattern: period followed by space and capital letter, but NOT preceded by single capital letter
            parts = [p.strip() for p in re.split(r'(?<!\b[A-Z])\.(?=\s+[A-Z])', s) if p.strip()]
            return parts

        implications = split_sentences(report.get('implications'))
        key_movements = split_sentences(report.get('key_movements') or report.get('keyMovements'))
        watch_points = split_sentences(report.get('watch_points') or report.get('watchPoints'))

        # Format generated_at -> "Wednesday, October 08, 2025"
        date_str = ''
        gen_at = report.get('generated_at')
        try:
            dt = None
            if isinstance(gen_at, datetime):
                dt = gen_at
            elif hasattr(gen_at, 'to_datetime'):
                dt = gen_at.to_datetime()
            elif isinstance(gen_at, (int, float)):
                dt = datetime.fromtimestamp(gen_at)
            elif isinstance(gen_at, str):
                try:
                    dt = datetime.fromisoformat(gen_at.replace('Z', '+00:00'))
                except Exception:
                    dt = None
            if dt:
                date_str = dt.strftime('%A, %B %d, %Y')
        except Exception:
            date_str = ''

        # === Market snapshot + lists ===
        api_key = os.environ.get("POLYGON_API_KEY")
        def _get(url, params=None):
            if not api_key:
                raise RuntimeError("Missing POLYGON_API_KEY")
            q = dict(params or {})
            q["apiKey"] = api_key
            r = requests.get(url, params=q, timeout=10)
            r.raise_for_status()
            return r.json()

        # Price/change for SPY from snapshot
        spy_last = None
        spy_chg = None
        spy_chg_pct = None
        spy_prev_close = None
        try:
            snap = _get("https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/SPY") or {}
            t = snap.get("ticker") or {}
            last_price = (t.get("lastTrade") or {}).get("p") or (t.get("day") or {}).get("c")
            prev_close = (t.get("prevDay") or {}).get("c")
            spy_last = last_price
            spy_prev_close = prev_close
            if isinstance(last_price, (int, float)) and isinstance(prev_close, (int, float)) and prev_close not in (0, 0.0):
                spy_chg = float(last_price) - float(prev_close)
                spy_chg_pct = (spy_chg / float(prev_close)) * 100.0
        except Exception as e:
            print(f"[GET /api/market-summary] Snapshot fetch failed for SPY: {e}")

        # Reusable formatters
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

        # Top Movers (existing - kept for compatibility, but frontend won't use)
        top_stocks = []

        
        try:
            gainers = _get("https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers") or {}
            losers = _get("https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/losers") or {}
            gl = (gainers.get("tickers") or [])[:15] + (losers.get("tickers") or [])[:15]
            for it in gl:
                sym = it.get("ticker")
                price = None
                last_trade = it.get("lastTrade") or {}
                price = last_trade.get("p") if isinstance(last_trade, dict) else None
                if price is None:
                    day = it.get("day") or {}
                    price = day.get("c")
                ch = it.get("todaysChange")
                chp = it.get("todaysChangePerc")
                top_stocks.append({
                    "symbol": sym or "",
                    "name": sym or "",
                    "price": _fmt_price(price),
                    "change": _fmt_signed(ch),
                    "changePercent": _fmt_signed_pct(chp),
                })
            # sort by absolute % change and take top 25
            def _abs_pct(x):
                try:
                    return abs(float((x.get("changePercent") or "0").replace('%','')))
                except Exception:
                    return 0.0
            top_stocks.sort(key=_abs_pct, reverse=True)
            top_stocks = top_stocks[:25]
        except Exception as e:
            print(f"[GET /api/market-summary] Top movers fetch failed: {e}")
            top_stocks = []

        # NEW: User watchlist quotes
        watchlist_stocks = []
        watchlist_news = []  # Add this new list
        seen_news_urls = set()  # Track unique news URLs for deduplication
        
        try:
            uref = _get_user_doc_ref(client, email)
            usnap = uref.get()
            udoc = (usnap.to_dict() or {}) if usnap else {}
            wl = ((udoc.get("onboarding") or {}).get("watchlist") or [])
            if isinstance(wl, list):
                syms = [str(x).strip().upper() for x in wl if str(x).strip()]
            else:
                syms = []
            for sym in syms[:25]:
                try:
                    s = _get(f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{sym}") or {}
                    t = s.get("ticker") or {}
                    last_price = (t.get("lastTrade") or {}).get("p") or (t.get("day") or {}).get("c")
                    prev_c = (t.get("prevDay") or {}).get("c")
                    ch = None; chp = None
                    if isinstance(last_price,(int,float)) and isinstance(prev_c,(int,float)) and prev_c not in (0,0.0):
                        ch = float(last_price) - float(prev_c)
                        chp = (ch / float(prev_c)) * 100.0
                    watchlist_stocks.append({
                        "symbol": sym,
                        "name": sym,
                        "price": _fmt_price(last_price),
                        "change": _fmt_signed(ch),
                        "changePercent": _fmt_signed_pct(chp),
                    })
                    
                    # Fetch 2 news articles for this ticker
                    try:
                        ticker_news = _get(
                            "https://api.polygon.io/v2/reference/news",
                            params={"ticker": sym, "order": "desc", "limit": 2, "sort": "published_utc"},
                        ) or {}
                        news_results = ticker_news.get("results") or []
                        for item in news_results:
                            news_url = item.get("article_url") or item.get("url")
                            # Deduplicate by URL
                            if news_url and news_url not in seen_news_urls:
                                seen_news_urls.add(news_url)
                                img = item.get("image_url")
                                if not img:
                                    imgs = item.get("images") or []
                                    if isinstance(imgs, list) and imgs:
                                        img = imgs[0].get("url")
                                watchlist_news.append({
                                    "ticker": sym,
                                    "title": item.get("title"),
                                    "date": item.get("published_utc"),
                                    "summary": item.get("description"),
                                    "url": news_url,
                                    "image": img,
                                    "publisher": item.get("publisher")
                                })
                    except Exception as e:
                        print(f"[GET /api/market-summary] News fetch failed for {sym}: {e}")
                        continue
                        
                except Exception as e:
                    print(f"[GET /api/market-summary] Watchlist quote failed for {sym}: {e}")
                    continue
        except Exception as e:
            print(f"[GET /api/market-summary] Watchlist load failed: {e}")
            watchlist_stocks = []
            watchlist_news = []
            
        # NEW: Top Movers by Volume (most active)
        top_volume_stocks = []
        try:
            actives = _get("https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/most_active") or {}
            rows = (actives.get("tickers") or [])[:50]
            for it in rows:
                sym = it.get("ticker")
                day = it.get("day") or {}
                last_trade = it.get("lastTrade") or {}
                price = last_trade.get("p") if isinstance(last_trade, dict) else None
                if price is None:
                    price = day.get("c")
                ch = it.get("todaysChange")
                chp = it.get("todaysChangePerc")
                vol = day.get("v") or it.get("volume") or 0
                try:
                    vol_int = int(vol or 0)
                except Exception:
                    vol_int = 0
                top_volume_stocks.append({
                    "symbol": sym or "",
                    "name": sym or "",
                    "price": _fmt_price(price),
                    "change": _fmt_signed(ch),
                    "changePercent": _fmt_signed_pct(chp),
                    "volume": vol_int,
                })
            top_volume_stocks.sort(key=lambda x: x.get("volume", 0), reverse=True)
            top_volume_stocks = top_volume_stocks[:25]
        except Exception as e:
            print(f"[GET /api/market-summary] Top volume fetch failed: {e}")
            top_volume_stocks = []

        data = {
            'greeting': 'Hi, ',
            'subtitle': 'What should we analyze next?',
            'mainArticle': {
                'title': headline or 'Market Update',
                'date': date_str,
                'content': headline_summary
            },
            'keyMovements': key_movements,
            'implications': implications,
            'watchPoints': watch_points,
            'marketChart': {
                'symbol': 'SPY',
                'price': spy_last,
                'prevClose': spy_prev_close,
                'change': round(spy_chg, 4) if isinstance(spy_chg, (int, float)) else None,
                'changePct': round(spy_chg_pct, 4) if isinstance(spy_chg_pct, (int, float)) else None,
            },
            'topStocks': top_stocks,           # Top market movers (combined gainers/losers)
            'watchlistStocks': watchlist_stocks,
            'news': watchlist_news,  # Add this new field
        }
        print(f"[GET /api/market-summary] Successfully retrieved market data for: {email}")
        return jsonify(data), 200
    except Exception as e:
        print(f"[GET /api/market-summary] ERROR: {e}")
        return jsonify({"error": "Failed to load market data"}), 500

# API route for dashboard data
@app.route('/api/dashboard', methods=['GET'])
def get_dashboard_data():
    print(f"[GET /api/dashboard] Request received")
    data = {
        'message': 'Dashboard data endpoint',
        'status': 'success'
    }
    print(f"[GET /api/dashboard] Successfully returned dashboard data")
    return jsonify(data)

# Health check route
@app.route('/api/health', methods=['GET'])
def health_check():
    print(f"[GET /api/health] Health check request")
    return jsonify({'status': 'healthy'})

# === SNAPTRADE INTEGRATION ===

@app.route('/api/snaptrade/connect_url', methods=['GET'])
@require_token
def snaptrade_connect_url():
    """Create a SnapTrade Connection Portal URL for the current user."""
    if not SNAPTRADE_CONSUMER_KEY or not SNAPTRADE_CLIENT_ID:
        return jsonify({"error": "not_configured",
                        "message": "Brokerage linking (SnapTrade) is built in but not configured on this deployment."}), 503
    try:
        email = request.user_email
        broker = request.args.get('broker')
        print(f"[GET /api/snaptrade/connect_url] Request from user: {email}, broker: {broker}")
        client = get_firestore_client()
        st_user = _ensure_snaptrade_user(client, email)
        print(f"[GET /api/snaptrade/connect_url] SnapTrade user ensured for: {email}")
        st_client = get_snaptrade_client()

        # Optional: pass 'broker' query ?broker=ALPACA etc.

        kwargs = {
            "user_id": st_user["userId"],
            "user_secret": st_user["userSecret"],
            # Use portal URL, not immediate redirect back
            "immediate_redirect": False,
            "custom_redirect": SNAPTRADE_REDIRECT_BASE,
            "connection_type": "read",
            "show_close_button": True,
            "connection_portal_version": "v4",
        }
        if broker:
            kwargs["broker"] = broker

        resp = st_client.authentication.login_snap_trade_user(**kwargs)
        body = getattr(resp, "body", None)
        redirect_url = None
        if isinstance(body, dict):
            redirect_url = body.get("redirectURI") or body.get("redirectUri") or body.get("redirect_url") or body.get("url")
        elif isinstance(body, str):
            redirect_url = body
        print(f"[GET /api/snaptrade/connect_url] Successfully created connect URL for: {email}")
        return jsonify({"url": redirect_url}), 200
    except Exception as e:
        print(f"[GET /api/snaptrade/connect_url] ERROR: {e}")
        return jsonify({"error": "Failed to create connect URL"}), 500


# ---------------------------------------------------------------------------
# Manual holdings (for users without a linked brokerage) + end-of-day pricing
# ---------------------------------------------------------------------------
_EOD_CACHE = {}  # date -> (fetched_at, {ticker: bar})
_QUOTE_CACHE = {}  # symbol -> (fetched_at, quote)


def _finnhub_quote(sym):
    """Real-time quote from Finnhub, cached 30s. Returns None if unavailable."""
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None
    hit = _QUOTE_CACHE.get(sym)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    try:
        r = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": sym, "token": key}, timeout=8)
        r.raise_for_status()
        q = r.json()
    except Exception as e:
        print(f"[finnhub] quote failed for {sym}: {e}")
        return None
    if not q.get("t"):  # unknown symbol comes back as all zeros
        return None
    _QUOTE_CACHE[sym] = (time.time(), q)
    return q
_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def _grouped_bars(day_str):
    """All US stock bars for one day in a single Polygon call (free plan: 5 req/min). Cached 1h."""
    hit = _EOD_CACHE.get(day_str)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("POLYGON_API_KEY not set")
    r = requests.get(f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{day_str}",
                     params={"adjusted": "true", "apiKey": api_key}, timeout=20)
    r.raise_for_status()
    bars = {b["T"]: b for b in (r.json().get("results") or [])}
    _EOD_CACHE[day_str] = (time.time(), bars)
    return bars


def _eod_quotes():
    """Return (as_of_date, latest_bars, previous_bars) for the two most recent sessions."""
    from datetime import date, timedelta
    found = []
    d = date.today()
    for _ in range(10):
        bars = _grouped_bars(d.isoformat())
        if bars:
            found.append((d.isoformat(), bars))
            if len(found) == 2:
                return found[0][0], found[0][1], found[1][1]
        d -= timedelta(days=1)
    raise RuntimeError("no recent sessions from Polygon")


def _clean_holdings(raw):
    out = []
    for h in raw or []:
        sym = str(h.get("symbol", "")).upper().strip().lstrip("$")
        try:
            qty = float(h.get("quantity"))
            cost = float(h["avgCost"]) if h.get("avgCost") not in (None, "") else None
        except (TypeError, ValueError):
            continue
        if _TICKER_RE.match(sym) and qty > 0:
            out.append({"symbol": sym, "quantity": qty, "avgCost": cost})
    return out[:50]


def _manual_portfolio_summary(doc):
    holdings = _clean_holdings(doc.get("manual_holdings"))
    cash = float(doc.get("manual_cash") or 0)
    if not holdings and not cash:
        return None
    try:
        as_of, cur, prev = _eod_quotes()
    except Exception as e:
        print(f"[portfolio/manual] EOD pricing unavailable: {e}")
        as_of, cur, prev = None, {}, {}
    positions, total = [], 0.0
    live = False
    for h in holdings:
        bar = cur.get(h["symbol"]) or {}
        q = _finnhub_quote(h["symbol"])
        if q:
            live = True
            price, prev_close = q["c"], q.get("pc")
        else:
            price = bar.get("c") or h.get("avgCost") or 0
            prev_close = (prev.get(h["symbol"]) or {}).get("c")
        mv = round(price * h["quantity"], 2)
        total += mv
        positions.append({
            "accountId": "manual", "symbol": h["symbol"], "name": h["symbol"],
            "quantity": h["quantity"], "price": price, "avgCost": h["avgCost"], "marketValue": mv,
            "dayChangePct": round(100 * (price - prev_close) / prev_close, 2) if prev_close else None,
            "unrealizedPlPct": round(100 * (price - h["avgCost"]) / h["avgCost"], 2) if h["avgCost"] else None,
            "priced": bool(q or bar),
        })
    grand = total or 1.0
    for pos in positions:
        pos["weight"] = round(100.0 * pos["marketValue"] / grand, 2)
    positions.sort(key=lambda x: x["marketValue"], reverse=True)
    return {
        "hasConnectedAccounts": True,
        "source": "manual",
        "asOf": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC") if live else as_of,
        "live": live,
        "totals": {"totalBalance": round(cash, 2), "totalInvestments": round(total, 2)},
        "accounts": [{"id": "manual", "institution": "Manual holdings", "name": "Self-reported"}],
        "positions": positions,
        "topHoldings": positions,
        "balances": [{"accountId": "manual", "amount": round(cash, 2)}],
        "orders": [],
    }


@app.route('/api/portfolio/manual', methods=['GET'])
@require_token
def get_manual_holdings():
    client = get_firestore_client()
    doc = _get_user_doc_ref(client, request.user_email).get().to_dict() or {}
    return jsonify({"holdings": _clean_holdings(doc.get("manual_holdings")),
                    "cash": float(doc.get("manual_cash") or 0)}), 200


@app.route('/api/portfolio/manual', methods=['PUT'])
@require_token
def save_manual_holdings():
    payload = request.get_json() or {}
    holdings = _clean_holdings(payload.get("holdings"))
    try:
        cash = max(0.0, float(payload.get("cash") or 0))
    except (TypeError, ValueError):
        cash = 0.0
    client = get_firestore_client()
    _get_user_doc_ref(client, request.user_email).set(
        {"manual_holdings": holdings, "manual_cash": cash, "updated_at": datetime.utcnow().isoformat()}, merge=True)
    return jsonify({"holdings": holdings, "cash": cash}), 200


@app.route('/api/portfolio/summary', methods=['GET'])
@require_token
def portfolio_summary():
    """Aggregate balances, investments, accounts, and top holdings across all SnapTrade accounts."""
    try:
        email = request.user_email
        print(f"[GET /api/portfolio/summary] Request from user: {email}")
        client = get_firestore_client()
        ref = _get_user_doc_ref(client, email)
        doc = ref.get().to_dict() or {}
        st = _get_snaptrade_info(doc)
        if not st:
            manual = _manual_portfolio_summary(doc)
            if manual:
                return jsonify(manual), 200
            print(f"[GET /api/portfolio/summary] No SnapTrade info found for: {email}")
            return jsonify({
                "hasConnectedAccounts": False,
                "totals": {"totalBalance": 0.0, "totalInvestments": 0.0},
                "accounts": [],
                "positions": [],
                "topHoldings": [],
                "balances": [],
            }), 200

        uid = st["userId"]
        sec = st["userSecret"]
        st_client = get_snaptrade_client()

        accounts_resp = st_client.account_information.list_user_accounts(
            user_id=uid, user_secret=sec
        )
        accounts = (accounts_resp.body or [])
        print(f"[GET /api/portfolio/summary] Found {len(accounts)} accounts for: {email}")

        # Fetch connections to resolve brokerage names (avoid showing "Default")
        auth_name_by_id = {}
        default_auth_name = None
        try:
            auths_resp = st_client.connections.list_brokerage_authorizations(
                user_id=uid, user_secret=sec
            )
            auth_list = (auths_resp.body or [])
            for a in auth_list:
                aid = a.get('id') or a.get('authorization_id')
                b = a.get('brokerage') or {}
                # Prefer display_name, then name, then slug
                bname = None
                if isinstance(b, dict):
                    bname = b.get('display_name') or b.get('name') or b.get('slug')
                bname = bname or a.get('name')
                if aid and bname:
                    auth_name_by_id[aid] = bname
            if auth_list:
                b = (auth_list[0] or {}).get('brokerage') or {}
                if isinstance(b, dict):
                    default_auth_name = b.get('display_name') or b.get('name') or b.get('slug')
        except Exception:
            pass

        total_balance = 0.0
        total_investments = 0.0
        all_positions = []
        balances_out = []
        acct_summaries = []
        orders_out = []

        # Helper to extract safe string symbol/name from varied SnapTrade shapes
        def _extract_symbol_and_name(position: dict):
            sym_field = position.get('symbol')
            ticker = None
            name = None

            if isinstance(sym_field, dict):
                # Could be { symbol: { symbol, description } } or direct fields
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

        for acct in accounts:
            account_id = acct.get('id') or acct.get('account_id') or acct.get('accountId')
            # Resolve brokerage/institution name
            brokerage_val = acct.get('brokerage')
            brokerage_name = None
            if isinstance(brokerage_val, dict):
                brokerage_name = brokerage_val.get('display_name') or brokerage_val.get('name') or brokerage_val.get('slug')
            elif isinstance(brokerage_val, str):
                brokerage_name = brokerage_val
            # Try via authorization mapping if name looks generic
            auth_id = (
                acct.get('authorization')
                or acct.get('brokerage_authorization')
                or acct.get('brokerage_authorization_id')
                or (acct.get('brokerage_authorization') or {}).get('id') if isinstance(acct.get('brokerage_authorization'), dict) else None
            )
            resolved_name = auth_name_by_id.get(auth_id) or brokerage_name or default_auth_name or 'Brokerage'
            if str(resolved_name).strip().lower() in {"default", "brokerage"} and default_auth_name:
                resolved_name = default_auth_name

            acct_summaries.append({
                "id": account_id,
                "name": acct.get('name') or acct.get('accountName'),
                "institution": resolved_name,
                "authorizationId": auth_id,
                "number": acct.get('number') or acct.get('accountNumber'),
            })

            # Balances
            try:
                bal_resp = st_client.account_information.get_user_account_balance(
                    user_id=uid, user_secret=sec, account_id=account_id
                )
                for b in (bal_resp.body or []):
                    amount = b.get('cash') or b.get('amount') or b.get('balance') or 0.0
                    currency = b.get('currency') or b.get('symbol') or 'USD'
                    total_balance += float(amount or 0)
                    balances_out.append({
                        "accountId": account_id,
                        "currency": currency,
                        "amount": amount,
                    })
            except Exception:
                pass

            # Positions
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

            # Recent Orders (simple: last 30 days, all states)
            try:
                ord_resp = st_client.account_information.get_user_account_orders(
                    user_id=uid, user_secret=sec, account_id=account_id, state='all', days=365
                )
                for o in (ord_resp.body or []):
                    # Minimal normalize
                    uni = o.get('universal_symbol') or o.get('quote_universal_symbol') or {}
                    symbol = ''
                    if isinstance(uni, dict):
                        symbol = uni.get('symbol') or uni.get('raw_symbol') or ''
                    if not symbol and isinstance(o.get('option_symbol'), dict):
                        symbol = (o.get('option_symbol') or {}).get('ticker') or ''
                    orders_out.append({
                        "accountId": account_id,
                        "brokerageOrderId": o.get('brokerage_order_id') or o.get('id'),
                        "status": o.get('status'),
                        "action": o.get('action'),
                        "totalQuantity": o.get('total_quantity'),
                        "filledQuantity": o.get('filled_quantity'),
                        "orderType": o.get('order_type'),
                        "timePlaced": o.get('time_placed'),
                        "timeUpdated": o.get('time_updated'),
                        "symbol": symbol,
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

        print(f"[GET /api/portfolio/summary] Successfully aggregated portfolio for: {email} - Balance: ${total_balance:.2f}, Investments: ${total_investments:.2f}, Positions: {len(all_positions)}")

        return jsonify({
            "hasConnectedAccounts": len(acct_summaries) > 0,
            "totals": {
                "totalBalance": round(float(total_balance), 2),
                "totalInvestments": round(float(total_investments), 2),
            },
            "accounts": acct_summaries,
            "positions": all_positions,
            "topHoldings": top,
            "balances": balances_out,
            "authNames": auth_name_by_id,
            "orders": sorted(orders_out, key=lambda x: (x.get('timeUpdated') or x.get('timePlaced') or ''), reverse=True),
        }), 200
    except Exception as e:
        print(f"[GET /api/portfolio/summary] ERROR: {e}")
        return jsonify({"error": "Failed to load portfolio"}), 500

@app.route('/api/orders', methods=['GET'])
@require_token
def list_orders():
    """Return recent orders. If ?accountId is omitted, returns orders from all accounts.
       Query: accountId (optional), days (int, default 30), state (default 'all')
    """
    try:
        email = request.user_email
        account_id = request.args.get('accountId')
        state = request.args.get('state') or 'all'
        try:
            days = int(request.args.get('days') or 30)
        except Exception:
            days = 30
        print(f"[GET /api/orders] Request from user: {email}, accountId: {account_id}, state: {state}, days: {days}")
        
        client = get_firestore_client()
        ref = _get_user_doc_ref(client, email)
        doc = ref.get().to_dict() or {}
        st = _get_snaptrade_info(doc)
        if not st:
            print(f"[GET /api/orders] No SnapTrade info found for: {email}")
            return jsonify({"orders": []}), 200

        uid = st["userId"]
        sec = st["userSecret"]
        st_client = get_snaptrade_client()

        def _order_symbol(o: dict):
            uni = o.get('universal_symbol') or o.get('quote_universal_symbol') or {}
            if isinstance(uni, dict):
                s = uni.get('symbol') or uni.get('raw_symbol')
                if s:
                    return s
            opt = o.get('option_symbol')
            if isinstance(opt, dict):
                t = opt.get('ticker')
                if t:
                    return t
            return ''

        def _norm(o: dict, aid: str):
            return {
                "accountId": aid,
                "brokerageOrderId": o.get("brokerage_order_id") or o.get("id"),
                "status": o.get("status"),
                "action": o.get("action"),
                "totalQuantity": o.get("total_quantity"),
                "filledQuantity": o.get("filled_quantity"),
                "orderType": o.get("order_type"),
                "timePlaced": o.get("time_placed"),
                "timeUpdated": o.get("time_updated"),
                "symbol": _order_symbol(o),
            }

        out = []
        if account_id:
            resp = st_client.account_information.get_user_account_orders(
                user_id=uid, user_secret=sec, account_id=account_id, state=state, days=days
            )
            for o in (getattr(resp, "body", None) or []):
                out.append(_norm(o, account_id))
        else:
            acc_resp = st_client.account_information.list_user_accounts(user_id=uid, user_secret=sec)
            for a in (getattr(acc_resp, "body", None) or []):
                aid = a.get('id') or a.get('account_id') or a.get('accountId')
                if not aid:
                    continue
                try:
                    resp = st_client.account_information.get_user_account_orders(
                        user_id=uid, user_secret=sec, account_id=aid, state=state, days=days
                    )
                    for o in (getattr(resp, "body", None) or []):
                        out.append(_norm(o, aid))
                except Exception:
                    continue

        out.sort(key=lambda x: (x.get('timeUpdated') or x.get('timePlaced') or ''), reverse=True)
        print(f"[GET /api/orders] Successfully retrieved {len(out)} orders for: {email}")
        return jsonify({"orders": out}), 200
    except Exception as e:
        print(f"[GET /api/orders] ERROR: {e}")
        return jsonify({"orders": []}), 200

# Helper function to get the best available logo URL
def get_logo_url(symbol):
    """
    Try different logo URLs for a symbol and return the first one that doesn't return 404.
    Falls back to a static image if all URLs return 404.
    """
    base_url = "https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main"
    icon_paths = [
        f"{base_url}/crypto_icons/{symbol}.png",
        f"{base_url}/ticker_icons/{symbol}.png", 
        f"{base_url}/forex_icons/{symbol}.png",
        f"{base_url}/exchange_icons/{symbol}.png"
    ]
    
    # Try each URL to see if it returns a valid response
    for url in icon_paths:
        try:
            response = requests.head(url, timeout=5)
            if response.status_code == 200:
                return url
        except Exception as e:
            print(f"Error checking URL {url}: {e}")
            continue
    
    # If all URLs return 404 or error, return a static fallback image
    return "https://via.placeholder.com/32x32/cccccc/666666?text=?"

@app.route('/api/ticker/<ticker>', methods=['GET'])
@require_token
def get_ticker_details(ticker: str):
    """Lean: v3 reference (details), 1M aggs (ticker), news (ticker), 1M aggs (SPY).
       No snapshot call; derive prevClose and day OHLC from the 1M aggs.
    """
    try:
        email = request.user_email
        sym = (ticker or "").strip().upper()
        print(f"[GET /api/ticker/<ticker>] Request from user: {email}, ticker: {sym}")
        
        api_key = os.environ.get("POLYGON_API_KEY")
        if not api_key:
            print(f"[GET /api/ticker/<ticker>] ERROR: Missing POLYGON_API_KEY")
            return jsonify({"error": "Missing POLYGON_API_KEY"}), 500

        if not sym:
            print(f"[GET /api/ticker/<ticker>] ERROR: Invalid ticker provided")
            return jsonify({"error": "Invalid ticker"}), 400

        def _get(url, params=None):
            q = dict(params or {})
            q["apiKey"] = api_key
            r = requests.get(url, params=q, timeout=10)
            r.raise_for_status()
            return r.json()

        # 1) v3 Reference: company details
        details = {}
        try:
            details = _get(f"https://api.polygon.io/v3/reference/tickers/{sym}")
            print(f"[GET /api/ticker/<ticker>] Fetched ticker details for: {sym}")
        except Exception as e:
            print(f"[GET /api/ticker/<ticker>] Details fetch failed for {sym}: {e}")
            details = {}
        dres = details.get("results") or {}
        branding = dres.get("branding") or {}
        branding_logo = branding.get("logo_url")
        branding_icon = branding.get("icon_url")

        # 2) Lightweight price/day using snapshot
        from datetime import datetime
        last_price = None
        prev_c = None
        day_vals = {"o": None, "h": None, "l": None, "c": None, "v": None, "vw": None}
        fq = _finnhub_quote(sym)
        if fq:
            last_price, prev_c = fq["c"], fq.get("pc")
            day_vals = {"o": fq.get("o"), "h": fq.get("h"), "l": fq.get("l"), "c": fq["c"], "v": None, "vw": None}
        else:
            try:
                snap = _get(f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{sym}") or {}
                t = snap.get("ticker") or {}
                last_price = (t.get("lastTrade") or {}).get("p") or (t.get("day") or {}).get("c")
                d = t.get("day") or {}
                day_vals = {k: d.get(k) for k in ("o", "h", "l", "c", "v", "vw")}
                prev_c = (t.get("prevDay") or {}).get("c")
            except Exception as e:
                print(f"[GET /api/ticker/<ticker>] Snapshot fetch failed for {sym}: {e}")

        change = None
        change_percent = None
        try:
            if isinstance(last_price, (int, float)) and isinstance(prev_c, (int, float)) and prev_c not in (0, 0.0):
                change = float(last_price) - float(prev_c)
                change_percent = (change / float(prev_c)) * 100.0
        except Exception:
            change = None
            change_percent = None

        # 3) News
        news = {}
        try:
            news = _get("https://api.polygon.io/v2/reference/news", params={"ticker": sym, "limit": 6})
            print(f"[GET /api/ticker/<ticker>] Fetched news for: {sym}")
        except Exception as e:
            print(f"[GET /api/ticker/<ticker>] News fetch failed for {sym}: {e}")
            news = {}

        out_news = []
        for item in (news.get("results") or [])[:6]:
            out_news.append({
                "title": item.get("title"),
                "author": item.get("author"),
                "url": item.get("article_url") or item.get("url"),
                "published": item.get("published_utc"),
                "description": item.get("description"),
                "source": item.get("source"),
            })

        # Benchmarks and timeframes are fetched on-demand by the chart now

        # Company info
        address = dres.get("address") or {}
        company = {
            "name": dres.get("name"),
            "description": dres.get("description"),
            "sector": dres.get("sic_description"),
            "industry": dres.get("sic_description"),
            "country": dres.get("locale"),
            "website": dres.get("homepage_url"),
            "ipoDate": dres.get("list_date"),
            "exchange": dres.get("primary_exchange"),
            "marketCap": dres.get("market_cap"),
            "currency": dres.get("currency_name"),
            "cik": dres.get("cik"),
            "employees": dres.get("total_employees"),
            "phone": dres.get("phone_number"),
            "address": {
                "line1": address.get("address1"),
                "city": address.get("city"),
                "state": address.get("state"),
                "postalCode": address.get("postal_code"),
            },
            "branding": {
                "icon": branding_icon,
                "logo": branding_logo,
            },
            "logo": get_logo_url(sym),
        }

        data = {
            "symbol": sym,
            "lastPrice": last_price,
            "prevClose": prev_c,
            "change": round(change, 4) if isinstance(change, (int, float)) else None,
            "changePercent": round(change_percent, 4) if isinstance(change_percent, (int, float)) else None,
            "day": {
                "open": day_vals.get("o"),
                "high": day_vals.get("h"),
                "low": day_vals.get("l"),
                "close": day_vals.get("c"),
                "volume": day_vals.get("v"),
                "vwap": day_vals.get("vw"),
            },
            "news": out_news,
            "company": company,
            # charts removed; client fetches on-demand
        }
        print(f"[GET /api/ticker/<ticker>] Successfully retrieved simplified ticker data for: {sym}, user: {email}")
        return jsonify(data), 200
    except Exception as e:
        print(f"[GET /api/ticker/<ticker>] ERROR: {e}")
        return jsonify({"error": "Failed to load ticker"}), 500


@app.route('/api/chart/timeframe', methods=['GET'])
@require_token
def get_chart_timeframe():
    """Return a single timeframe series for a symbol along with benchmark series.
       Query params:
         - ticker: main symbol (e.g., SPY)
         - tf: timeframe key in {1D, 5D, 1M, 6M, YTD, 1Y}
         - benchmarks: CSV of entries like "QQQ:nasdaq:NASDAQ 100,DIA:dow:Dow Jones"
    """
    try:
        email = request.user_email
        sym = (request.args.get('ticker') or '').strip().upper()
        tf = (request.args.get('tf') or '1M').strip().upper()
        benchmarks_param = request.args.get('benchmarks', '')
        print(f"[GET /api/chart/timeframe] User: {email}, ticker: {sym}, tf: {tf}")

        api_key = os.environ.get("POLYGON_API_KEY")
        if not api_key:
            return jsonify({"error": "Missing POLYGON_API_KEY"}), 500

        def _get(url, params=None):
            q = dict(params or {})
            q["apiKey"] = api_key
            r = requests.get(url, params=q, timeout=10)
            r.raise_for_status()
            return r.json()

        # Parse benchmark configs
        benchmark_configs = []
        if benchmarks_param:
            for bench in benchmarks_param.split(','):
                parts = bench.strip().split(':')
                if len(parts) >= 3:
                    benchmark_configs.append({'symbol': parts[0].strip().upper(), 'key': parts[1].strip().lower(), 'label': parts[2].strip()})
                elif len(parts) == 2:
                    symbol = parts[0].strip().upper()
                    benchmark_configs.append({'symbol': symbol, 'key': parts[1].strip().lower(), 'label': symbol})
                elif len(parts) == 1 and parts[0].strip():
                    symbol = parts[0].strip().upper()
                    benchmark_configs.append({'symbol': symbol, 'key': symbol.lower(), 'label': symbol})

        from datetime import timedelta, date, datetime
        today = date.today()
        today_str = today.isoformat()

        def _get_last_trading_day():
            current = date.today()
            for days_back in range(0, 8):
                check_date = current - timedelta(days=days_back)
                if check_date.weekday() < 5:
                    return check_date
            return current - timedelta(days=3)

        def _series_for_tf(ticker_sym: str, tf_key: str):
            tf_key = (tf_key or '').upper()
            if tf_key == '1D':
                try:
                    last_trading_day = _get_last_trading_day()
                    from_1d = (last_trading_day - timedelta(days=7)).isoformat()
                    aggs = _get(
                        f"https://api.polygon.io/v2/aggs/ticker/{ticker_sym}/range/5/minute/{from_1d}/{today_str}",
                        params={"adjusted": "true", "sort": "asc", "limit": 5000},
                    )
                    rows = aggs.get("results") or []
                    if rows:
                        last_ts = rows[-1].get("t")
                        if last_ts:
                            last_date = datetime.utcfromtimestamp(last_ts / 1000).date()
                            rows = [r for r in rows if datetime.utcfromtimestamp(r.get("t", 0) / 1000).date() == last_date]
            
                    # Filter for market hours: 9:30 AM - 4:00 PM EST
                    # Polygon data is in UTC, so EST market hours (9:30-16:00) are UTC (14:30-21:00) during daylight saving
                    # and UTC (14:30-21:00) during standard time
                    filtered_rows = []
                    for r in rows:
                        tms = r.get("t")
                        if isinstance(tms, (int, float)):
                            dt = datetime.utcfromtimestamp(tms / 1000)
                            # Convert UTC to EST (UTC-5) or EDT (UTC-4)
                            # Simple approach: subtract 4 or 5 hours based on DST
                            # For now, using fixed UTC-4 for EDT (most of year)
                            hour = dt.hour
                            minute = dt.minute
                            
                            # Market hours in UTC during EDT: 13:30 (9:30 AM EDT) to 20:00 (4:00 PM EDT)
                            # Market hours in UTC during EST: 14:30 (9:30 AM EST) to 21:00 (4:00 PM EST)
                            # Using EDT times (most common)
                            market_start_minutes = 13 * 60 + 30  # 13:30 UTC (9:30 AM EDT)
                            market_end_minutes = 20 * 60  # 20:00 UTC (4:00 PM EDT)
                            current_minutes = hour * 60 + minute
                            
                            if market_start_minutes <= current_minutes <= market_end_minutes:
                                filtered_rows.append(r)
                    
                    series = []
                    for r in filtered_rows:
                        tms = r.get("t")
                        cpx = r.get("c")
                        if isinstance(tms, (int, float)) and isinstance(cpx, (int, float)):
                            series.append({"t": datetime.utcfromtimestamp(tms / 1000).isoformat(), "c": cpx})
                    return series
                except Exception as e:
                    print(f"[GET /api/chart/timeframe] 1D fetch failed for {ticker_sym}: {e}")
                    return []
            elif tf_key == '5D':
                try:
                    from_5d = (today - timedelta(days=7)).isoformat()
                    aggs = _get(
                        f"https://api.polygon.io/v2/aggs/ticker/{ticker_sym}/range/1/hour/{from_5d}/{today_str}",
                        params={"adjusted": "true", "sort": "asc", "limit": 5000},
                    )
                    rows = aggs.get("results") or []
                    series = []
                    for r in rows:
                        tms = r.get("t"); cpx = r.get("c")
                        if isinstance(tms, (int, float)) and isinstance(cpx, (int, float)):
                            series.append({"t": datetime.utcfromtimestamp(tms / 1000).isoformat(), "c": cpx})
                    return series
                except Exception as e:
                    print(f"[GET /api/chart/timeframe] 5D fetch failed for {ticker_sym}: {e}")
                    return []
            elif tf_key in {'1M', '6M', 'YTD', '1Y', 'ALL'}:
                try:
                    if tf_key == '1M':
                        from_d = (today - timedelta(days=30)).isoformat()
                    elif tf_key == '6M':
                        from_d = (today - timedelta(days=180)).isoformat()
                    elif tf_key == '1Y':
                        from_d = (today - timedelta(days=365)).isoformat()
                    elif tf_key == 'ALL':
                        from_d = (today - timedelta(days=3650)).isoformat()  # ~10 years
                    else:  # YTD
                        from_d = f"{today.year}-01-01"
                    aggs = _get(
                        f"https://api.polygon.io/v2/aggs/ticker/{ticker_sym}/range/1/day/{from_d}/{today_str}",
                        params={"adjusted": "true", "sort": "asc", "limit": 50000},
                    )
                    rows = aggs.get("results") or []
                    series = []
                    for r in rows:
                        tms = r.get("t"); cpx = r.get("c")
                        if isinstance(tms, (int, float)) and isinstance(cpx, (int, float)):
                            series.append({"t": datetime.utcfromtimestamp(tms / 1000).date().isoformat(), "c": cpx})
                    return series
                except Exception as e:
                    print(f"[GET /api/chart/timeframe] {tf_key} fetch failed for {ticker_sym}: {e}")
                    return []
            else:
                return []

        # Build response for main symbol
        main_series = _series_for_tf(sym, tf)

        # Build benchmarks
        bench_out = []
        for b in benchmark_configs:
            series = _series_for_tf(b['symbol'], tf)
            bench_out.append({
                'key': b['key'],
                'label': b['label'],
                'symbol': b['symbol'],
                'series': series,
            })

        return jsonify({
            'symbol': sym,
            'timeframe': tf,
            'series': main_series,
            'benchmarks': bench_out,
        }), 200
    except Exception as e:
        print(f"[GET /api/chart/timeframe] ERROR: {e}")
        return jsonify({"error": "Failed to load timeframe"}), 500


# Add these imports at the top with other imports
from google import genai
from google.genai import types

# Add this after the existing environment variables
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
CHATBOT_MODEL = os.environ.get("CHATBOT_MODEL", "gemini-2.5-flash")

# Add this function after the existing helper functions
def get_google_genai_client():
    """Initialize Google Gemini client for chatbot responses."""
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is required for chatbot functionality")
    return genai.Client(api_key=GOOGLE_API_KEY)

def is_financial_query(query: str) -> bool:
    """Check if the query is related to financial topics."""
    financial_keywords = [
        'stock', 'stocks', 'market', 'markets', 'investment', 'investments', 'portfolio', 'trading', 'trade',
        'financial', 'finance', 'economy', 'economic', 'earnings', 'revenue', 'profit', 'loss', 'dividend',
        'bond', 'bonds', 'etf', 'etfs', 'mutual fund', 'mutual funds', 'crypto', 'cryptocurrency', 'bitcoin',
        'forex', 'currency', 'dollar', 'euro', 'yen', 'pound', 'commodity', 'commodities', 'gold', 'silver',
        'oil', 'gas', 'energy', 'sector', 'industry', 'company', 'companies', 'ipo', 'merger', 'acquisition',
        'fed', 'federal reserve', 'interest rate', 'inflation', 'recession', 'bull market', 'bear market',
        'volatility', 'risk', 'return', 'yield', 'price', 'valuation', 'analyst', 'recommendation', 'buy',
        'sell', 'hold', 'outperform', 'underperform', 'target price', 'price target', 'analyst', 'research',
        'equity', 'debt', 'balance sheet', 'income statement', 'cash flow', 'pe ratio', 'p/e', 'pb ratio',
        'p/b', 'roe', 'roa', 'debt to equity', 'current ratio', 'quick ratio', 'working capital'
    ]
    
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in financial_keywords)

# Add this endpoint after the existing routes
@app.route('/api/chatbot/query', methods=['POST'])
@require_token
def chatbot_query():
    """Handle chatbot queries using Google Gemini API, restricted to financial topics."""
    try:
        email = request.user_email
        payload = request.get_json() or {}
        user_message = payload.get('message', '').strip()
        
        print(f"[POST /api/chatbot/query] Request from user: {email}, message: {user_message[:100]}...")
        
        if not user_message:
            return jsonify({"error": "Message is required"}), 400
        
        # Check if query is financial-related
        if not is_financial_query(user_message):
            return jsonify({
                "response": "I'm Spade, your investment assistant. I can only help with financial and investment-related questions. Please ask me about stocks, markets, portfolios, or other financial topics.",
                "is_financial": False
            }), 200
        
        # Initialize Gemini client
        try:
            client = get_google_genai_client()
        except Exception as e:
            print(f"[POST /api/chatbot/query] Failed to initialize Gemini client: {e}")
            return jsonify({"error": "Chatbot service unavailable"}), 500
        
        # Create financial-focused prompt
        financial_prompt = f"""
You are Spade, a professional investment assistant. You help users with financial and investment-related questions.

User Query: {user_message}

Guidelines:
- Provide accurate, helpful financial information
- Be professional and educational in tone
- If you don't have specific current data, say so and provide general guidance
- Focus on investment education and market insights
- Do not provide specific investment advice or recommendations
- Keep responses concise but informative
- If the query is not clearly financial, politely redirect to financial topics

Respond as Spade, the investment assistant.
"""
        
        try:
            # Generate response using Gemini
            config = types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=500,
                top_p=0.8,
                top_k=40
            )
            
            response = client.models.generate_content(
                model=CHATBOT_MODEL,
                contents=financial_prompt,
                config=config
            )
            
            bot_response = getattr(response, "text", "").strip()
            
            if not bot_response:
                bot_response = "I apologize, but I couldn't generate a response. Please try rephrasing your financial question."
            
            print(f"[POST /api/chatbot/query] Successfully generated response for: {email}")
            
            return jsonify({
                "response": bot_response,
                "is_financial": True,
                "timestamp": datetime.utcnow().isoformat()
            }), 200
            
        except Exception as e:
            print(f"[POST /api/chatbot/query] Gemini API error: {e}")
            return jsonify({
                "response": "I'm experiencing technical difficulties. Please try again in a moment.",
                "is_financial": True,
                "error": "API error"
            }), 200
            
    except Exception as e:
        print(f"[POST /api/chatbot/query] ERROR: {e}")
        return jsonify({"error": "Failed to process chatbot query"}), 500

if __name__ == '__main__':
    print(f"[APP] Starting Flask server on host=0.0.0.0, port=5000, debug=True")
    app.run(debug=True, host='0.0.0.0', port=5000)
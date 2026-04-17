import os
import uuid
import hashlib
import re
import json
import queue
import threading
import requests as http
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, jsonify, send_from_directory, Response, stream_with_context, session, redirect, url_for
from PIL import Image
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool as pg_pool
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24).hex())

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXT      = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
DATABASE_URL     = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/slideshow")
DIYANET_USERNAME = os.getenv("DIYANET_USERNAME", "")
DIYANET_PASSWORD = os.getenv("DIYANET_PASSWORD", "")
DIYANET_CITY_ID  = os.getenv("DIYANET_CITY_ID", "")   # find via /api/prayer/countries -> states -> cities

# ── Predefined screens — seeded on startup ────────────────────────────────────
PREDEFINED_SCREENS = [
    {"name": "Aabenraa Camii",                  "slug": "aabenraa-camii",               "city_id": 12646},
    {"name": "Aarhus Selimiye Camii",           "slug": "aarhus-selimiye-camii",        "city_id": 12620},
    {"name": "Albertslund Alaaddin Camii",      "slug": "albertslund-alaaddin-camii",   "city_id": 17795},
    {"name": "Avedøre Haci Bayram Camii",       "slug": "avedore-haci-bayram-camii",    "city_id": 17798},
    {"name": "Ballerup Fatih Camii",            "slug": "ballerup-fatih-camii",         "city_id": 17801},
    {"name": "Brabrand Kvinde afd.",            "slug": "brabrand-kvinde-afd",          "city_id": 12620},
    {"name": "Brabrand Ulu Camii",              "slug": "brabrand-ulu-camii",           "city_id": 12620},
    {"name": "Diyanet 1",                       "slug": "diyanet-1",                    "city_id": None},
    {"name": "Diyanet 2",                       "slug": "diyanet-2",                    "city_id": None},
    {"name": "Esbjerg Cami",                    "slug": "esbjerg-cami",                 "city_id": 12638},
    {"name": "Farum Camii",                     "slug": "farum-camii",                  "city_id": 17799},
    {"name": "Fredericia Camii",                "slug": "fredericia-camii",             "city_id": 12623},
    {"name": "Frederikssund Camii",             "slug": "frederikssund-camii",          "city_id": 12627},
    {"name": "Hedehusene Fetih Camii",          "slug": "hedehusene-fetih-camii",       "city_id": 17796},
    {"name": "Herning Eyüp Camii",              "slug": "herning-eyup-camii",           "city_id": 12631},
    {"name": "Holbæk Süleymaniye Camii",        "slug": "holbaek-suleymaniye-camii",    "city_id": 12622},
    {"name": "Horsens Yunus Emre Camii",        "slug": "horsens-yunus-emre-camii",     "city_id": 12633},
    {"name": "Ikast Fatih Camii",               "slug": "ikast-fatih-camii",            "city_id": 12625},
    {"name": "Ishøj Mevlana Camii",             "slug": "ishoj-mevlana-camii",          "city_id": 17797},
    {"name": "Kocatepe Camii",                  "slug": "kocatepe-camii",               "city_id": None},
    {"name": "Køge Camii",                      "slug": "koge-camii",                   "city_id": 12629},
    {"name": "Næstved Mimar Sinan Camii",       "slug": "naestved-mimar-sinan-camii",   "city_id": 12641},
    {"name": "Nyborg Camii",                    "slug": "nyborg-camii",                 "city_id": 12614},
    {"name": "Odense Selimiye Camii",           "slug": "odense-selimiye-camii",        "city_id": 12619},
    {"name": "Randers Camii",                   "slug": "randers-camii",                "city_id": 12643},
    {"name": "Ringsted Yeni Camii",             "slug": "ringsted-yeni-camii",          "city_id": 12628},
    {"name": "Roskilde Ayasofya Camii",         "slug": "roskilde-ayasofya-camii",      "city_id": 12624},
    {"name": "Silkeborg Camii",                 "slug": "silkeborg-camii",              "city_id": 12634},
    {"name": "Slagelse Vakiflar Camii",         "slug": "slagelse-vakiflar-camii",      "city_id": 12621},
    {"name": "Svendborg Bilal Habesi Camii",    "slug": "svendborg-bilal-habesi-camii", "city_id": 12635},
    {"name": "Taastrup Yunus Emre Camii",       "slug": "taastrup-yunus-emre-camii",    "city_id": 17800},
    {"name": "Vejle Camii",                     "slug": "vejle-camii",                  "city_id": 12645},
]

PREDEFINED_GROUPS = {
    "Jutland/Fyn": [
        "aabenraa-camii",
        "aarhus-selimiye-camii",
        "brabrand-kvinde-afd",
        "brabrand-ulu-camii",
        "esbjerg-cami",
        "fredericia-camii",
        "herning-eyup-camii",
        "horsens-yunus-emre-camii",
        "ikast-fatih-camii",
        "nyborg-camii",
        "odense-selimiye-camii",
        "randers-camii",
        "silkeborg-camii",
        "svendborg-bilal-habesi-camii",
        "vejle-camii",
    ],
    "Zealand": [
        "albertslund-alaaddin-camii",
        "avedore-haci-bayram-camii",
        "ballerup-fatih-camii",
        "diyanet-1",
        "diyanet-2",
        "farum-camii",
        "frederikssund-camii",
        "hedehusene-fetih-camii",
        "holbaek-suleymaniye-camii",
        "ishoj-mevlana-camii",
        "kocatepe-camii",
        "koge-camii",
        "naestved-mimar-sinan-camii",
        "ringsted-yeni-camii",
        "roskilde-ayasofya-camii",
        "slagelse-vakiflar-camii",
        "taastrup-yunus-emre-camii",
    ],
}

# ── SSE listeners (in-memory, no need to persist) ─────────────────────────────
listeners: dict[str, list[queue.Queue]] = {}
listeners_lock = threading.Lock()

# ── Database pool ─────────────────────────────────────────────────────────────
_pool = None

def get_conn():
    return _pool.getconn()

def rel_conn(conn):
    _pool.putconn(conn)

def init_db():
    global _pool
    _pool = pg_pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS screens (
                    id     SERIAL PRIMARY KEY,
                    name   TEXT NOT NULL,
                    slug    TEXT UNIQUE NOT NULL,
                    city_id INT  DEFAULT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS library (
                    id            TEXT PRIMARY KEY,
                    filename      TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    width         INT  DEFAULT 0,
                    height        INT  DEFAULT 0,
                    start_date    DATE DEFAULT NULL,
                    end_date      DATE DEFAULT NULL,
                    created_at    TIMESTAMPTZ DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS slides (
                    id            TEXT PRIMARY KEY,
                    screen_slug   TEXT NOT NULL REFERENCES screens(slug) ON DELETE CASCADE,
                    filename      TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    duration      REAL DEFAULT 5,
                    position      INT  DEFAULT 0,
                    width         INT  DEFAULT 0,
                    height        INT  DEFAULT 0,
                    start_date    DATE DEFAULT NULL,
                    end_date      DATE DEFAULT NULL,
                    created_at    TIMESTAMPTZ DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS prayer_cache (
                    cache_date  DATE NOT NULL,
                    city_id     INT  NOT NULL,
                    times_json  TEXT NOT NULL,
                    fetched_at  TIMESTAMPTZ DEFAULT now(),
                    PRIMARY KEY (cache_date, city_id)
                );

                CREATE TABLE IF NOT EXISTS groups (
                    id   SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL
                );

                CREATE TABLE IF NOT EXISTS group_screens (
                    group_slug  TEXT NOT NULL REFERENCES groups(slug) ON DELETE CASCADE,
                    screen_slug TEXT NOT NULL REFERENCES screens(slug) ON DELETE CASCADE,
                    PRIMARY KEY (group_slug, screen_slug)
                );

                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    username      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_admin      BOOLEAN DEFAULT FALSE,
                    created_at    TIMESTAMPTZ DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS user_screens (
                    user_id     INT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    screen_slug TEXT NOT NULL REFERENCES screens(slug) ON DELETE CASCADE,
                    PRIMARY KEY (user_id, screen_slug)
                );
            """)

            # Add city_id column if upgrading from older DB
            cur.execute("ALTER TABLE screens ADD COLUMN IF NOT EXISTS city_id INT DEFAULT NULL;")
            cur.execute("ALTER TABLE slides ADD COLUMN IF NOT EXISTS start_date DATE DEFAULT NULL;")
            cur.execute("ALTER TABLE slides ADD COLUMN IF NOT EXISTS end_date DATE DEFAULT NULL;")
            # Recreate prayer_cache with city_id if it's missing that column
            cur.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='prayer_cache' AND column_name='city_id'
                    ) THEN
                        DROP TABLE IF EXISTS prayer_cache;
                    END IF;
                END $$;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS prayer_cache (
                    cache_date  DATE    NOT NULL,
                    city_id     INT     NOT NULL,
                    times_json  TEXT    NOT NULL,
                    fetched_at  TIMESTAMPTZ DEFAULT now(),
                    PRIMARY KEY (cache_date, city_id)
                );
            """)

            # Seed predefined screens — skip if already exists, update city_id if set
            for s in PREDEFINED_SCREENS:
                cur.execute(
                    "INSERT INTO screens (name, slug, city_id) VALUES (%s, %s, %s) ON CONFLICT (slug) DO UPDATE SET city_id = EXCLUDED.city_id WHERE EXCLUDED.city_id IS NOT NULL",
                    (s["name"], s["slug"], s.get("city_id"))
                )

            # Seed predefined groups
            import re as _re
            for group_name, screen_slugs in PREDEFINED_GROUPS.items():
                group_slug = _re.sub(r"[^a-z0-9_-]", "-", group_name.lower()).strip("-")
                cur.execute(
                    "INSERT INTO groups (name, slug) VALUES (%s, %s) ON CONFLICT (slug) DO NOTHING",
                    (group_name, group_slug)
                )
                for screen_slug in screen_slugs:
                    cur.execute(
                        "INSERT INTO group_screens (group_slug, screen_slug) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (group_slug, screen_slug)
                    )
            conn.commit()
    finally:
        rel_conn(conn)

# ── DB helpers ────────────────────────────────────────────────────────────────
def q_screens():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT name, slug FROM screens ORDER BY name")
            return [dict(r) for r in cur.fetchall()]
    finally:
        rel_conn(conn)

def serialize_slide(row):
    """Convert a DB row to a JSON-safe dict (strip datetime fields)."""
    d = dict(row)
    result = {k: v for k, v in d.items() if k != 'created_at'}
    # Convert date objects to ISO strings
    for f in ('start_date', 'end_date'):
        if result.get(f) is not None:
            result[f] = str(result[f])
    return result

def q_slides(slug, active_only=False):
    conn = get_conn()
    today = date.today()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if active_only:
                cur.execute(
                    """SELECT * FROM slides WHERE screen_slug=%s
                       AND (start_date IS NULL OR start_date <= %s)
                       AND (end_date IS NULL OR end_date >= %s)
                       ORDER BY position, created_at""",
                    (slug, today, today)
                )
            else:
                cur.execute(
                    "SELECT * FROM slides WHERE screen_slug=%s ORDER BY position, created_at",
                    (slug,)
                )
            return [serialize_slide(r) for r in cur.fetchall()]
    finally:
        rel_conn(conn)

def q_library():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM library ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]
    finally:
        rel_conn(conn)

def screen_exists(slug):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM screens WHERE slug=%s", (slug,))
            return cur.fetchone() is not None
    finally:
        rel_conn(conn)

# ── SSE helpers ───────────────────────────────────────────────────────────────
def push_event(slug: str, event_type: str, data: dict):
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with listeners_lock:
        for q in listeners.get(slug, []):
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

def sse_stream(slug: str):
    q: queue.Queue = queue.Queue(maxsize=20)
    with listeners_lock:
        listeners.setdefault(slug, []).append(q)
    slides = q_slides(slug, active_only=True)
    yield f"event: init\ndata: {json.dumps(slides)}\n\n"
    try:
        while True:
            try:
                msg = q.get(timeout=25)
                yield msg
            except queue.Empty:
                yield ": keep-alive\n\n"
    finally:
        with listeners_lock:
            try:
                listeners[slug].remove(q)
            except (KeyError, ValueError):
                pass

# ── Prayer Times Service ──────────────────────────────────────────────────────
class PrayerService:
    BASE = "https://awqatsalah.diyanet.gov.tr"

    def __init__(self):
        self._token      = None
        self._expires    = datetime.min
        self._lock       = threading.Lock()

    def _login(self) -> bool:
        if not DIYANET_USERNAME or not DIYANET_PASSWORD:
            return False
        try:
            r = http.post(
                f"{self.BASE}/Auth/Login",
                json={"Email": DIYANET_USERNAME, "Password": DIYANET_PASSWORD},
                timeout=10
            )
            d = r.json()
            if d.get("success"):
                self._token   = d["data"]["accessToken"]
                self._expires = datetime.now() + timedelta(minutes=40)
                return True
        except Exception as e:
            print(f"[Prayer] login error: {e}")
        return False

    def _auth_headers(self):
        if datetime.now() >= self._expires:
            self._login()
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def today(self, city_id=None):
        """Return today's prayer times for a specific city, cached in DB."""
        cid = city_id or (int(DIYANET_CITY_ID) if DIYANET_CITY_ID else None)
        if not cid:
            return None
        today = date.today()

        # Try DB cache first
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT times_json FROM prayer_cache WHERE cache_date=%s AND city_id=%s", (today, cid))
                row = cur.fetchone()
                if row:
                    return json.loads(row["times_json"])
        finally:
            rel_conn(conn)

        # Not cached — fetch from API
        with self._lock:
            conn = get_conn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT times_json FROM prayer_cache WHERE cache_date=%s AND city_id=%s", (today, cid))
                    row = cur.fetchone()
                    if row:
                        return json.loads(row["times_json"])
            finally:
                rel_conn(conn)

            try:
                hdrs = self._auth_headers()
                if not hdrs:
                    return None
                r = http.get(
                    f"{self.BASE}/api/PrayerTime/Daily/{cid}",
                    headers=hdrs,
                    timeout=10
                )
                d = r.json()
                print(f"[Prayer] daily response: {str(d)[:400]}")
                # API may return a list or a dict
                # API returns {"data": [...], "success": true}
                t = None
                if isinstance(d, dict) and d.get("data"):
                    data = d["data"]
                    t = data[0] if isinstance(data, list) and data else data
                elif isinstance(d, list) and d:
                    t = d[0]
                if t:
                    result = {
                        "sabah":  t.get("fajr") or t.get("fajrTime") or t.get("shapeFajrTime", "—"),
                        "ogle":   t.get("dhuhr") or t.get("dhuhrTime") or t.get("zuhrTime", "—"),
                        "ikindi": t.get("asr") or t.get("asrTime", "—"),
                        "aksam":  t.get("maghrib") or t.get("maghribTime", "—"),
                        "yatsi":  t.get("isha") or t.get("ishaTime", "—"),
                    }
                if t and result:
                    # Save to DB cache
                    conn = get_conn()
                    try:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO prayer_cache (cache_date, city_id, times_json)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (cache_date, city_id) DO UPDATE SET times_json=EXCLUDED.times_json
                            """, (today, cid, json.dumps(result)))
                            conn.commit()
                    finally:
                        rel_conn(conn)
                    return result
            except Exception as e:
                print(f"[Prayer] fetch error: {e}")
        return None

    def countries(self):
        hdrs = self._auth_headers()
        if not hdrs:
            return []
        try:
            r = http.get(f"{self.BASE}/api/Place/Countries", headers=hdrs, timeout=10)
            return r.json().get("data", [])
        except Exception as e:
            print(f"[Prayer] countries error: {e}")
            return []

    def states(self, country_id):
        hdrs = self._auth_headers()
        if not hdrs:
            return []
        try:
            r = http.get(f"{self.BASE}/api/Place/States/{country_id}", headers=hdrs, timeout=10)
            return r.json().get("data", [])
        except Exception as e:
            return []

    def cities(self, state_id):
        hdrs = self._auth_headers()
        if not hdrs:
            return []
        try:
            r = http.get(f"{self.BASE}/api/Place/Cities/{state_id}", headers=hdrs, timeout=10)
            return r.json().get("data", [])
        except Exception as e:
            return []

prayer = PrayerService()

# ── Utility ───────────────────────────────────────────────────────────────────
def get_ext(f): return os.path.splitext(f)[1].lower()

def validate_image(path):
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None

def save_upload(file):
    e = get_ext(file.filename)
    if e not in ALLOWED_EXT:
        return None, None
    uid  = f"{uuid.uuid4().hex}{e}"
    path = os.path.join(UPLOAD_DIR, uid)
    file.save(path)
    size = validate_image(path)
    if not size:
        os.remove(path)
        return None, None
    return uid, size

def make_slide(filename, original_name, size, duration, screen_slug, position=0, start_date=None, end_date=None):
    return {
        "id":            uuid.uuid4().hex,
        "screen_slug":   screen_slug,
        "filename":      filename,
        "original_name": original_name,
        "duration":      float(duration),
        "position":      position,
        "width":         size[0],
        "height":        size[1],
        "start_date":    start_date or None,
        "end_date":      end_date or None,
    }

def insert_slide(slide):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO slides (id, screen_slug, filename, original_name, duration, position, width, height, start_date, end_date)
                VALUES (%(id)s, %(screen_slug)s, %(filename)s, %(original_name)s, %(duration)s, %(position)s, %(width)s, %(height)s, %(start_date)s, %(end_date)s)
            """, slide)
            conn.commit()
    finally:
        rel_conn(conn)

def next_position(screen_slug):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM slides WHERE screen_slug=%s", (screen_slug,))
            return cur.fetchone()[0]
    finally:
        rel_conn(conn)

def q_groups():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT slug, name FROM groups ORDER BY name")
            grps = [dict(r) for r in cur.fetchall()]
            result = {}
            for g in grps:
                cur.execute("SELECT screen_slug FROM group_screens WHERE group_slug=%s", (g["slug"],))
                result[g["slug"]] = {"name": g["name"], "screens": [r["screen_slug"] for r in cur.fetchall()]}
            return result
    finally:
        rel_conn(conn)

# ── Auth helpers ─────────────────────────────────────────────────────────────
def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Admin access required."}), 403
        return f(*args, **kwargs)
    return decorated

def q_user_screens(user_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT screen_slug FROM user_screens WHERE user_id=%s", (user_id,))
            return [r[0] for r in cur.fetchall()]
    finally:
        rel_conn(conn)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        # Check master admin first
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            session["is_admin"]  = True
            session["username"]  = username
            session["user_id"]   = None
            return redirect(url_for("admin"))
        # Check DB users
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE username=%s AND password_hash=%s",
                            (username, hash_pw(password)))
                user = cur.fetchone()
        finally:
            rel_conn(conn)
        if user:
            session["logged_in"] = True
            session["is_admin"]  = user["is_admin"]
            session["username"]  = user["username"]
            session["user_id"]   = user["id"]
            return redirect(url_for("admin"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Admin page ────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def admin():
    is_admin    = session.get("is_admin", False)
    all_screens = q_screens()
    library     = q_library()
    groups      = q_groups()
    if is_admin:
        screens = all_screens
    else:
        user_id = session.get("user_id")
        allowed = set(q_user_screens(user_id)) if user_id else set()
        screens = [s for s in all_screens if s["slug"] in allowed]
    # Get slide counts for all screens in one query
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT screen_slug, COUNT(*) FROM slides GROUP BY screen_slug")
            slide_counts = {r[0]: r[1] for r in cur.fetchall()}
    finally:
        rel_conn(conn)

    return render_template("admin.html",
        screens=screens, library=library,
        groups=groups if is_admin else {},
        is_admin=is_admin,
        current_user=session.get("username", ""),
        slide_counts=slide_counts)

# ── Prayer times API ──────────────────────────────────────────────────────────
@app.route("/api/prayer/today")
def prayer_today():
    city_id = request.args.get("city_id", type=int)
    times = prayer.today(city_id=city_id)
    if times:
        return jsonify({"success": True, "times": times})
    return jsonify({"success": False, "times": None}), 200

# Helper routes to find city IDs (use once, then set DIYANET_CITY_ID in .env)
@app.route("/api/prayer/countries")
def prayer_countries():
    return jsonify(prayer.countries())

@app.route("/api/prayer/states/<int:country_id>")
def prayer_states(country_id):
    return jsonify(prayer.states(country_id))

@app.route("/api/prayer/cities/<int:state_id>")
def prayer_cities(state_id):
    return jsonify(prayer.cities(state_id))

# ── Library routes ────────────────────────────────────────────────────────────
@app.route("/api/library", methods=["GET"])
@login_required
def get_library():
    return jsonify(q_library())

@app.route("/api/library/upload", methods=["POST"])
@login_required
def library_upload():
    files = request.files.getlist("files")
    if not files:
        # fallback for single file
        f = request.files.get("file")
        if f:
            files = [f]
    if not files:
        return jsonify({"error": "No files provided."}), 400

    uploaded = []
    errors   = []
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for file in files:
                if not file.filename:
                    continue
                e = get_ext(file.filename)
                if e not in ALLOWED_EXT:
                    errors.append(f"{file.filename}: unsupported type")
                    continue
                uid, size = save_upload(file)
                if not uid:
                    errors.append(f"{file.filename}: could not read image")
                    continue
                item = {
                    "id": uuid.uuid4().hex,
                    "filename": uid,
                    "original_name": file.filename,
                    "width": size[0],
                    "height": size[1]
                }
                cur.execute(
                    "INSERT INTO library (id, filename, original_name, width, height) VALUES (%(id)s, %(filename)s, %(original_name)s, %(width)s, %(height)s)",
                    item
                )
                uploaded.append(item)
            conn.commit()
    finally:
        rel_conn(conn)

    if not uploaded and errors:
        return jsonify({"error": "; ".join(errors)}), 400
    return jsonify({"uploaded": uploaded, "errors": errors}), 201

@app.route("/api/library/<item_id>/remove-from-screens", methods=["DELETE"])
@login_required
def remove_from_all_screens(item_id):
    """Remove all slides using this library item from all screens."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get the filename for this library item
            cur.execute("SELECT filename FROM library WHERE id=%s", (item_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Library item not found."}), 404
            filename = row["filename"]
            # Find all slides using this file
            cur.execute("SELECT id, screen_slug FROM slides WHERE filename=%s", (filename,))
            slides = cur.fetchall()
            # Delete all those slides
            cur.execute("DELETE FROM slides WHERE filename=%s", (filename,))
            conn.commit()
            # Notify all affected screens via SSE
            notified = set()
            for slide in slides:
                slug = slide["screen_slug"]
                if slug not in notified:
                    push_event(slug, "slide_removed", {"id": slide["id"]})
                    notified.add(slug)
            return jsonify({"message": f"Removed from {len(slides)} slide(s) across {len(notified)} screen(s).", "count": len(slides)}), 200
    finally:
        rel_conn(conn)

@app.route("/api/library/<item_id>", methods=["DELETE"])
@login_required
def delete_library(item_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM library WHERE id=%s", (item_id,))
            conn.commit()
    finally:
        rel_conn(conn)
    return jsonify({"message": "Deleted."}), 200

# ── Push media to screens ─────────────────────────────────────────────────────
@app.route("/api/push", methods=["POST"])
@login_required
def push_media():
    data          = request.get_json()
    filename      = data.get("filename")
    original_name = data.get("original_name", filename)
    duration      = float(data.get("duration", 5))
    start_date    = data.get("start_date") or None
    end_date      = data.get("end_date") or None
    target_screens = data.get("screens", [])
    target_groups  = data.get("groups", [])

    if not filename:
        return jsonify({"error": "filename is required."}), 400
    filepath = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found."}), 404
    size = validate_image(filepath)
    if not size:
        return jsonify({"error": "Cannot read image."}), 400

    pushed = []

    def push_to(slug):
        if slug in pushed or not screen_exists(slug):
            return
        pos   = next_position(slug)
        slide = make_slide(filename, original_name, size, duration, slug, pos, start_date, end_date)
        insert_slide(slide)
        push_event(slug, "slide_added", slide)
        pushed.append(slug)

    # Push to individual screens
    for slug in target_screens:
        push_to(slug)

    # Push to groups — resolve screen slugs from DB
    if target_groups:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                for group_slug in target_groups:
                    cur.execute(
                        "SELECT screen_slug FROM group_screens WHERE group_slug=%s",
                        (group_slug,)
                    )
                    for row in cur.fetchall():
                        push_to(row[0])
        finally:
            rel_conn(conn)

    return jsonify({"message": f"Pushed to {len(pushed)} screen(s).", "screens": pushed}), 200

# ── Slide counts for all screens ─────────────────────────────────────────────
@app.route("/api/slide-counts")
@login_required
def slide_counts():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT screen_slug, COUNT(*) as count FROM slides GROUP BY screen_slug")
            rows = cur.fetchall()
            return jsonify({r[0]: r[1] for r in rows})
    finally:
        rel_conn(conn)

# ── Screen routes ─────────────────────────────────────────────────────────────
@app.route("/api/screens", methods=["GET"])
def list_screens():
    return jsonify(q_screens())

@app.route("/api/screens", methods=["POST"])
@login_required
def create_screen():
    data = request.get_json()
    name = (data or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Name required."}), 400
    slug = re.sub(r"[^a-z0-9_-]", "-", name.lower().strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        return jsonify({"error": "Invalid name."}), 400
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("INSERT INTO screens (name, slug) VALUES (%s, %s)", (name, slug))
                conn.commit()
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                return jsonify({"error": f"Screen '{slug}' already exists."}), 409
    finally:
        rel_conn(conn)
    return jsonify({"name": name, "slug": slug}), 201

@app.route("/api/screens/<slug>", methods=["DELETE"])
@login_required
def delete_screen(slug):
    if not screen_exists(slug):
        return jsonify({"error": "Screen not found."}), 404
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM screens WHERE slug=%s", (slug,))
            conn.commit()
    finally:
        rel_conn(conn)
    push_event(slug, "deleted", {})
    return jsonify({"message": "Deleted."}), 200

# ── Slide management ──────────────────────────────────────────────────────────
@app.route("/api/screens/<slug>/slides", methods=["GET"])
def get_slides(slug):
    if not screen_exists(slug):
        return jsonify({"error": "Screen not found."}), 404
    return jsonify(q_slides(slug))

@app.route("/api/screens/<slug>/slides/<slide_id>", methods=["DELETE"])
def remove_slide(slug, slide_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM slides WHERE id=%s AND screen_slug=%s", (slide_id, slug))
            affected = cur.rowcount
            conn.commit()
    finally:
        rel_conn(conn)
    if not affected:
        return jsonify({"error": "Slide not found."}), 404
    push_event(slug, "slide_removed", {"id": slide_id})
    return jsonify({"message": "Removed."}), 200

@app.route("/api/screens/<slug>/slides/<slide_id>/duration", methods=["PATCH"])
def update_duration(slug, slide_id):
    data = request.get_json()
    try:
        dur = float(data.get("duration", 0))
        if dur <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Duration must be a positive number."}), 400
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE slides SET duration=%s WHERE id=%s AND screen_slug=%s RETURNING *",
                (dur, slide_id, slug)
            )
            row = cur.fetchone()
            conn.commit()
    finally:
        rel_conn(conn)
    if not row:
        return jsonify({"error": "Slide not found."}), 404
    push_event(slug, "slide_updated", serialize_slide(row))
    return jsonify(serialize_slide(row)), 200

@app.route("/api/screens/<slug>/reorder", methods=["POST"])
def reorder_slides(slug):
    data      = request.get_json()
    new_order = data.get("order", [])
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for pos, slide_id in enumerate(new_order):
                cur.execute(
                    "UPDATE slides SET position=%s WHERE id=%s AND screen_slug=%s",
                    (pos, slide_id, slug)
                )
            conn.commit()
    finally:
        rel_conn(conn)
    slides = q_slides(slug)
    push_event(slug, "reordered", {"slides": slides})
    return jsonify({"message": "Reordered."}), 200

@app.route("/api/screens/<slug>/slides/<slide_id>/dates", methods=["PATCH"])
@login_required
def update_dates(slug, slide_id):
    data = request.get_json()
    start = data.get("start_date") or None
    end   = data.get("end_date") or None
    conn  = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE slides SET start_date=%s, end_date=%s WHERE id=%s AND screen_slug=%s RETURNING *",
                (start, end, slide_id, slug)
            )
            row = cur.fetchone()
            conn.commit()
    finally:
        rel_conn(conn)
    if not row:
        return jsonify({"error": "Slide not found."}), 404
    push_event(slug, "slide_updated", serialize_slide(row))
    return jsonify(serialize_slide(row)), 200

# ── SSE endpoint ──────────────────────────────────────────────────────────────
@app.route("/api/screens/<slug>/events")
def screen_events(slug):
    if not screen_exists(slug):
        return jsonify({"error": "Screen not found."}), 404
    return Response(
        stream_with_context(sse_stream(slug)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    )

# ── Display screen ────────────────────────────────────────────────────────────
@app.route("/<slug>")
def display_screen(slug):
    if not screen_exists(slug):
        return render_template("404.html", name=slug), 404
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT name, city_id FROM screens WHERE slug=%s", (slug,))
            screen = cur.fetchone()
    finally:
        rel_conn(conn)
    return render_template("screen.html", screen_slug=slug, screen_name=screen["name"], city_id=screen["city_id"] or "")

# ── Static files ──────────────────────────────────────────────────────────────
@app.route("/static/uploads/<filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/static/service-worker.js")
def service_worker():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "service-worker.js", mimetype="application/javascript")

@app.route("/logo.png")
def serve_logo():
    return send_from_directory(BASE_DIR, "logo.png")

# ── Groups API ────────────────────────────────────────────────────────────────
@app.route("/api/groups", methods=["GET"])
@login_required
def get_groups():
    return jsonify(q_groups())

@app.route("/api/groups", methods=["POST"])
@login_required
@admin_required
def create_group():
    data = request.get_json()
    name = (data or {}).get("name", "").strip()
    screens = (data or {}).get("screens", [])
    if not name:
        return jsonify({"error": "Name required."}), 400
    slug = re.sub(r"[^a-z0-9_-]", "-", name.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        return jsonify({"error": "Invalid name."}), 400
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("INSERT INTO groups (name, slug) VALUES (%s, %s)", (name, slug))
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                return jsonify({"error": f"Group '{name}' already exists."}), 409
            for screen_slug in screens:
                cur.execute(
                    "INSERT INTO group_screens (group_slug, screen_slug) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (slug, screen_slug)
                )
            conn.commit()
    finally:
        rel_conn(conn)
    return jsonify({"slug": slug, "name": name, "screens": screens}), 201

@app.route("/api/groups/<group_slug>", methods=["DELETE"])
@login_required
@admin_required
def delete_group(group_slug):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM groups WHERE slug=%s", (group_slug,))
            conn.commit()
    finally:
        rel_conn(conn)
    return jsonify({"message": "Deleted."}), 200

@app.route("/api/groups/<group_slug>/screens", methods=["PUT"])
@login_required
@admin_required
def update_group_screens(group_slug):
    data    = request.get_json()
    screens = (data or {}).get("screens", [])
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM group_screens WHERE group_slug=%s", (group_slug,))
            for slug in screens:
                cur.execute(
                    "INSERT INTO group_screens (group_slug, screen_slug) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (group_slug, slug)
                )
            conn.commit()
    finally:
        rel_conn(conn)
    return jsonify({"screens": screens}), 200

# ── Users API ────────────────────────────────────────────────────────────────
@app.route("/api/users", methods=["GET"])
@login_required
@admin_required
def list_users():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY username")
            users = [dict(r) for r in cur.fetchall()]
            for u in users:
                u["created_at"] = str(u["created_at"])[:10]
                cur.execute("SELECT screen_slug FROM user_screens WHERE user_id=%s", (u["id"],))
                u["screens"] = [r["screen_slug"] for r in cur.fetchall()]
            return jsonify(users)
    finally:
        rel_conn(conn)

@app.route("/api/users", methods=["POST"])
@login_required
@admin_required
def create_user():
    data     = request.get_json()
    username = (data or {}).get("username", "").strip()
    password = (data or {}).get("password", "").strip()
    screens  = (data or {}).get("screens", [])
    is_adm   = bool((data or {}).get("is_admin", False))
    if not username or not password:
        return jsonify({"error": "Username and password required."}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters."}), 400
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s) RETURNING id, username, is_admin",
                    (username, hash_pw(password), is_adm)
                )
                user = dict(cur.fetchone())
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                return jsonify({"error": f"Username '{username}' already exists."}), 409
            for slug in screens:
                cur.execute(
                    "INSERT INTO user_screens (user_id, screen_slug) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (user["id"], slug)
                )
            conn.commit()
            user["screens"] = screens
            return jsonify(user), 201
    finally:
        rel_conn(conn)

@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@login_required
@admin_required
def delete_user(user_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
            conn.commit()
    finally:
        rel_conn(conn)
    return jsonify({"message": "Deleted."}), 200

@app.route("/api/users/<int:user_id>/screens", methods=["PUT"])
@login_required
@admin_required
def update_user_screens(user_id):
    data    = request.get_json()
    screens = (data or {}).get("screens", [])
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_screens WHERE user_id=%s", (user_id,))
            for slug in screens:
                cur.execute(
                    "INSERT INTO user_screens (user_id, screen_slug) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (user_id, slug)
                )
            conn.commit()
    finally:
        rel_conn(conn)
    return jsonify({"screens": screens}), 200

# ── Boot ──────────────────────────────────────────────────────────────────────
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)

import os
import uuid
import json
import queue
import threading
import requests as http
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, jsonify, send_from_directory, Response, stream_with_context
from PIL import Image
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool as pg_pool
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

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
    {"name": "Aabenraa Camii",             "slug": "aabenraa-camii"},
    {"name": "Aarhus Selimiye Camii",      "slug": "aarhus-selimiye-camii"},
    {"name": "Albertslund Alaaddin Camii", "slug": "albertslund-alaaddin-camii"},
    {"name": "Avedøre Haci Bayram Camii",  "slug": "avedore-haci-bayram-camii"},
    {"name": "Ballerup Fatih Camii",       "slug": "ballerup-fatih-camii"},
    {"name": "Brabrand Kvinde afd",        "slug": "brabrand-kvinde-afd"},
    {"name": "Brabrand Ulu Camii",         "slug": "brabrand-ulu-camii"},
]

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
                    slug   TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS library (
                    id            TEXT PRIMARY KEY,
                    filename      TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    width         INT  DEFAULT 0,
                    height        INT  DEFAULT 0,
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
                    created_at    TIMESTAMPTZ DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS prayer_cache (
                    cache_date  DATE PRIMARY KEY,
                    times_json  TEXT NOT NULL,
                    fetched_at  TIMESTAMPTZ DEFAULT now()
                );
            """)
            # Seed predefined screens — skip if already exists
            for s in PREDEFINED_SCREENS:
                cur.execute(
                    "INSERT INTO screens (name, slug) VALUES (%s, %s) ON CONFLICT (slug) DO NOTHING",
                    (s["name"], s["slug"])
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

def q_slides(slug):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM slides WHERE screen_slug=%s ORDER BY position, created_at",
                (slug,)
            )
            return [dict(r) for r in cur.fetchall()]
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
    slides = q_slides(slug)
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

    def today(self):
        """Return today's prayer times, using DB cache to avoid wasting API calls."""
        if not DIYANET_CITY_ID:
            return None
        today = date.today()

        # Try DB cache first
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT times_json FROM prayer_cache WHERE cache_date=%s", (today,))
                row = cur.fetchone()
                if row:
                    return json.loads(row["times_json"])
        finally:
            rel_conn(conn)

        # Not cached — fetch from API (uses 1 of your 5 daily requests)
        with self._lock:
            # Double-check after acquiring lock
            conn = get_conn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT times_json FROM prayer_cache WHERE cache_date=%s", (today,))
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
                    f"{self.BASE}/api/PrayerTime/Daily/{DIYANET_CITY_ID}",
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
                                INSERT INTO prayer_cache (cache_date, times_json)
                                VALUES (%s, %s)
                                ON CONFLICT (cache_date) DO UPDATE SET times_json=EXCLUDED.times_json
                            """, (today, json.dumps(result)))
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

def make_slide(filename, original_name, size, duration, screen_slug, position=0):
    return {
        "id":            uuid.uuid4().hex,
        "screen_slug":   screen_slug,
        "filename":      filename,
        "original_name": original_name,
        "duration":      float(duration),
        "position":      position,
        "width":         size[0],
        "height":        size[1],
    }

def insert_slide(slide):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO slides (id, screen_slug, filename, original_name, duration, position, width, height)
                VALUES (%(id)s, %(screen_slug)s, %(filename)s, %(original_name)s, %(duration)s, %(position)s, %(width)s, %(height)s)
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

# ── Admin page ────────────────────────────────────────────────────────────────
@app.route("/")
def admin():
    screens = q_screens()
    library = q_library()
    return render_template("admin.html", screens=screens, library=library)

# ── Prayer times API ──────────────────────────────────────────────────────────
@app.route("/api/prayer/today")
def prayer_today():
    times = prayer.today()
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
def get_library():
    return jsonify(q_library())

@app.route("/api/library/upload", methods=["POST"])
def library_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename."}), 400
    e = get_ext(file.filename)
    if e not in ALLOWED_EXT:
        return jsonify({"error": f"Unsupported type '{e}'. Use JPG, PNG, GIF, or WEBP."}), 400
    uid, size = save_upload(file)
    if not uid:
        return jsonify({"error": "Could not read image."}), 400
    item = {"id": uuid.uuid4().hex, "filename": uid, "original_name": file.filename, "width": size[0], "height": size[1]}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO library (id, filename, original_name, width, height) VALUES (%(id)s, %(filename)s, %(original_name)s, %(width)s, %(height)s)",
                item
            )
            conn.commit()
    finally:
        rel_conn(conn)
    return jsonify(item), 201

@app.route("/api/library/<item_id>", methods=["DELETE"])
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
def push_media():
    data          = request.get_json()
    filename      = data.get("filename")
    original_name = data.get("original_name", filename)
    duration      = float(data.get("duration", 5))
    targets       = data.get("screens", [])

    if not filename:
        return jsonify({"error": "filename is required."}), 400
    filepath = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found."}), 404
    size = validate_image(filepath)
    if not size:
        return jsonify({"error": "Cannot read image."}), 400

    pushed = []
    for slug in targets:
        if not screen_exists(slug):
            continue
        pos   = next_position(slug)
        slide = make_slide(filename, original_name, size, duration, slug, pos)
        insert_slide(slide)
        push_event(slug, "slide_added", slide)
        pushed.append(slug)

    return jsonify({"message": f"Pushed to {len(pushed)} screen(s).", "screens": pushed}), 200

# ── Screen routes ─────────────────────────────────────────────────────────────
@app.route("/api/screens", methods=["GET"])
def list_screens():
    return jsonify(q_screens())

@app.route("/api/screens", methods=["POST"])
def create_screen():
    data = request.get_json()
    name = (data or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Name required."}), 400
    import re
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
    push_event(slug, "slide_updated", dict(row))
    return jsonify(dict(row)), 200

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
            cur.execute("SELECT name FROM screens WHERE slug=%s", (slug,))
            screen = cur.fetchone()
    finally:
        rel_conn(conn)
    return render_template("screen.html", screen_slug=slug, screen_name=screen["name"])

# ── Static files ──────────────────────────────────────────────────────────────
@app.route("/static/uploads/<filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/static/service-worker.js")
def service_worker():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "service-worker.js", mimetype="application/javascript")

# ── Boot ──────────────────────────────────────────────────────────────────────
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
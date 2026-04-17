import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/slideshow")

SCREENS = [
    {"name": "Aabenraa Camii",                  "slug": "aabenraa-camii",               "city_id": 12646},
    {"name": "Aarhus Selimiye Camii",           "slug": "aarhus-selimiye-camii",        "city_id": 12620},
    {"name": "Albertslund Alaaddin Camii",      "slug": "albertslund-alaaddin-camii",   "city_id": 17795},
    {"name": "Avedøre Haci Bayram Camii",       "slug": "avedore-haci-bayram-camii",    "city_id": 17798},
    {"name": "Ballerup Fatih Camii",            "slug": "ballerup-fatih-camii",         "city_id": 17801},
    {"name": "Brabrand Kvinde afd.",            "slug": "brabrand-kvinde-afd",          "city_id": 12620},
    {"name": "Brabrand Ulu Camii",              "slug": "brabrand-ulu-camii",           "city_id": 12620},
    {"name": "Diyanet 1",                       "slug": "diyanet-1",                    "city_id": None},   # city ID unknown
    {"name": "Diyanet 2",                       "slug": "diyanet-2",                    "city_id": None},   # city ID unknown
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
    {"name": "Kocatepe Camii",                  "slug": "kocatepe-camii",               "city_id": None},   # Frederiksberg — city ID not found yet
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

# ── Groups ────────────────────────────────────────────────────────────────────
GROUPS = {
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


def run():
    import re
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()

    print("Seeding screens...")
    for s in SCREENS:
        cur.execute(
            """INSERT INTO screens (name, slug, city_id)
               VALUES (%s, %s, %s)
               ON CONFLICT (slug) DO UPDATE
                 SET city_id = EXCLUDED.city_id
                 WHERE EXCLUDED.city_id IS NOT NULL""",
            (s["name"], s["slug"], s["city_id"])
        )
        status = f"city_id={s['city_id']}" if s["city_id"] else "no city_id"
        print(f"  {'✓' if s['city_id'] else '?'} {s['name']} ({status})")

    print("\nSeeding groups...")
    for group_name, screen_slugs in GROUPS.items():
        slug = re.sub(r"[^a-z0-9_-]", "-", group_name.lower()).strip("-")
        cur.execute(
            "INSERT INTO groups (name, slug) VALUES (%s, %s) ON CONFLICT (slug) DO NOTHING",
            (group_name, slug)
        )
        for screen_slug in screen_slugs:
            cur.execute(
                "INSERT INTO group_screens (group_slug, screen_slug) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (slug, screen_slug)
            )
        print(f"  ✓ {group_name} ({len(screen_slugs)} screens)")

    conn.commit()
    cur.close()
    conn.close()

    print("\nDone! Missing city IDs:")
    missing = [s for s in SCREENS if not s["city_id"]]
    if missing:
        for s in missing:
            print(f"  - {s['name']} ({s['slug']})")
        print("\n  To find a city ID, open: http://localhost:5000/api/prayer/cities/685")
        print("  Then update seed.py and app.py with the correct city_id.")
    else:
        print("  All screens have city IDs!")


if __name__ == "__main__":
    run()
"""Import set data from PokemonTCG/pokemon-tcg-data GitHub repo."""
import json
import requests

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GITHUB_SETS_URL, ERA_PREFIXES
from database.connection import get_db


def detect_era(set_id):
    """Determine era from set ID prefix."""
    for prefix, era in sorted(ERA_PREFIXES.items(), key=lambda x: -len(x[0])):
        if set_id.startswith(prefix):
            return era
    return "classic"


def import_all_sets():
    """Download sets/en.json and upsert all sets into DB. Returns count."""
    print("Downloading sets from GitHub...")
    resp = requests.get(GITHUB_SETS_URL, timeout=30)
    resp.raise_for_status()
    sets_data = resp.json()

    with get_db() as conn:
        for s in sets_data:
            conn.execute("""
                INSERT OR REPLACE INTO sets
                (id, name, series, printed_total, total_cards, release_date,
                 logo_url, symbol_url, ptcgo_code, era, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s["id"], s["name"], s.get("series"),
                s.get("printedTotal"), s.get("total"),
                s.get("releaseDate"),
                s.get("images", {}).get("logo"),
                s.get("images", {}).get("symbol"),
                s.get("ptcgoCode"),
                detect_era(s["id"]),
                s.get("updatedAt"),
            ))
    return len(sets_data)

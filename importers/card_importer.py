"""Import card data from PokemonTCG/pokemon-tcg-data GitHub repo."""
import json
import requests

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GITHUB_CARDS_URL
from database.connection import get_db


def import_set_cards(set_id):
    """Download cards/en/{set_id}.json and upsert cards. Returns count."""
    url = f"{GITHUB_CARDS_URL}/{set_id}.json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    cards_data = resp.json()

    with get_db() as conn:
        for c in cards_data:
            conn.execute("""
                INSERT OR REPLACE INTO cards
                (id, set_id, name, number, rarity, supertype, subtypes,
                 hp, types, artist, image_url_small, image_url_large,
                 regulation_mark)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                c["id"], set_id, c["name"], c["number"],
                c.get("rarity"),
                c.get("supertype"),
                json.dumps(c.get("subtypes", [])),
                c.get("hp"),
                json.dumps(c.get("types", [])),
                c.get("artist"),
                c.get("images", {}).get("small"),
                c.get("images", {}).get("large"),
                c.get("regulationMark"),
            ))
    return len(cards_data)


def import_all_cards():
    """Import cards for all sets in the DB. Returns total card count."""
    total = 0
    with get_db() as conn:
        set_ids = [row["id"] for row in conn.execute("SELECT id FROM sets ORDER BY release_date").fetchall()]

    print(f"Importing cards for {len(set_ids)} sets...")
    for i, set_id in enumerate(set_ids, 1):
        try:
            count = import_set_cards(set_id)
            total += count
            if i % 20 == 0 or i == len(set_ids):
                print(f"  [{i}/{len(set_ids)}] {total} cards imported so far...")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"  [{i}/{len(set_ids)}] SKIP {set_id} (no card file)")
            else:
                print(f"  [{i}/{len(set_ids)}] ERROR {set_id}: {e}")
        except Exception as e:
            print(f"  [{i}/{len(set_ids)}] ERROR {set_id}: {e}")
    return total

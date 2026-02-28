"""Pull rate resolution: era-based templates with per-set overrides."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import get_db


def get_set_pull_rates(set_id):
    """
    Return resolved pull rates for a set.
    Each entry: {rarity, slot_type, guaranteed_count, probability_per_pack, notes}

    Logic:
    1. Look up the set's era.
    2. Load all template rates for that era.
    3. Apply any overrides from pull_rate_overrides for this set_id.
    """
    with get_db() as conn:
        row = conn.execute("SELECT era FROM sets WHERE id = ?", (set_id,)).fetchone()
        if not row:
            return []
        era = row["era"]

        templates = conn.execute(
            "SELECT rarity, slot_type, guaranteed_count, probability_per_pack, notes "
            "FROM pull_rate_templates WHERE era = ?", (era,)
        ).fetchall()

        overrides = conn.execute(
            "SELECT rarity, slot_type, guaranteed_count, probability_per_pack, notes "
            "FROM pull_rate_overrides WHERE set_id = ?", (set_id,)
        ).fetchall()

    # Build result: start with templates, then apply overrides
    rates = {}
    for t in templates:
        key = (t["rarity"], t["slot_type"])
        rates[key] = {
            "rarity": t["rarity"],
            "slot_type": t["slot_type"],
            "guaranteed_count": t["guaranteed_count"],
            "probability_per_pack": t["probability_per_pack"],
            "notes": t["notes"],
        }

    for o in overrides:
        key = (o["rarity"], o["slot_type"])
        rates[key] = {
            "rarity": o["rarity"],
            "slot_type": o["slot_type"],
            "guaranteed_count": o["guaranteed_count"] if o["guaranteed_count"] is not None
                else rates.get(key, {}).get("guaranteed_count", 0),
            "probability_per_pack": o["probability_per_pack"] if o["probability_per_pack"] is not None
                else rates.get(key, {}).get("probability_per_pack", 0),
            "notes": o["notes"],
        }

    return list(rates.values())


def get_god_pack_data(set_id):
    """Return god pack configurations for a set."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT name, odds, composition, description FROM god_packs WHERE set_id = ?",
            (set_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_available_rarities(set_id):
    """Return list of distinct rarities present in a set."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT rarity FROM cards WHERE set_id = ? AND rarity IS NOT NULL ORDER BY rarity",
            (set_id,),
        ).fetchall()
    return [r["rarity"] for r in rows]

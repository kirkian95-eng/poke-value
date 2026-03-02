#!/usr/bin/env python3
"""Zero-token EV query for Stephen. Reads SQLite directly, prints JSON."""
import json
import re
import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pokemon_tcg_ev.db")

# Common prefixes to strip from search input
_STRIP_PREFIXES = re.compile(
    r'^(pokemon|pokémon|ptcg|tcg|pkmn)\s+', re.IGNORECASE
)
# Era prefixes like "sv:", "swsh:", "sv " used as qualifiers
_ERA_PREFIX = re.compile(
    r'^(sv|swsh|sm|xy|bw)[:\s]+', re.IGNORECASE
)


def _normalize_search(term):
    """Normalize search term: strip common prefixes, lowercase, collapse whitespace."""
    t = term.strip()
    t = _STRIP_PREFIXES.sub('', t)
    t = _ERA_PREFIX.sub('', t)
    return ' '.join(t.split()).lower()


def _score_set(row, search_lower, search_words):
    """Score a set match. Lower = better. Returns None if no match."""
    name_lower = (row["name"] or "").lower()
    id_lower = (row["id"] or "").lower()
    ptcgo_lower = (row["ptcgo_code"] or "").lower()
    series_lower = (row["series"] or "").lower()
    combined = f"{name_lower} {series_lower} {id_lower} {ptcgo_lower}"

    # Exact name match
    if search_lower == name_lower:
        return 0
    # Exact ptcgo_code match
    if search_lower == ptcgo_lower and ptcgo_lower:
        return 1
    # Exact id match
    if search_lower == id_lower:
        return 2
    # All search words found in combined fields
    if search_words and all(w in combined for w in search_words):
        return 3
    # Partial name match
    if search_lower in name_lower:
        return 4
    # Partial id match
    if search_lower in id_lower:
        return 5
    # Partial combined match
    if search_lower in combined:
        return 6
    return None


def _find_set(conn, search_term):
    """Find best matching set using word-based scoring."""
    search_lower = _normalize_search(search_term)
    search_words = search_lower.split() if ' ' in search_lower or len(search_lower) <= 4 else []

    # Also try the raw term (un-normalized) for direct matches
    raw_lower = search_term.strip().lower()

    rows = conn.execute("""
        SELECT s.id, s.name, s.series, s.release_date, s.total_cards, s.era,
               s.has_god_pack, s.ptcgo_code,
               e.ev_per_pack, e.pack_price, e.calculated_at
        FROM sets s
        LEFT JOIN ev_cache e ON s.id = e.set_id
    """).fetchall()

    best_row = None
    best_score = 999
    best_date = ""

    for row in rows:
        # Try normalized search
        score = _score_set(row, search_lower, search_words)
        # Also try raw input (handles cases where normalization hurts)
        if score is None and raw_lower != search_lower:
            score = _score_set(row, raw_lower, raw_lower.split())
        if score is None:
            continue
        release = row["release_date"] or ""
        # Prefer: lower score, then more recent release date
        if score < best_score or (score == best_score and release > best_date):
            best_score = score
            best_date = release
            best_row = row

    return best_row


def query_ev(search_term):
    if not os.path.exists(DB_PATH):
        return {"error": f"Database not found at {DB_PATH}"}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = _find_set(conn, search_term)

    if not row:
        conn.close()
        return {"error": f'No set found matching "{search_term}"'}

    set_id = row["id"]
    ev = row["ev_per_pack"]

    if ev is None:
        conn.close()
        return {
            "error": f'Set "{row["name"]}" ({set_id}) found but has no price data yet.',
            "fix": f"Run: python3 /home/ubuntu/pokemon-tcg-ev/cli.py update-prices --set {set_id} --no-pokewallet && python3 /home/ubuntu/pokemon-tcg-ev/cli.py calc-ev --set {set_id}",
        }

    # Top 10 most valuable cards
    top_cards = conn.execute("""
        SELECT c.name, c.rarity,
               COALESCE(p.tcg_market, p.cm_trend * 1.08, p.cm_avg * 1.08, 0) as price
        FROM cards c
        LEFT JOIN prices p ON c.id = p.card_id
        WHERE c.set_id = ?
        ORDER BY price DESC
        LIMIT 10
    """, (set_id,)).fetchall()

    # Rarity breakdown
    rarity_summary = conn.execute("""
        SELECT c.rarity, COUNT(*) as cnt,
               ROUND(AVG(COALESCE(p.tcg_market, p.cm_trend * 1.08, p.cm_avg * 1.08, 0)), 2) as avg_price
        FROM cards c
        LEFT JOIN prices p ON c.id = p.card_id
        WHERE c.set_id = ? AND c.rarity IS NOT NULL
        GROUP BY c.rarity
        ORDER BY avg_price DESC
    """, (set_id,)).fetchall()

    conn.close()

    # Pack value distribution stats (import lazily to avoid circular deps)
    dist_stats = {}
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from engine.ev_calculator import calculate_pack_distribution
        dist = calculate_pack_distribution(set_id)
        if dist and dist.get("stats"):
            s = dist["stats"]
            dist_stats = {
                "median_pack": s["median"],
                "p_beat_msrp_pct": s["p_profit"],
                "p_10_plus_pct": s["p_10"],
                "p_20_plus_pct": s["p_20"],
                "p_50_plus_pct": s["p_50"],
                "p90_value": s["p90"],
                "p99_value": s["p99"],
                "base_value": s["base_value"],
            }
    except Exception:
        pass

    msrp = row["pack_price"] or 4.49
    output = {
        "set_name": row["name"],
        "set_id": set_id,
        "series": row["series"] or "",
        "release_date": row["release_date"] or "",
        "total_cards": row["total_cards"] or 0,
        "ev_per_pack": round(ev, 2),
        "pack_msrp": msrp,
        "value_ratio_pct": round(ev / msrp * 100, 1) if msrp > 0 else 0,
        "fair_price": round(ev, 2),
        "has_god_pack": bool(row["has_god_pack"]),
        "calculated_at": row["calculated_at"] or "",
        "top_cards": [
            {"name": c["name"], "rarity": c["rarity"], "price": round(c["price"], 2)}
            for c in top_cards
        ],
        "rarity_summary": [
            {"rarity": r["rarity"], "count": r["cnt"], "avg_price": r["avg_price"]}
            for r in rarity_summary
        ],
    }
    if dist_stats:
        output["distribution"] = dist_stats
    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: query_ev.py 'set name'"}))
        sys.exit(1)

    result = query_ev(sys.argv[1])
    print(json.dumps(result, indent=2))

    if "error" in result:
        sys.exit(2 if "fix" in result else 1)

"""
Set-level analysis functions: completion cost, rip-or-flip, cross-set comparisons,
pack investment ROI, chase card trends.

Shared engine module used by multiple features.
"""
import re
import sys
import os
from datetime import datetime, date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import get_db
from engine.ev_calculator import calculate_set_ev

# Flat MSRP assumption for pack investment ROI
PACK_MSRP = 4.00


# Pack count mapping: product_type -> packs per product
PACK_COUNTS = {
    "booster_box": 36,
    "booster_bundle": 6,
    "elite_trainer_box": 9,
    "etb": 9,
    "collection_box": 4,
    "premium_collection": 6,
    "ultra_premium_collection": 16,
    "blister": 1,
    "3_pack_blister": 3,
    "sleeved_booster": 1,
    "build_battle_box": 4,
    "build_battle_stadium": 12,
    "mini_tin": 2,
    "tin": 4,
    "booster_pack": 1,
}

# Name-based heuristics for when product_type is missing or generic
_NAME_PACK_PATTERNS = [
    (r"booster\s*box", 36),
    (r"elite\s*trainer\s*box", 9),
    (r"\betb\b", 9),
    (r"ultra\s*premium", 16),
    (r"premium\s*collection", 6),
    (r"booster\s*bundle", 6),
    (r"build.*battle.*stadium", 12),
    (r"build.*battle", 4),
    (r"3[\s-]*pack\s*blister", 3),
    (r"mini\s*tin", 2),
    (r"\btin\b", 4),
    (r"collection", 4),
    (r"blister", 1),
]


def _estimate_pack_count(product_type, name):
    """Estimate number of packs in a sealed product."""
    if product_type:
        pt = product_type.lower().strip()
        if pt in PACK_COUNTS:
            return PACK_COUNTS[pt]

    # Fall back to name heuristics
    name_lower = (name or "").lower()
    for pattern, count in _NAME_PACK_PATTERNS:
        if re.search(pattern, name_lower):
            return count

    return None


def get_set_completion_cost(set_id):
    """Compute the total cost to complete a set (one of every card).

    Returns dict with market/low/mid totals, cards priced vs missing,
    and breakdown by rarity. Missing prices are excluded from totals
    but counted in cards_missing.
    """
    with get_db() as conn:
        set_row = conn.execute(
            "SELECT id, name, total_cards FROM sets WHERE id = ?",
            (set_id,)
        ).fetchone()

        if not set_row:
            return None

        rows = conn.execute("""
            SELECT c.id, c.name, c.number, c.rarity,
                   p.tcg_market, p.tcg_low, p.tcg_mid
            FROM cards c
            LEFT JOIN prices p ON c.id = p.card_id
            WHERE c.set_id = ?
            ORDER BY CAST(c.number AS INTEGER)
        """, (set_id,)).fetchall()

    cards = [dict(r) for r in rows]
    total_cards = len(cards)

    total_market = 0.0
    total_low = 0.0
    total_mid = 0.0
    cards_priced = 0
    rarity_map = {}  # rarity -> {count, priced, market, low, mid}

    for card in cards:
        rarity = card["rarity"] or "Unknown"

        if rarity not in rarity_map:
            rarity_map[rarity] = {
                "rarity": rarity,
                "count": 0,
                "priced": 0,
                "market": 0.0,
                "low": 0.0,
                "mid": 0.0,
            }

        bucket = rarity_map[rarity]
        bucket["count"] += 1

        market = card["tcg_market"] or 0
        low = card["tcg_low"] or 0
        mid = card["tcg_mid"] or 0

        if market > 0 or low > 0:
            cards_priced += 1
            bucket["priced"] += 1
            bucket["market"] += market
            bucket["low"] += low
            bucket["mid"] += mid
            total_market += market
            total_low += low
            total_mid += mid

    # Sort breakdown by market cost descending (most expensive rarities first)
    breakdown = sorted(rarity_map.values(), key=lambda b: b["market"], reverse=True)

    return {
        "set_id": set_row["id"],
        "set_name": set_row["name"],
        "total_cards": total_cards,
        "cards_priced": cards_priced,
        "cards_missing": total_cards - cards_priced,
        "total_market": round(total_market, 2),
        "total_low": round(total_low, 2),
        "total_mid": round(total_mid, 2),
        "breakdown": [
            {
                "rarity": b["rarity"],
                "count": b["count"],
                "priced": b["priced"],
                "market": round(b["market"], 2),
                "low": round(b["low"], 2),
                "mid": round(b["mid"], 2),
            }
            for b in breakdown
        ],
    }


def get_rip_or_flip(set_id):
    """Compare sealed product prices vs EV of contents for a set.

    Returns list of sealed products with rip/flip verdict and margin.
    """
    # Get EV per pack
    ev_result = calculate_set_ev(set_id)
    ev_per_pack = ev_result.get("ev_per_pack", 0) if ev_result else 0

    with get_db() as conn:
        set_row = conn.execute(
            "SELECT id, name FROM sets WHERE id = ?", (set_id,)
        ).fetchone()
        if not set_row:
            return None

        products = conn.execute("""
            SELECT id, name, product_type, tcg_market, tcg_low
            FROM sealed_products
            WHERE set_id = ?
            ORDER BY tcg_market DESC
        """, (set_id,)).fetchall()

    results = []
    for p in products:
        product = dict(p)
        sealed_price = product["tcg_market"] or 0
        pack_count = _estimate_pack_count(product["product_type"], product["name"])

        if not pack_count or sealed_price <= 0 or ev_per_pack <= 0:
            product["pack_count"] = pack_count
            product["ev_contents"] = 0
            product["margin"] = 0
            product["margin_pct"] = 0
            product["verdict"] = "unknown"
            product["confidence"] = "low"
            results.append(product)
            continue

        ev_contents = round(ev_per_pack * pack_count, 2)
        margin = round(ev_contents - sealed_price, 2)
        margin_pct = round(margin / sealed_price * 100, 1) if sealed_price > 0 else 0

        if margin_pct > 10:
            verdict = "rip"
        elif margin_pct < -10:
            verdict = "flip"
        else:
            verdict = "even"

        # Confidence based on price data coverage
        coverage = ev_result.get("cards_with_prices", 0) / max(ev_result.get("total_cards", 1), 1)
        if coverage >= 0.9:
            confidence = "high"
        elif coverage >= 0.7:
            confidence = "medium"
        else:
            confidence = "low"

        product["pack_count"] = pack_count
        product["ev_contents"] = ev_contents
        product["margin"] = margin
        product["margin_pct"] = margin_pct
        product["verdict"] = verdict
        product["confidence"] = confidence
        results.append(product)

    return {
        "set_id": set_row["id"],
        "set_name": set_row["name"],
        "ev_per_pack": round(ev_per_pack, 2),
        "products": sorted(results, key=lambda x: x["margin"], reverse=True),
    }


# ── Filters for identifying a single loose booster pack per set ──

_PACK_EXCLUDE_PATTERNS = re.compile(
    r"code card|art bundle|set of \d|bundle|sleeved|1st edition|"
    r"first edition|blister|case|half case|sample|display",
    re.IGNORECASE,
)


def _pick_loose_pack(products):
    """From a list of booster_pack products, pick the single loose unlimited pack.

    Prefers the simplest name (plain 'X Booster Pack' or 'X Booster Pack [Unlimited Edition]').
    Falls back to cheapest remaining after exclusions.
    Returns a single product dict or None.
    """
    candidates = []
    for p in products:
        name = p["name"] or ""
        if _PACK_EXCLUDE_PATTERNS.search(name):
            continue
        price = p["tcg_market"]
        if not price or price <= 0:
            continue
        candidates.append(p)

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Prefer the one with the shortest name (most likely the plain booster pack)
    candidates.sort(key=lambda p: len(p["name"] or ""))
    return candidates[0]


def get_pack_investment_data(era_filter=None, min_year=None):
    """Calculate investment ROI for sealed loose booster packs across all sets.

    Assumes $4 MSRP cost basis. Returns list sorted by release_date.
    """
    with get_db() as conn:
        query = """
            SELECT sp.name, sp.tcg_market, sp.tcg_low,
                   s.id as set_id, s.name as set_name, s.era, s.release_date
            FROM sealed_products sp
            JOIN sets s ON sp.set_id = s.id
            WHERE sp.product_type = 'booster_pack'
              AND sp.tcg_market IS NOT NULL AND sp.tcg_market > 0
        """
        params = []
        if era_filter:
            query += " AND s.era = ?"
            params.append(era_filter)
        if min_year:
            query += " AND s.release_date >= ?"
            params.append(f"{min_year}/01/01")
        query += " ORDER BY s.release_date"
        rows = conn.execute(query, params).fetchall()

    # Group by set_id, pick one loose pack per set
    by_set = {}
    for r in rows:
        sid = r["set_id"]
        if sid not in by_set:
            by_set[sid] = {
                "set_id": sid,
                "set_name": r["set_name"],
                "era": r["era"],
                "release_date": r["release_date"],
                "packs": [],
            }
        by_set[sid]["packs"].append({
            "name": r["name"],
            "tcg_market": r["tcg_market"],
            "tcg_low": r["tcg_low"],
        })

    today = date.today()
    results = []
    for info in by_set.values():
        pack = _pick_loose_pack(info["packs"])
        if not pack:
            continue

        # Parse release date (format: YYYY/MM/DD)
        rd = info["release_date"]
        if not rd:
            continue
        try:
            parts = rd.split("/")
            release = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            continue

        days_held = (today - release).days
        if days_held <= 0:
            continue
        years_held = days_held / 365.25

        current_price = pack["tcg_market"]
        total_return = (current_price / PACK_MSRP) - 1
        if years_held >= 1:
            annualized_roi = (current_price / PACK_MSRP) ** (1 / years_held) - 1
        else:
            annualized_roi = total_return  # less than 1 year, just use total

        results.append({
            "set_id": info["set_id"],
            "set_name": info["set_name"],
            "era": info["era"],
            "release_date": info["release_date"],
            "release_year": release.year,
            "years_held": round(years_held, 1),
            "pack_name": pack["name"],
            "current_price": round(current_price, 2),
            "cost_basis": PACK_MSRP,
            "total_return_pct": round(total_return * 100, 1),
            "annualized_roi_pct": round(annualized_roi * 100, 1),
        })

    results.sort(key=lambda x: x["release_date"])
    return results


def get_chase_card_trends(top_n=1):
    """Get the most valuable cards per set, ordered by release date.

    Args:
        top_n: Number of top cards per set (1, 3, or 10)

    Returns list of sets with their top card(s) and values.
    """
    with get_db() as conn:
        sets = conn.execute("""
            SELECT s.id, s.name, s.era, s.release_date
            FROM sets s
            ORDER BY s.release_date
        """).fetchall()

        results = []
        for s in sets:
            cards = conn.execute("""
                SELECT c.name, c.number, c.rarity, p.tcg_market
                FROM cards c
                JOIN prices p ON c.id = p.card_id
                WHERE c.set_id = ? AND p.tcg_market IS NOT NULL AND p.tcg_market > 0
                ORDER BY p.tcg_market DESC
                LIMIT ?
            """, (s["id"], max(top_n, 10))).fetchall()

            if not cards:
                continue

            rd = s["release_date"]
            if not rd:
                continue
            try:
                parts = rd.split("/")
                release_year = int(parts[0])
            except (ValueError, IndexError):
                continue

            top_cards = [dict(c) for c in cards]

            top_1 = top_cards[0] if top_cards else None
            top_3_avg = (sum(c["tcg_market"] for c in top_cards[:3]) / min(len(top_cards), 3)
                         if top_cards else 0)
            top_10_avg = (sum(c["tcg_market"] for c in top_cards[:10]) / min(len(top_cards), 10)
                          if top_cards else 0)

            results.append({
                "set_id": s["id"],
                "set_name": s["name"],
                "era": s["era"],
                "release_date": rd,
                "release_year": release_year,
                "top_1_card": top_1["name"] if top_1 else None,
                "top_1_rarity": top_1["rarity"] if top_1 else None,
                "top_1_price": round(top_1["tcg_market"], 2) if top_1 else 0,
                "top_3_avg": round(top_3_avg, 2),
                "top_10_avg": round(top_10_avg, 2),
                "cards_priced": len(top_cards),
            })

    return results


# Default PSA grading fee (economy tier)
GRADING_FEE = 20.0


def get_psa_analysis(set_id=None, sort_by="pop_score", grade="10",
                     min_price=0, limit=500):
    """Analyze PSA pop + graded price data to find undervalued cards.

    Metrics per card:
    - pop: PSA population at the given grade
    - graded_price: market price at the given grade
    - raw_price: ungraded/TCGCSV market price
    - grade_premium: graded_price / raw_price
    - pop_score: price / ln(pop + 1) — lower = potentially undervalued for its rarity
    - grading_roi: (graded_price - raw_price - fee) / (raw_price + fee)

    sort_by: 'pop_score' (asc), 'pop' (asc), 'graded_price', 'grade_premium', 'grading_roi'
    """
    import math

    grade_col = f"psa_{grade}" if grade.isdigit() else "psa_10"
    grade_label = f"Grade {grade}" if grade.isdigit() else "Grade 10"

    with get_db() as conn:
        query = """
            SELECT c.id, c.name, c.number, c.rarity, c.set_id,
                   s.name as set_name, s.era,
                   pop.psa_7, pop.psa_8, pop.psa_9, pop.psa_10, pop.total_graded,
                   p.tcg_market as raw_price
            FROM psa_pop pop
            JOIN cards c ON pop.card_id = c.id
            JOIN sets s ON c.set_id = s.id
            LEFT JOIN prices p ON c.id = p.card_id
        """
        params = []
        if set_id:
            query += " WHERE c.set_id = ?"
            params.append(set_id)

        rows = conn.execute(query, params).fetchall()

        gp_rows = conn.execute(
            "SELECT card_id, grade, market_price FROM graded_prices"
        ).fetchall()

    gp_map = {}
    for r in gp_rows:
        if r["card_id"] not in gp_map:
            gp_map[r["card_id"]] = {}
        gp_map[r["card_id"]][r["grade"]] = r["market_price"]

    results = []
    for r in rows:
        card_id = r["id"]
        pop_val = r[grade_col] if grade_col in r.keys() else r["psa_10"]
        raw_price = r["raw_price"] or 0

        card_prices = gp_map.get(card_id, {})
        graded_price = card_prices.get(grade_label)

        grade_premium = None
        grading_roi = None
        pop_score = None

        if graded_price and graded_price > 0:
            if raw_price > 0:
                grade_premium = round(graded_price / raw_price, 1)
                grading_roi = round(
                    (graded_price - raw_price - GRADING_FEE) /
                    (raw_price + GRADING_FEE) * 100, 1
                )
            if pop_val > 0:
                pop_score = round(graded_price / math.log(pop_val + 1), 2)

        entry = {
            "card_id": card_id,
            "card_name": r["name"],
            "card_number": r["number"],
            "rarity": r["rarity"],
            "set_id": r["set_id"],
            "set_name": r["set_name"],
            "era": r["era"],
            "psa_7": r["psa_7"],
            "psa_8": r["psa_8"],
            "psa_9": r["psa_9"],
            "psa_10": r["psa_10"],
            "total_graded": r["total_graded"],
            "pop": pop_val,
            "raw_price": round(raw_price, 2) if raw_price else None,
            "graded_price": round(graded_price, 2) if graded_price else None,
            "grade_premium": grade_premium,
            "pop_score": pop_score,
            "grading_roi": grading_roi,
        }
        results.append(entry)

    if sort_by == "pop_score":
        results.sort(key=lambda x: (x["pop_score"] is None, x["pop_score"] or 0))
    elif sort_by == "pop":
        results.sort(key=lambda x: x["pop"])
    elif sort_by == "graded_price":
        results.sort(key=lambda x: (x["graded_price"] is None, -(x["graded_price"] or 0)))
    elif sort_by == "grade_premium":
        results.sort(key=lambda x: (x["grade_premium"] is None, -(x["grade_premium"] or 0)))
    elif sort_by == "grading_roi":
        results.sort(key=lambda x: (x["grading_roi"] is None, -(x["grading_roi"] or 0)))
    else:
        results.sort(key=lambda x: -(x["total_graded"] or 0))

    if min_price > 0:
        results = [r for r in results if (r["raw_price"] or 0) >= min_price]

    return results[:limit]


# ── Sealed Product Contents — promo card overrides for specific products ──
# Products are auto-detected by type (booster_box=36 packs, etb=8-9, upc=16).
# This dict adds promo card info. Key: lowercase substring match on product name.

PRODUCT_PROMOS = {
    # ── Pokemon 151 (sv3pt5) ──
    "151 ultra-premium collection": ["svp-51", "svp-52", "svp-53"],
    "151: zapdos ex collection": ["svp-49"],
    "151: alakazam ex collection": ["svp-50"],
    "151 poster collection": ["svp-46", "svp-47", "svp-48"],
    "151 binder collection": ["svp-55"],
    # ── Sword & Shield UPCs ──
    "charizard ultra-premium collection": ["swshp-SWSH262"],
    "arceus vstar ultra-premium collection": ["swshp-SWSH307"],
    # ── Celebrations ──
    "celebrations ultra-premium collection": [],
}

# Skip these substrings when scanning sealed products
_SEALED_SKIP = re.compile(
    r"code card|case|display|half|bulk|sample|set of \d",
    re.IGNORECASE,
)


def _detect_pack_count(product_type, name, era):
    """Auto-detect pack count for booster boxes, ETBs, and UPCs."""
    name_lower = (name or "").lower()

    # Booster box
    if product_type == "booster_box" or "booster box" in name_lower:
        if "enhanced" in name_lower:
            return 30
        return 36

    # Elite Trainer Box
    if product_type in ("etb", "elite_trainer_box") or "elite trainer box" in name_lower:
        if era in ("sv", "classic"):
            return 9
        return 8

    # Ultra-Premium Collection
    if "ultra-premium" in name_lower or "ultra premium" in name_lower:
        return 16

    return None


def get_sealed_value_breakdown(set_id=None):
    """Break down sealed product value: packs + promos vs sealed price.

    Auto-detects booster boxes (36 packs), ETBs (8-9 by era), and UPCs (16).
    Overlays promo card prices from PRODUCT_PROMOS where known.
    """
    with get_db() as conn:
        query = """
            SELECT sp.*, s.name as set_name, s.era
            FROM sealed_products sp
            JOIN sets s ON sp.set_id = s.id
            WHERE sp.tcg_market > 0
        """
        params = []
        if set_id:
            query += " AND sp.set_id = ?"
            params.append(set_id)
        query += " ORDER BY s.release_date DESC, sp.tcg_market DESC"
        products = conn.execute(query, params).fetchall()

        # Loose booster pack price per set
        pack_rows = conn.execute("""
            SELECT set_id, name, tcg_market FROM sealed_products
            WHERE product_type = 'booster_pack' AND tcg_market > 0
            ORDER BY set_id, LENGTH(name)
        """).fetchall()
        pack_by_set = {}
        for r in pack_rows:
            pack_by_set.setdefault(r["set_id"], []).append(
                {"name": r["name"], "tcg_market": r["tcg_market"]})
        pack_prices = {}
        for sid, packs in pack_by_set.items():
            picked = _pick_loose_pack(packs)
            if picked:
                pack_prices[sid] = picked["tcg_market"]

        # EV per pack
        ev_rows = conn.execute(
            "SELECT set_id, ev_per_pack FROM ev_cache WHERE ev_per_pack > 0"
        ).fetchall()
        ev_map = {r["set_id"]: r["ev_per_pack"] for r in ev_rows}

        # Promo card prices — batch lookup all referenced cards
        all_promo_ids = set()
        for promo_list in PRODUCT_PROMOS.values():
            all_promo_ids.update(promo_list)
        card_prices = {}
        if all_promo_ids:
            ph = ",".join("?" * len(all_promo_ids))
            rows = conn.execute(f"""
                SELECT c.id, c.name, c.number, p.tcg_market
                FROM cards c LEFT JOIN prices p ON c.id = p.card_id
                WHERE c.id IN ({ph})
            """, list(all_promo_ids)).fetchall()
            for r in rows:
                card_prices[r["id"]] = {
                    "name": r["name"], "number": r["number"],
                    "price": r["tcg_market"] or 0,
                }

    seen = set()
    results = []
    for product in products:
        pname = product["name"] or ""
        pname_lower = pname.lower()

        # Skip unwanted products
        if _SEALED_SKIP.search(pname):
            continue

        # Auto-detect pack count
        era = product["era"]
        num_packs = _detect_pack_count(product["product_type"], pname, era)
        if not num_packs:
            continue

        # Dedupe (TCGCSV sometimes lists same product under multiple groups)
        dedup_key = (pname_lower, product["set_id"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        pack_set = product["set_id"]
        pack_market = pack_prices.get(pack_set, 0)
        ev_per_pack = ev_map.get(pack_set, 0)

        pack_resale = round(pack_market * num_packs, 2)
        pack_ev = round(ev_per_pack * num_packs, 2)

        # Look up promo cards from override dict
        promo_details = []
        promo_total = 0
        for match_key, promo_ids in PRODUCT_PROMOS.items():
            if match_key in pname_lower:
                for card_id in promo_ids:
                    info = card_prices.get(card_id)
                    if info:
                        promo_details.append({
                            "card_id": card_id,
                            "name": info["name"],
                            "price": round(info["price"], 2),
                        })
                        promo_total += info["price"]
                break

        sealed_price = product["tcg_market"] or 0
        resale_total = round(pack_resale + promo_total, 2)
        ev_total = round(pack_ev + promo_total, 2)

        results.append({
            "product_name": pname,
            "product_type": product["product_type"],
            "set_id": pack_set,
            "set_name": product["set_name"],
            "era": era,
            "sealed_price": round(sealed_price, 2),
            "num_packs": num_packs,
            "pack_market_each": round(pack_market, 2),
            "pack_resale_total": pack_resale,
            "pack_ev_each": round(ev_per_pack, 2),
            "pack_ev_total": pack_ev,
            "promos": promo_details,
            "promo_total": round(promo_total, 2),
            "resale_total": resale_total,
            "ev_total": ev_total,
            "resale_delta": round(resale_total - sealed_price, 2),
            "ev_delta": round(ev_total - sealed_price, 2),
        })

    return results


# ── Phase 2: Cross-Set Rarity, Grading ROI, Arbitrage, Price-Rarity Scatter ──

# Rarity rank for scatter plot ordering (1=Common ... 9=Hyper Rare)
RARITY_RANK = {
    "Common": 1, "Uncommon": 2, "Rare": 3, "Promo": 3, "Black White Rare": 3,
    "Rare Holo": 4,
    "Double Rare": 5, "Rare Holo EX": 5, "Rare Holo GX": 5, "Rare Holo V": 5,
    "Rare Ultra": 5, "Ultra Rare": 5, "Rare BREAK": 5, "Rare Prime": 5,
    "ACE SPEC Rare": 5, "Trainer Gallery Rare Holo": 5, "LEGEND": 5,
    "Rare Prism Star": 5, "Rare ACE": 5, "Classic Collection": 5,
    "Rare Holo VMAX": 6, "Rare Holo VSTAR": 6, "Rare Holo LV.X": 6,
    "Illustration Rare": 6, "Shiny Rare": 6, "Rare Shiny": 6,
    "Rare Shiny GX": 6, "Radiant Rare": 6, "Amazing Rare": 6,
    "MEGA_ATTACK_RARE": 6,
    "Rare Rainbow": 7, "Rare Secret": 7, "Shiny Ultra Rare": 7,
    "Rare Shining": 7, "Rare Holo Star": 7,
    "Special Illustration Rare": 8,
    "Hyper Rare": 9, "Mega Hyper Rare": 9,
}

# Expected grade distribution for grading ROI (community averages)
GRADE_DISTRIBUTION = {
    "Grade 10": 0.15,
    "Grade 9": 0.40,
    "Grade 8": 0.25,
    "Grade 7": 0.10,
    "Grade 6": 0.05,
    "Grade 5": 0.03,
    "Grade 4": 0.02,
}


def get_cross_set_rarity_stats(rarity_filter=None, era_filter=None):
    """Compare average card prices by rarity across sets."""
    with get_db() as conn:
        query = """
            SELECT c.set_id, s.name as set_name, s.era, s.release_date,
                   c.rarity,
                   COUNT(*) as card_count,
                   COUNT(CASE WHEN p.tcg_market > 0 THEN 1 END) as priced,
                   AVG(CASE WHEN p.tcg_market > 0 THEN p.tcg_market END) as avg_price,
                   MIN(CASE WHEN p.tcg_market > 0 THEN p.tcg_market END) as min_price,
                   MAX(CASE WHEN p.tcg_market > 0 THEN p.tcg_market END) as max_price,
                   SUM(CASE WHEN p.tcg_market > 0 THEN p.tcg_market ELSE 0 END) as total_price
            FROM cards c
            JOIN sets s ON c.set_id = s.id
            LEFT JOIN prices p ON c.id = p.card_id
            WHERE c.rarity IS NOT NULL
        """
        params = []
        if rarity_filter:
            query += " AND c.rarity = ?"
            params.append(rarity_filter)
        else:
            query += " AND c.rarity NOT IN ('Common', 'Uncommon')"
        if era_filter:
            query += " AND s.era = ?"
            params.append(era_filter)
        query += " GROUP BY c.set_id, c.rarity HAVING priced > 0"
        query += " ORDER BY s.release_date DESC, avg_price DESC"
        rows = conn.execute(query, params).fetchall()

    return [
        {
            "set_id": r["set_id"],
            "set_name": r["set_name"],
            "era": r["era"],
            "release_date": r["release_date"],
            "rarity": r["rarity"],
            "card_count": r["card_count"],
            "priced": r["priced"],
            "avg_price": round(r["avg_price"], 2) if r["avg_price"] else 0,
            "min_price": round(r["min_price"], 2) if r["min_price"] else 0,
            "max_price": round(r["max_price"], 2) if r["max_price"] else 0,
            "total_price": round(r["total_price"], 2) if r["total_price"] else 0,
        }
        for r in rows
    ]


def get_grading_roi_candidates(set_id=None, grading_fee=20.0, limit=500):
    """Find best grading candidates using grade distribution probabilities.

    Expected graded value = sum(grade_prob * grade_price) for known grades,
    normalized if not all grades have prices.
    """
    with get_db() as conn:
        query = """
            SELECT DISTINCT c.id, c.name, c.number, c.rarity, c.set_id,
                   s.name as set_name, s.era,
                   p.tcg_market as raw_price
            FROM graded_prices gp
            JOIN cards c ON gp.card_id = c.id
            JOIN sets s ON c.set_id = s.id
            LEFT JOIN prices p ON c.id = p.card_id
        """
        params = []
        if set_id:
            query += " WHERE c.set_id = ?"
            params.append(set_id)
        cards = conn.execute(query, params).fetchall()
        gp_rows = conn.execute(
            "SELECT card_id, grade, market_price FROM graded_prices"
        ).fetchall()

    gp_map = {}
    for r in gp_rows:
        gp_map.setdefault(r["card_id"], {})[r["grade"]] = r["market_price"]

    results = []
    for c in cards:
        card_id = c["id"]
        raw_price = c["raw_price"] or 0
        prices = gp_map.get(card_id, {})
        if not prices or raw_price <= 0:
            continue

        expected_value = 0
        total_prob = 0
        grade_prices = {}
        for grade_label, prob in GRADE_DISTRIBUTION.items():
            price = prices.get(grade_label)
            if price and price > 0:
                expected_value += prob * price
                total_prob += prob
                grade_prices[grade_label] = round(price, 2)

        if total_prob > 0 and total_prob < 1:
            expected_value = expected_value / total_prob
        if expected_value <= 0:
            continue

        expected_profit = expected_value - raw_price - grading_fee
        roi = (expected_profit / (raw_price + grading_fee)) * 100
        psa_10 = prices.get("Grade 10", 0)

        results.append({
            "card_id": card_id,
            "card_name": c["name"],
            "card_number": c["number"],
            "rarity": c["rarity"],
            "set_id": c["set_id"],
            "set_name": c["set_name"],
            "era": c["era"],
            "raw_price": round(raw_price, 2),
            "expected_graded_value": round(expected_value, 2),
            "expected_profit": round(expected_profit, 2),
            "roi_pct": round(roi, 1),
            "psa_10_price": round(psa_10, 2) if psa_10 else None,
            "psa_10_premium": round(psa_10 / raw_price, 1) if psa_10 and raw_price > 0 else None,
            "grade_prices": grade_prices,
        })

    results.sort(key=lambda x: -x["roi_pct"])
    return results[:limit]


def get_arbitrage_opportunities(set_id=None, min_spread=2.0):
    """Find price gaps between TCGPlayer and PriceCharting for the same card."""
    with get_db() as conn:
        query = """
            SELECT c.id, c.name, c.number, c.rarity, c.set_id,
                   s.name as set_name, s.era,
                   p.tcg_market, p.tcg_low,
                   gp.market_price as pc_ungraded
            FROM graded_prices gp
            JOIN cards c ON gp.card_id = c.id
            JOIN sets s ON c.set_id = s.id
            JOIN prices p ON c.id = p.card_id
            WHERE gp.grade = 'Ungraded'
              AND p.tcg_market > 0 AND gp.market_price > 0
        """
        params = []
        if set_id:
            query += " AND c.set_id = ?"
            params.append(set_id)
        rows = conn.execute(query, params).fetchall()

    results = []
    for r in rows:
        tcg = r["tcg_market"]
        pc = r["pc_ungraded"]
        spread = abs(tcg - pc)
        avg_p = (tcg + pc) / 2
        spread_pct = (spread / avg_p * 100) if avg_p > 0 else 0
        if spread < min_spread:
            continue
        direction = ("Buy PriceCharting, Sell TCGPlayer" if tcg > pc
                     else "Buy TCGPlayer, Sell PriceCharting")
        results.append({
            "card_id": r["id"],
            "card_name": r["name"],
            "card_number": r["number"],
            "rarity": r["rarity"],
            "set_id": r["set_id"],
            "set_name": r["set_name"],
            "era": r["era"],
            "tcgplayer_price": round(tcg, 2),
            "pricecharting_price": round(pc, 2),
            "spread": round(spread, 2),
            "spread_pct": round(spread_pct, 1),
            "direction": direction,
        })

    results.sort(key=lambda x: -x["spread"])
    return results


def get_rarity_scatter_data(set_id):
    """Get price vs rarity data for scatter plot on set detail page."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.name, c.number, c.rarity, p.tcg_market
            FROM cards c
            JOIN prices p ON c.id = p.card_id
            WHERE c.set_id = ? AND p.tcg_market > 0
            ORDER BY p.tcg_market DESC
        """, (set_id,)).fetchall()

    return [
        {
            "name": r["name"],
            "number": r["number"],
            "rarity": r["rarity"] or "Unknown",
            "rarity_rank": RARITY_RANK.get(r["rarity"], 3),
            "price": round(r["tcg_market"], 2),
        }
        for r in rows
    ]

"""
Expected Value calculator for Pokemon TCG booster packs.

EV Model:
---------
A pack has multiple slot types:

1. GUARANTEED SLOTS (commons, uncommons):
   P(specific card in pack) = guaranteed_count / N_cards_of_that_rarity
   EV contribution = sum over all cards: P(card) * price(card)

2. HIT SLOT (the rare+ slot, one per pack):
   P(rarity) = probability from pull rate template/override
   P(specific card in pack) = P(rarity) / N_cards_of_that_rarity
   EV contribution = sum: P(card) * price(card)

3. REVERSE HOLO SLOTS (2 per pack in SV era, 1 in older eras):
   Drawn from common+uncommon+rare pool with reverse holo treatment.
   Priced using actual TCGPlayer reverse holo market prices (tcg_reverse_holo).
   P(specific card) = slot_count / N_reverse_eligible

4. GOD PACK ADJUSTMENT:
   EV = (1 - god_pack_odds) * normal_EV + god_pack_odds * god_pack_EV
"""
import json
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import EUR_TO_USD
from database.connection import get_db
from engine.pull_rates import get_set_pull_rates, get_god_pack_data

# Rarities eligible for reverse holo slot
REVERSE_HOLO_POOL = ("Common", "Uncommon", "Rare", "Rare Holo")


def _get_price(card):
    """Get the best available USD price for a card (normal/holofoil print)."""
    tcg = card.get("tcg_market")
    if tcg and tcg > 0:
        return tcg
    cm_trend = card.get("cm_trend")
    if cm_trend and cm_trend > 0:
        return cm_trend * EUR_TO_USD
    cm_avg = card.get("cm_avg")
    if cm_avg and cm_avg > 0:
        return cm_avg * EUR_TO_USD
    return 0.0


def _get_reverse_holo_price(card):
    """Get the reverse holo price for a card. Falls back to normal price if unavailable."""
    rev = card.get("tcg_reverse_holo")
    if rev and rev > 0:
        return rev
    # Fallback: use normal price (better than the old 50% assumption)
    return _get_price(card)


def calculate_set_ev(set_id):
    """
    Calculate expected value of opening one booster pack from a set.

    Returns dict with ev_per_pack, ev_breakdown, god_pack_adjustment, etc.
    """
    pull_rates = get_set_pull_rates(set_id)
    god_packs = get_god_pack_data(set_id)

    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.id, c.name, c.number, c.rarity, c.supertype,
                   p.tcg_market, p.tcg_reverse_holo, p.cm_avg, p.cm_trend
            FROM cards c
            LEFT JOIN prices p ON c.id = p.card_id
            WHERE c.set_id = ?
        """, (set_id,)).fetchall()

        set_info = conn.execute(
            "SELECT name, printed_total FROM sets WHERE id = ?", (set_id,)
        ).fetchone()

    cards = [dict(r) for r in rows]

    # Group cards by rarity
    by_rarity = {}
    for card in cards:
        r = card.get("rarity") or "Unknown"
        by_rarity.setdefault(r, []).append(card)

    # Calculate EV for each pull rate entry
    ev_total = 0.0
    breakdown = []

    for rate in pull_rates:
        rarity = rate["rarity"]
        slot_type = rate["slot_type"]
        guaranteed = rate["guaranteed_count"]
        prob_per_pack = rate["probability_per_pack"]

        if slot_type == "reverse_holo":
            # Reverse holos drawn from common+uncommon+rare pool
            reverse_cards = []
            for r in REVERSE_HOLO_POOL:
                reverse_cards.extend(by_rarity.get(r, []))
            n_rev = len(reverse_cards)
            if n_rev == 0:
                continue

            rarity_ev = 0.0
            for card in reverse_cards:
                price = _get_reverse_holo_price(card)
                p_card = guaranteed / n_rev
                rarity_ev += p_card * price

            ev_total += rarity_ev
            avg_price = sum(_get_reverse_holo_price(c) for c in reverse_cards) / n_rev
            breakdown.append({
                "rarity": "Reverse Holo",
                "card_count": n_rev,
                "slot_type": slot_type,
                "ev_contribution": round(rarity_ev, 4),
                "avg_price": round(avg_price, 2),
                "probability_each": round(guaranteed / n_rev, 6),
            })
            continue

        # Guaranteed or hit_slot
        rarity_cards = by_rarity.get(rarity, [])
        n_cards = len(rarity_cards)
        if n_cards == 0:
            continue

        if slot_type == "guaranteed":
            p_each = guaranteed / n_cards
        else:  # hit_slot
            p_each = prob_per_pack / n_cards

        rarity_ev = 0.0
        for card in rarity_cards:
            price = _get_price(card)
            rarity_ev += p_each * price

        ev_total += rarity_ev
        avg_price = sum(_get_price(c) for c in rarity_cards) / n_cards
        breakdown.append({
            "rarity": rarity,
            "card_count": n_cards,
            "slot_type": slot_type,
            "ev_contribution": round(rarity_ev, 4),
            "avg_price": round(avg_price, 2),
            "probability_each": round(p_each, 6),
        })

    # God pack adjustment
    god_pack_adj = 0.0
    for gp in god_packs:
        gp_odds = gp["odds"]
        gp_composition = json.loads(gp.get("composition") or "[]")
        gp_ev = _compute_god_pack_ev(gp_composition, cards)
        # God pack replaces normal pack:
        # total = (1 - odds) * normal + odds * god_pack
        # adjustment = odds * (god_pack_ev - normal_ev)
        god_pack_adj += gp_odds * (gp_ev - ev_total)

    final_ev = ev_total + god_pack_adj

    cards_with_prices = sum(1 for c in cards if _get_price(c) > 0)

    # Sort breakdown by EV contribution descending
    breakdown.sort(key=lambda x: x["ev_contribution"], reverse=True)

    result = {
        "set_id": set_id,
        "set_name": set_info["name"] if set_info else set_id,
        "ev_per_pack": round(final_ev, 2),
        "ev_breakdown": breakdown,
        "god_pack_adjustment": round(god_pack_adj, 4),
        "total_cards": len(cards),
        "cards_with_prices": cards_with_prices,
        "calculated_at": datetime.utcnow().isoformat(),
    }

    # Only cache if the set exists in DB
    if set_info:
        _cache_ev(set_id, result)
    return result


def _compute_god_pack_ev(composition, all_cards):
    """Compute EV of a god pack given its composition."""
    if not composition:
        return 0.0

    card_map = {c["id"]: c for c in all_cards}
    total = 0.0

    for item in composition:
        if isinstance(item, str):
            card = card_map.get(item)
            if card:
                total += _get_price(card)
        elif isinstance(item, dict):
            rarity = item.get("rarity")
            count = item.get("count", 1)
            matching = [c for c in all_cards if c.get("rarity") == rarity]
            if matching:
                avg = sum(_get_price(c) for c in matching) / len(matching)
                total += avg * count
    return total


def _cache_ev(set_id, result):
    """Store computed EV in the cache table."""
    with get_db() as conn:
        # Use real sealed pack price if available, else fall back to MSRP
        pack_row = conn.execute("""
            SELECT MIN(tcg_market) FROM sealed_products
            WHERE set_id = ? AND tcg_market > 0
              AND (name LIKE '%ooster Pack%' OR name LIKE '%ooster pack%')
              AND name NOT LIKE '%Case%'
              AND name NOT LIKE '%Bundle%'
              AND name NOT LIKE '%Set of%'
              AND name NOT LIKE '%Art Bundle%'
              AND name NOT LIKE '%Code Card%'
              AND name NOT LIKE '%code card%'
              AND name NOT LIKE '%Sleeved%'
        """, (set_id,)).fetchone()
        if pack_row and pack_row[0]:
            pack_price = pack_row[0]
        else:
            # Only use default MSRP for modern sets still in print
            from config import DEFAULT_PACK_MSRP
            era = conn.execute(
                "SELECT era FROM sets WHERE id = ?", (set_id,)
            ).fetchone()
            era_val = era["era"] if era else ""
            if era_val in ("sv", "mega"):
                pack_price = DEFAULT_PACK_MSRP
            else:
                pack_price = None

        conn.execute("""
            INSERT OR REPLACE INTO ev_cache
            (set_id, ev_per_pack, ev_breakdown, pack_price, calculated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            set_id,
            result["ev_per_pack"],
            json.dumps(result["ev_breakdown"]),
            pack_price,
            result["calculated_at"],
        ))


def calculate_pack_distribution(set_id):
    """
    Calculate the full probability distribution of pack values.

    Every pack has a fixed base value from guaranteed slots (commons, uncommons,
    reverse holos). The variance comes from the hit slot, which can land on any
    hit-eligible card. This function computes the discrete distribution over all
    possible hit slot outcomes.

    Returns dict with:
      - outcomes: list of {value, probability, card_name, rarity} sorted by value
      - histogram: list of {label, probability, min_val, max_val} bucketed for display
      - stats: {median, p75, p90, p99, p_profit, p_10, p_20, p_50, base_value, msrp}
    """
    from config import DEFAULT_PACK_MSRP

    pull_rates = get_set_pull_rates(set_id)

    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.id, c.name, c.number, c.rarity, c.supertype,
                   p.tcg_market, p.tcg_reverse_holo, p.cm_avg, p.cm_trend
            FROM cards c
            LEFT JOIN prices p ON c.id = p.card_id
            WHERE c.set_id = ?
        """, (set_id,)).fetchall()

        # Use real pack price from ev_cache if available
        pack_row = conn.execute(
            "SELECT pack_price FROM ev_cache WHERE set_id = ?", (set_id,)
        ).fetchone()

    pack_price = (pack_row["pack_price"] if pack_row and pack_row["pack_price"]
                  else DEFAULT_PACK_MSRP)

    cards = [dict(r) for r in rows]
    if not cards:
        return {"outcomes": [], "histogram": [], "stats": {}}

    by_rarity = {}
    for card in cards:
        r = card.get("rarity") or "Unknown"
        by_rarity.setdefault(r, []).append(card)

    # 1. Calculate base_value from guaranteed + reverse holo slots
    base_value = 0.0
    for rate in pull_rates:
        rarity = rate["rarity"]
        slot_type = rate["slot_type"]
        guaranteed = rate["guaranteed_count"]

        if slot_type == "reverse_holo":
            reverse_cards = []
            for r in REVERSE_HOLO_POOL:
                reverse_cards.extend(by_rarity.get(r, []))
            n_rev = len(reverse_cards)
            if n_rev == 0:
                continue
            for card in reverse_cards:
                price = _get_reverse_holo_price(card)
                p_card = guaranteed / n_rev
                base_value += p_card * price

        elif slot_type == "guaranteed":
            rarity_cards = by_rarity.get(rarity, [])
            n_cards = len(rarity_cards)
            if n_cards == 0:
                continue
            p_each = guaranteed / n_cards
            for card in rarity_cards:
                base_value += p_each * _get_price(card)

    # 2. Build distribution from hit slot outcomes
    outcomes = []
    for rate in pull_rates:
        if rate["slot_type"] != "hit_slot":
            continue
        rarity = rate["rarity"]
        prob_rarity = rate["probability_per_pack"]
        rarity_cards = by_rarity.get(rarity, [])
        n_cards = len(rarity_cards)
        if n_cards == 0:
            continue

        p_each = prob_rarity / n_cards
        for card in rarity_cards:
            card_price = _get_price(card)
            pack_value = round(base_value + card_price, 2)
            outcomes.append({
                "value": pack_value,
                "probability": p_each,
                "card_name": card["name"],
                "rarity": rarity,
            })

    if not outcomes:
        return {"outcomes": [], "histogram": [], "stats": {}}

    # Sort by value
    outcomes.sort(key=lambda x: x["value"])

    # 3. Compute summary stats
    total_prob = sum(o["probability"] for o in outcomes)

    # Cumulative probability for percentiles
    cum = 0.0
    median = outcomes[-1]["value"]
    p75 = outcomes[-1]["value"]
    p90 = outcomes[-1]["value"]
    p99 = outcomes[-1]["value"]
    found_median = found_p75 = found_p90 = found_p99 = False

    for o in outcomes:
        cum += o["probability"]
        frac = cum / total_prob if total_prob > 0 else 0
        if not found_median and frac >= 0.50:
            median = o["value"]
            found_median = True
        if not found_p75 and frac >= 0.75:
            p75 = o["value"]
            found_p75 = True
        if not found_p90 and frac >= 0.90:
            p90 = o["value"]
            found_p90 = True
        if not found_p99 and frac >= 0.99:
            p99 = o["value"]
            found_p99 = True

    # P(pack >= threshold) = sum of probabilities where value >= threshold
    p_profit = sum(o["probability"] for o in outcomes if o["value"] >= pack_price) / total_prob if total_prob > 0 else 0
    p_10 = sum(o["probability"] for o in outcomes if o["value"] >= 10) / total_prob if total_prob > 0 else 0
    p_20 = sum(o["probability"] for o in outcomes if o["value"] >= 20) / total_prob if total_prob > 0 else 0
    p_50 = sum(o["probability"] for o in outcomes if o["value"] >= 50) / total_prob if total_prob > 0 else 0

    # 4. Build histogram bins
    max_val = max(o["value"] for o in outcomes)
    if max_val <= 10:
        bin_edges = [0, 1, 2, 3, 4, 5, 7, 10]
    elif max_val <= 30:
        bin_edges = [0, 1, 2, 3, 5, 10, 15, 20, 30]
    elif max_val <= 60:
        bin_edges = [0, 2, 5, 10, 20, 30, 50, 60]
    else:
        bin_edges = [0, 2, 5, 10, 20, 50, 100, max_val + 1]

    # Insert pack_price as a bin edge if it fits within range
    if 2 < pack_price < max_val and pack_price not in bin_edges:
        bin_edges.append(pack_price)
        bin_edges.sort()

    # Ensure max_val is covered
    if bin_edges[-1] <= max_val:
        bin_edges.append(max_val + 1)

    histogram = []
    for i in range(len(bin_edges) - 1):
        lo = bin_edges[i]
        hi = bin_edges[i + 1]
        bin_prob = sum(o["probability"] for o in outcomes if lo <= o["value"] < hi)
        bin_pct = bin_prob / total_prob * 100 if total_prob > 0 else 0
        if lo == 0:
            label = f"< ${hi:.0f}" if hi == int(hi) else f"< ${hi:.2f}"
        elif i == len(bin_edges) - 2:
            label = f"${lo:.0f}+" if lo == int(lo) else f"${lo:.2f}+"
        else:
            lo_s = f"${lo:.0f}" if lo == int(lo) else f"${lo:.2f}"
            hi_s = f"${hi:.0f}" if hi == int(hi) else f"${hi:.2f}"
            label = f"{lo_s}-{hi_s}"
        histogram.append({
            "label": label,
            "probability": round(bin_pct, 1),
            "min_val": lo,
            "max_val": hi,
        })

    stats = {
        "median": round(median, 2),
        "p75": round(p75, 2),
        "p90": round(p90, 2),
        "p99": round(p99, 2),
        "p_profit": round(p_profit * 100, 1),
        "p_10": round(p_10 * 100, 1),
        "p_20": round(p_20 * 100, 1),
        "p_50": round(p_50 * 100, 1),
        "base_value": round(base_value, 2),
        "pack_price": round(pack_price, 2),
    }

    return {
        "outcomes": outcomes,
        "histogram": histogram,
        "stats": stats,
    }


# ── Graded EV Model ──────────────────────────────────────────────────────
# Pack-fresh grade distributions derived from PSA pop data by era.
# Represents P(grade | card pulled from a sealed pack).
# Keys are PSA grades 10 down to 6; remainder lumped into "below".
_GRADE_DIST = {
    "sv":    {10: 0.37, 9: 0.48, 8: 0.12, 7: 0.02, 6: 0.01},
    "mega":  {10: 0.37, 9: 0.48, 8: 0.12, 7: 0.02, 6: 0.01},
    "swsh":  {10: 0.54, 9: 0.35, 8: 0.08, 7: 0.02, 6: 0.01},
    "sm":    {10: 0.41, 9: 0.37, 8: 0.16, 7: 0.03, 6: 0.02},
    "xy":    {10: 0.22, 9: 0.37, 8: 0.24, 7: 0.09, 6: 0.05},
    "bw":    {10: 0.08, 9: 0.28, 8: 0.31, 7: 0.16, 6: 0.09},
    "hgss":  {10: 0.05, 9: 0.25, 8: 0.35, 7: 0.18, 6: 0.09},
    "pl":    {10: 0.05, 9: 0.25, 8: 0.35, 7: 0.18, 6: 0.09},
    "dp":    {10: 0.05, 9: 0.25, 8: 0.35, 7: 0.18, 6: 0.09},
    "ex":    {10: 0.11, 9: 0.28, 8: 0.26, 7: 0.13, 6: 0.09},
    "ecard": {10: 0.05, 9: 0.20, 8: 0.30, 7: 0.20, 6: 0.12},
    "neo":   {10: 0.05, 9: 0.21, 8: 0.32, 7: 0.18, 6: 0.12},
    "base":  {10: 0.03, 9: 0.17, 8: 0.30, 7: 0.20, 6: 0.14},
}

# Grade price multipliers vs raw (ungraded) price.
# Derived from PriceCharting graded price data (20-card sample).
# Modern cards have lower multipliers; vintage has extreme PSA 10 premiums.
_GRADE_MULT_MODERN = {10: 2.5, 9: 1.4, 8: 1.0, 7: 0.85, 6: 0.70}
_GRADE_MULT_VINTAGE = {10: 12.0, 9: 3.5, 8: 1.5, 7: 1.0, 6: 0.75}
_MODERN_ERAS = {"sv", "mega", "swsh", "sm"}


def _expected_graded_value(card_id, raw_price, era, graded_prices_map=None):
    """
    Estimate the expected graded value of a card.

    Uses actual graded prices from graded_prices_map when available,
    otherwise applies era-based grade multipliers to the raw price.
    Weights by pack-fresh grade distribution for the era.
    Remainder probability (grades below 6) uses raw price.

    Args:
        graded_prices_map: dict of {card_id: {int_grade: price}} pre-loaded
            from DB. If None, will query DB (slower, avoid in loops).

    Returns the expected value (before grading fee).
    """
    if raw_price <= 0:
        return 0.0

    grade_dist = _GRADE_DIST.get(era, _GRADE_DIST.get("sv"))

    # Get graded prices for this card
    if graded_prices_map is not None:
        graded_map = graded_prices_map.get(card_id, {})
    else:
        with get_db() as conn:
            graded = conn.execute("""
                SELECT grade, market_price FROM graded_prices
                WHERE card_id = ? AND market_price > 0
            """, (card_id,)).fetchall()
        graded_map = {}
        for g in graded:
            grade_str = g["grade"].replace("Grade ", "")
            try:
                graded_map[int(grade_str)] = g["market_price"]
            except ValueError:
                pass

    # Calculate expected value across grade distribution
    mults = _GRADE_MULT_MODERN if era in _MODERN_ERAS else _GRADE_MULT_VINTAGE
    ev = 0.0
    dist_total = sum(grade_dist.values())
    for grade, prob in grade_dist.items():
        if grade in graded_map:
            ev += prob * graded_map[grade]
        else:
            ev += prob * raw_price * mults.get(grade, 0.8)

    # Remainder probability (grades below 6) — assume raw price value
    remainder = 1.0 - dist_total
    if remainder > 0:
        ev += remainder * raw_price

    return ev


def calculate_graded_ev(set_id, grading_fee=20.0):
    """
    Calculate graded EV of a booster pack — expected value if you grade
    every hit-slot card pulled.

    Only grades hit-slot cards (rares, ultras, etc). Commons/uncommons
    use raw prices since grading them isn't worthwhile.

    Returns dict with graded_ev_per_pack and breakdown, or None if no data.
    """
    pull_rates = get_set_pull_rates(set_id)

    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.id, c.name, c.number, c.rarity, c.supertype,
                   p.tcg_market, p.tcg_reverse_holo, p.cm_avg, p.cm_trend
            FROM cards c
            LEFT JOIN prices p ON c.id = p.card_id
            WHERE c.set_id = ?
        """, (set_id,)).fetchall()

        set_info = conn.execute(
            "SELECT name, era FROM sets WHERE id = ?", (set_id,)
        ).fetchone()

        # Batch-load all graded prices for cards in this set
        gp_rows = conn.execute("""
            SELECT gp.card_id, gp.grade, gp.market_price
            FROM graded_prices gp
            JOIN cards c ON gp.card_id = c.id
            WHERE c.set_id = ? AND gp.market_price > 0
        """, (set_id,)).fetchall()

    if not set_info:
        return None

    era = set_info["era"] or "sv"
    cards = [dict(r) for r in rows]

    # Build graded prices map: {card_id: {int_grade: price}}
    graded_prices_map = {}
    for g in gp_rows:
        grade_str = g["grade"].replace("Grade ", "")
        try:
            grade_int = int(grade_str)
        except ValueError:
            continue
        graded_prices_map.setdefault(g["card_id"], {})[grade_int] = g["market_price"]

    by_rarity = {}
    for card in cards:
        r = card.get("rarity") or "Unknown"
        by_rarity.setdefault(r, []).append(card)

    # Base value from guaranteed + reverse holo slots (same as raw EV)
    base_value = 0.0
    for rate in pull_rates:
        slot_type = rate["slot_type"]
        guaranteed = rate["guaranteed_count"]
        rarity = rate["rarity"]

        if slot_type == "reverse_holo":
            reverse_cards = []
            for r in REVERSE_HOLO_POOL:
                reverse_cards.extend(by_rarity.get(r, []))
            n_rev = len(reverse_cards)
            if n_rev == 0:
                continue
            for card in reverse_cards:
                base_value += (guaranteed / n_rev) * _get_reverse_holo_price(card)
        elif slot_type == "guaranteed":
            rarity_cards = by_rarity.get(rarity, [])
            n_cards = len(rarity_cards)
            if n_cards == 0:
                continue
            for card in rarity_cards:
                base_value += (guaranteed / n_cards) * _get_price(card)

    # Graded EV from hit slot cards
    graded_ev_total = 0.0
    raw_ev_total = 0.0
    breakdown = []

    for rate in pull_rates:
        if rate["slot_type"] != "hit_slot":
            continue
        rarity = rate["rarity"]
        prob_rarity = rate["probability_per_pack"]
        rarity_cards = by_rarity.get(rarity, [])
        n_cards = len(rarity_cards)
        if n_cards == 0:
            continue

        p_each = prob_rarity / n_cards
        rarity_graded_ev = 0.0
        rarity_raw_ev = 0.0

        for card in rarity_cards:
            raw = _get_price(card)
            graded_val = _expected_graded_value(card["id"], raw, era, graded_prices_map)
            # Net graded value: only grade if it beats raw - fee
            net_graded = max(raw, graded_val - grading_fee)
            rarity_graded_ev += p_each * net_graded
            rarity_raw_ev += p_each * raw

        graded_ev_total += rarity_graded_ev
        raw_ev_total += rarity_raw_ev

        if rarity_graded_ev > 0:
            breakdown.append({
                "rarity": rarity,
                "card_count": n_cards,
                "raw_ev": round(rarity_raw_ev, 4),
                "graded_ev": round(rarity_graded_ev, 4),
                "uplift_pct": round(
                    (rarity_graded_ev / rarity_raw_ev - 1) * 100, 1
                ) if rarity_raw_ev > 0 else 0,
            })

    breakdown.sort(key=lambda x: x["graded_ev"], reverse=True)

    graded_pack_ev = base_value + graded_ev_total
    raw_pack_ev = base_value + raw_ev_total

    return {
        "set_id": set_id,
        "set_name": set_info["name"],
        "era": era,
        "graded_ev_per_pack": round(graded_pack_ev, 2),
        "raw_ev_per_pack": round(raw_pack_ev, 2),
        "grading_fee": grading_fee,
        "uplift_pct": round(
            (graded_pack_ev / raw_pack_ev - 1) * 100, 1
        ) if raw_pack_ev > 0 else 0,
        "breakdown": breakdown,
        "grade_distribution": _GRADE_DIST.get(era, _GRADE_DIST["sv"]),
    }



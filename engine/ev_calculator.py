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
   Priced at ~50% of normal card price (approximation).
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


def _get_price(card):
    """Get the best available USD price for a card."""
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
                   p.tcg_market, p.cm_avg, p.cm_trend
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
            for r in ("Common", "Uncommon", "Rare", "Rare Holo"):
                reverse_cards.extend(by_rarity.get(r, []))
            n_rev = len(reverse_cards)
            if n_rev == 0:
                continue

            rarity_ev = 0.0
            for card in reverse_cards:
                price = _get_price(card) * 0.5  # reverse holos ~50% of normal
                p_card = guaranteed / n_rev
                rarity_ev += p_card * price

            ev_total += rarity_ev
            avg_price = sum(_get_price(c) for c in reverse_cards) / n_rev * 0.5
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
        conn.execute("""
            INSERT OR REPLACE INTO ev_cache
            (set_id, ev_per_pack, ev_breakdown, pack_price, calculated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            set_id,
            result["ev_per_pack"],
            json.dumps(result["ev_breakdown"]),
            4.49,
            result["calculated_at"],
        ))


def get_card_ev_details(set_id):
    """Get per-card EV contribution details for display."""
    pull_rates = get_set_pull_rates(set_id)

    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.id, c.name, c.number, c.rarity, c.supertype,
                   p.tcg_market, p.cm_avg, p.cm_trend
            FROM cards c
            LEFT JOIN prices p ON c.id = p.card_id
            WHERE c.set_id = ?
            ORDER BY CAST(c.number AS INTEGER)
        """, (set_id,)).fetchall()

    cards = [dict(r) for r in rows]

    # Build rarity count map
    rarity_counts = {}
    for card in cards:
        r = card.get("rarity") or "Unknown"
        rarity_counts[r] = rarity_counts.get(r, 0) + 1

    # Build rarity -> probability map from pull rates
    rarity_prob = {}
    for rate in pull_rates:
        if rate["slot_type"] == "guaranteed":
            rarity_prob[rate["rarity"]] = ("guaranteed", rate["guaranteed_count"])
        elif rate["slot_type"] == "hit_slot":
            rarity_prob[rate["rarity"]] = ("hit_slot", rate["probability_per_pack"])

    # Calculate per-card EV
    result = []
    for card in cards:
        price = _get_price(card)
        rarity = card.get("rarity") or "Unknown"
        n_of_rarity = rarity_counts.get(rarity, 1)

        prob_info = rarity_prob.get(rarity)
        if prob_info:
            mode, val = prob_info
            if mode == "guaranteed":
                p_card = val / n_of_rarity
            else:
                p_card = val / n_of_rarity
        else:
            p_card = 0.0

        ev_contribution = p_card * price

        result.append({
            "id": card["id"],
            "name": card["name"],
            "number": card["number"],
            "rarity": rarity,
            "price": round(price, 2),
            "probability": round(p_card, 6),
            "ev_contribution": round(ev_contribution, 4),
        })

    return result

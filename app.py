#!/usr/bin/env python3
"""Flask web application for Pokemon TCG EV Calculator."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify, redirect, url_for
from database.connection import get_db
from database.schema import init_db
from engine.ev_calculator import calculate_set_ev, calculate_pack_distribution
from engine.set_analysis import (get_set_completion_cost, get_rip_or_flip,
                                 get_pack_investment_data, get_chase_card_trends,
                                 get_psa_analysis, get_cross_set_rarity_stats,
                                 get_grading_roi_candidates, get_arbitrage_opportunities,
                                 get_rarity_scatter_data, get_sealed_value_breakdown,
                                 global_search)

app = Flask(__name__)


@app.route("/")
def dashboard():
    """Dashboard landing page with quick stats and highlights."""
    with get_db() as conn:
        total_sets = conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
        total_cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        cards_priced = conn.execute("SELECT COUNT(*) FROM prices WHERE tcg_market > 0").fetchone()[0]

        top_ev = conn.execute("""
            SELECT s.id, s.name, s.logo_url, e.ev_per_pack
            FROM ev_cache e
            JOIN sets s ON e.set_id = s.id
            WHERE e.ev_per_pack > 0
            ORDER BY e.ev_per_pack DESC
            LIMIT 5
        """).fetchall()

        avg_ev = conn.execute(
            "SELECT AVG(ev_per_pack) FROM ev_cache WHERE ev_per_pack > 0"
        ).fetchone()[0] or 0

    return render_template("dashboard.html",
        total_sets=total_sets,
        total_cards=total_cards,
        cards_priced=cards_priced,
        avg_ev=avg_ev,
        top_ev=top_ev,
    )


@app.route("/search")
def search():
    """Global search across cards, sets, and sealed products."""
    q = request.args.get("q", "").strip()
    results = global_search(q) if q else {"cards": [], "sets": [], "sealed": [], "intent": "cards", "query": ""}
    return render_template("search.html", results=results, q=q)


@app.route("/api/search")
def api_search():
    """Search API endpoint."""
    q = request.args.get("q", "").strip()
    return jsonify(global_search(q) if q else {"cards": [], "sets": [], "sealed": [], "intent": "cards", "query": ""})


@app.route("/sets")
def sets_list():
    """All sets grid view."""
    with get_db() as conn:
        sets = conn.execute("""
            SELECT s.id, s.name, s.series, s.release_date, s.logo_url,
                   s.total_cards, s.era, s.has_god_pack,
                   e.ev_per_pack, e.pack_price, e.calculated_at
            FROM sets s
            LEFT JOIN ev_cache e ON s.id = e.set_id
            ORDER BY s.release_date DESC
        """).fetchall()
    return render_template("index.html", sets=sets)


@app.route("/set/<set_id>")
def set_detail(set_id):
    """Detailed view of a single set with card table and EV breakdown."""
    with get_db() as conn:
        set_info = conn.execute(
            "SELECT * FROM sets WHERE id = ?", (set_id,)
        ).fetchone()
        if not set_info:
            return "Set not found", 404

        cards = conn.execute("""
            SELECT c.id, c.name, c.number, c.rarity, c.supertype,
                   c.image_url_small, c.image_url_large,
                   p.tcg_market, p.cm_avg, p.cm_trend, p.price_source
            FROM cards c
            LEFT JOIN prices p ON c.id = p.card_id
            WHERE c.set_id = ?
            ORDER BY CAST(c.number AS INTEGER)
        """, (set_id,)).fetchall()

        ev_cache = conn.execute(
            "SELECT * FROM ev_cache WHERE set_id = ?", (set_id,)
        ).fetchone()

        # Get resolved pull rates (templates + overrides)
        pull_rates = conn.execute("""
            SELECT rarity, slot_type, guaranteed_count, probability_per_pack, notes
            FROM pull_rate_overrides WHERE set_id = ?
            UNION ALL
            SELECT t.rarity, t.slot_type, t.guaranteed_count, t.probability_per_pack, t.notes
            FROM pull_rate_templates t
            JOIN sets s ON s.era = t.era AND s.id = ?
            WHERE (t.rarity, t.slot_type) NOT IN (
                SELECT rarity, slot_type FROM pull_rate_overrides WHERE set_id = ?
            )
        """, (set_id, set_id, set_id)).fetchall()

        god_packs = conn.execute(
            "SELECT * FROM god_packs WHERE set_id = ?", (set_id,)
        ).fetchall()

    ev_breakdown = json.loads(ev_cache["ev_breakdown"]) if ev_cache and ev_cache["ev_breakdown"] else []

    # Calculate pack value distribution
    distribution = calculate_pack_distribution(set_id)

    # Set completion cost
    completion = get_set_completion_cost(set_id)

    # Rip-or-flip analysis
    rip_or_flip = get_rip_or_flip(set_id)

    # Price vs rarity scatter data
    scatter_data = get_rarity_scatter_data(set_id)

    return render_template("set_detail.html",
        set_info=set_info,
        cards=cards,
        ev_cache=ev_cache,
        ev_breakdown=ev_breakdown,
        pull_rates=pull_rates,
        god_packs=god_packs,
        distribution=distribution,
        completion=completion,
        rip_or_flip=rip_or_flip,
        scatter_data=scatter_data,
    )


@app.route("/api/recalculate/<set_id>", methods=["POST"])
def recalculate(set_id):
    """Trigger EV recalculation for a set."""
    result = calculate_set_ev(set_id)
    return jsonify(result)


@app.route("/completion")
def completion():
    """Set completion cost comparison page."""
    with get_db() as conn:
        sets = conn.execute("""
            SELECT s.id, s.name, s.era, s.release_date, s.total_cards
            FROM sets s
            ORDER BY s.release_date DESC
        """).fetchall()

    results = []
    for s in sets:
        cost = get_set_completion_cost(s["id"])
        if cost and cost["cards_priced"] > 0:
            cost["era"] = s["era"]
            cost["release_date"] = s["release_date"]
            results.append(cost)

    return render_template("completion.html", sets=results)


@app.route("/rip-or-flip")
def rip_or_flip_page():
    """Cross-set rip-or-flip rankings."""
    with get_db() as conn:
        sets = conn.execute("""
            SELECT DISTINCT s.id, s.name, s.era
            FROM sets s
            JOIN sealed_products sp ON s.id = sp.set_id
            ORDER BY s.release_date DESC
        """).fetchall()

    all_products = []
    for s in sets:
        result = get_rip_or_flip(s["id"])
        if result:
            for p in result["products"]:
                if p["ev_contents"] > 0:
                    p["set_name"] = result["set_name"]
                    p["set_id"] = result["set_id"]
                    p["era"] = s["era"]
                    all_products.append(p)

    all_products.sort(key=lambda x: x["margin"], reverse=True)
    return render_template("rip_or_flip.html", products=all_products)


@app.route("/distributions")
def distributions():
    """Multi-set pack value distribution comparison."""
    with get_db() as conn:
        sets = conn.execute("""
            SELECT s.id, s.name
            FROM sets s
            JOIN ev_cache e ON s.id = e.set_id
            WHERE e.ev_per_pack > 0
            ORDER BY s.release_date DESC
        """).fetchall()
    return render_template("distributions.html", sets=sets)


@app.route("/api/set/<set_id>/distribution")
def api_set_distribution(set_id):
    """Pack value distribution data."""
    result = calculate_pack_distribution(set_id)
    if not result or not result.get("outcomes"):
        return jsonify({"error": "No distribution data available"}), 404
    return jsonify(result)


@app.route("/api/set/<set_id>/rip-or-flip")
def api_rip_or_flip(set_id):
    """Rip-or-flip analysis for sealed products in a set."""
    result = get_rip_or_flip(set_id)
    if result is None:
        return jsonify({"error": "Set not found"}), 404
    return jsonify(result)


@app.route("/api/set/<set_id>/completion")
def api_set_completion(set_id):
    """Set completion cost data."""
    result = get_set_completion_cost(set_id)
    if result is None:
        return jsonify({"error": "Set not found"}), 404
    return jsonify(result)


@app.route("/investment/packs")
def pack_investment():
    """Sealed pack investment ROI tracker."""
    data = get_pack_investment_data()
    return render_template("pack_investment.html", packs=data)


@app.route("/investment/chase-cards")
def chase_cards():
    """Chase card appreciation tracker."""
    data = get_chase_card_trends()
    prices = sorted(s["top_1_price"] for s in data if s["top_1_price"] > 0)
    median = prices[len(prices) // 2] if prices else 0
    return render_template("chase_cards.html", sets=data, median_top1=median)


@app.route("/api/investment/packs")
def api_pack_investment():
    """Pack investment ROI data."""
    era = request.args.get("era")
    min_year = request.args.get("min_year", type=int)
    data = get_pack_investment_data(era_filter=era, min_year=min_year)
    return jsonify(data)


@app.route("/api/investment/chase-cards")
def api_chase_cards():
    """Chase card trend data."""
    data = get_chase_card_trends()
    return jsonify(data)


@app.route("/psa")
def psa_pop():
    """PSA pop report pricing tool."""
    set_id = request.args.get("set")
    sort_by = request.args.get("sort", "pop_score")
    grade = request.args.get("grade", "10")

    data = get_psa_analysis(set_id=set_id, sort_by=sort_by, grade=grade)

    # Get list of sets that have pop data for the filter dropdown
    with get_db() as conn:
        sets_with_pop = conn.execute("""
            SELECT DISTINCT s.id, s.name
            FROM psa_pop pop
            JOIN cards c ON pop.card_id = c.id
            JOIN sets s ON c.set_id = s.id
            ORDER BY s.name
        """).fetchall()

    return render_template("psa.html", cards=data, sets_with_pop=sets_with_pop,
                           current_set=set_id, current_sort=sort_by, current_grade=grade)


@app.route("/api/psa/cards")
def api_psa_cards():
    """PSA pop + price data."""
    set_id = request.args.get("set_id")
    sort_by = request.args.get("sort", "pop_score")
    grade = request.args.get("grade", "10")
    min_price = request.args.get("min_price", 0, type=float)
    data = get_psa_analysis(set_id=set_id, sort_by=sort_by, grade=grade,
                            min_price=min_price)
    return jsonify(data)


@app.route("/sealed-value")
def sealed_value():
    """Sealed product value breakdown — packs + promos vs sealed price."""
    set_id = request.args.get("set")
    ptype = request.args.get("type")
    data = get_sealed_value_breakdown(set_id=set_id)
    if ptype:
        type_map = {
            "box": "booster_box", "etb": "etb", "upc": "collection",
        }
        target = type_map.get(ptype, ptype)
        if ptype == "upc":
            data = [d for d in data if "ultra-premium" in d["product_name"].lower()
                    or "ultra premium" in d["product_name"].lower()]
        else:
            data = [d for d in data if d["product_type"] == target]
    # Get sets that have products
    all_data = get_sealed_value_breakdown() if set_id else data
    set_ids = sorted(set(d["set_id"] for d in all_data))
    with get_db() as conn:
        sets_list = conn.execute(
            f"SELECT id, name FROM sets WHERE id IN ({','.join('?' * len(set_ids))})"
            " ORDER BY release_date DESC", set_ids
        ).fetchall() if set_ids else []
    return render_template("sealed_value.html", products=data, sets=sets_list,
                           current_set=set_id, current_type=ptype)


@app.route("/api/sealed-value")
def api_sealed_value():
    """Sealed product value breakdown data."""
    set_id = request.args.get("set_id")
    return jsonify(get_sealed_value_breakdown(set_id=set_id))


@app.route("/compare")
def compare():
    """Cross-set rarity price comparison."""
    rarity = request.args.get("rarity", "Special Illustration Rare")
    era = request.args.get("era")
    data = get_cross_set_rarity_stats(rarity_filter=rarity, era_filter=era)
    with get_db() as conn:
        rarities = conn.execute("""
            SELECT DISTINCT c.rarity, COUNT(*) as cnt
            FROM cards c JOIN prices p ON c.id = p.card_id
            WHERE c.rarity IS NOT NULL AND p.tcg_market > 0
              AND c.rarity NOT IN ('Common', 'Uncommon')
            GROUP BY c.rarity ORDER BY cnt DESC
        """).fetchall()
    return render_template("compare.html", data=data, rarities=rarities,
                           current_rarity=rarity, current_era=era)


@app.route("/grading")
def grading():
    """Grading ROI calculator."""
    set_id = request.args.get("set")
    fee = request.args.get("fee", 20.0, type=float)
    data = get_grading_roi_candidates(set_id=set_id, grading_fee=fee)
    with get_db() as conn:
        sets_with_graded = conn.execute("""
            SELECT DISTINCT s.id, s.name
            FROM graded_prices gp JOIN cards c ON gp.card_id = c.id
            JOIN sets s ON c.set_id = s.id ORDER BY s.name
        """).fetchall()
    return render_template("grading.html", cards=data, sets=sets_with_graded,
                           current_set=set_id, current_fee=fee)


@app.route("/arbitrage")
def arbitrage():
    """Arbitrage finder — TCGPlayer vs PriceCharting price gaps."""
    set_id = request.args.get("set")
    min_spread = request.args.get("min_spread", 2.0, type=float)
    data = get_arbitrage_opportunities(set_id=set_id, min_spread=min_spread)
    with get_db() as conn:
        sets_with_arb = conn.execute("""
            SELECT DISTINCT s.id, s.name
            FROM graded_prices gp JOIN cards c ON gp.card_id = c.id
            JOIN sets s ON c.set_id = s.id WHERE gp.grade = 'Ungraded'
            ORDER BY s.name
        """).fetchall()
    return render_template("arbitrage.html", cards=data, sets=sets_with_arb,
                           current_set=set_id, current_min_spread=min_spread)


@app.route("/api/rarity-comparison")
def api_rarity_comparison():
    """Cross-set rarity stats."""
    rarity = request.args.get("rarity")
    era = request.args.get("era")
    return jsonify(get_cross_set_rarity_stats(rarity_filter=rarity, era_filter=era))


@app.route("/api/grading-roi")
def api_grading_roi():
    """Grading ROI candidates."""
    set_id = request.args.get("set_id")
    fee = request.args.get("fee", 20.0, type=float)
    return jsonify(get_grading_roi_candidates(set_id=set_id, grading_fee=fee))


@app.route("/api/arbitrage")
def api_arbitrage():
    """Arbitrage opportunities."""
    set_id = request.args.get("set_id")
    min_spread = request.args.get("min_spread", 2.0, type=float)
    return jsonify(get_arbitrage_opportunities(set_id=set_id, min_spread=min_spread))


@app.route("/api/set/<set_id>/scatter")
def api_set_scatter(set_id):
    """Price vs rarity scatter data."""
    return jsonify(get_rarity_scatter_data(set_id))


@app.route("/about")
def about():
    """Methodology explanation page."""
    return render_template("about.html")


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5001, debug=True)

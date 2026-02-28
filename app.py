#!/usr/bin/env python3
"""Flask web application for Pokemon TCG EV Calculator."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify, redirect, url_for
from database.connection import get_db
from database.schema import init_db
from engine.ev_calculator import calculate_set_ev

app = Flask(__name__)


@app.route("/")
def index():
    """Home page: list of all sets with cached EV values."""
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

    return render_template("set_detail.html",
        set_info=set_info,
        cards=cards,
        ev_cache=ev_cache,
        ev_breakdown=ev_breakdown,
        pull_rates=pull_rates,
        god_packs=god_packs,
    )


@app.route("/api/recalculate/<set_id>", methods=["POST"])
def recalculate(set_id):
    """Trigger EV recalculation for a set."""
    result = calculate_set_ev(set_id)
    return jsonify(result)


@app.route("/about")
def about():
    """Methodology explanation page."""
    return render_template("about.html")


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)

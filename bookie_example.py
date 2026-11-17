"""Starter template for implementing a new bookie adapter against Pinnacle (PinnWire).

To add your own bookie:
1. Copy this file (e.g. `mozzart_adapter.py`) and import it in `pinnwire_dashboard.py` (or `bookie_adapter.py`).
2. Subclass `BookieAdapter`, set `name` and `label`, and decorate with `@register_adapter`.
3. Implement `offer(sport)`, `comp_id(sport, row)` (for football/basketball/hockey), and `decode_markets(sport, row, period)`.
4. Run with `python pinnwire_dashboard.py --bookie <name>` (or set `XTIP_BOOKIE=<name>` / `"bookie"` in config).
"""
from __future__ import annotations

import bookie_adapter


@bookie_adapter.register_adapter
class ExampleBookieAdapter(bookie_adapter.BookieAdapter):
    """Minimal skeleton showing the exact shapes expected by the dashboard."""

    name = "example"
    label = "ExampleBookie"

    # Map your bookie's league IDs/codes to PinnWire `league_id`s for tracked-league sports.
    # (Tennis, MMA, and Handball/Volleyball pair across all leagues without a competition map.)
    COMP_MAP = {
        "football": {
            # "ENG_PL": 1980,
        },
        "basketball": {
            # "NBA": 487,
        },
        "hockey": {
            # "NHL": 1456,
        },
    }

    def offer(self, sport):
        """Fetch and normalize the prematch offer for `sport` into a list of dicts.

        Required keys per row:
          - id: unique match id at your bookie
          - home, away: team/player names (str)
          - kickOffTime: UTC kickoff timestamp in milliseconds (int)
          - live: bool
        Optional keys:
          - leagueId / leagueShort: competition identifier passed to `comp_id()`
          - matchCode: display code (football)
          - sport: "HB" (handball) or "V" (volleyball) for the combined `handball` board
        """
        return []

    def comp_id(self, sport, row):
        mapping = self.COMP_MAP.get(sport) or {}
        return mapping.get(row.get("leagueId")) or mapping.get(row.get("leagueShort"))

    def decode_markets(self, sport, row, period=None):
        """Decode one offer row into the normalized market dict for `sport`."""
        markets = bookie_adapter.empty_markets(sport)
        if sport == "football":
            # Full-match (0) and 1st half (1):
            # markets[0]["ml"] = {"home": 2.40, "draw": 3.30, "away": 2.95}
            # markets[0]["totals"] = {2.5: {"over": 1.90, "under": 1.95}}
            # markets[0]["spreads"] = {-0.5: {"home": 2.40, "away": 1.60}}
            # markets[0]["teamTotals"] = {"home": {1.5: {"over": 2.1, "under": 1.7}}, "away": {...}}
            return markets if period is None else markets[period]

        # Basketball / Tennis / Hockey / MMA / Handball:
        # `period` is "ft", "ht", "q1", "s1", "p1".."p3", or "h1" depending on the sport.
        # Example:
        # markets["ml"] = {"home": 1.85, "away": 1.95}
        # markets["totals"] = {215.5: {"over": 1.90, "under": 1.90}}
        # markets["spreads"] = {-3.5: {"home": 1.90, "away": 1.90}}
        return markets


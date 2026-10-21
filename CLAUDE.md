# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Pinnacle Board": a local dashboard comparing Pinnacle prematch odds (via the PinnWire API) with the public MerkurXtip offer for top-5 leagues + UEFA club competitions. `README.md` documents the user-facing behaviour in detail (comparison rules, line filtering, derived handicaps, PWA, request budget) — read it before changing comparison logic.

## Commands

```powershell
python -m pip install -r requirements.txt        # only dependency: requests
cd frontend; npm install; npm run build; cd ..   # builds into ../static/dashboard_build
python pinnwire_dashboard.py                     # serves http://127.0.0.1:8070 (--port, --no-browser, --host)
python -m unittest test_pinnwire_dashboard       # all tests
python -m unittest test_pinnwire_dashboard.ClassName.test_name   # single test
```

`start.bat` / `start.sh` install deps, build and run. Frontend dev: run the Python server, then `npm run dev` in `frontend/` (Vite on 5175, proxies `/api` to 8070). No linter is configured.

## Architecture

- `pinnwire_dashboard.py` — stdlib `http.server` app. `DashboardState` holds the event cache, delta merging (`since=` requests, full snapshot hourly), and `History` (opening/previous 1X2 prices persisted to `data/dashboard_history.json`). `Handler` serves `/api/board`, `/api/match/<id>` and the static bundle. `COMPETITIONS` (keyed by PinnWire `league_id`, with a `merkur` `leagueShort`) defines tracked leagues. The `compare_*` / `value_items` / `best_edge` / `goals_line` functions build the Pinnacle-vs-MerkurXtip comparison served to the UI.
- `pinnwire_client.py` — PinnWire REST client, devig (Shin for two-way markets, power for 1X2) and market parsing. `allowed_line()` is the single rule for which handicap/total lines are used (half-goal lines only, plus AH 0 ↔ draw-no-bet).
- `merkur_client.py` — MerkurXtip offer client (~7 MB list cached 60 s), odds-code decoding, derived handicap construction (docstring documents the verified code mappings), and event pairing (competition + kickoff within 3 h + fuzzy team names; add misses to `ALIASES`).
- `basketball.py` — basketball board (PinnWire sport 3 vs the MerkurXtip `sport/B` offer): code tables, Pinnacle/Merkur decoding, comparison and `BasketballState`; served at `/api/basketball/board`. Competitions are keyed by PinnWire `league_id` with the MerkurXtip numeric `leagueId`.
- `frontend/dashboard/` — React 19 + Vite SPA; nearly all UI is in `App.jsx`. PWA files (manifest, `sw.js`, icons) live in `frontend/dashboard/public/`; bump `VERSION` in `sw.js` when caching rules change.
- `static/dashboard_build/` — **committed** production bundle served by Python. After frontend changes, run `npm run build` so the bundle stays in sync.
- `data/` — runtime state and the API key (`pinnwire_config.json`, never share; `PINNWIRE_API_KEY` env overrides).

## Constraints

- The PinnWire trial plan is 20 req/min and 100/day; avoid code that adds API calls (Osveži uses delta requests deliberately).
- UI strings are in Serbian (e.g. Osveži, Više/Manje, Max kvota).

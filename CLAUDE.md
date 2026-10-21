# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Pinnacle Board": a local dashboard comparing Pinnacle prematch odds (via the PinnWire API) with the public MerkurXtip offer, for football (top leagues, UEFA, a few second divisions) basketball (NBA, European and national leagues) and tennis (ATP, WTA, Challenger, ITF). `README.md` documents the user-facing behaviour in detail (comparison rules, line filtering, derived handicaps, PWA, request budget, basketball, tennis) — read it before changing comparison logic.

## Commands

```powershell
python -m pip install -r requirements.txt        # only dependency: requests
cd frontend; npm install; npm run build; cd ..   # builds into ../static/dashboard_build
python pinnwire_dashboard.py                     # serves http://127.0.0.1:8070 (--port, --no-browser, --host)
python -m unittest test_pinnwire_dashboard       # all tests
python -m unittest test_pinnwire_dashboard.ClassName.test_name   # single test
```

`start.bat` / `start.sh` install deps, build and run. Frontend dev: run the Python server, then `npm run dev` in `frontend/` (Vite on 5175, proxies `/api` to 8070). No linter is configured. The Python server does not reload: restart it after backend changes. Deep links for checking UI: `/?sport=basketball|tennis`, `&view=value|missing|compare`, `#<event id>`.

## Architecture

One Python process serves both sports; each sport has its own PinnWire snapshot cache, MerkurXtip offer cache and comparison code.

- `pinnwire_dashboard.py` — stdlib `http.server` app, **football**. `DashboardState` holds the event cache, delta merging (`since=` requests, full snapshot hourly), and `History` (opening/previous 1X2 prices and the daily request counter, persisted to `data/dashboard_history.json`, shared with basketball). `Handler` serves `/api/board`, `/api/match/<id>`, `/api/basketball/board`, `/api/basketball/match/<id>`, `/api/tennis/board`, `/api/tennis/match/<id>` and the static bundle. `COMPETITIONS` (keyed by PinnWire `league_id`, with a `merkur` `leagueShort`) defines tracked leagues. To add a league, find its PinnWire `league_id` in a snapshot and the MerkurXtip `leagueShort` in the offer (names differ, e.g. PinnWire "Liga Pro" is MerkurXtip "Liga Profesional"), add the entry and a `.comp-badge.<key>` colour in `dashboard.css`. The `compare_*` / `value_items` / `best_edge` / `goals_line` functions build the comparison served to the UI.
- `basketball.py` — **basketball**, independent of the football code (it must not import `pinnwire_dashboard`: run as a script that module is `__main__`, so importing it would create a second state). `BasketballState`, the MerkurXtip code tables (`MX_PERIOD`), `compare()` per period (full game, 1st half; 1st quarter is decoded but PinnWire only quotes it close to the start), lines outside Pinnacle's ladder priced from a normal model (`model_probability`, flagged `modeled`), and the "Merkur kasni" check (`stale_gaps`: MerkurXtip main line ≥ 2 points from Pinnacle's). `COMPETITIONS` maps PinnWire `league_id` to the MerkurXtip numeric `leagueId` (`leagueShort` is not unique in basketball).
- `tennis.py` — **tennis**, `TennisState` subclasses `BasketballState` (overriding its hook methods: `incoming`, `merge`, `complete`, `shape`, `pair`, `hints`, `offered`, `competitions`; it imports `basketball` for `compare_row`, `board_cell` and event helpers). The Merkur feed is the same with letter `T`. PinnWire quotes tennis as a main event in sets plus a `parent_id` side event in games (`include_alt_units=1`), folded into one event under `games`. Competitions are tournaments derived from league names (league_id changes every round), pairing is by player names (`player_score`: surname plus initial) and a 12 h kickoff window with no competition check. Exact lines only, no model.
- `pinnwire_client.py` — PinnWire REST client, devig and market parsing. `devig()` uses Shin for two-way markets and the power method for 1X2 (power overshoots on lopsided two-way prices). `allowed_line()` is the rule for which handicap/total lines are used (half-point lines only; football additionally keeps AH 0 ↔ draw-no-bet); basketball applies it to both books. `best_per_line_market()` is the Value-list rule shared by both sports: one outcome per match, period and line market (the largest edge), markets without a line keep every outcome.
- `merkur_client.py` — MerkurXtip offer client (`MerkurAPI(offer_path=...)`, football list ~7 MB cached 60 s), odds-code decoding for football (docstring documents the verified code mappings), and event pairing (competition + kickoff within 3 h + fuzzy team names; add misses to `ALIASES`). `closest_unpaired()` feeds the "Nedostaju" hints. `is_prematch()` matters: MerkurXtip flags matches `live` hours before kickoff, so only started matches may be dropped, never every `live` row.
- `frontend/dashboard/` — React 19 + Vite SPA; nearly all UI is in `App.jsx`: the football screen lives in `App`, basketball and tennis in `BasketballPane` (texts and market groups per sport in `SPORT_VIEWS`, boards loaded by `useSportBoard`), all share `SideMenu` (sport icons with match counts, competitions grouped by country), `ValueTable`, `MissingTable` and the odds modal pattern. Views: compare, pinnacle (football only), value, missing ("Nedostaju"). All boards are loaded at startup so the sport icons can show counts. PWA files (manifest, `sw.js`, icons) live in `frontend/dashboard/public/`; bump `VERSION` in `sw.js` when caching rules change.
- `static/dashboard_build/` — **committed** production bundle served by Python. After frontend changes, run `npm run build` so the bundle stays in sync.
- `data/` — runtime state and the API key (`pinnwire_config.json`, never share; `PINNWIRE_API_KEY` env overrides).

## Constraints

- "Max bet" is the Pinnacle limit (`max` of a spread/total line in PinnWire). The odds modals show it per market as `maxBet` on compare rows (`pinnacle_max` for football, `pinnacle_limits` in `basketball.py`/`tennis.py`); the 1X2 / moneyline carries no limit, and modelled lines have none. The board shows the main line's limit in green.
- The sport menu has only football, basketball and tennis; hockey and volleyball were removed on purpose.
- The PinnWire trial plan is 20 req/min and 100/day; avoid code that adds API calls (Osveži uses delta requests deliberately; each sport costs one request per refresh, three sports three, and the odds modals use only MerkurXtip single-match requests).
- UI strings are in Serbian (e.g. Osveži, Više/Manje, Max kvota, Nedostaju).
- MerkurXtip code tables come from `https://www.merkurxtip.rs/restapi/offer/sr/ttg_lang` (`betPickMap` keys `<code>_<sport suffix>`, basketball `_B`/`_BB`, tennis `_T`); verify a code against live data (EV should centre on about −MerkurXtip margin) before relying on it.

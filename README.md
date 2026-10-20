# Pinnacle Board

A local dashboard of Pinnacle prematch prices from [PinnWire](https://pinnwire.com/docs.html), compared with MerkurXtip odds, for the top 5 leagues and the UEFA club competitions: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League and Conference League.

## Run

Requirements: Python 3.9+, Node.js 20+, npm.

```powershell
python -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
python pinnwire_dashboard.py     # http://127.0.0.1:8070
```

Or run `start.bat` (Windows) / `./start.sh`. Both install missing dependencies, build the app and start the server.

Enter a PinnWire API key in the app. It is saved to `data/pinnwire_config.json`; `PINNWIRE_API_KEY` overrides it. The key is sent only from the local server to pinnwire.com. Free trial keys are at https://pinnwire.com/#trial.

Stop with `Ctrl+C`. Options: `--port 9000`, `--no-browser`.

## What it shows

- **Board:** one row per match with Pinnacle 1X2 and fair (no-vig) odds, margin, the main Asian handicap and goal line, and the move since opening. Prices that changed since the previous refresh are green (up) or red (down). There are tabs per competition, day filters and search.
- **Detail panel:** click a match to see full match and 1st half: a probability bar, 1X2 with the opening price, all handicap and total lines (GL = main line), and team totals. `#<event id>` in the URL opens a match directly.
- Fair odds remove the margin with the power method.

## MerkurXtip comparison

The **MerkurXtip vs Pinnacle** view (default) compares the public MerkurXtip prematch offer with Pinnacle fair odds. No key is needed.

- **Difference** = MerkurXtip odds / Pinnacle fair odds − 1. Red (≥ 0%) means the MerkurXtip price is at or above the fair price. Amber means 0 to −2%.
- **Board:** one row per match: kickoff, Pinnacle limit of the main line (handicap, else total), teams and league. Then **Max kvota**: Pinnacle fair odds of the favourite × (1 + tolerance; set in the toolbar, default 1%). Then 1X2 as Pinnacle no-vig, Pinnacle, and MerkurXtip. After that comes the same layout for goals (over/under). It shows the line both books price that is closest to Pinnacle's main line, because MerkurXtip only sells half-goal lines (ties go to the line whose Pinnacle prices are nearest to even). Unpaired matches show Pinnacle's main line. MerkurXtip cells are red when at or above the fair price and amber when above the Pinnacle price. They are outlined purple when the MerkurXtip price changed on the last refresh. Pinnacle cells are green when the price rose and blue when it fell on the last refresh. Filter by largest difference across all comparable markets, or show matches MerkurXtip does not offer.
- **Value view:** every outcome, across all comparable markets and both periods, where the MerkurXtip price beats Pinnacle. It covers all competitions together, and the competition tabs are replaced by a per-league summary: count and largest difference. Click a league to narrow the list. It is sorted by the difference to the fair price and defaults to MX ≥ fair; other thresholds are MX > Pinnacle and MX ≥ fair +2%. There is also a market-type filter, and the day and search filters apply. Open it directly with `/?view=value`.
- **Detail panel:** every comparable market for full match and 1st half: 1X2, goal totals, two-way handicap, and home/away team goals (1st half: 0.5 via MerkurXtip "D I 1+ / D I 0" and "G I 1+ / G I 0", codes 307/337 and 308/338). Opening a match fetches fresh odds for that match from MerkurXtip.
- **Pairing:** same competition, kickoff within 3 hours, and team-name similarity (prefixes, initials such as PSG, small typos). Add names the rules miss to `ALIASES` in `merkur_client.py`. A ⏱ badge marks matches whose MerkurXtip kickoff differs from Pinnacle.
- **Sources:** offer list `GET /restapi/custom/offer/sr/sport/S/mob?annex=0` (~7 MB, cached 60 s and refetched on **Osveži**). Single match `GET /restapi/offer/sr/match/<id>`. Odds codes are defined in `/restapi/offer/sr/ttg_lang` (`betPickMap`). Goal totals are sold as ranges: `0-2` = under 2.5, `3+` = over 2.5.
- **Lines:** handicaps and totals (including team totals) use only half-goal lines (x.5), everywhere: board, detail, comparison and value. Quarter (x.25/x.75) and whole lines are dropped, because MerkurXtip does not sell them. The exception is the level handicap **AH 0**, which is compared with MerkurXtip **X vraća ulog** (draw no bet, codes 264/265) and shown as "0 · X vraća ulog". Pinnacle's main line is chosen among the allowed lines (prices closest to even). The rule is `allowed_line()` in `pinnwire_client.py`.
- MerkurXtip competitions are mapped by `leagueShort` (`merkur` in `COMPETITIONS`).

## Install as an app (PWA)

The dashboard is a Progressive Web App. In Chrome or Edge, open http://127.0.0.1:8070 and click **⤓ Instaliraj** in the top bar, or use the install icon in the address bar. It then runs in its own window, with a Start-menu or desktop icon. Right-clicking the icon gives the shortcuts **Value** and **MerkurXtip vs Pinnacle**.

- The Python server must still be running; the PWA is a window onto it. `start.bat` can be added to Windows startup.
- **Offline / server down:** the app still opens from the service worker cache and shows the last odds it loaded, with a banner saying they are not live. Refresh works again once the server is back.
- **Caching:** the app shell and hashed `/assets/*` are cached. API calls go network-first, and the last good response is kept per path. `index.html`, `sw.js` and the manifest are served `no-cache`, so a new `npm run build` is picked up on the next visit.
- **Phones:** browsers only allow service workers on `https://` or `localhost`. Opening `http://<pc-ip>:8070` from a phone (server started with `--host 0.0.0.0`) works as a web page but cannot be installed. Installing on a phone needs HTTPS in front of the server, for example Tailscale Serve or a reverse proxy with a certificate.
- Files: `frontend/dashboard/public/` (`manifest.webmanifest`, `sw.js`, `icons/`). Bump `VERSION` in `sw.js` to drop old caches when the caching rules change.

## Request budget

PinnWire has no league filter, so one request returns all soccer fixtures. The first load takes that full snapshot. **Osveži** sends `since=<last>` and merges only events that changed since the previous response. A full snapshot is taken at least hourly, or on demand with **Pun reload**. **Osveži meč** in the detail panel requests only that event.

The trial plan allows 20 requests per minute and 100 per day. Auto-refresh is off by default; 15 minutes or slower fits the trial. The top bar shows today's request count.

Opening and previous 1X2 prices are stored in `data/dashboard_history.json`, so they survive restarts. "Opening" is the first price the dashboard saw, not Pinnacle's opening line.

## Project layout

| File | Purpose |
|---|---|
| `pinnwire_dashboard.py` | Local server on port 8070: competition filter, delta merge, price history, `/api/board`, `/api/match/<id>`, static files |
| `merkur_client.py` | MerkurXtip offer client, odds-code decoding and event pairing |
| `pinnwire_client.py` | PinnWire REST client (`x-api-key`, 429/Retry-After handling), devig and market parsing |
| `frontend/` | React + Vite app (source in `frontend/dashboard/`; PWA manifest, service worker and icons in `frontend/dashboard/public/`) |
| `static/dashboard_build/` | Production bundle served by Python |
| `test_pinnwire_dashboard.py` | Unit tests: `python -m unittest test_pinnwire_dashboard` |
| `data/` | API key and price history; do not share `pinnwire_config.json` |

Competitions are the `COMPETITIONS` list in `pinnwire_dashboard.py`, keyed by PinnWire `league_id`. Add an entry to track another league.

During frontend development, run the Python server in one terminal and `npm run dev` in `frontend/` in another. Vite runs on port 5175 and proxies `/api` to 8070.

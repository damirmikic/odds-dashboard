# Xtip Monitor

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

## Server (subdomain on Linux)

The app has no login of its own, so on a server it listens only on `127.0.0.1:8070` and a reverse proxy in front adds HTTPS and a password. Files are in `deploy/`; Python 3.10+, git and Caddy (or nginx) are needed on the server, Node is not (the bundle is committed).

1. DNS: an `A` record for the subdomain (`oddsmonitor.merkurxtip.app`) pointing to the server.
2. Check the server can reach MerkurXtip (it may block foreign IPs): `curl -sI https://www.merkurxtip.rs/restapi/offer/sr/ttg_lang`.
3. As root: `git clone <repo> /opt/xtip && sh /opt/xtip/deploy/install.sh`. It creates the `xtip` user, a venv, `/etc/xtip.env` and the `xtip` systemd service. Put the key in `/etc/xtip.env` (`PINNWIRE_API_KEY=...`) and `systemctl restart xtip`. To keep the history, copy `data/*.sqlite3` and `data/dashboard_history.json` to `/opt/xtip/data/` (owner `xtip`) before the first start.
4. Proxy: copy `deploy/Caddyfile` into `/etc/caddy/Caddyfile` with your subdomain and a hash from `caddy hash-password`, then `systemctl reload caddy`. With nginx use `deploy/nginx.conf`, `htpasswd` and `certbot --nginx`.
5. Updates: commit and push (with the rebuilt bundle), then on the server `sh /opt/xtip/deploy/update.sh`. Logs: `journalctl -u xtip -f`.

The service runs with `--no-browser`, so the CLV worker and the drop stream keep recording without a browser open. The PWA installs from the subdomain (HTTPS); the manifest is requested with credentials so the password does not block it.

## What it shows

- **Board:** one row per match with Pinnacle 1X2 and fair (no-vig) odds, margin, the main Asian handicap and goal line, and the move since opening. Prices that changed since the previous refresh are green (up) or red (down). A side menu lists the competitions grouped by country; there are also day filters and search.
- **Detail panel:** click a match to see full match and 1st half: a probability bar, 1X2 with the opening price, all handicap and total lines (GL = main line), and team totals. `#<event id>` in the URL opens a match directly.
- Fair odds remove the margin with the power method for three-way markets (1X2) and with Shin's method for two-way ones (handicaps, totals, winner in basketball). Power overshoots on lopsided two-way prices.

## MerkurXtip comparison

The **MerkurXtip vs Pinnacle** view (default) compares the public MerkurXtip prematch offer with Pinnacle fair odds. No key is needed.

- **Difference** = MerkurXtip odds / Pinnacle fair odds − 1. Red (≥ 0%) means the MerkurXtip price is at or above the fair price. Amber means 0 to −2%.
- **Board:** one row per match: kickoff, Pinnacle limit of the main line (handicap, else total), teams and league. Then 1X2 as Pinnacle no-vig, Pinnacle, and MerkurXtip. After that comes the same layout for goals (over/under). It shows the line both books price that is closest to Pinnacle's main line, because MerkurXtip only sells half-goal lines (ties go to the line whose Pinnacle prices are nearest to even). Unpaired matches show Pinnacle's main line. MerkurXtip cells are red when at or above the fair price and amber when above the Pinnacle price. They are outlined purple when the MerkurXtip price changed on the last refresh. Pinnacle cells are green when the price rose and blue when it fell on the last refresh. Filter by largest difference across all comparable markets, or show matches MerkurXtip does not offer.
- **Value view:** every outcome, across all comparable markets and both periods, where the MerkurXtip price beats Pinnacle. It covers all competitions together, and the side menu shows a per-league summary instead: count and largest difference. Click a league to narrow the list. It is sorted by the difference to the fair price and defaults to MX ≥ fair; other thresholds are MX > Pinnacle and MX ≥ fair +2%. There is also a market-type filter, and the day and search filters apply. Open it directly with `/?view=value`.
- **Value, svi sportovi:** the **Value** button in the side menu (next to Alerti, its badge counts MX ≥ fair outcomes) opens one list of the value outcomes of all five sports, sorted by the difference to the fair price. The side menu groups the leagues by sport; the buttons above the table narrow to one sport. Filters: level, market type (winner / 1X2, handicap, total, team or player totals), difference range, top leagues only, modelled basketball lines, day and search. Clicking a row opens that sport's odds modal. Auto refresh on this screen reloads every sport. Open it directly with `/?sport=value`.
- **Detail panel:** every comparable market for full match and 1st half: 1X2, goal totals, two-way handicap, and home/away team goals. Opening a match fetches fresh odds for that match from MerkurXtip.
- **Pairing:** same competition, kickoff within 3 hours, and team-name similarity (prefixes, initials such as PSG, small typos). Add names the rules miss to `ALIASES` in `merkur_client.py`. A ⏱ badge marks matches whose MerkurXtip kickoff differs from Pinnacle.
- **Sources:** offer list `GET /restapi/custom/offer/sr/sport/S/mob?annex=0` (~7 MB, cached 60 s and refetched on **Osveži**). Single match `GET /restapi/offer/sr/match/<id>`. Odds codes are defined in `/restapi/offer/sr/ttg_lang` (`betPickMap`). Goal totals are sold as ranges: `0-2` = under 2.5, `3+` = over 2.5.
- **Lines:** handicaps and totals (including team totals) use only half-goal lines (x.5), everywhere: board, detail, comparison and value. Quarter (x.25/x.75) and whole lines are dropped, because MerkurXtip does not sell them. The exception is the level handicap **AH 0**, which is compared with MerkurXtip **X vraća ulog** (draw no bet, codes 264/265) and shown as "0 · X vraća ulog". Pinnacle's main line is chosen among the allowed lines (prices closest to even). The rule is `allowed_line()` in `pinnwire_client.py`.
- **Derived handicaps:** MerkurXtip only sells a two-way handicap on `hd2w` (usually ±1.5) and AH 0, so the other handicap lines are built from other markets (all checked against live prices; see the docstring in `merkur_client.py`):
  - **±0.5, full match and 1st half:** from 1X2 and double chance. AH −0.5 is "1" against "X2", AH +0.5 is "1X" against "2" (1st half: codes 4/399 and 397/6).
  - **European handicap** (`hd2`, `handicap2`, `handicap3`; 1st half `hdp`) with integer h: H1 is the home side of AH h − 0.5 and H2 is the away side of AH h + 0.5. This fills ±1.5, ±2.5 and −3.5.
  - Direct prices win over derived ones. A derived line is tagged **izv.** and has no MerkurXtip margin, because its two sides come from different markets. It can hold a single side, which is still compared with Pinnacle's fair price.
- **Team goals and totals:** full match team goals at 0.5–3.5 (codes 238/239, 248/247, 276/551, 555/553 and the guest equivalents), 1st half team goals at 0.5 and 1.5 (307/337, 274/817), 1st half totals at 0.5–2.5. Team goals 4.5 is only compared when MerkurXtip publishes that line in `homeOverUnder` / `awayOverUnder`.
- **Not compared:** 1st half AH 0 and AH −1.5 (MerkurXtip has no 1st half draw no bet and does not offer `hdp` / `hd2wp1` on these matches), 2nd half (Pinnacle does not price it) and everything Pinnacle does not offer (BTTS, correct score, corners, cards). About 94% of Pinnacle's lines are compared.
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

The dashboard runs on the **Pro + Drops** plan (10 requests per second, SSE drop stream). Auto-refresh defaults to 5 s (options from 3 s; the next delta request starts after the previous one finishes). On the trial plan (20 requests per minute, 100 per day) set it to 15 minutes or slower; drop alerts need a plan with drops. The top bar shows today's request count.

## Drop alerts

The server keeps one connection to PinnWire's prematch drop stream (`/odds-drop-prematch`, SSE, not counted as REST requests) with `min_drop=1` and `recheck=15`: PinnWire holds each drop 15 s and sends it only if the price has not come back. Moneyline, handicap and total drops of football, basketball, tennis, hockey, MMA, handball and volleyball are kept for 3 hours (team total drops do not say which team and are skipped). The UI polls the local `/api/drops?sport=` every 3 s and shows the drops of matches on its boards at or above the chosen threshold.

For a paired match each drop carries the MerkurXtip price of the same outcome (from the last board) and its edge `Merkur / nvp − 1`, where `nvp` is PinnWire's no-vig price after the drop. A positive edge means MerkurXtip has not followed the move yet. **Samo gde Merkur kasni** limits the list, the toasts and the sound to those. Spread drops on the away side carry the away line (away +4 is the home handicap −4); tennis games drops come on the games side event and are mapped to the main match.

Opening and previous 1X2 prices are stored in `data/dashboard_history.json`, so they survive restarts. "Opening" is the first price the dashboard saw, not Pinnacle's opening line.

## CLV (closing line value)

PinnWire has no historical data, so the dashboard builds its own. The first time an outcome shows a MerkurXtip price at least 2% above Pinnacle's fair price (`MIN_EV` in `clv.py`; modelled basketball lines are skipped), it is stored as a **signal** in `data/clv.sqlite3` (SQLite, git-ignored). Every later board updates that outcome's latest Pinnacle fair and MerkurXtip price until kickoff, and the last one seen is the closing line. **CLV = MerkurXtip price at the signal / closing fair price − 1**; above zero means MerkurXtip offered more than Pinnacle finally thought fair, which is the only check that the value was real without waiting for results.

A background worker refreshes the three boards every 30 s (10 s while a signalled match starts within 15 minutes) when nobody refreshes in the browser, so closing lines are recorded with the UI closed. A signal counts only if its closing line was seen at most 30 minutes before kickoff; the others are listed as "bez zatvaranja". The page is **Alerti → CLV**: totals, then by sport, market and league, then the last 200 signals. `/api/clv?days=&sport=` serves it.

## Line movement

Every board also records the Pinnacle price, Pinnacle fair price and MerkurXtip price of each compared outcome in `data/prices.sqlite3` (SQLite, git-ignored), but only when one of them changed since the last board, so the background worker fills it with the UI closed. A match is deleted 24 hours after kickoff (`KEEP_HOURS` in `price_history.py`). Roughly 30 000 outcomes take about 6 MB, plus about 10 MB of changes a day.

- **Odds modals and the football detail panel:** the **Kretanje** column shows a sparkline per outcome, with Pinnacle in blue and MerkurXtip in orange. Click it for a chart with the Pinnacle fair price (dashed) and a crosshair that shows all three prices at any moment. "—" means the price has not moved since it was first seen.
- **Value view:** the **Promena** column shows when each book last changed that price (bold within the last 15 minutes). Times are as precise as the board refresh. Hover shows since when the outcome has been tracked.
- `/api/history?sport=&id=<board match id>` serves the stored series.

## Project layout

| File | Purpose |
|---|---|
| `pinnwire_dashboard.py` | Local server on port 8070: competition filter, delta merge, price history, `/api/board`, `/api/match/<id>`, static files |
| `merkur_client.py` | MerkurXtip offer client, odds-code decoding and event pairing |
| `football_competitions.py` | Football leagues that are compared (`COMPETITIONS`) and leagues never listed as missing |
| `common.py` | What every sport shares: snapshot state (fetching, delta merging), compare rows, value items, time helpers |
| `pinnwire_client.py` | PinnWire REST client (`x-api-key`, 429/Retry-After handling), devig and market parsing |
| `frontend/` | React + Vite app (source in `frontend/dashboard/`; PWA manifest, service worker and icons in `frontend/dashboard/public/`) |
| `static/dashboard_build/` | Production bundle served by Python; `source-hash.txt` lets the tests catch a missing `npm run build` |
| `test_pinnwire_dashboard.py` | Unit tests: `python -m unittest test_pinnwire_dashboard`; lint with `python -m ruff check .` and `npm run lint` in `frontend/` |
| `applog.py` | Application log: `data/logs/app.log` (git-ignored, 25 MB at most with rotation) and the console |
| `data/` | API key, price history and the log; do not share `pinnwire_config.json` |

`data/logs/app.log` records how the running server stands, with the UI closed too: PinnWire and MerkurXtip outages and recoveries (one line per outage, not per refresh), PinnWire retries, the drop stream connecting and dropping, full snapshots and a warning when a sport's match count halves, bugs with their traceback, and once an hour a status line with matches and paired matches per sport. Prices are not logged; they are in `data/prices.sqlite3` and `data/clv.sqlite3`.

Competitions are the `COMPETITIONS` list in `football_competitions.py`, keyed by PinnWire `league_id`. Add an entry to track another league; the tests check that its key and badge code are unique and that it has a badge colour.

During frontend development, run the Python server in one terminal and `npm run dev` in `frontend/` in another. Vite runs on port 5175 and proxies `/api` to 8070.

## Basketball

Pick the basketball icon at the top of the side menu (or open `/?sport=basketball`). It has its own board, built in `basketball.py`:

- PinnWire sport 3 against the MerkurXtip basketball offer (`/restapi/custom/offer/sr/sport/B/mob`). Both are cached and refreshed like football (delta requests), so basketball adds one PinnWire request per refresh.
- Compared markets are full game with overtime: winner, handicap, total points and home/away team totals. Lines are matched exactly and only half-point lines (x.5) are used; whole-number lines are dropped because a push refunds the stake. Quarters and halves are not compared yet.
- Competitions are the `COMPETITIONS` list in `basketball.py`: PinnWire `league_id` plus the MerkurXtip `leagueId` (basketball `leagueShort` values are not unique, so the numeric id is used). Add an entry to track another league. The other PinnWire leagues are paired against the whole MerkurXtip offer by names and kickoff (like football): their matches MerkurXtip does not offer show under "Nedostaju", and leagues MerkurXtip does offer are listed there with their PinnWire `league_id` and MerkurXtip `leagueId`, ready to be added.
- MerkurXtip codes: winner `50291/50293`; handicap, total and team-total lines come in numbered sets (`handicapOvertime`, `handicapOvertime2` … in `params`) with the codes listed in `basketball.py`. The board shows the shared line closest to Pinnacle's main line; click a row for every compared line.


## Tennis

Pick the tennis icon (or open `/?sport=tennis`). The board is built in `tennis.py` and reuses the basketball state and pane; the MerkurXtip feed is the same URL with the sport letter `T` (`/restapi/custom/offer/sr/sport/T/mob`).

- PinnWire sport 2. A match is two PinnWire events: the main one in sets (winner, set handicap, total sets, 1st set winner) and a side event with `parent_id` in games (game handicap, total games, games per player, 1st set total games). The side events are requested with `include_alt_units=1` in the same single request and folded into the main event, so tennis adds one PinnWire request per refresh.
- Compared markets: winner, set handicap, total sets (only the 2.5 line, best of three), game handicap, total games, games per player, and for the 1st set the winner and total games. Lines are matched exactly, half-point lines only, nothing is modelled. The board shows the games handicap and total games; the other markets are in the odds modal and the Value list.
- Competitions are tournaments derived from the PinnWire league names (`ATP Lyon - R16` and `ATP Lyon - Doubles` are both "ATP Lyon"), grouped by ATP, WTA, Challenger and ITF; PinnWire changes the `league_id` every round, so there is no list to maintain.
- Matches are paired by player names and kickoff within 12 hours, with no competition check (the two books name tournaments differently). MerkurXtip writes initials ("K. Kawa") and its tennis kickoff is often a rough time, up to a few hours from Pinnacle's; the ⏱ tag shows the difference. Pairing needs the surname of every player, and an initial must match a name.
- MerkurXtip codes are listed in `tennis.py` (`MX_PERIOD`); the line params are `hd2` (set handicap), `handicapGames`, `overUnderGames`/`overUnderGames2`, `homeOverUnderGames`/`awayOverUnderGames` and `overUnderGamesFirstSet`…`5`. Small ITF matches only carry the winner and 1st set winner in the MerkurXtip offer.

## Ice hockey

Pick the hockey icon (or open `/?sport=hockey`). The board is built in `hockey.py` and reuses the basketball state and pane; the MerkurXtip feed is the same URL with the sport letter `H` (`/restapi/custom/offer/sr/sport/H/mob`).

- PinnWire sport 4, one request per refresh like basketball. Periods: 0 is the whole game with overtime and shootout (two-way winner), 6 is regulation time (60 minutes: three-way winner, handicap, totals, team totals) and 1, 2, 3 are the thirds (two-way winner that refunds a drawn third, handicap, totals). Only the leagues in `COMPETITIONS` are compared; the rest feed "Nedostaju" as in basketball.
- The board winner is the game winner with overtime (MerkurXtip "P1" / "P2"); the handicap and total columns are the 60 minutes. The odds modal's "Ceo meč" tab adds the 60-minute 1X2, the level handicap (AH 0, MerkurXtip "X vraća ulog") and team goals; the period tabs compare the winner without the draw ("W1"/"W2"), handicap and totals of a third. Lines are matched exactly, half-point lines only (plus AH 0), no model.
- MerkurXtip codes are listed in `hockey.py` (`MX_PERIOD`); the line params are `hd2w`, `overUnder`…`overUnder4`, `homeOverUnder`/`awayOverUnder` and `handicap…Period`/`overUnder…Period` for the thirds.
- Pairing is by competition, kickoff (3 h) and team names. MerkurXtip's short names that the token rules cannot pair ("Zurich" for ZSC Lions) go in `hockey.ALIASES`, which applies to hockey only.
- To add a league find its PinnWire `league_id` in a snapshot and the MerkurXtip `leagueId` in the offer, add the entry to `COMPETITIONS` and a `.comp-badge.<key>` colour in `dashboard.css`. Leagues MerkurXtip does not list at the moment (SHL, OHL) are missing until their `leagueId` can be read from the offer.

## MMA

Pick the MMA icon (or open `/?sport=mma`). The board is built in `mma.py` and reuses the basketball state and pane; the MerkurXtip feed is the same URL with the sport letter `MM` (`/restapi/custom/offer/sr/sport/MM/mob`).

- PinnWire sport 8, one request per refresh. Pinnacle prices a fight in period 0 only: the winner and total rounds (usually one line, 1.5 or 2.5). MerkurXtip's method of victory and "odlučen na poene" markets have no Pinnacle price and are not compared. The board has no handicap columns.
- MerkurXtip codes: winner `264` / `265` ("W1" / "W2"; the draw `2` is ignored), total rounds over `54291` / under `54290` with the line in `params.our`. Lines are matched exactly, half-point lines only, no model.
- Every PinnWire MMA league is shown, the promotion is the competition (badges for UFC, PFL, Bellator, ONE, Oktagon, KSW, the rest "MMA"). Fights pair by fighter names (tennis rules: "Reese, Zach" against "Zachary Reese") and kickoff within 12 hours, with no competition check: Pinnacle gives the card's start, MerkurXtip each fight's own time, so the ⏱ tag is normal here.
- The two books often list the fighters the other way round. A fight pairs in either order; a reversed MerkurXtip row is flagged `pinSwapped` and its winner prices and names are turned to Pinnacle's order. Fighters known under another name (Yana Kunitskaya is Yana Santos at Pinnacle) go in `mma.ALIASES`.

## Handball and volleyball

Pick the "Rukomet i odbojka" icon (or open `/?sport=handball`). One board for two sports, built in `handball.py` on the basketball state and pane. PinnWire files both under sport 10 (one request per refresh) and tells them apart only by the lines: a total of 20-99 goals is handball, 3.5-4.5 sets or 100+ points is volleyball; an event with no total yet is not shown until it has one. The MerkurXtip feeds are the same URL with the sport letters `HB` and `V`, fetched together (one feed down still shows the other); each row says its `sport` and a match pairs only within its own.

- Handball: winner `264` / `265` (draw refunded, like Pinnacle's two-way line; a three-way Pinnacle price is compared with the 1X2 `1` / `2` / `3` instead), handicap `hd2w` (`53877` / `53878`) and total goals `overUnder` (`227` / `228`), first half `hd2wp1` / `overUnderP` when Pinnacle quotes period 1. Half-point lines, matched exactly, no model.
- Volleyball: the match winner only (`1` / `3`). MerkurXtip sells point handicaps and totals, Pinnacle set lines; their numbers collide (2.5 sets, 2.5 points), so they are not compared.
- The competitions are the PinnWire leagues ("Serbia - Superliga", badge colour per sport), not mapped to MerkurXtip leagues. Matches pair by team names and kickoff within 3 hours; a women's side pairs only with a women's side (a `W` marker is added from a "Women" league name).

## Football "Nedostaju" and the full feed

The football request already returns every league PinnWire quotes (about 1300 matches), so the "Nedostaju" view uses all of it at no extra request cost. Matches of leagues that are not in `COMPETITIONS` (`otherMissing` and `otherCompetitions` in `/api/board`) are paired against the whole MerkurXtip offer by team names and kickoff only (3 h window, name score 0.75, a women's/youth/reserve side never pairs with the senior side); the ones left unpaired are listed under their league, grouped by country in the side menu. Matches of those leagues that MerkurXtip does offer are not shown anywhere. They are never compared, only listed, and the result is cached until the offer or the event set changes because the pairing without a league check takes a couple of seconds.

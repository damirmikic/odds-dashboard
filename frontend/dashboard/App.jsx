import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { readStored, requestJson, serverDownStore, writeStored } from "./api.js";
import { useBuildReload, usePwa, useStickyHeaderOffsets, useTheme } from "./hooks.js";
import { DAY_FILTERS, clockFmt, dayKey, dayLabel, evClass, fmtEv, fmtOdds, inDayFilter } from "./format.js";
import { VALUE_GROUPS, VALUE_LEVELS, ValueRange, ValueTable, isTopLeague, rangePasses, valuePasses } from "./value.jsx";
import { SideMenu } from "./menu.jsx";
import { MissingTable, OtherOffered, SuspendedTable, missingEmpty } from "./missing.jsx";
import { BoardTable, CompareTable } from "./football/board.jsx";
import { DetailPanel, OddsModal } from "./football/detail.jsx";
import { SPORT_VIEWS } from "./sportViews.js";
import { SportPane, useSportBoard } from "./sport.jsx";
import { AlertsPage, useDropAlerts } from "./alerts.jsx";
import { ClvPage } from "./clv.jsx";
import { AllValuePane, collectValues } from "./allValue.jsx";
import { GlobalSearch, matchesQuery, searchAll } from "./search.jsx";

const AUTO_OPTIONS = [0, 3, 5, 10, 15, 30, 60, 120, 300];
const BACKGROUND_SECONDS = 30;
const STATUS_RETRY_SECONDS = 5;

const DROP_OPTIONS = [2, 3, 5, 10];

const fmtAuto = (sec) => (!sec ? "isklj." : sec < 60 ? `${sec} sek` : `${sec / 60} min`);

function KeyPanel({ onSaved }) {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await requestJson("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apiKey }),
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="key-panel">
      <h1>Poveži PinnWire</h1>
      <p>Ključ se čuva lokalno (data/pinnwire_config.json) i šalje samo sa ovog servera na pinnwire.com.</p>
      <form onSubmit={submit}>
        <input
          type="password"
          autoComplete="off"
          placeholder="PinnWire API ključ"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          required
        />
        <button className="button primary" type="submit" disabled={saving}>{saving ? "Čuvam…" : "Poveži"}</button>
      </form>
      {error && <p className="state error" role="alert">{error}</p>}
    </section>
  );
}

// ?sport=basketball deep-links to a sport (?sport=value: the all-sports Value screen); otherwise the last one used
function initialSport() {
  const fromUrl = new URLSearchParams(window.location.search).get("sport");
  const sport = fromUrl || readStored("pb.sport", "football");
  return ["basketball", "tennis", "hockey", "mma", "handball", "value"].includes(sport) ? sport : "football";
}

export default function App() {
  const serverDown = useSyncExternalStore(serverDownStore.subscribe, serverDownStore.get);
  useStickyHeaderOffsets();
  const [apiKeySet, setApiKeySet] = useState(null);
  const [sport, setSport] = useState(initialSport);
  const [board, setBoard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [, setCallsToday] = useState(0);
  const bb = useSportBoard("basketball", setCallsToday, setApiKeySet);
  const tn = useSportBoard("tennis", setCallsToday, setApiKeySet);
  const hk = useSportBoard("hockey", setCallsToday, setApiKeySet);
  const mm = useSportBoard("mma", setCallsToday, setApiKeySet);
  const hb = useSportBoard("handball", setCallsToday, setApiKeySet);
  const [competition, setCompetition] = useState(() => readStored("pb.competition", "all"));
  const [dayFilter, setDayFilter] = useState(() => readStored("pb.day", "all"));
  const [query, setQuery] = useState("");
  const [autoSeconds, setAutoSeconds] = useState(() => readStored("pb.autoSec", 5));
  const [dropAlerts, setDropAlerts] = useState(() => readStored("pb.dropAlerts", true));
  const [dropPct, setDropPct] = useState(() => readStored("pb.dropPct", 3));
  const [dropEdge, setDropEdge] = useState(() => readStored("pb.dropEdge", false));
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [alertsPage, setAlertsPage] = useState("drops");
  const [view, setView] = useState(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("view");
    const view = ["compare", "value", "missing", "suspended"].includes(fromUrl) ? fromUrl : readStored("pb.view", "compare");
    return view === "pinnacle" ? "compare" : view;
  });
  const [edgeFilter, setEdgeFilter] = useState(() => readStored("pb.edge", "all"));
  const [valueLevel, setValueLevel] = useState(() => readStored("pb.valueLevel2", "fair"));
  const [valueLeague, setValueLeague] = useState("all");
  const [valueGroup, setValueGroup] = useState(() => readStored("pb.valueGroup", "all"));
  const [evMin, setEvMin] = useState(() => readStored("pb.evMin", ""));
  const [evMax, setEvMax] = useState(() => readStored("pb.evMax", ""));
  const [topOnly, setTopOnly] = useState(() => readStored("pb.topOnly", false));
  const [selectedId, setSelectedId] = useState(() => window.location.hash.replace(/\D/g, ""));
  const [oddsId, setOddsId] = useState("");
  const [paneOpen, setPaneOpen] = useState(null);
  const pwa = usePwa();
  const { theme, toggle: toggleTheme } = useTheme();

  // #<event id> deep-links to a match
  useEffect(() => {
    const url = `${window.location.pathname}${window.location.search}${selectedId ? `#${selectedId}` : ""}`;
    window.history.replaceState(null, "", url);
  }, [selectedId]);

  const loadBoard = useCallback(async (mode) => {
    setLoading(true);
    setError("");
    try {
      const suffix = mode === "full" ? "?full=1" : mode === "refresh" ? "?refresh=1" : "";
      const data = await requestJson(`/api/board${suffix}`);
      setBoard(data);
      setCallsToday(data.callsToday);
    } catch (err) {
      setError(err.message);
      if (err.message.includes("ključ")) setApiKeySet(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const twoWay = sport !== "football";
  const allValue = sport === "value";
  const pane = { basketball: bb, tennis: tn, hockey: hk, mma: mm, handball: hb }[sport] || null;
  const boards = useMemo(
    () => ({ football: board, basketball: bb.board, tennis: tn.board, hockey: hk.board, mma: mm.board, handball: hb.board }),
    [board, bb.board, tn.board, hk.board, mm.board, hb.board],
  );
  // the all-sports Value screen refreshes every board (one request per sport)
  const { load: bbLoad } = bb;
  const { load: tnLoad } = tn;
  const { load: hkLoad } = hk;
  const { load: mmLoad } = mm;
  const { load: hbLoad } = hb;
  const reloadAll = useCallback(
    (mode) => Promise.all([loadBoard, bbLoad, tnLoad, hkLoad, mmLoad, hbLoad].map((load) => load(mode))),
    [loadBoard, bbLoad, tnLoad, hkLoad, mmLoad, hbLoad],
  );
  const reload = allValue ? reloadAll : pane ? pane.load : loadBoard;
  const cur = pane ? pane.board : board;
  const curLoading = allValue ? loading || bb.loading || tn.loading || hk.loading || mm.loading || hb.loading
    : pane ? pane.loading : loading;
  const drops = useDropAlerts(boards, dropAlerts, dropPct, apiKeySet, dropEdge);
  const pickSport = useCallback((key) => {
    setAlertsOpen(false);
    setSport(key);
  }, []);
  const alertsTab = { count: drops.alerts.length, active: alertsOpen, onOpen: () => setAlertsOpen(true) };
  const fairCount = useMemo(() => collectValues(boards).filter((v) => v.ev >= 0 && !v.modeled).length, [boards]);
  const valueTab = { count: fairCount, active: allValue && !alertsOpen, onOpen: () => pickSport("value") };
  const openAlert = useCallback((a) => {
    setAlertsOpen(false);
    setSport(a.sport);
    // the full match opens as the centred odds modal, in every sport
    if (a.sport === "football") setOddsId(String(a.matchId));
    else setPaneOpen({ id: String(a.matchId) });
  }, []);
  useEffect(() => writeStored("pb.sport", sport), [sport]);
  // all boards are loaded up front so the sport icons can show their match counts
  useEffect(() => {
    if (apiKeySet && !bb.board && !bb.loading && !bb.error) bb.load();
    if (apiKeySet && !tn.board && !tn.loading && !tn.error) tn.load();
    if (apiKeySet && !hk.board && !hk.loading && !hk.error) hk.load();
    if (apiKeySet && !mm.board && !mm.loading && !mm.error) mm.load();
    if (apiKeySet && !hb.board && !hb.loading && !hb.error) hb.load();
    if (apiKeySet && !board && !loading && !error) loadBoard();
  }, [apiKeySet, bb, tn, hk, mm, hb, board, loading, error, loadBoard]);
  const sportCounts = {
    football: board?.matches.length, basketball: bb.board?.matches.length, tennis: tn.board?.matches.length,
    hockey: hk.board?.matches.length, mma: mm.board?.matches.length,
    handball: hb.board?.matches.length,
  };
  const search = useMemo(() => searchAll(boards, query), [boards, query]);
  const searching = query.trim() !== "";
  const menuCounts = searching ? search.counts : sportCounts;
  const searchBox = (
    <GlobalSearch query={query} setQuery={setQuery} hits={search.hits}
      onOpen={(hit) => openAlert({ sport: hit.sport, matchId: hit.match.id })} />
  );

  // retried until the server answers, so a page opened while the server was down recovers by itself
  useEffect(() => {
    if (apiKeySet !== null) return undefined;
    let stopped = false;
    let timer;
    const check = () => requestJson("/api/status")
      .then((status) => {
        if (stopped) return;
        setError("");
        setApiKeySet(status.apiKeySet);
        setCallsToday(status.callsToday);
      })
      .catch((err) => {
        if (stopped) return;
        setError(err.message);
        timer = setTimeout(check, STATUS_RETRY_SECONDS * 1000);
      });
    check();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [apiKeySet]);

  useEffect(() => {
    if (!autoSeconds || !apiKeySet || curLoading) return undefined;
    const timer = setTimeout(() => reload("refresh"), autoSeconds * 1000);
    return () => clearTimeout(timer);
  }, [autoSeconds, apiKeySet, reload, curLoading, cur?.fetchedAt]);

  // The boards not on screen (and the shown one with Auto off) re-read the server's snapshot, which the
  // CLV worker keeps fresh: no PinnWire request, and a board that failed (server down) retries by itself.
  const live = useRef(null);
  useEffect(() => {
    live.current = {
      boards: {
        football: [loadBoard, loading], basketball: [bbLoad, bb.loading], tennis: [tnLoad, tn.loading],
        hockey: [hkLoad, hk.loading], mma: [mmLoad, mm.loading], handball: [hbLoad, hb.loading],
      },
      onScreen: (key) => !!autoSeconds && (allValue || key === sport),
      wake: () => { if (!curLoading) reload(autoSeconds ? "refresh" : undefined); },
    };
  });
  useEffect(() => {
    if (!apiKeySet) return undefined;
    const timer = setInterval(() => {
      const { boards, onScreen } = live.current;
      for (const [key, [load, busy]] of Object.entries(boards)) if (!busy && !onScreen(key)) load();
    }, BACKGROUND_SECONDS * 1000);
    // back to the tab, out of sleep or back online: the shown board at once, not after a throttled timer
    const wake = () => { if (document.visibilityState === "visible") live.current.wake(); };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", wake);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("online", wake);
    };
  }, [apiKeySet]);
  useBuildReload();

  useEffect(() => writeStored("pb.competition", competition), [competition]);
  useEffect(() => writeStored("pb.day", dayFilter), [dayFilter]);
  useEffect(() => writeStored("pb.autoSec", autoSeconds), [autoSeconds]);
  useEffect(() => writeStored("pb.dropAlerts", dropAlerts), [dropAlerts]);
  useEffect(() => writeStored("pb.dropPct", dropPct), [dropPct]);
  useEffect(() => writeStored("pb.dropEdge", dropEdge), [dropEdge]);
  useEffect(() => writeStored("pb.view", view), [view]);
  useEffect(() => writeStored("pb.edge", edgeFilter), [edgeFilter]);
  useEffect(() => writeStored("pb.valueLevel2", valueLevel), [valueLevel]);
  useEffect(() => writeStored("pb.valueGroup", valueGroup), [valueGroup]);
  useEffect(() => writeStored("pb.evMin", evMin), [evMin]);
  useEffect(() => writeStored("pb.evMax", evMax), [evMax]);
  useEffect(() => writeStored("pb.topOnly", topOnly), [topOnly]);

  const competitions = useMemo(() => board?.competitions || [], [board]);
  // "Nedostaju" also lists the rest of the PinnWire feed: leagues outside `competitions` that MerkurXtip does not offer
  const otherCompetitions = board?.otherCompetitions;
  const allCompetitions = useMemo(() => [...competitions, ...(otherCompetitions || [])], [competitions, otherCompetitions]);
  const compById = useMemo(() => new Map(allCompetitions.map((c) => [c.id, c])), [allCompetitions]);
  const otherKeys = useMemo(() => new Set((otherCompetitions || []).map((c) => c.key)), [otherCompetitions]);

  const filtered = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    const pool = view === "missing" ? [...(board?.matches || []), ...(board?.otherMissing || [])] : board?.matches || [];
    return pool.filter((m) => {
      if (competition !== "all" && (view !== "missing" && otherKeys.has(competition) ? false : compById.get(m.leagueId)?.key !== competition)) return false;
      if (!inDayFilter(new Date(m.starts), dayFilter)) return false;
      if (view === "missing" && m.merkur) return false;
      if (view === "compare" && edgeFilter !== "all") {
        if (edgeFilter === "missing") {
          if (m.merkur) return false;
        } else if (!m.merkur || (edgeFilter !== "paired" && (m.merkur.best?.ev ?? -1) < Number(edgeFilter))) {
          return false;
        }
      }
      return matchesQuery(m, q);
    });
  }, [board, competition, dayFilter, query, compById, otherKeys, view, edgeFilter]);

  // Value view: all competitions together (the tabs do not apply); day and search filters do.
  const matchesById = useMemo(() => new Map((board?.matches || []).map((m) => [m.id, m])), [board]);
  const valueList = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return (board?.values || []).filter((v) => {
      const m = matchesById.get(v.matchId);
      if (!m || !inDayFilter(new Date(m.starts), dayFilter)) return false;
      return !q || `${m.home} ${m.away}`.toLocaleLowerCase().includes(q);
    });
  }, [board, matchesById, dayFilter, query]);
  const levelValues = useMemo(
    () => valueList.filter((v) => valuePasses(v, valueLevel, valueGroup) && rangePasses(v, evMin, evMax)
      && (!topOnly || isTopLeague("football", compById.get(matchesById.get(v.matchId).leagueId)))),
    [valueList, valueLevel, valueGroup, evMin, evMax, topOnly, compById, matchesById],
  );
  // per-competition summary of the outcomes passing the level and market filters
  const valueSummary = useMemo(() => {
    const byLeague = new Map();
    for (const v of levelValues) {
      const leagueId = matchesById.get(v.matchId).leagueId;
      const row = byLeague.get(leagueId) || { count: 0, best: -Infinity, matches: new Set() };
      row.count += 1;
      row.best = Math.max(row.best, v.ev);
      row.matches.add(v.matchId);
      byLeague.set(leagueId, row);
    }
    return byLeague;
  }, [levelValues, matchesById]);
  const shownValues = useMemo(
    () => (valueLeague === "all" ? levelValues
      : levelValues.filter((v) => String(matchesById.get(v.matchId).leagueId) === valueLeague)),
    [levelValues, valueLeague, matchesById],
  );
  const fairValueCount = useMemo(() => valueList.filter((v) => v.ev >= 0).length, [valueList]);

  // "Sve" groups by day (competition shown per row); a single competition groups by day too.
  const groups = useMemo(() => {
    const map = new Map();
    for (const m of filtered) {
      const date = new Date(m.starts);
      const key = dayKey(date);
      if (!map.has(key)) map.set(key, { key, title: dayLabel(date), matches: [] });
      map.get(key).matches.push(m);
    }
    return [...map.values()];
  }, [filtered]);

  const selectedMatch = board?.matches.find((m) => String(m.id) === selectedId);
  const onCalls = useCallback((n) => setCallsToday(n), []);

  const totalCount = board?.matches.length || 0;

  // Side menu: competitions grouped by country; in the value view the counts are value outcomes.
  const inValue = view === "value";
  const inMissing = view === "missing";
  const missingCounts = useMemo(() => {
    const counts = new Map();
    for (const m of [...(board?.matches || []), ...(board?.otherMissing || [])]) {
      if (!m.merkur) counts.set(m.leagueId, (counts.get(m.leagueId) || 0) + 1);
    }
    return counts;
  }, [board]);
  const missingTotal = useMemo(() => [...missingCounts.values()].reduce((a, b) => a + b, 0), [missingCounts]);
  const menuCompetitions = useMemo(
    () => (inMissing ? allCompetitions.map((c) => ({ ...c, count: missingCounts.get(c.id) || 0 })) : competitions),
    [competitions, allCompetitions, inMissing, missingCounts],
  );
  const menuGroups = useMemo(() => {
    const menuItem = (c) => {
      const row = inValue ? valueSummary.get(c.id) : null;
      return {
        id: c.id,
        key: c.key,
        comp: c,
        count: inValue ? (row ? row.count : 0) : c.count,
        extra: row ? fmtEv(row.best) : null,
        extraClass: row ? evClass(row.best) : "",
        disabled: inValue ? !row : !c.count,
        active: inValue ? valueLeague === String(c.id) : competition === c.key,
        title: row ? `${row.count} ishoda na ${row.matches.size} mečeva, najveća razlika vs fer ${fmtEv(row.best)}` : undefined,
      };
    };
    const map = new Map();
    for (const c of menuCompetitions) {
      if (!map.has(c.country)) map.set(c.country, { title: c.country, items: [] });
      map.get(c.country).items.push(menuItem(c));
    }
    return [...map.values()];
  }, [menuCompetitions, inValue, valueSummary, valueLeague, competition]);
  const allItem = inValue
    ? { id: null, key: "all", label: "Sve lige", count: levelValues.length, active: valueLeague === "all" }
    : { id: null, key: "all", label: "Sve", count: inMissing ? missingTotal : totalCount, active: competition === "all" };


  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">P</span>
          <div>
            <strong>Xtip Monitor</strong>
            <small>{allValue ? "Value, svi sportovi" : SPORT_VIEWS[sport]?.label || "Fudbal"} · Pinnacle vs MerkurXtip</small>
          </div>
        </div>

        <div className="status">
          {cur?.fetchedAt && (
            <span title={cur.mode === "delta" ? "Delta osvežavanje: preuzete samo promene" : "Pun snapshot"}>
              <i className={`dot${curLoading ? " busy" : ""}`} />
              {clockFmt.format(new Date(cur.fetchedAt))}
              <em>{cur.mode === "delta" ? `Δ ${cur.changed} promena` : "pun snapshot"}</em>
            </span>
          )}
          {cur?.merkur && (
            <span
              className={cur.merkur.error ? "status-error" : ""}
              title={cur.merkur.error || "MerkurXtip ponuda: upareni mečevi / mečevi ovih takmičenja u ponudi"}
            >
              MX {cur.merkur.fetchedAt ? clockFmt.format(new Date(cur.merkur.fetchedAt)) : "—"}
              <em>upareno {cur.merkur.paired}/{cur.merkur.offered}</em>
              {cur.merkur.error && <em>· greška</em>}
            </span>
          )}
        </div>

        <div className="actions">
          <button
            type="button"
            className="button ghost"
            onClick={toggleTheme}
            title={theme === "dark" ? "Svetla tema" : "Tamna tema"}
          >
            {theme === "dark" ? "☀" : "☾"}
          </button>
          {pwa.canInstall && (
            <button type="button" className="button ghost" onClick={pwa.install} title="Instaliraj Xtip Monitor kao aplikaciju">
              ⤓ Instaliraj
            </button>
          )}
          <label className="auto">
            Auto
            <select value={autoSeconds} onChange={(e) => setAutoSeconds(Number(e.target.value))}>
              {AUTO_OPTIONS.map((m) => <option key={m} value={m}>{fmtAuto(m)}</option>)}
            </select>
          </label>
          <button type="button" className="button primary" onClick={() => reload("refresh")} disabled={!apiKeySet || curLoading}>
            ↻ Osveži
          </button>
          <button
            type="button"
            className="button ghost"
            onClick={() => reload("full")}
            disabled={!apiKeySet || curLoading}
            title="Preuzmi kompletan snapshot umesto samo promena"
          >
            Pun reload
          </button>
        </div>
      </header>

      {(!pwa.online || cur?.__cachedAt || serverDown) && (
        <div className="offline-banner" role="status">
          {!pwa.online ? "Offline." : "Server nije dostupan."}{" "}
          {cur?.__cachedAt
            ? `Prikazane su poslednje sačuvane kvote${
                Number.isNaN(new Date(cur.__cachedAt).getTime()) ? "" : ` (${clockFmt.format(new Date(cur.__cachedAt))})`
              } — nisu žive.`
            : "Kvote se ne mogu osvežiti dok veza ne proradi."}{" "}
          Ponovo pokušavam automatski.
          <button type="button" className="button small" onClick={() => window.location.reload()}>Osveži stranu</button>
        </div>
      )}

      {apiKeySet === false && <KeyPanel onSaved={() => { setApiKeySet(true); bb.reset(); tn.reset(); hk.reset(); mm.reset(); hb.reset(); reload("full"); }} />}

      {apiKeySet && alertsOpen && (
        <div className="shell">
          <SideMenu sport="" onSport={pickSport} sportCounts={menuCounts} searching={searching} alerts={alertsTab} valueTab={valueTab} />
          <div className="content">
        <div className="segmented view-switch">
          <button type="button" className={alertsPage === "drops" ? "active" : ""} onClick={() => setAlertsPage("drops")}>Padovi</button>
          <button type="button" className={alertsPage === "clv" ? "active" : ""} onClick={() => setAlertsPage("clv")}>CLV</button>
        </div>
        {alertsPage === "clv" ? <ClvPage /> : <AlertsPage
          alerts={drops.alerts}
          threshold={dropPct}
          setThreshold={setDropPct}
          notify={dropAlerts}
          setNotify={setDropAlerts}
          edgeOnly={dropEdge}
          setEdgeOnly={setDropEdge}
          stream={drops.stream}
          onClear={drops.clear}
          onOpen={openAlert}
        />}
          </div>
        </div>
      )}

      {apiKeySet && !alertsOpen && pane && (
        <SportPane
          key={sport}
          board={pane.board}
          error={pane.error}
          loading={pane.loading}
          dayFilter={dayFilter}
          setDayFilter={setDayFilter}
          query={query}
          searchBox={searchBox}
          sport={sport}
          onSport={pickSport}
          alertsTab={alertsTab}
          valueTab={valueTab}
          sportCounts={menuCounts}
          searching={searching}
          setCallsToday={setCallsToday}
          openReq={paneOpen}
        />
      )}

      {apiKeySet && !alertsOpen && allValue && (
        <AllValuePane
          boards={boards}
          errors={{ football: error, basketball: bb.error, tennis: tn.error, hockey: hk.error, mma: mm.error, handball: hb.error }}
          dayFilter={dayFilter}
          setDayFilter={setDayFilter}
          query={query}
          searchBox={searchBox}
          onSport={pickSport}
          alertsTab={alertsTab}
          valueTab={valueTab}
          sportCounts={menuCounts}
          searching={searching}
          setCallsToday={setCallsToday}
        />
      )}

      {apiKeySet && !alertsOpen && !twoWay && (
        <>
          <div className="shell">
            <SideMenu
              sport={sport}
              onSport={pickSport}
              alerts={alertsTab}
              valueTab={valueTab}
              sportCounts={menuCounts}
              searching={searching}
              groups={menuGroups}
              all={allItem}
              onPick={(item) => (view === "value"
                ? setValueLeague((cur) => (item.id == null || cur === String(item.id) ? "all" : String(item.id)))
                : setCompetition(item.key))}
              label={view === "value" ? "Value po takmičenjima" : "Takmičenja"}
            />
            <div className="content">
            <div className="filters">
              <div className="segmented view-switch">
                <button type="button" className={view === "compare" ? "active" : ""} onClick={() => setView("compare")}>
                  MerkurXtip vs Pinnacle
                </button>
                <button
                  type="button"
                  className={view === "value" ? "active" : ""}
                  onClick={() => setView("value")}
                  title={`${valueList.length} ishoda gde je MX > Pinnacle, od toga ${fairValueCount} gde je MX ≥ fer`}
                >
                  Value <span className="view-count">{fairValueCount}/{valueList.length}</span>
                </button>
                <button
                  type="button"
                  className={view === "missing" ? "active" : ""}
                  onClick={() => setView("missing")}
                  title="Mečevi koje Pinnacle ima, a MerkurXtip nema"
                >
                  Nedostaju <span className="view-count">{missingTotal}</span>
                </button>
                <button
                  type="button"
                  className={view === "suspended" ? "active" : ""}
                  onClick={() => setView("suspended")}
                  title="Mečevi kojima je Pinnacle imao kvotu, a sada je nema"
                >
                  Suspended <span className="view-count">{board?.suspended?.length || 0}</span>
                </button>
              </div>
              {view === "value" && (
                <>
                  <div className="segmented">
                    {VALUE_LEVELS.map(([key, label]) => (
                      <button key={key} type="button" className={valueLevel === key ? "active" : ""} onClick={() => setValueLevel(key)}>
                        {label}
                      </button>
                    ))}
                  </div>
                  <label className="auto">
                    Tržište
                    <select value={valueGroup} onChange={(e) => setValueGroup(e.target.value)}>
                      {VALUE_GROUPS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                    </select>
                  </label>
                  <ValueRange min={evMin} max={evMax} setMin={setEvMin} setMax={setEvMax} topOnly={topOnly} setTopOnly={setTopOnly} />
                </>
              )}
              {view === "compare" && (
                <label className="auto">
                  Odstupanje
                  <select value={edgeFilter} onChange={(e) => setEdgeFilter(e.target.value)}>
                    <option value="all">svi mečevi</option>
                    <option value="paired">upareni</option>
                    <option value="-0.02">najveće ≥ −2%</option>
                    <option value="0">najveće ≥ 0%</option>
                    <option value="0.02">najveće ≥ +2%</option>
                    <option value="missing">nije u ponudi MX</option>
                  </select>
                </label>
              )}
              <div className="segmented">
                {DAY_FILTERS.map(([key, label]) => (
                  <button key={key} type="button" className={dayFilter === key ? "active" : ""} onClick={() => setDayFilter(key)}>
                    {label}
                  </button>
                ))}
              </div>
              {searchBox}
              {view === "pinnacle" ? (
                <span className="legend">
                  <span className="price up"><span className="price-odds">▲</span></span> kvota raste
                  <span className="price down"><span className="price-odds">▼</span></span> kvota pada
                  <span className="legend-fair">sivo = fer kvota (bez marže)</span>
                </span>
              ) : (
                <span className="legend mc-legend">
                  <span className="mc-cell mx-fair">MX ≥ fer</span>
                  <span className="mc-cell mx-above">MX &gt; Pinnacle</span>
                  {view === "compare" && (
                    <>
                      <span className="mc-cell mx-moved" title="Promena pri poslednjem osvežavanju">MX promena</span>
                      <span className="mc-cell pin-up" title="Promena pri poslednjem osvežavanju">PIN raste</span>
                      <span className="mc-cell pin-down" title="Promena pri poslednjem osvežavanju">PIN pada</span>
                    </>
                  )}
                </span>
              )}
            </div>

            <main className={`workspace${selectedId ? " with-detail" : ""}`}>
              <section className="board-wrap">
                {error && <p className="state error" role="alert">{error}</p>}
                {!board && loading && <p className="state">Učitavam ponudu…</p>}
                {board && view !== "value" && view !== "suspended" && !filtered.length && (
                  <p className="state">
                    {view === "missing" ? missingEmpty(missingTotal, competition !== "all", () => setCompetition("all")) : "Nema mečeva za izabrani filter."}
                  </p>
                )}
                {view === "suspended" && (board?.suspended?.length
                  ? <SuspendedTable matches={board.suspended} />
                  : <p className="state">Nijedan meč nije izgubio Pinnacle kvotu od pokretanja servera.</p>)}
                {view === "missing" && <OtherOffered leagues={board?.otherOffered} />}
                {!!filtered.length && view === "missing" && (
                  <MissingTable matches={filtered} competitions={allCompetitions} sport="football" />
                )}
                {!!filtered.length && view === "compare" && (
                  <CompareTable
                    matches={filtered}
                    pinStamp={board.fetchedAt}
                    mxStamp={board.merkur?.fetchedAt}
                    selectedId={oddsId}
                    onOdds={setOddsId}
                    onSelect={setOddsId}
                  />
                )}
                {board && view === "value" && !shownValues.length && (
                  <p className="state">Nema ishoda za izabrane filtere.</p>
                )}
                {board && view === "value" && !!shownValues.length && (
                  <ValueTable
                    values={shownValues}
                    matchesById={matchesById}
                    competitions={competitions}
                    selectedId={oddsId}
                    onOdds={setOddsId}
                    onSelect={setOddsId}
                  />
                )}
                {!!filtered.length && view === "pinnacle" && (
                  <BoardTable
                    groups={groups}
                    competitions={competitions}
                    selectedId={selectedId}
                    fetchedAt={board.fetchedAt}
                    onSelect={(id) => setSelectedId((current) => (current === id ? "" : id))}
                    showLeague={competition === "all"}
                  />
                )}
              </section>
              {selectedId && (
                <DetailPanel
                  key={selectedId}
                  matchId={selectedId}
                  boardMatch={selectedMatch}
                  competition={selectedMatch ? compById.get(selectedMatch.leagueId) : null}
                  onClose={() => setSelectedId("")}
                  onCalls={onCalls}
                />
              )}
            </main>
            {oddsId && (
              <OddsModal
                key={oddsId}
                matchId={oddsId}
                boardMatch={matchesById.get(Number(oddsId)) || matchesById.get(oddsId)}
                onClose={() => setOddsId("")}
                onCalls={onCalls}
              />
            )}
            </div>
          </div>
        </>
      )}

      {drops.toasts.length > 0 && !alertsOpen && !selectedId && !oddsId && (
        <div className="drop-alerts" role="alert">
          <button type="button" className="button drop-clear" onClick={() => drops.dismiss()}>
            Obriši sve ({drops.toasts.length})
          </button>
          {drops.toasts.slice(0, 3).map((a) => (
            <button
              key={a.id}
              type="button"
              className={`drop-alert${a.mxEv > 0 ? " edge" : ""}`}
              onClick={() => { drops.dismiss(a.id); openAlert(a); }}
              title="Klik za zatvaranje"
            >
              <b>▼ {a.match}</b>
              <span>
                {a.market}{a.line} {a.side}: {fmtOdds(a.from)} → {fmtOdds(a.to)} (−{a.pct.toFixed(1)}%)
                {a.mx != null
                  ? ` · Merkur ${fmtOdds(a.mx)}, prednost ${fmtEv(a.mxEv)}`
                  : a.nvp ? ` · fer ${fmtOdds(a.nvp)}` : ""}
              </span>
            </button>
          ))}
        </div>
      )}

      <footer>Kvote: Pinnacle preko PinnWire · Kvote se mogu promeniti u svakom trenutku.</footer>
    </div>
  );
}

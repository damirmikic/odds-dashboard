// Drop alerts: polling /api/drops, toasts and the Alerti page.
import { useCallback, useEffect, useRef, useState } from "react";
import { requestJson } from "./api.js";
import { LOCALE, evClass, fmtEv, fmtKickoffShort, fmtLine, fmtOdds } from "./format.js";

const DROP_MARKETS = { moneyline: "Pobednik", spread: "Hendikep", total: "Ukupno" };

const DROP_SIDES = { home: "1", draw: "X", away: "2", over: "V", under: "M" };

const DROP_PERIODS = { football: { 1: "1. pol. " }, basketball: { 1: "1. pol. ", 3: "1. čet. " }, tennis: { 1: "1. set " }, hockey: { 1: "1. per. ", 2: "2. per. ", 3: "3. per. " }, mma: {} };

// One alert per match, market, period and side: of several drops on different lines the one with the largest
// MerkurXtip edge stays (without a MerkurXtip price, the largest drop).
const dropRank = (a) => a.mxEv ?? -Infinity;

const dropBetter = (a, b) => (dropRank(a) !== dropRank(b) ? dropRank(a) > dropRank(b) : a.pct > b.pct);

// Polls the server's buffer of PinnWire's SSE drop stream (local, no PinnWire request) for every sport and keeps
// the prematch drops of at least `threshold` percent that belong to matches on the loaded boards, with the
// MerkurXtip price of the same outcome. `toasts` are the ones not yet seen (only Merkur edges with `edgeOnly`);
// `alerts` is the history.
export function useDropAlerts(boards, enabled, threshold, apiKeySet, edgeOnly) {
  const seen = useRef(new Set());
  const groups = useRef(new Map()); // alert group -> the alert shown for it
  const boardsRef = useRef(boards);
  boardsRef.current = boards;
  const [alerts, setAlerts] = useState([]);
  const [toasts, setToasts] = useState([]);
  const [stream, setStream] = useState(null);
  const notify = useRef(enabled);
  notify.current = enabled;
  const edgeRef = useRef(edgeOnly);
  edgeRef.current = edgeOnly;
  useEffect(() => {
    seen.current = new Set();
    groups.current = new Map();
    setAlerts([]);
    setToasts([]);
  }, [threshold]);
  useEffect(() => {
    if (!apiKeySet) return undefined;
    let stop = false;
    const poll = async () => {
      const found = [];
      for (const sport of Object.keys(boardsRef.current)) {
        if (!boardsRef.current[sport]?.matches) continue;
        try {
          const data = await requestJson(`/api/drops?sport=${sport}&min=${threshold}&age=300`);
          setStream(data.stream || null);
          const matches = new Map(boardsRef.current[sport].matches.map((m) => [String(m.id), m]));
          for (const d of data.drops || []) {
            // tennis games markets drop on a side event; the server maps it to the board match
            const match = matches.get(String(d.match_id ?? d.event_id));
            const id = `${d.event_id}:${d.market}:${d.period}:${d.side}:${d.points}:${d.to}:${d.alerted}`;
            if (!match || seen.current.has(id)) continue;
            seen.current.add(id);
            const line = d.points != null && d.market !== "moneyline" ? ` ${fmtLine(d.points, d.market === "spread")}` : "";
            const period = d.period ? DROP_PERIODS[sport]?.[d.period] ?? `P${d.period} ` : "";
            found.push({
              id, group: `${sport}:${match.id}:${d.market}:${d.period}:${d.side}`, sport, matchId: match.id, match: `${match.home} – ${match.away}`, league: match.leagueName || d.league,
              starts: match.starts, at: Date.now() - (d.age_s || 0) * 1000,
              market: period + (DROP_MARKETS[d.market] || d.market), line, side: DROP_SIDES[d.side] || d.side,
              from: d.from, to: d.to, pct: d.drop_pct, nvp: d.nvp,
              mx: d.merkur?.odds ?? null, mxEv: d.merkur?.ev ?? null,
            });
          }
        } catch {
          /* the next poll retries */
        }
      }
      if (stop || !found.length) return;
      found.sort((x, y) => y.at - x.at);
      const shown = [];
      for (const a of found) {
        const current = groups.current.get(a.group);
        if (current && !dropBetter(a, current)) continue;
        groups.current.set(a.group, a);
        const at = shown.findIndex((x) => x.group === a.group);
        if (at >= 0) shown.splice(at, 1);
        shown.push(a);
      }
      if (!shown.length) return;
      const replaced = new Set(shown.map((a) => a.group));
      const keep = (list) => list.filter((a) => !replaced.has(a.group));
      setAlerts((list) => [...shown, ...keep(list)].slice(0, 300));
      const fresh = edgeRef.current ? shown.filter((a) => a.mxEv > 0) : shown;
      if (notify.current && fresh.length) {
        setToasts((list) => [...fresh, ...keep(list)].slice(0, 30));
      }
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [threshold, apiKeySet]);
  const dismiss = useCallback((id) => setToasts((list) => (id ? list.filter((a) => a.id !== id) : [])), []);
  const clear = useCallback(() => {
    groups.current = new Map();
    setAlerts([]);
    setToasts([]);
  }, []);
  return { alerts, toasts, dismiss, clear, stream };
}

const DROP_LEVELS = [1, 2, 3, 5, 7.5, 10, 15];

const DROP_RECHECK = 15; // seconds, DROP_RECHECK in pinnwire_dashboard.py

const dropTimeFmt = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function AlertsPage({ alerts, threshold, setThreshold, notify, setNotify, edgeOnly, setEdgeOnly, stream, onClear, onOpen }) {
  const [sportFilter, setSportFilter] = useState("all");
  const shown = alerts.filter((a) => (sportFilter === "all" || a.sport === sportFilter) && (!edgeOnly || a.mxEv > 0));
  return (
    <div className="alerts-page">
      <div className="filters">
        <label className="auto" title="Prikazuju se samo padovi Pinnacle kvote od najmanje ovoliko procenata">
          Minimalni pad
          <select value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}>
            {DROP_LEVELS.map((p) => <option key={p} value={p}>≥ {p}%</option>)}
          </select>
        </label>
        <div className="segmented">
          {[["all", "Svi"], ["football", "Fudbal"], ["basketball", "Košarka"], ["tennis", "Tenis"], ["hockey", "Hokej"], ["mma", "MMA"]].map(([key, label]) => (
            <button key={key} type="button" className={sportFilter === key ? "active" : ""} onClick={() => setSportFilter(key)}>
              {label}
            </button>
          ))}
        </div>
        <label className="auto" title="Skočna kartica i zvuk kad stigne novi pad">
          <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
          Obaveštenja i zvuk
        </label>
        <label className="auto" title="Prikaži i javi samo padove gde je MerkurXtip kvota iznad nove Pinnacle fer kvote">
          <input type="checkbox" checked={edgeOnly} onChange={(e) => setEdgeOnly(e.target.checked)} />
          Samo gde Merkur kasni
        </label>
        <button type="button" className="button ghost" onClick={onClear} disabled={!alerts.length}>Obriši listu</button>
      </div>
      {stream && !stream.connected && (
        <p className="state">Drop stream nije povezan{stream.error ? `: ${stream.error}` : ""}. Ponovo se povezuje…</p>
      )}
      {!shown.length ? (
        <p className="state">
          Nema padova od {threshold}% ili više{edgeOnly ? " sa Merkur prednošću" : ""}. Padovi stižu uživo preko PinnWire
          streama (posle {DROP_RECHECK} s provere da kvota nije vraćena) i čuvaju se dok je stranica otvorena.
        </p>
      ) : (
        <div className="board-scroll">
          <table className="board alerts-table">
            <thead>
              <tr><th>Vreme</th><th>Meč</th><th>Tržište</th><th>Pinnacle</th><th>Pad</th><th>Fer</th><th>Merkur</th><th>Prednost</th></tr>
            </thead>
            <tbody>
              {shown.map((a) => (
                <tr key={a.id} className="match-row" onClick={() => onOpen(a)}>
                  <td>{dropTimeFmt.format(new Date(a.at))}</td>
                  <td className="col-match">
                    <b>{a.match}</b>
                    <span className="row-league">{a.league} · {fmtKickoffShort(new Date(a.starts))}</span>
                  </td>
                  <td>{a.market}{a.line} <b>{a.side}</b></td>
                  <td>{fmtOdds(a.from)} → <b>{fmtOdds(a.to)}</b></td>
                  <td className="drop-pct">−{a.pct.toFixed(1)}%</td>
                  <td>{a.nvp ? fmtOdds(a.nvp) : "—"}</td>
                  <td>{a.mx != null ? <b>{fmtOdds(a.mx)}</b> : "—"}</td>
                  <td>{a.mxEv != null ? <span className={`ev-chip ${evClass(a.mxEv)}`}>{fmtEv(a.mxEv)}</span> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

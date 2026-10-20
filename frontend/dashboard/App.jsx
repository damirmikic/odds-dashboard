import { useCallback, useEffect, useMemo, useState } from "react";

const LOCALE = "sr-Latn-RS";
const timeFmt = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" });
const clockFmt = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dayFmt = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" });
const AUTO_OPTIONS = [0, 2, 5, 15, 30];
const DAY_FILTERS = [
  ["all", "Sve"],
  ["today", "Danas"],
  ["tomorrow", "Sutra"],
  ["week", "7 dana"],
];
const ML_SIDES = [["home", "1"], ["draw", "X"], ["away", "2"]];

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const result = await response.json().catch((error) => {
    if (error.name === "AbortError" || response.ok) throw error;
    return {};
  });
  if (!response.ok) throw new Error(result.error || `Zahtev nije uspeo (${response.status})`);
  // set by the service worker when it answers offline from its copy of the last good response
  const cachedAt = response.headers.get("X-PB-Cache");
  if (cachedAt && result && typeof result === "object") result.__cachedAt = cachedAt;
  return result;
}

// PWA install prompt (Chrome/Edge) and connectivity state.
function usePwa() {
  const [installEvent, setInstallEvent] = useState(null);
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const onPrompt = (event) => {
      event.preventDefault();
      setInstallEvent(event);
    };
    const onInstalled = () => setInstallEvent(null);
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);
  const install = useCallback(async () => {
    if (!installEvent) return;
    installEvent.prompt();
    await installEvent.userChoice.catch(() => null);
    setInstallEvent(null);
  }, [installEvent]);
  return { canInstall: !!installEvent, install, online };
}

function readStored(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value == null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

function writeStored(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable */
  }
}

function dayKey(date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function dayLabel(date) {
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  if (dayKey(date) === dayKey(today)) return "Danas";
  if (dayKey(date) === dayKey(tomorrow)) return "Sutra";
  const label = dayFmt.format(date);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function inDayFilter(date, filter) {
  if (filter === "all") return true;
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const days = (date - start) / 86400000;
  if (filter === "today") return days < 1;
  if (filter === "tomorrow") return days >= 1 && days < 2;
  return days < 7;
}

// Pinnacle quotes up to 3 decimals (1.578); show them as given, at least 2 decimals.
function fmtOdds(value) {
  if (!value) return "—";
  const fixed = Number(value).toFixed(3);
  return fixed.endsWith("0") ? fixed.slice(0, -1) : fixed;
}

function CompBadge({ competition }) {
  return <i className={`comp-badge ${competition.key}`} aria-hidden="true">{competition.code}</i>;
}

function fmtLine(line, signed) {
  if (line == null) return "—";
  if (!signed) return String(line);
  if (line === 0) return "0";
  return line > 0 ? `+${line}` : `−${Math.abs(line)}`;
}

// Handicap/total line label; AH 0 is MerkurXtip "X vraća ulog" (draw no bet).
function marketLine(group, line) {
  if (line == null) return "";
  if (group === "Hendikep" && line === 0) return "0 · X vraća ulog";
  return fmtLine(line, group === "Hendikep");
}

const DERIVED_HINT =
  "Izvedeno: MerkurXtip nema ovu liniju kao dvosmernu igru. Kvota je iz 1X2, dvostruke šanse ili evropskog hendikepa, pa nema marže.";

function fmtMargins(mx, pin) {
  const fmt = (value) => (value != null ? `${value.toFixed(1)}%` : "—");
  return `${fmt(mx)} / ${fmt(pin)}`;
}

function DerivedTag() {
  return <i className="derived-tag" title={DERIVED_HINT}>izv.</i>;
}

function fmtPct(value, digits = 1) {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function movement(current, previous) {
  if (!current || !previous || current === previous) return "";
  return current > previous ? "up" : "down";
}

function Price({ odds, fair, prev, open, compact }) {
  const move = movement(odds, prev);
  const title = [
    fair ? `Fer: ${fmtOdds(fair)}` : null,
    prev ? `Prethodna: ${fmtOdds(prev)}` : null,
    open ? `Otvaranje: ${fmtOdds(open)}` : null,
  ].filter(Boolean).join(" · ");
  return (
    <span className={`price ${move}`} title={title}>
      <span className="price-odds">
        {fmtOdds(odds)}
        {move && <i className="arrow" aria-label={move === "up" ? "raste" : "pada"}>{move === "up" ? "▲" : "▼"}</i>}
      </span>
      {!compact && <span className="price-fair">{fmtOdds(fair)}</span>}
    </span>
  );
}

function OpenDelta({ match }) {
  if (!match.open || !match.ml) return <span className="muted">—</span>;
  // Biggest relative move of the home or away price since we first saw the match.
  const moves = ["home", "away"].map((side) => {
    const open = match.open[side];
    const now = match.ml[side]?.odds;
    return open && now ? { side, pct: (now - open) / open } : null;
  }).filter(Boolean);
  if (!moves.length) return <span className="muted">—</span>;
  const top = moves.reduce((a, b) => (Math.abs(b.pct) > Math.abs(a.pct) ? b : a));
  if (Math.abs(top.pct) < 0.005) return <span className="muted">0%</span>;
  const shortening = top.pct < 0;
  return (
    <span className={`delta ${shortening ? "short" : "drift"}`} title="Najveća promena kvote 1 ili 2 od otvaranja">
      {top.side === "home" ? "1" : "2"} {shortening ? "▼" : "▲"} {Math.abs(top.pct * 100).toFixed(1)}%
    </span>
  );
}

function MatchRow({ match, selected, fresh, onSelect, showLeague, competition }) {
  const kickoff = new Date(match.starts);
  return (
    <tr className={`match-row${selected ? " selected" : ""}${fresh ? " fresh" : ""}`} onClick={() => onSelect(match.id)}>
      <td className="col-time">
        <span className="kickoff">{timeFmt.format(kickoff)}</span>
      </td>
      <td className="col-match">
        <button type="button" className="match-name" aria-pressed={selected}>
          <span>{match.home}</span>
          <span>{match.away}</span>
        </button>
        {showLeague && competition && <span className="row-league"><CompBadge competition={competition} /> {competition.name}</span>}
      </td>
      {ML_SIDES.map(([side]) => (
        <td className="col-price" key={side}>
          <Price
            odds={match.ml[side]?.odds}
            fair={match.ml[side]?.fair}
            prev={match.prev?.[side]}
            open={match.open?.[side]}
          />
        </td>
      ))}
      <td className="col-margin">{match.margin != null ? `${match.margin.toFixed(1)}%` : "—"}</td>
      <td className="col-line">{match.ah ? fmtLine(match.ah.line, true) : "—"}</td>
      <td className="col-price">{match.ah ? <Price odds={match.ah.odds.home} fair={match.ah.fair.home} /> : "—"}</td>
      <td className="col-price">{match.ah ? <Price odds={match.ah.odds.away} fair={match.ah.fair.away} /> : "—"}</td>
      <td className="col-line">{match.ou ? fmtLine(match.ou.line) : "—"}</td>
      <td className="col-price">{match.ou ? <Price odds={match.ou.odds.over} fair={match.ou.fair.over} /> : "—"}</td>
      <td className="col-price">{match.ou ? <Price odds={match.ou.odds.under} fair={match.ou.fair.under} /> : "—"}</td>
      <td className="col-delta"><OpenDelta match={match} /></td>
    </tr>
  );
}

function BoardTable({ groups, competitions, selectedId, fetchedAt, onSelect, showLeague }) {
  const byId = useMemo(() => new Map(competitions.map((c) => [c.id, c])), [competitions]);
  return (
    <div className="board-scroll">
      <table className="board">
        <thead>
          <tr className="board-head-groups">
            <th colSpan={2} />
            <th colSpan={3}>1X2 <small>kvota / fer</small></th>
            <th />
            <th colSpan={3}>Azijski hendikep</th>
            <th colSpan={3}>Golovi</th>
            <th />
          </tr>
          <tr>
            <th className="col-time">Vreme</th>
            <th className="col-match">Meč</th>
            <th className="col-price">1</th>
            <th className="col-price">X</th>
            <th className="col-price">2</th>
            <th className="col-margin">Marža</th>
            <th className="col-line">Linija</th>
            <th className="col-price">Dom.</th>
            <th className="col-price">Gost</th>
            <th className="col-line">Linija</th>
            <th className="col-price">Više</th>
            <th className="col-price">Manje</th>
            <th className="col-delta">Od otv.</th>
          </tr>
        </thead>
        {groups.map((group) => (
          <tbody key={group.key}>
            <tr className="group-row">
              <th colSpan={13}>
                {group.title}
                <span>{group.matches.length}</span>
              </th>
            </tr>
            {group.matches.map((match) => (
              <MatchRow
                key={match.id}
                match={match}
                competition={byId.get(match.leagueId)}
                showLeague={showLeague}
                selected={String(match.id) === selectedId}
                fresh={!!fetchedAt && match.changedAt === fetchedAt}
                onSelect={(id) => onSelect(String(id))}
              />
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

// ev = MerkurXtip odds / Pinnacle fair odds - 1; above zero the Merkur price beats the fair price.
function fmtEv(ev) {
  if (ev == null) return "—";
  const pct = ev * 100;
  return `${pct > 0 ? "+" : pct < 0 ? "−" : ""}${Math.abs(pct).toFixed(1)}%`;
}

function evClass(ev) {
  if (ev == null) return "";
  if (ev >= 0) return "edge-pos";
  if (ev >= -0.02) return "edge-near";
  return "edge-neg";
}

function KickoffWarning({ diff }) {
  if (!diff) return null;
  return (
    <span className="kickoff-warn" title="Vreme početka u MerkurXtip ponudi se razlikuje od Pinnacle-a">
      ⏱ MX {diff > 0 ? "+" : "−"}{Math.abs(diff)} min
    </span>
  );
}

function fmt2(value) {
  return value ? Number(value).toFixed(2) : "—";
}

function fmtKickoffShort(date) {
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}. ${timeFmt.format(date)}`;
}

function fmtLimit(value) {
  if (!value) return null;
  if (value >= 1e6) return `€${+(value / 1e6).toFixed(1)}M`;
  if (value >= 1000) return `€${Math.round(value / 1000)}K`;
  return `€${Math.round(value)}`;
}

// Favourite = outcome with the shortest Pinnacle fair odds.
function favorite(match) {
  let best = null;
  for (const [side, label] of ML_SIDES) {
    const fair = match.ml?.[side]?.fair;
    if (fair && (!best || fair < best.fair)) best = { side, label, fair };
  }
  return best;
}

function pinnacleClass(odds, prev) {
  const move = movement(odds, prev);
  return move === "up" ? "pin-up" : move === "down" ? "pin-down" : "";
}

// MerkurXtip cell: red = at/above Pinnacle fair, amber = above the Pinnacle price, purple = MX price changed.
function merkurClass(odds, pinnacle, ev, prev) {
  const classes = [];
  if (ev != null && ev >= 0) classes.push("mx-fair");
  else if (odds && pinnacle && odds > pinnacle) classes.push("mx-above");
  if (prev && odds && prev !== odds) classes.push("mx-moved");
  return classes.join(" ");
}

function merkurTitle(odds, pinnacle, fair, ev, prev) {
  return [
    `Pinnacle ${fmtOdds(pinnacle)}`,
    `fer ${fmtOdds(fair)}`,
    `razlika ${fmtEv(ev)}`,
    prev && prev !== odds ? `prethodna MX ${fmtOdds(prev)}` : null,
  ].filter(Boolean).join(" · ");
}

function CompareRow({ match, tolerance, selected, onSelect, pinStamp, mxStamp }) {
  const x = match.merkur;
  // colour only moves from the latest refresh
  const pinPrev = pinStamp && match.changedAt === pinStamp ? match.prev : null;
  const mxPrev = mxStamp && x?.changedAt === mxStamp ? x.prev : null;
  const kickoff = new Date(match.starts);
  const fav = favorite(match);
  const limit = fmtLimit(match.ah?.max || match.ou?.max);
  return (
    <tr className={`mc-row${selected ? " selected" : ""}`} onClick={() => onSelect(String(match.id))}>
      <td className="mc-match">
        <div className="mc-when">
          {fmtKickoffShort(kickoff)}
          {x && <KickoffWarning diff={x.kickoffDiff} />}
        </div>
        {limit && <div className="mc-limit" title="Pinnacle limit glavne linije (hendikep, inače golovi)">{limit}</div>}
        <div className="mc-teams">
          <b>{match.home}</b> <span>vs</span> <b>{match.away}</b>
        </div>
        <div className="mc-league">{match.leagueName}</div>
      </td>
      <td className="mc-max" title={fav ? `Fer ${fmtOdds(fav.fair)} × (1 + ${tolerance}%)` : undefined}>
        {fav ? (
          <>
            <b>{fmt2(fav.fair * (1 + tolerance / 100))}</b>
            <small>{fav.label}</small>
          </>
        ) : "—"}
      </td>
      {ML_SIDES.map(([side], i) => (
        <td key={`f${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>{fmt2(match.ml[side]?.fair)}</td>
      ))}
      {ML_SIDES.map(([side], i) => (
        <td key={`p${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>
          <span
            className={`mc-cell ${pinnacleClass(match.ml[side]?.odds, pinPrev?.[side])}`}
            title={match.prev?.[side] ? `Prethodna: ${fmtOdds(match.prev[side])}` : undefined}
          >
            {fmt2(match.ml[side]?.odds)}
          </span>
        </td>
      ))}
      {ML_SIDES.map(([side], i) => {
        const odds = x?.ml?.[side]?.odds;
        const ev = x?.ml?.[side]?.ev;
        const pin = match.ml[side]?.odds;
        const prev = mxPrev?.[side];
        return (
          <td key={`m${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>
            {odds ? (
              <span className={`mc-cell ${merkurClass(odds, pin, ev, prev)}`} title={merkurTitle(odds, pin, match.ml[side]?.fair, ev, prev)}>
                {fmt2(odds)}
              </span>
            ) : (
              <span className="muted" title={x ? "MerkurXtip nema 1X2" : "Nije u ponudi MerkurXtip"}>—</span>
            )}
          </td>
        );
      })}
      <GoalCells goals={match.goals} pinStamp={pinStamp} mxStamp={mxStamp} />
    </tr>
  );
}

const OU = [["over", "V"], ["under", "M"]];

function GoalCells({ goals, pinStamp, mxStamp }) {
  if (!goals) {
    return <td className="mc-line mc-group-strong" colSpan={7}><span className="muted">—</span></td>;
  }
  const pinPrev = pinStamp && goals.pinChangedAt === pinStamp ? goals.pinPrev : null;
  const mxPrev = mxStamp && goals.mxChangedAt === mxStamp ? goals.mxPrev : null;
  return (
    <>
      <td className="mc-line mc-group-strong" title={goals.merkur ? "Linija koju imaju obe kuće, najbliža Pinnacle glavnoj" : "Pinnacle glavna linija"}>
        {goals.line}
      </td>
      {OU.map(([side], i) => (
        <td key={`gf${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>{fmt2(goals.fair[side])}</td>
      ))}
      {OU.map(([side], i) => (
        <td key={`gp${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>
          <span
            className={`mc-cell ${pinnacleClass(goals.pinnacle[side], pinPrev?.[side])}`}
            title={pinPrev?.[side] ? `Prethodna: ${fmtOdds(pinPrev[side])}` : undefined}
          >
            {fmt2(goals.pinnacle[side])}
          </span>
        </td>
      ))}
      {OU.map(([side], i) => {
        const odds = goals.merkur?.[side];
        const ev = goals.ev?.[side];
        const pin = goals.pinnacle[side];
        const prev = mxPrev?.[side];
        return (
          <td key={`gm${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>
            {odds ? (
              <span className={`mc-cell ${merkurClass(odds, pin, ev, prev)}`} title={merkurTitle(odds, pin, goals.fair[side], ev, prev)}>
                {fmt2(odds)}
              </span>
            ) : (
              <span className="muted" title="MerkurXtip nema ovu liniju">—</span>
            )}
          </td>
        );
      })}
    </>
  );
}

function CompareTable({ matches, tolerance, selectedId, onSelect, pinStamp, mxStamp }) {
  return (
    <div className="board-scroll mc-wrap">
      <table className="mc-board">
        <thead>
          <tr>
            <th rowSpan={2} className="mc-match">Meč</th>
            <th className="mc-max">Max kvota</th>
            <th colSpan={3} className="mc-group">Pinnacle no-vig</th>
            <th colSpan={3} className="mc-group">Pinnacle</th>
            <th colSpan={3} className="mc-group">MerkurXtip</th>
            <th className="mc-line mc-group-strong">Golovi</th>
            <th colSpan={2} className="mc-group">No-vig</th>
            <th colSpan={2} className="mc-group">Pinnacle</th>
            <th colSpan={2} className="mc-group">MerkurXtip</th>
          </tr>
          <tr className="mc-sub">
            <th className="mc-max">fav <small>+{tolerance}%</small></th>
            {["f", "p", "m"].map((group) =>
              ML_SIDES.map(([side, label], i) => (
                <th key={`${group}${side}`} className={i === 0 ? "mc-group" : ""}>{label}</th>
              )),
            )}
            <th className="mc-line mc-group-strong">linija</th>
            {["gf", "gp", "gm"].map((group) =>
              OU.map(([side, label], i) => (
                <th key={`${group}${side}`} className={i === 0 ? "mc-group" : ""} title={side === "over" ? "Više" : "Manje"}>
                  {label}
                </th>
              )),
            )}
          </tr>
        </thead>
        <tbody>
          {matches.map((match) => (
            <CompareRow
              key={match.id}
              match={match}
              tolerance={tolerance}
              selected={String(match.id) === selectedId}
              onSelect={onSelect}
              pinStamp={pinStamp}
              mxStamp={mxStamp}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

const VALUE_LEVELS = [
  ["all", "MX > Pinnacle"],
  ["fair", "MX ≥ fer"],
  ["0.02", "MX ≥ fer +2%"],
];
const VALUE_GROUPS = [
  ["all", "Sva tržišta"],
  ["1X2", "1X2"],
  ["Ukupno golova", "Golovi"],
  ["Hendikep", "Hendikep"],
  ["team", "Golovi timova"],
];

function valuePasses(value, level, group) {
  if (level === "fair" && value.ev < 0) return false;
  if (level !== "all" && level !== "fair" && value.ev < Number(level)) return false;
  if (group === "team") return value.group.startsWith("Golovi ");
  return group === "all" || value.group === group;
}

function ValueTable({ values, matchesById, competitions, selectedId, onSelect }) {
  const byComp = useMemo(() => new Map(competitions.map((c) => [c.id, c])), [competitions]);
  return (
    <div className="board-scroll mc-wrap">
      <table className="mc-board value-board">
        <thead>
          <tr>
            <th className="mc-match">Meč</th>
            <th>Tržište</th>
            <th>Ishod</th>
            <th className="mc-group">MX</th>
            <th>PIN</th>
            <th>Fer</th>
            <th className="mc-group" title="MerkurXtip kvota / Pinnacle kvota − 1">MX vs PIN</th>
            <th title="MerkurXtip kvota / Pinnacle fer kvota − 1">MX vs fer</th>
            <th className="mc-group" title="Marža tržišta MerkurXtip / Pinnacle">Marža MX / PIN</th>
          </tr>
        </thead>
        <tbody>
          {values.map((v) => {
            const match = matchesById.get(v.matchId);
            const comp = byComp.get(match.leagueId);
            const id = String(v.matchId);
            return (
              <tr
                key={`${v.matchId}-${v.period}-${v.group}-${v.line}-${v.key}`}
                className={`mc-row${id === selectedId ? " selected" : ""}`}
                onClick={() => onSelect(id)}
              >
                <td className="mc-match">
                  <div className="mc-when">
                    {fmtKickoffShort(new Date(match.starts))}
                    {comp && <CompBadge competition={comp} />}
                    <KickoffWarning diff={match.merkur?.kickoffDiff} />
                  </div>
                  <div className="mc-teams">
                    <b>{match.home}</b> <span>vs</span> <b>{match.away}</b>
                  </div>
                </td>
                <td className="value-market">
                  {v.group}
                  {v.line != null && <b> {marketLine(v.group, v.line)}</b>}
                  {v.derived && <DerivedTag />}
                  {v.period === "ht" && <small>1. poluvreme</small>}
                </td>
                <td className="value-side">{v.label}</td>
                <td className="mc-odds mc-group">
                  <span className={`mc-cell ${v.ev >= 0 ? "mx-fair" : "mx-above"}`}>{fmt2(v.merkur)}</span>
                </td>
                <td className="mc-odds">{fmtOdds(v.pinnacle)}</td>
                <td className="mc-odds muted">{fmtOdds(v.fair)}</td>
                <td className="mc-odds mc-group value-pct">{fmtEv(v.overPinnacle)}</td>
                <td className="mc-odds">
                  <span className={`ev-chip ${evClass(v.ev)}`}>{fmtEv(v.ev)}</span>
                </td>
                <td className="mc-group muted value-margin">
                  {fmtMargins(v.merkurMargin, v.pinnacleMargin)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MerkurComparison({ merkur, periodKey, home, away }) {
  if (!merkur) {
    return <p className="state">Meč nije u ponudi MerkurXtip (ili nije uparen).</p>;
  }
  const rows = merkur.periods[periodKey] || [];
  const sideLabel = (group, label) => {
    if (group === "Hendikep") return label === "1" ? home : away;
    return label;
  };
  return (
    <section className="detail-card mx-card">
      <h3>
        MerkurXtip vs Pinnacle fer
        <small>šifra {merkur.code} · {clockFmt.format(new Date(merkur.fetchedAt))}</small>
      </h3>
      <p className="mx-names">
        {merkur.home} – {merkur.away}
        <KickoffWarning diff={merkur.kickoffDiff} />
      </p>
      {merkur.error && <p className="state error">{merkur.error} Prikazane su kvote iz liste ponude.</p>}
      {!rows.length && <p className="muted">Nema tržišta koja postoje kod obe kuće za ovaj period.</p>}
      {!!rows.length && (
        <table className="lines mx-table">
          <thead>
            <tr>
              <th>Tržište</th>
              <th>Ishod</th>
              <th>MX</th>
              <th>Fer</th>
              <th>Razlika</th>
            </tr>
          </thead>
          {rows.map((row) => (
            <tbody key={`${row.group}-${row.line}`}>
              {row.outcomes.map((o, index) => (
                <tr key={o.key} className={index === 0 ? "mx-first" : ""}>
                  {index === 0 && (
                    <th rowSpan={row.outcomes.length} className="mx-market">
                      {row.group}
                      {row.line != null && <span>{marketLine(row.group, row.line)}{row.derived && <DerivedTag />}</span>}
                      <small title="Marža MerkurXtip / Pinnacle">
                        {fmtMargins(row.merkurMargin, row.pinnacleMargin)}
                      </small>
                    </th>
                  )}
                  <td className="mx-side">{sideLabel(row.group, o.label)}</td>
                  <td><b>{fmtOdds(o.merkur)}</b></td>
                  <td className="muted">{fmtOdds(o.fair)}</td>
                  <td><span className={`ev-chip ${evClass(o.ev)}`}>{fmtEv(o.ev)}</span></td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      )}
    </section>
  );
}

function ProbabilityBar({ ml, home, away }) {
  return (
    <div className="prob-bar" aria-label="Fer verovatnoće">
      {ML_SIDES.map(([side, label]) => (
        <div key={side} className={`prob-seg ${side}`} style={{ flexGrow: ml[side].prob }}>
          <span>{side === "home" ? home : side === "away" ? away : "Nerešeno"}</span>
          <strong>{fmtPct(ml[side].prob)}</strong>
          <small>{label}</small>
        </div>
      ))}
    </div>
  );
}

function LinesTable({ title, rows, sides, signed, lineLabel }) {
  if (!rows?.length) return null;
  return (
    <section className="detail-card">
      <h3>{title}</h3>
      <table className="lines">
        <thead>
          <tr>
            <th>{lineLabel}</th>
            {sides.map(([key, label]) => <th key={key}>{label}</th>)}
            <th>Marža</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.line} className={row.main ? "main" : ""}>
              <th>
                {fmtLine(row.line, signed)}
                {row.main && <span className="main-tag">GL</span>}
              </th>
              {sides.map(([key]) => (
                <td key={key}><Price odds={row.odds[key]} fair={row.fair[key]} /></td>
              ))}
              <td className="muted">{row.margin != null ? `${row.margin.toFixed(1)}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DetailPanel({ matchId, boardMatch, competition, onClose, onCalls }) {
  const [detail, setDetail] = useState(null);
  const [periodKey, setPeriodKey] = useState("ft");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    requestJson(`/api/match/${matchId}${refreshTick ? "?refresh=1" : ""}`, { signal: controller.signal })
      .then((data) => {
        setDetail(data);
        onCalls(data.callsToday);
      })
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // boardMatch?.changedAt: re-read the cached snapshot when a board refresh changed this match
  }, [matchId, refreshTick, boardMatch?.changedAt, onCalls]);

  const match = detail?.match || boardMatch;
  const period = detail?.periods.find((p) => p.key === periodKey);

  return (
    <aside className="detail" aria-live="polite">
      <header className="detail-head">
        <div>
          <span className="eyebrow">{competition ? <><CompBadge competition={competition} /> {competition.name}</> : "Fudbal"}</span>
          <h2>{match?.home} <span>–</span> {match?.away}</h2>
          {match?.starts && <p>{dayLabel(new Date(match.starts))}, {timeFmt.format(new Date(match.starts))}</p>}
        </div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Zatvori detalje">✕</button>
      </header>

      <div className="detail-toolbar">
        <div className="segmented" role="tablist">
          {(detail?.periods || [{ key: "ft", label: "Ceo meč" }, { key: "ht", label: "1. poluvreme" }]).map((p) => (
            <button
              key={p.key}
              type="button"
              role="tab"
              aria-selected={periodKey === p.key}
              className={periodKey === p.key ? "active" : ""}
              onClick={() => setPeriodKey(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="button ghost small"
          onClick={() => setRefreshTick((t) => t + 1)}
          disabled={loading}
          title="Svež zahtev samo za ovaj meč (1 API zahtev)"
        >
          ↻ {loading ? "Učitavam…" : "Osveži meč"}
        </button>
      </div>

      {error && <p className="state error" role="alert">{error}</p>}
      {!detail && loading && <p className="state">Učitavam kvote…</p>}

      {detail && <MerkurComparison merkur={detail.merkur} periodKey={periodKey} home={match.home} away={match.away} />}

      {period && !period.ml && <p className="state">Pinnacle nema ponudu za ovaj period.</p>}
      {period?.ml && (
        <>
          <section className="detail-card">
            <h3>1X2 <small>marža {period.margin != null ? `${period.margin.toFixed(2)}%` : "—"}</small></h3>
            <ProbabilityBar ml={period.ml} home={match.home} away={match.away} />
            <table className="lines ml-table">
              <thead>
                <tr>
                  <th />
                  <th>Pinnacle</th>
                  <th>Fer kvota</th>
                  <th>Fer %</th>
                  {periodKey === "ft" && <th>Otvaranje</th>}
                </tr>
              </thead>
              <tbody>
                {ML_SIDES.map(([side, label]) => (
                  <tr key={side}>
                    <th>{label}</th>
                    <td>
                      <Price odds={period.ml[side].odds} prev={periodKey === "ft" ? match.prev?.[side] : null} compact />
                    </td>
                    <td className="fair">{fmtOdds(period.ml[side].fair)}</td>
                    <td>{fmtPct(period.ml[side].prob)}</td>
                    {periodKey === "ft" && <td className="muted">{fmtOdds(match.open?.[side])}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <LinesTable
            title="Azijski hendikep"
            lineLabel="Domaćin"
            rows={period.spreads}
            sides={[["home", match.home], ["away", match.away]]}
            signed
          />
          <LinesTable title="Ukupno golova" lineLabel="Golovi" rows={period.totals} sides={[["over", "Više"], ["under", "Manje"]]} />
          {["home", "away"].map((side) => (
            <LinesTable
              key={side}
              title={`Golovi tima · ${side === "home" ? match.home : match.away}`}
              lineLabel="Golovi"
              rows={period.teamTotals?.[side]}
              sides={[["over", "Više"], ["under", "Manje"]]}
            />
          ))}
        </>
      )}

      {detail && (
        <p className="detail-foot">
          Ažurirano {clockFmt.format(new Date(detail.fetchedAt))}. Fer kvote: power devig. GL = glavna linija.
        </p>
      )}
    </aside>
  );
}

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

export default function App() {
  const [apiKeySet, setApiKeySet] = useState(null);
  const [board, setBoard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [callsToday, setCallsToday] = useState(0);
  const [competition, setCompetition] = useState(() => readStored("pb.competition", "all"));
  const [dayFilter, setDayFilter] = useState(() => readStored("pb.day", "all"));
  const [query, setQuery] = useState("");
  const [autoMinutes, setAutoMinutes] = useState(() => readStored("pb.auto", 0));
  const [view, setView] = useState(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("view");
    return ["compare", "pinnacle", "value"].includes(fromUrl) ? fromUrl : readStored("pb.view", "compare");
  });
  const [edgeFilter, setEdgeFilter] = useState(() => readStored("pb.edge", "all"));
  const [tolerance, setTolerance] = useState(() => readStored("pb.tolerance", 1));
  const [valueLevel, setValueLevel] = useState(() => readStored("pb.valueLevel2", "fair"));
  const [valueLeague, setValueLeague] = useState("all");
  const [valueGroup, setValueGroup] = useState(() => readStored("pb.valueGroup", "all"));
  const [selectedId, setSelectedId] = useState(() => window.location.hash.replace(/\D/g, ""));
  const pwa = usePwa();

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

  useEffect(() => {
    requestJson("/api/status")
      .then((status) => {
        setApiKeySet(status.apiKeySet);
        setCallsToday(status.callsToday);
        if (status.apiKeySet) loadBoard();
      })
      .catch((err) => setError(err.message));
  }, [loadBoard]);

  useEffect(() => {
    if (!autoMinutes || !apiKeySet) return undefined;
    const timer = setInterval(() => loadBoard("refresh"), autoMinutes * 60000);
    return () => clearInterval(timer);
  }, [autoMinutes, apiKeySet, loadBoard]);

  useEffect(() => writeStored("pb.competition", competition), [competition]);
  useEffect(() => writeStored("pb.day", dayFilter), [dayFilter]);
  useEffect(() => writeStored("pb.auto", autoMinutes), [autoMinutes]);
  useEffect(() => writeStored("pb.view", view), [view]);
  useEffect(() => writeStored("pb.edge", edgeFilter), [edgeFilter]);
  useEffect(() => writeStored("pb.tolerance", tolerance), [tolerance]);
  useEffect(() => writeStored("pb.valueLevel2", valueLevel), [valueLevel]);
  useEffect(() => writeStored("pb.valueGroup", valueGroup), [valueGroup]);

  const competitions = board?.competitions || [];
  const compById = useMemo(() => new Map(competitions.map((c) => [c.id, c])), [competitions]);

  const filtered = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return (board?.matches || []).filter((m) => {
      if (competition !== "all" && compById.get(m.leagueId)?.key !== competition) return false;
      if (!inDayFilter(new Date(m.starts), dayFilter)) return false;
      if (view === "compare" && edgeFilter !== "all") {
        if (edgeFilter === "missing") {
          if (m.merkur) return false;
        } else if (!m.merkur || (edgeFilter !== "paired" && (m.merkur.best?.ev ?? -1) < Number(edgeFilter))) {
          return false;
        }
      }
      return !q || `${m.home} ${m.away} ${m.merkur?.home || ""} ${m.merkur?.away || ""}`.toLocaleLowerCase().includes(q);
    });
  }, [board, competition, dayFilter, query, compById, view, edgeFilter]);

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
    () => valueList.filter((v) => valuePasses(v, valueLevel, valueGroup)),
    [valueList, valueLevel, valueGroup],
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

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">P</span>
          <div>
            <strong>Pinnacle Board</strong>
            <small>Top 5 liga + UEFA · Pinnacle vs MerkurXtip</small>
          </div>
        </div>

        <div className="status">
          {board?.fetchedAt && (
            <span title={board.mode === "delta" ? "Delta osvežavanje: preuzete samo promene" : "Pun snapshot"}>
              <i className={`dot${loading ? " busy" : ""}`} />
              {clockFmt.format(new Date(board.fetchedAt))}
              <em>{board.mode === "delta" ? `Δ ${board.changed} promena` : "pun snapshot"}</em>
            </span>
          )}
          {board?.merkur && (
            <span
              className={board.merkur.error ? "status-error" : ""}
              title={board.merkur.error || "MerkurXtip ponuda: upareni mečevi / mečevi ovih takmičenja u ponudi"}
            >
              MX {board.merkur.fetchedAt ? clockFmt.format(new Date(board.merkur.fetchedAt)) : "—"}
              <em>upareno {board.merkur.paired}/{board.merkur.offered}</em>
              {board.merkur.error && <em>· greška</em>}
            </span>
          )}
          <span title="Broj PinnWire zahteva danas (trial: 100/dan, 20/min)">API danas: <b>{callsToday}</b></span>
        </div>

        <div className="actions">
          {pwa.canInstall && (
            <button type="button" className="button ghost" onClick={pwa.install} title="Instaliraj Pinnacle Board kao aplikaciju">
              ⤓ Instaliraj
            </button>
          )}
          <label className="auto">
            Auto
            <select value={autoMinutes} onChange={(e) => setAutoMinutes(Number(e.target.value))}>
              {AUTO_OPTIONS.map((m) => <option key={m} value={m}>{m ? `${m} min` : "isklj."}</option>)}
            </select>
          </label>
          <button type="button" className="button primary" onClick={() => loadBoard("refresh")} disabled={!apiKeySet || loading}>
            ↻ Osveži
          </button>
          <button
            type="button"
            className="button ghost"
            onClick={() => loadBoard("full")}
            disabled={!apiKeySet || loading}
            title="Preuzmi kompletan snapshot umesto samo promena"
          >
            Pun reload
          </button>
        </div>
      </header>

      {(!pwa.online || board?.__cachedAt) && (
        <div className="offline-banner" role="status">
          {!pwa.online ? "Offline." : "Server nije dostupan."}{" "}
          {board?.__cachedAt
            ? `Prikazane su poslednje sačuvane kvote${
                Number.isNaN(new Date(board.__cachedAt).getTime()) ? "" : ` (${clockFmt.format(new Date(board.__cachedAt))})`
              } — nisu žive.`
            : "Kvote se ne mogu osvežiti dok veza ne proradi."}
        </div>
      )}

      {apiKeySet === false && <KeyPanel onSaved={() => { setApiKeySet(true); loadBoard("full"); }} />}

      {apiKeySet && (
        <>
          {view !== "value" && (
          <nav className="tabs" aria-label="Takmičenja">
            <button type="button" className={competition === "all" ? "active" : ""} onClick={() => setCompetition("all")}>
              Sve <span>{totalCount}</span>
            </button>
            {competitions.map((c) => (
              <button
                type="button"
                key={c.key}
                className={competition === c.key ? "active" : ""}
                onClick={() => setCompetition(c.key)}
                disabled={!c.count}
              >
                <CompBadge competition={c} /> {c.name} <span>{c.count}</span>
              </button>
            ))}
          </nav>
          )}
          {view === "value" && (
            <nav className="tabs value-summary" aria-label="Value po takmičenjima">
              <button type="button" className={valueLeague === "all" ? "active" : ""} onClick={() => setValueLeague("all")}>
                Sve lige <span>{levelValues.length}</span>
              </button>
              {competitions.map((c) => {
                const row = valueSummary.get(c.id);
                return (
                  <button
                    type="button"
                    key={c.key}
                    className={valueLeague === String(c.id) ? "active" : ""}
                    onClick={() => setValueLeague((current) => (current === String(c.id) ? "all" : String(c.id)))}
                    disabled={!row}
                    title={row ? `${row.count} ishoda na ${row.matches.size} mečeva, najveća razlika vs fer ${fmtEv(row.best)}` : "Nema ishoda za izabrane filtere"}
                  >
                    <CompBadge competition={c} /> {c.name}
                    <span>{row ? row.count : 0}</span>
                    {row && <em className={evClass(row.best)}>{fmtEv(row.best)}</em>}
                  </button>
                );
              })}
            </nav>
          )}

          <div className="filters">
            <div className="segmented view-switch">
              <button type="button" className={view === "compare" ? "active" : ""} onClick={() => setView("compare")}>
                MerkurXtip vs Pinnacle
              </button>
              <button type="button" className={view === "pinnacle" ? "active" : ""} onClick={() => setView("pinnacle")}>
                Samo Pinnacle
              </button>
              <button
                type="button"
                className={view === "value" ? "active" : ""}
                onClick={() => setView("value")}
                title={`${valueList.length} ishoda gde je MX > Pinnacle, od toga ${fairValueCount} gde je MX ≥ fer`}
              >
                Value <span className="view-count">{fairValueCount}/{valueList.length}</span>
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
            {view === "compare" && (
              <label className="auto" title="Max kvota = Pinnacle fer kvota favorita × (1 + tolerancija)">
                Tolerancija
                <input
                  className="tolerance"
                  type="number"
                  min="-10"
                  max="20"
                  step="0.1"
                  value={tolerance}
                  onChange={(e) => setTolerance(Number(e.target.value) || 0)}
                />
                %
              </label>
            )}
            <div className="segmented">
              {DAY_FILTERS.map(([key, label]) => (
                <button key={key} type="button" className={dayFilter === key ? "active" : ""} onClick={() => setDayFilter(key)}>
                  {label}
                </button>
              ))}
            </div>
            <input
              className="search"
              type="search"
              placeholder="Pretraga timova…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
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
              {board && view !== "value" && !filtered.length && <p className="state">Nema mečeva za izabrani filter.</p>}
              {!!filtered.length && view === "compare" && (
                <CompareTable
                  matches={filtered}
                  tolerance={tolerance}
                  pinStamp={board.fetchedAt}
                  mxStamp={board.merkur?.fetchedAt}
                  selectedId={selectedId}
                  onSelect={(id) => setSelectedId((current) => (current === id ? "" : id))}
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
                  selectedId={selectedId}
                  onSelect={(id) => setSelectedId((current) => (current === id ? "" : id))}
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
        </>
      )}

      <footer>Kvote: Pinnacle preko PinnWire · Kvote se mogu promeniti u svakom trenutku.</footer>
    </div>
  );
}

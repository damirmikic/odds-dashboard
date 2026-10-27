// Value view: filters and the table of outcomes where MerkurXtip beats Pinnacle.
import { useMemo } from "react";
import { evClass, fmt2, fmtEv, fmtKickoffShort, fmtMargins, fmtOdds, marketLine } from "./format.js";
import { CompBadge, DerivedTag, KickoffWarning, ModeledTag, StaleTag } from "./ui.jsx";
import { ChangeTimes } from "./priceHistory.jsx";

export const VALUE_LEVELS = [
  ["all", "MX > Pinnacle"],
  ["fair", "MX ≥ fer"],
  ["0.02", "MX ≥ fer +2%"],
];

export const VALUE_GROUPS = [
  ["all", "Sva tržišta"],
  ["1X2", "1X2"],
  ["Ukupno golova", "Golovi"],
  ["Hendikep", "Hendikep"],
  ["team", "Golovi timova"],
];

export function valuePasses(value, level, group) {
  if (level === "fair" && value.ev < 0) return false;
  if (level !== "all" && level !== "fair" && value.ev < Number(level)) return false;
  if (group === "team") return value.group.startsWith("Golovi ");
  return group === "all" || value.group === group;
}

// Competitions kept by the "samo top lige" switch, per sport (tennis has no fixed list: ATP and WTA tours).
const TOP_LEAGUES = {
  football: new Set(["epl", "laliga", "seriea", "bundesliga", "ligue1", "ucl", "uel", "uecl", "eredivisie", "ligapt",
    "championship", "superlig", "jupiler", "libertadores", "brasileirao", "mls", "gercup", "eflcup", "superligasrb"]),
  basketball: new Set(["nba", "euroleague", "eurocup", "bcl"]),
  hockey: new Set(["nhl", "khl", "liiga", "del", "nla"]),
  mma: new Set(["ufc"]),
};

export function isTopLeague(sport, comp) {
  if (!comp) return false;
  if (sport === "tennis") return comp.badge === "atp" || comp.badge === "wta";
  return (TOP_LEAGUES[sport] || new Set()).has(comp.key);
}

// Range of the difference vs fair price in percent; an empty bound is open.
export function rangePasses(value, min, max) {
  const pct = value.ev * 100;
  return (min === "" || pct >= Number(min)) && (max === "" || pct <= Number(max));
}

export function ValueRange({ min, max, setMin, setMax, topOnly, setTopOnly }) {
  return (
    <>
      <label className="auto" title="Razlika MerkurXtip kvote u odnosu na Pinnacle fer kvotu, u procentima">
        Razlika od
        <input type="number" step="0.5" className="range-input" placeholder="−∞" value={min}
          onChange={(e) => setMin(e.target.value)} />
        do
        <input type="number" step="0.5" className="range-input" placeholder="+∞" value={max}
          onChange={(e) => setMax(e.target.value)} />
        %
      </label>
      <label className="auto" title="Samo najjača takmičenja">
        <input type="checkbox" checked={topOnly} onChange={(e) => setTopOnly(e.target.checked)} />
        samo top lige
      </label>
    </>
  );
}

export function ValueTable({ values, matchesById, competitions, selectedId, onSelect, onOdds }) {
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
            <th className="mc-group" title="Poslednja promena kvote kod MerkurXtip i Pinnacle (podebljano: u poslednjih 15 min)">Promena</th>
          </tr>
        </thead>
        <tbody>
          {values.map((v) => {
            const match = matchesById.get(v.matchId);
            const comp = byComp.get(match.leagueId);
            const id = String(v.matchId);
            const oddsClick = (event) => {
              event.stopPropagation();
              onOdds(id);
            };
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
                  {v.modeled && <ModeledTag />}
                  {v.stale != null && <StaleTag gap={v.stale} />}
                  {v.period && v.period !== "ft" && <small>{v.periodLabel || "1. poluvreme"}</small>}
                </td>
                <td className="value-side">{v.label}</td>
                <td className="mc-odds mc-click mc-group" onClick={oddsClick}>
                  <span className={`mc-cell ${v.ev >= 0 ? "mx-fair" : "mx-above"}`}>{fmt2(v.merkur)}</span>
                </td>
                <td className="mc-odds mc-click" onClick={oddsClick}>{fmtOdds(v.pinnacle)}</td>
                <td className="mc-odds mc-click muted" onClick={oddsClick}>{fmtOdds(v.fair)}</td>
                <td className="mc-odds mc-group value-pct">{fmtEv(v.overPinnacle)}</td>
                <td className="mc-odds">
                  <span className={`ev-chip ${evClass(v.ev)}`}>{fmtEv(v.ev)}</span>
                </td>
                <td className="mc-group muted value-margin">
                  {fmtMargins(v.merkurMargin, v.pinnacleMargin)}
                </td>
                <td className="mc-group value-change"><ChangeTimes value={v} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// One outcome per line market of a match (the largest edge); markets without a line keep every outcome.
export function bestPerMarket(values) {
  const best = new Map();
  const out = [];
  for (const v of values) {
    if (v.line == null) {
      out.push(v);
      continue;
    }
    const key = `${v.matchId}|${v.period}|${v.group}`;
    if (!best.has(key) || v.ev > best.get(key).ev) best.set(key, v);
  }
  return [...out, ...best.values()];
}

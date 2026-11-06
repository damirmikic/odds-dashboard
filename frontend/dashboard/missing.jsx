// "Nedostaju" view: Pinnacle matches MerkurXtip does not offer.
import { useEffect, useMemo, useState } from "react";
import { readStored, writeStored } from "./api.js";
import { fmt2, fmtKickoffShort, fmtLine } from "./format.js";
import { CompBadge, ML_SIDES } from "./ui.jsx";
import { SPORT_VIEWS } from "./sportViews.js";

// Empty "missing" view: say whether nothing is missing at all or only under the current filters.
export function missingEmpty(total, filtered, showAll) {
  if (!total) return "Svi mečevi su u ponudi MerkurXtip.";
  return (
    <>
      Nema nedostajućih mečeva za izabrane filtere (liga, dan, pretraga). Ukupno nedostaje {total}.{" "}
      {filtered && <button type="button" className="button small" onClick={showAll}>Sve lige</button>}
    </>
  );
}

// Untracked leagues whose matches MerkurXtip does offer: everything a new competition entry needs.
export function OtherOffered({ leagues }) {
  if (!leagues?.length) return null;
  return (
    <details className="other-offered">
      <summary>U ponudi MerkurXtip, a ne pratimo ({leagues.length} liga)</summary>
      <ul>
        {leagues.map((o) => (
          <li key={o.leagueId}>
            <b>{o.leagueName}</b> · {o.count} {o.count === 1 ? "meč" : "mečeva"}
            <small> · PinnWire {o.leagueId} · MerkurXtip {o.mxLeague} ({o.mxLeagueId})</small>
          </li>
        ))}
      </ul>
    </details>
  );
}

// Matches Pinnacle prices but MerkurXtip does not offer (or could not be paired by team names).
export function MissingTable({ matches: unsorted, competitions, sport }) {
  const [sortBy, setSortBy] = useState(() => readStored("missingSort", "time"));
  useEffect(() => writeStored("missingSort", sortBy), [sortBy]);
  const matches = useMemo(() => (sortBy === "league"
    ? [...unsorted].sort((a, b) => (a.leagueName || "").localeCompare(b.leagueName || "") || a.starts.localeCompare(b.starts))
    : [...unsorted].sort((a, b) => a.starts.localeCompare(b.starts) || a.home.localeCompare(b.home))), [unsorted, sortBy]);
  const byId = useMemo(() => new Map(competitions.map((c) => [c.id, c])), [competitions]);
  const football = sport === "football";
  const lines = (match) => (football
    ? { ah: match.ah && { line: match.ah.line, home: match.ah.odds.home, away: match.ah.odds.away },
        ou: match.ou && { line: match.ou.line, over: match.ou.odds.over, under: match.ou.odds.under } }
    : { ah: match.spread && { line: match.spread.line, home: match.spread.pinnacle.home, away: match.spread.pinnacle.away },
        ou: match.total && { line: match.total.line, over: match.total.pinnacle.over, under: match.total.pinnacle.under } });
  const sides = football ? ML_SIDES : ML_SIDES.filter(([side]) => side !== "draw");
  return (
    <>
    <div className="missing-sort">
      Sortiraj:{" "}
      <button type="button" className={`button small${sortBy === "time" ? " primary" : " ghost"}`} onClick={() => setSortBy("time")}>Vreme početka</button>{" "}
      <button type="button" className={`button small${sortBy === "league" ? " primary" : " ghost"}`} onClick={() => setSortBy("league")}>Turnir</button>
    </div>
    <div className="board-scroll mc-wrap">
      <table className="mc-board missing-board">
        <thead>
          <tr>
            <th className="mc-match">Meč</th>
            <th colSpan={sides.length} className="mc-group">Pinnacle {football ? "1X2" : "pobednik"}</th>
            <th colSpan={3} className="mc-group-strong">{SPORT_VIEWS[sport]?.spreadTitle || "Hendikep"}</th>
            <th colSpan={3} className="mc-group-strong">{SPORT_VIEWS[sport]?.totalTitle || "Golovi"}</th>
            <th className="mc-group">Najbliže u ponudi MerkurXtip</th>
          </tr>
        </thead>
        <tbody>
          {matches.map((match) => {
            const comp = byId.get(match.leagueId);
            const { ah, ou } = lines(match);
            return (
              <tr key={match.id} className="mc-row">
                <td className="mc-match">
                  <div className="mc-when">{fmtKickoffShort(new Date(match.starts))}</div>
                  <div className="mc-teams"><b>{match.home}</b> <span>vs</span> <b>{match.away}</b></div>
                  <div className="mc-league">{comp && <CompBadge competition={comp} />} {match.leagueName}</div>
                </td>
                {sides.map(([side], i) => (
                  <td key={side} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>{fmt2(match.ml?.[side]?.odds)}</td>
                ))}
                {ah ? (
                  <>
                    <td className="mc-line mc-group-strong">{fmtLine(ah.line, true)}</td>
                    <td className="mc-odds">{fmt2(ah.home)}</td>
                    <td className="mc-odds">{fmt2(ah.away)}</td>
                  </>
                ) : <td className="mc-group-strong muted" colSpan={3}>—</td>}
                {ou ? (
                  <>
                    <td className="mc-line mc-group-strong">{fmtLine(ou.line)}</td>
                    <td className="mc-odds">{fmt2(ou.over)}</td>
                    <td className="mc-odds">{fmt2(ou.under)}</td>
                  </>
                ) : <td className="mc-group-strong muted" colSpan={3}>—</td>}
                <td className="mc-group missing-hint">
                  {match.hint ? (
                    <span title="Najbolje poklapanje među neuparenim mečevima iste lige. Verovatno isti meč pod drugim imenima: dodaj alias u merkur_client.py.">
                      {match.hint.home} – {match.hint.away}
                      <small> sličnost {Math.round(match.hint.score * 100)}%
                        {match.hint.kickoffDiff ? ` · ${match.hint.kickoffDiff > 0 ? "+" : "−"}${Math.abs(match.hint.kickoffDiff)} min` : ""}
                      </small>
                    </span>
                  ) : <span className="muted">nije u ponudi</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    </>
  );
}

// Matches Pinnacle quoted and then stopped quoting (suspended, or taken off the feed) before kickoff.
export function SuspendedTable({ matches }) {
  return (
    <div className="board-scroll mc-wrap">
      <table className="mc-board missing-board">
        <thead>
          <tr>
            <th className="mc-match">Meč</th>
            <th className="mc-group">Poslednja Pinnacle {`1X2 / pobednik`}</th>
            <th className="mc-group">Početak</th>
            <th className="mc-group">Nestala kvota</th>
          </tr>
        </thead>
        <tbody>
          {matches.map((m) => (
            <tr key={m.id}>
              <td className="mc-match">
                <b>{m.home} – {m.away}</b>
                <small>{m.leagueName}</small>
              </td>
              <td>{ML_SIDES.filter(([side]) => m.ml?.[side]).map(([side]) => fmt2(m.ml[side])).join(" · ") || "–"}</td>
              <td>{fmtKickoffShort(new Date(m.starts))}</td>
              <td>{fmtKickoffShort(new Date(m.since))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Football boards: Pinnacle board and the MerkurXtip vs Pinnacle comparison board.
import { useMemo } from "react";
import { fmt2, fmtKickoffShort, fmtLimit, fmtLine, fmtOdds, merkurClass, merkurTitle, pinnacleClass, timeFmt } from "../format.js";
import { CompBadge, KickoffWarning, ML_SIDES, Price } from "../ui.jsx";

function OpenDelta({ match }) {
  if (!match.open || !match.ml) return <span className="muted">—</span>;
  // Biggest relative move of the home or away price since we first saw the match.
  const moves = ["home", "away"].map((side) => {
    const open = match.open[side];
    const now = match.ml?.[side]?.odds;
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
            odds={match.ml?.[side]?.odds}
            fair={match.ml?.[side]?.fair}
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

export function BoardTable({ groups, competitions, selectedId, fetchedAt, onSelect, showLeague }) {
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

function CompareRow({ match, selected, onSelect, onOdds, pinStamp, mxStamp }) {
  const x = match.merkur;
  // colour only moves from the latest refresh
  const pinPrev = pinStamp && match.changedAt === pinStamp ? match.prev : null;
  const mxPrev = mxStamp && x?.changedAt === mxStamp ? x.prev : null;
  const kickoff = new Date(match.starts);
  const limit = fmtLimit(match.ah?.max || match.ou?.max);
  const oddsClick = (event) => {
    event.stopPropagation();
    onOdds(String(match.id));
  };
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
      {ML_SIDES.map(([side], i) => (
        <td key={`f${side}`} className={`mc-odds mc-click${i === 0 ? " mc-group" : ""}`} onClick={oddsClick}>{fmt2(match.ml?.[side]?.fair)}</td>
      ))}
      {ML_SIDES.map(([side], i) => (
        <td key={`p${side}`} className={`mc-odds mc-click${i === 0 ? " mc-group" : ""}`} onClick={oddsClick}>
          <span
            className={`mc-cell ${pinnacleClass(match.ml?.[side]?.odds, pinPrev?.[side])}`}
            title={match.prev?.[side] ? `Prethodna: ${fmtOdds(match.prev[side])}` : undefined}
          >
            {fmt2(match.ml?.[side]?.odds)}
          </span>
        </td>
      ))}
      {ML_SIDES.map(([side], i) => {
        const odds = x?.ml?.[side]?.odds;
        const ev = x?.ml?.[side]?.ev;
        const pin = match.ml?.[side]?.odds;
        const prev = mxPrev?.[side];
        return (
          <td key={`m${side}`} className={`mc-odds mc-click${i === 0 ? " mc-group" : ""}`} onClick={oddsClick}>
            {odds ? (
              <span className={`mc-cell ${merkurClass(odds, pin, ev, prev)}`} title={merkurTitle(odds, pin, match.ml?.[side]?.fair, ev, prev)}>
                {fmt2(odds)}
              </span>
            ) : (
              <span className="muted" title={x ? "MerkurXtip nema 1X2" : "Nije u ponudi MerkurXtip"}>—</span>
            )}
          </td>
        );
      })}
      <GoalCells goals={match.goals} pinStamp={pinStamp} mxStamp={mxStamp} onClick={oddsClick} />
    </tr>
  );
}

const OU = [["over", "V"], ["under", "M"]];

function GoalCells({ goals, pinStamp, mxStamp, onClick }) {
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
        <td key={`gf${side}`} className={`mc-odds mc-click${i === 0 ? " mc-group" : ""}`} onClick={onClick}>{fmt2(goals.fair[side])}</td>
      ))}
      {OU.map(([side], i) => (
        <td key={`gp${side}`} className={`mc-odds mc-click${i === 0 ? " mc-group" : ""}`} onClick={onClick}>
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
          <td key={`gm${side}`} className={`mc-odds mc-click${i === 0 ? " mc-group" : ""}`} onClick={onClick}>
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

export function CompareTable({ matches, selectedId, onSelect, onOdds, pinStamp, mxStamp }) {
  return (
    <div className="board-scroll mc-wrap">
      <table className="mc-board">
        <thead>
          <tr>
            <th rowSpan={2} className="mc-match">Meč</th>
            <th colSpan={3} className="mc-group">Pinnacle no-vig</th>
            <th colSpan={3} className="mc-group">Pinnacle</th>
            <th colSpan={3} className="mc-group">MerkurXtip</th>
            <th className="mc-line mc-group-strong">Golovi</th>
            <th colSpan={2} className="mc-group">No-vig</th>
            <th colSpan={2} className="mc-group">Pinnacle</th>
            <th colSpan={2} className="mc-group">MerkurXtip</th>
          </tr>
          <tr className="mc-sub">
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
              selected={String(match.id) === selectedId}
              onSelect={onSelect}
              onOdds={onOdds}
              pinStamp={pinStamp}
              mxStamp={mxStamp}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

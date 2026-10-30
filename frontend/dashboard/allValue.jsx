// All-sports Value screen: the value outcomes of every loaded board in one table, side menu by sport and competition.
import { useCallback, useEffect, useMemo, useState } from "react";
import { readStored, writeStored } from "./api.js";
import { DAY_FILTERS, evClass, fmtEv, inDayFilter } from "./format.js";
import { SPORTS, SideMenu } from "./menu.jsx";
import { VALUE_LEVELS, ValueRange, ValueTable, bestPerMarket, isTopLeague, rangePasses } from "./value.jsx";
import { matchesQuery } from "./search.jsx";
import { OddsModal } from "./football/detail.jsx";
import { SportOddsModal } from "./sport.jsx";

// Market types shared by every sport (group labels differ per sport: "Ukupno golova", "Ukupno poena" …).
const ALL_VALUE_GROUPS = [
  ["all", "Sva tržišta"],
  ["winner", "Pobednik / 1X2"],
  ["Hendikep", "Hendikep"],
  ["Ukupno", "Ukupno"],
  ["team", "Timovi / igrači"],
];
const TEAM_PREFIXES = ["Golovi ", "Poeni ", "Gemovi igrač"];

function groupPasses(value, group) {
  if (group === "all") return true;
  if (group === "winner") return value.group === "1X2" || value.group === "Pobednik";
  if (group === "team") return TEAM_PREFIXES.some((p) => value.group.startsWith(p));
  return value.group.startsWith(group);
}

// Every value outcome of every board, tagged with its sport, match and competition.
export function collectValues(boards) {
  const out = [];
  for (const { key } of SPORTS) {
    const board = boards[key];
    if (!board) continue;
    const matches = new Map((board.matches || []).map((m) => [m.id, m]));
    const comps = new Map((board.competitions || []).map((c) => [c.id, c]));
    for (const v of board.values || []) {
      const match = matches.get(v.matchId);
      if (match) out.push({ ...v, sport: key, match, comp: comps.get(match.leagueId) });
    }
  }
  return out;
}

export function AllValuePane({ boards, errors, dayFilter, setDayFilter, query, searchBox, onSport, sportCounts, searching, alertsTab, valueTab, setCallsToday }) {
  const [valueLevel, setValueLevel] = useState(() => readStored("pb.all.valueLevel", "fair"));
  const [valueGroup, setValueGroup] = useState(() => readStored("pb.all.valueGroup", "all"));
  const [showModeled, setShowModeled] = useState(() => readStored("pb.all.modeled", false));
  const [evMin, setEvMin] = useState(() => readStored("pb.all.evMin", ""));
  const [evMax, setEvMax] = useState(() => readStored("pb.all.evMax", ""));
  const [topOnly, setTopOnly] = useState(() => readStored("pb.all.topOnly", false));
  // "all", "<sport>" or "<sport>:<league id>"
  const [pick, setPick] = useState("all");
  const [odds, setOdds] = useState(null);
  useEffect(() => writeStored("pb.all.valueLevel", valueLevel), [valueLevel]);
  useEffect(() => writeStored("pb.all.valueGroup", valueGroup), [valueGroup]);
  useEffect(() => writeStored("pb.all.modeled", showModeled), [showModeled]);
  useEffect(() => writeStored("pb.all.evMin", evMin), [evMin]);
  useEffect(() => writeStored("pb.all.evMax", evMax), [evMax]);
  useEffect(() => writeStored("pb.all.topOnly", topOnly), [topOnly]);

  const all = useMemo(() => collectValues(boards), [boards]);
  const q = query.trim().toLocaleLowerCase();
  const valueList = useMemo(
    () => all.filter((v) => inDayFilter(new Date(v.match.starts), dayFilter) && matchesQuery(v.match, q)
      && (showModeled || !v.modeled)),
    [all, dayFilter, q, showModeled],
  );
  const levelValues = useMemo(
    () => bestPerMarket(valueList.filter((v) => (
      (valueLevel === "all" || v.ev >= (valueLevel === "fair" ? 0 : Number(valueLevel))) && groupPasses(v, valueGroup)
    )))
      .filter((v) => rangePasses(v, evMin, evMax) && (!topOnly || isTopLeague(v.sport, v.comp)))
      .sort((a, b) => b.ev - a.ev),
    [valueList, valueLevel, valueGroup, evMin, evMax, topOnly],
  );
  const shownValues = useMemo(
    () => (pick === "all" ? levelValues
      : levelValues.filter((v) => v.sport === pick || `${v.sport}:${v.match.leagueId}` === pick)),
    [levelValues, pick],
  );
  const fairValueCount = useMemo(() => valueList.filter((v) => v.ev >= 0).length, [valueList]);

  // side menu: one group per sport (its own row narrows to the sport), its competitions with value outcomes
  const menuGroups = useMemo(() => {
    const rows = new Map();
    for (const v of levelValues) {
      const id = `${v.sport}:${v.match.leagueId}`;
      const row = rows.get(id) || { v, count: 0, best: -Infinity, matches: new Set() };
      row.count += 1;
      row.best = Math.max(row.best, v.ev);
      row.matches.add(v.matchId);
      rows.set(id, row);
    }
    return SPORTS.map(({ key, label }) => ({
      title: label,
      items: [...rows.entries()].filter(([, row]) => row.v.sport === key).map(([id, row]) => ({
        id,
        key: id,
        comp: row.v.comp || { key: "other", code: "?", name: `Liga ${row.v.match.leagueId}` },
        count: row.count,
        extra: fmtEv(row.best),
        extraClass: evClass(row.best),
        active: pick === id,
        title: `${row.count} ishoda na ${row.matches.size} mečeva, najveća razlika vs fer ${fmtEv(row.best)}`,
      })),
    }));
  }, [levelValues, pick]);
  const allItem = { id: null, key: "all", label: "Svi sportovi", count: levelValues.length, active: pick === "all" };
  const sportItems = SPORTS.map(({ key, label }) => ({
    key, label, count: levelValues.filter((v) => v.sport === key).length,
  }));

  const loading = SPORTS.some(({ key }) => !boards[key] && !errors[key]);
  const failed = SPORTS.filter(({ key }) => errors[key]);
  const onCalls = useCallback((n) => setCallsToday(n), [setCallsToday]);
  const oddsMatch = odds && boards[odds.sport]?.matches.find((m) => String(m.id) === odds.id);

  return (
    <div className="shell">
      <SideMenu
        sport="value"
        onSport={onSport}
        alerts={alertsTab}
        valueTab={valueTab}
        sportCounts={sportCounts}
        searching={searching}
        groups={menuGroups}
        all={allItem}
        onPick={(item) => setPick((cur) => (item.id == null || cur === item.id ? "all" : item.id))}
        label="Value po sportovima"
      />
      <div className="content">
        <div className="filters">
          <div className="segmented view-switch">
            <button type="button" className={pick === "all" ? "active" : ""} onClick={() => setPick("all")}
              title={`${valueList.length} ishoda gde je MX > Pinnacle, od toga ${fairValueCount} gde je MX ≥ fer`}>
              Svi <span className="view-count">{levelValues.length}</span>
            </button>
            {sportItems.map((s) => (
              <button key={s.key} type="button" className={pick === s.key ? "active" : ""}
                onClick={() => setPick((cur) => (cur === s.key ? "all" : s.key))} disabled={!s.count}>
                {s.label} <span className="view-count">{s.count}</span>
              </button>
            ))}
          </div>
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
              {ALL_VALUE_GROUPS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <ValueRange min={evMin} max={evMax} setMin={setEvMin} setMax={setEvMax} topOnly={topOnly} setTopOnly={setTopOnly} />
          <label className="auto" title="Košarka: linije koje Pinnacle nema; fer kvota je procena modelom">
            <input type="checkbox" checked={showModeled} onChange={(e) => setShowModeled(e.target.checked)} />
            modelirano
          </label>
          <div className="segmented">
            {DAY_FILTERS.map(([key, label]) => (
              <button key={key} type="button" className={dayFilter === key ? "active" : ""} onClick={() => setDayFilter(key)}>
                {label}
              </button>
            ))}
          </div>
          {searchBox}
          <span className="legend mc-legend">
            <span className="mc-cell mx-fair">MX ≥ fer</span>
            <span className="mc-cell mx-above">MX &gt; Pinnacle</span>
          </span>
        </div>
        <main className="workspace">
          <section className="board-wrap">
            {failed.map(({ key, label }) => (
              <p key={key} className="state error" role="alert">{label}: {errors[key]}</p>
            ))}
            {loading && !all.length && <p className="state">Učitavam ponudu…</p>}
            {!loading && !shownValues.length && <p className="state">Nema ishoda za izabrane filtere.</p>}
            {!!shownValues.length && (
              <ValueTable
                values={shownValues}
                matchesById={new Map()}
                competitions={[]}
                selectedId={odds?.id}
                onOdds={(id, v) => setOdds({ id, sport: v.sport })}
                onSelect={(id, v) => setOdds({ id, sport: v.sport })}
              />
            )}
          </section>
        </main>
        {odds && odds.sport === "football" && (
          <OddsModal key={odds.id} matchId={odds.id} boardMatch={oddsMatch} onClose={() => setOdds(null)} onCalls={onCalls} />
        )}
        {odds && odds.sport !== "football" && (
          <SportOddsModal key={`${odds.sport}-${odds.id}`} sport={odds.sport} matchId={odds.id} boardMatch={oddsMatch}
            onClose={() => setOdds(null)} onCalls={onCalls} />
        )}
      </div>
    </div>
  );
}

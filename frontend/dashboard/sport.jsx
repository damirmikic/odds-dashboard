// Basketball, tennis, hockey and MMA screen (SportPane), its board, odds modal and board loading.
import { useCallback, useEffect, useMemo, useState } from "react";
import { readStored, requestJson, writeStored } from "./api.js";
import { DAY_FILTERS, clockFmt, dayKey, dayLabel, evClass, fmt2, fmtEv, fmtKickoffShort, fmtLimit, fmtLine, fmtOdds, inDayFilter, merkurClass, merkurTitle, timeFmt } from "./format.js";
import { CompBadge, KickoffWarning, ModeledTag, StaleTag } from "./ui.jsx";
import { PriceChart, Sparkline, histKey, usePriceHistory } from "./priceHistory.jsx";
import { VALUE_LEVELS, ValueRange, ValueTable, bestPerMarket, isTopLeague, rangePasses } from "./value.jsx";
import { SideMenu, buildMenuGroups } from "./menu.jsx";
import { MissingTable, missingEmpty } from "./missing.jsx";
import { SPORT_VIEWS } from "./sportViews.js";

const SPORT_ML = [["home", "1"], ["away", "2"]];

const SPORT_OU = [["over", "V"], ["under", "M"]];

function sportValuePasses(value, level, group, teamPrefix) {
  if (level === "fair" && value.ev < 0) return false;
  if (level !== "all" && level !== "fair" && value.ev < Number(level)) return false;
  if (group === "team") return !!teamPrefix && value.group.startsWith(teamPrefix);
  return group === "all" || value.group === group;
}

// Fair / Pinnacle / MerkurXtip cells of one two-way line market (handicap or total points).
function SportLineCells({ cell, sides, signed }) {
  if (!cell) return <td className="mc-line mc-group-strong" colSpan={7}><span className="muted">—</span></td>;
  return (
    <>
      <td className="mc-line mc-group-strong" title={cell.merkur ? "Linija koju imaju obe kuće, najbliža Pinnacle glavnoj" : "Pinnacle glavna linija"}>
        {fmtLine(cell.line, signed)}
      </td>
      {sides.map(([side], i) => (
        <td key={`f${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>{fmt2(cell.fair[side])}</td>
      ))}
      {sides.map(([side], i) => (
        <td key={`p${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>
          <span className="mc-cell">{fmt2(cell.pinnacle[side])}</span>
        </td>
      ))}
      {sides.map(([side], i) => {
        const odds = cell.merkur?.[side];
        return (
          <td key={`m${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>
            {odds ? (
              <span
                className={`mc-cell ${merkurClass(odds, cell.pinnacle[side], cell.ev?.[side])}`}
                title={merkurTitle(odds, cell.pinnacle[side], cell.fair[side], cell.ev?.[side])}
              >
                {fmt2(odds)}
              </span>
            ) : <span className="muted" title="MerkurXtip nema ovu liniju">—</span>}
          </td>
        );
      })}
    </>
  );
}

function SportDetail({ match, periodKey = "ft", history }) {
  const [open, setOpen] = useState("");
  const rows = (periodKey === "ft" ? match.rows : match.periods?.[periodKey]) || [];
  if (!match.merkur) return <p className="muted bb-detail">Meč nije u ponudi MerkurXtip (ili nije uparen).</p>;
  const modeled = rows.filter((r) => r.modeled).length;
  return (
    <div className="bb-detail">
      <p className="mx-names">
        {match.merkur.home} – {match.merkur.away}
        <KickoffWarning diff={match.merkur.kickoffDiff} />
        {match.merkur.stale?.map((st) => <StaleTag key={st.group} gap={st.gap} />)}
        <small> · upoređeno {rows.length} tržišta{modeled ? `, od toga ${modeled} modelirano` : ""}</small>
      </p>
      {!rows.length && <p className="muted">Nema tržišta koja postoje kod obe kuće.</p>}
      <table className="lines mx-table">
        <thead>
          <tr><th>Tržište</th><th>Linija</th><th>Ishod</th><th>Fer</th><th>PIN</th><th>MX</th><th>Razlika</th><th title="Pinnacle limit (max bet) tržišta">Max bet</th><th title="Kretanje kvota: Pinnacle (plavo) i MerkurXtip (narandžasto). Klik za grafikon.">Kretanje</th></tr>
        </thead>
        <tbody>
          {rows.flatMap((r) => {
            const keyOf = (o) => histKey(r.period || periodKey, r.group, r.line, o.key);
            const opened = r.outcomes.find((o) => keyOf(o) === open);
            const side = (o) => (r.group.startsWith("Hendikep") ? (o.key === "home" ? match.home : match.away) : o.label);
            const lines = r.outcomes.map((o, i) => (
            <tr key={`${r.group}-${r.line}-${o.key}`} className={i === 0 ? "mx-first" : ""}>
              <td>{i === 0 ? r.group : ""}</td>
              <td>{i === 0 && r.line != null ? fmtLine(r.line, r.group.startsWith("Hendikep")) : ""}{i === 0 && r.modeled && <ModeledTag />}</td>
              <td>{side(o)}</td>
              <td className="mx-fair-cell">{fmtOdds(o.fair)}</td>
              <td>{fmtOdds(o.pinnacle)}</td>
              <td><span className={`mc-cell ${merkurClass(o.merkur, o.pinnacle, o.ev)}`}>{fmt2(o.merkur)}</span></td>
              <td><span className={`ev-chip ${evClass(o.ev)}`}>{fmtEv(o.ev)}</span></td>
              <td className="mx-maxbet">{i === 0 ? fmtLimit(r.maxBet) || "—" : ""}</td>
              <td>
                <Sparkline
                  points={history?.get(keyOf(o))}
                  active={opened === o}
                  onToggle={() => setOpen((current) => (current === keyOf(o) ? "" : keyOf(o)))}
                />
              </td>
            </tr>
            ));
            if (opened) {
              lines.push(
                <tr key={`${r.group}-${r.line}-chart`} className="hist-row">
                  <td colSpan={9}>
                    <PriceChart
                      points={history.get(open)}
                      label={`${r.group}${r.line != null ? ` ${fmtLine(r.line, r.group.startsWith("Hendikep"))}` : ""} · ${side(opened)}`}
                    />
                  </td>
                </tr>,
              );
            }
            return lines;
          })}
        </tbody>
      </table>
    </div>
  );
}

function SportOddsModal({ sport, matchId, boardMatch, onClose, onCalls }) {
  const [detail, setDetail] = useState(null);
  const [periodKey, setPeriodKey] = useState("ft");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    requestJson(`/api/${sport}/match/${matchId}`, { signal: controller.signal })
      .then((data) => {
        setDetail(data);
        onCalls(data.callsToday);
      })
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [sport, matchId, onCalls]);
  const history = usePriceHistory(sport, matchId);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const match = detail?.match || boardMatch;
  const periodKeys = ["ft", ...Object.keys(match?.periods || {})];
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Uporedne kvote" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <div>
            <h2>{match?.home} <span>–</span> {match?.away}</h2>
            {match?.starts && <p>{dayLabel(new Date(match.starts))}, {timeFmt.format(new Date(match.starts))} · {match.leagueName}</p>}
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Zatvori">✕</button>
        </header>
        <div className="segmented" role="tablist">
          {periodKeys.map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={periodKey === key}
              className={periodKey === key ? "active" : ""}
              onClick={() => setPeriodKey(key)}
            >
              {SPORT_VIEWS[sport].periods[key]}
            </button>
          ))}
        </div>
        {error && <p className="state error" role="alert">{error}</p>}
        {!detail && !error && <p className="state">Učitavam kvote…</p>}
        {detail?.error && <p className="state error">{detail.error} Prikazane su kvote iz liste ponude.</p>}
        {detail && <SportDetail match={detail.match} periodKey={periodKey} history={history} />}
        {detail?.fetchedAt && <p className="muted bb-fetched">MerkurXtip {clockFmt.format(new Date(detail.fetchedAt))}</p>}
      </div>
    </div>
  );
}

function SportRow({ match, competition, expanded, onToggle, spread }) {
  const x = match.merkur;
  return (
    <>
      <tr className={`mc-row${expanded ? " selected" : ""}`} onClick={onToggle}>
        <td className="mc-match">
          <div className="mc-when">
            {fmtKickoffShort(new Date(match.starts))}
            {x && <KickoffWarning diff={x.kickoffDiff} />}
            {x?.stale?.map((st) => (
              <span key={st.group} title={`${st.group}: glavna linija MerkurXtip se razlikuje od Pinnacle`}>
                <StaleTag gap={st.gap} />
              </span>
            ))}
          </div>
          <div className="mc-teams"><b>{match.home}</b> <span>vs</span> <b>{match.away}</b></div>
          <div className="mc-league">{competition && <CompBadge competition={competition} />} {match.leagueName}</div>
        </td>
        {SPORT_ML.map(([side], i) => (
          <td key={`f${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>{fmt2(match.ml?.[side]?.fair)}</td>
        ))}
        {SPORT_ML.map(([side], i) => (
          <td key={`p${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>
            <span className="mc-cell">{fmt2(match.ml?.[side]?.odds)}</span>
          </td>
        ))}
        {SPORT_ML.map(([side], i) => {
          const odds = x?.ml?.[side]?.odds;
          const ev = x?.ml?.[side]?.ev;
          return (
            <td key={`m${side}`} className={`mc-odds${i === 0 ? " mc-group" : ""}`}>
              {odds ? (
                <span
                  className={`mc-cell ${merkurClass(odds, match.ml?.[side]?.odds, ev)}`}
                  title={merkurTitle(odds, match.ml?.[side]?.odds, match.ml?.[side]?.fair, ev)}
                >
                  {fmt2(odds)}
                </span>
              ) : <span className="muted" title={x ? "MerkurXtip nema pobednika" : "Nije u ponudi MerkurXtip"}>—</span>}
            </td>
          );
        })}
        {spread && <SportLineCells cell={match.spread} sides={SPORT_ML} signed />}
        <SportLineCells cell={match.total} sides={SPORT_OU} />
      </tr>
    </>
  );
}

function SportCompareTable({ sport, matches, competitions, selectedId, onOpen }) {
  const cfg = SPORT_VIEWS[sport];
  const byId = useMemo(() => new Map(competitions.map((c) => [c.id, c])), [competitions]);
  return (
    <div className="board-scroll mc-wrap">
      <table className="mc-board">
        <thead>
          <tr>
            <th rowSpan={2} className="mc-match">Meč</th>
            <th colSpan={6} className="mc-group-strong">Pobednik {cfg.winnerNote && <small>{cfg.winnerNote}</small>}</th>
            {cfg.spreadTitle && <th colSpan={7} className="mc-group-strong">{cfg.spreadTitle}</th>}
            <th colSpan={7} className="mc-group-strong">{cfg.totalTitle}</th>
          </tr>
          <tr className="mc-sub">
            {["No-vig", "Pinnacle", "MerkurXtip"].map((title) => (
              <th key={`ml${title}`} colSpan={2} className="mc-group">{title}</th>
            ))}
            {cfg.spreadTitle && (
              <>
                <th className="mc-line mc-group-strong">linija</th>
                {["No-vig", "Pinnacle", "MerkurXtip"].map((title) => (
                  <th key={`h${title}`} colSpan={2} className="mc-group">{title}</th>
                ))}
              </>
            )}
            <th className="mc-line mc-group-strong">linija</th>
            {["No-vig", "Pinnacle", "MerkurXtip"].map((title) => (
              <th key={`t${title}`} colSpan={2} className="mc-group">{title}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matches.map((match) => (
            <SportRow
              key={match.id}
              match={match}
              competition={byId.get(match.leagueId)}
              expanded={String(match.id) === selectedId}
              onToggle={() => onOpen(String(match.id))}
              spread={!!cfg.spreadTitle}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SportPane({ board, error, loading, dayFilter, setDayFilter, query, setQuery, sport, onSport, sportCounts, setCallsToday, alertsTab, openReq }) {
  const cfg = SPORT_VIEWS[sport];
  const store = useCallback((name) => `pb.${cfg.store}.${name}`, [cfg.store]);
  const [competition, setCompetition] = useState(() => readStored(store("competition"), "all"));
  const [view, setView] = useState(() => (
    ["value", "missing"].includes(new URLSearchParams(window.location.search).get("view"))
      ? new URLSearchParams(window.location.search).get("view") : readStored(store("view"), "compare")
  ));
  const [valueLevel, setValueLevel] = useState(() => readStored(store("valueLevel"), "fair"));
  const [valueGroup, setValueGroup] = useState(() => readStored(store("valueGroup"), "all"));
  const [showModeled, setShowModeled] = useState(() => readStored(store("modeled"), false));
  const [evMin, setEvMin] = useState(() => readStored(store("evMin"), ""));
  const [evMax, setEvMax] = useState(() => readStored(store("evMax"), ""));
  const [topOnly, setTopOnly] = useState(() => readStored(store("topOnly"), false));
  const [onlyStale, setOnlyStale] = useState(false);
  const [valueLeague, setValueLeague] = useState("all");
  const [oddsId, setOddsId] = useState(() => openReq?.id || window.location.hash.replace(/\D/g, ""));
  useEffect(() => {
    if (openReq) setOddsId(openReq.id);
  }, [openReq]);
  useEffect(() => writeStored(store("competition"), competition), [store, competition]);
  useEffect(() => writeStored(store("view"), view), [store, view]);
  useEffect(() => writeStored(store("valueLevel"), valueLevel), [store, valueLevel]);
  useEffect(() => writeStored(store("valueGroup"), valueGroup), [store, valueGroup]);
  useEffect(() => writeStored(store("modeled"), showModeled), [store, showModeled]);
  useEffect(() => writeStored(store("evMin"), evMin), [store, evMin]);
  useEffect(() => writeStored(store("evMax"), evMax), [store, evMax]);
  useEffect(() => writeStored(store("topOnly"), topOnly), [store, topOnly]);

  const competitions = useMemo(() => board?.competitions || [], [board]);
  const compById = useMemo(() => new Map(competitions.map((c) => [c.id, c])), [competitions]);
  const matchesById = useMemo(() => new Map((board?.matches || []).map((m) => [m.id, m])), [board]);
  const q = query.trim().toLocaleLowerCase();
  const textOk = useCallback(
    (m) => !q || `${m.home} ${m.away} ${m.merkur?.home || ""} ${m.merkur?.away || ""}`.toLocaleLowerCase().includes(q),
    [q],
  );

  const missingCounts = useMemo(() => {
    const counts = new Map();
    for (const m of board?.matches || []) if (!m.merkur) counts.set(m.leagueId, (counts.get(m.leagueId) || 0) + 1);
    return counts;
  }, [board]);
  const missingTotal = useMemo(() => [...missingCounts.values()].reduce((a, b) => a + b, 0), [missingCounts]);

  const filtered = useMemo(
    () => (board?.matches || []).filter((m) => (
      (competition === "all" || compById.get(m.leagueId)?.key === competition)
      && inDayFilter(new Date(m.starts), dayFilter) && textOk(m)
      && (view !== "missing" || !m.merkur)
    )),
    [board, competition, dayFilter, textOk, compById, view],
  );
  const valueList = useMemo(
    () => (board?.values || []).filter((v) => {
      const m = matchesById.get(v.matchId);
      return m && inDayFilter(new Date(m.starts), dayFilter) && textOk(m)
        && (showModeled || !v.modeled) && (!onlyStale || v.stale != null);
    }),
    [board, matchesById, dayFilter, textOk, showModeled, onlyStale],
  );
  const levelValues = useMemo(
    () => bestPerMarket(valueList.filter((v) => sportValuePasses(v, valueLevel, valueGroup, cfg.teamPrefix)))
      .filter((v) => rangePasses(v, evMin, evMax)
        && (!topOnly || isTopLeague(sport, compById.get(matchesById.get(v.matchId).leagueId))))
      .sort((a, b) => b.ev - a.ev),
    [valueList, valueLevel, valueGroup, cfg, evMin, evMax, topOnly, sport, compById, matchesById],
  );
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

  const inValue = view === "value";
  const inMissing = view === "missing";
  const menuCompetitions = useMemo(
    () => (inMissing ? competitions.map((c) => ({ ...c, count: missingCounts.get(c.id) || 0 })) : competitions),
    [competitions, inMissing, missingCounts],
  );
  const menuGroups = useMemo(
    () => buildMenuGroups({
      competitions: menuCompetitions, valueSummary: inValue ? valueSummary : null, activeKey: competition,
      activeLeague: valueLeague,
    }),
    [menuCompetitions, inValue, valueSummary, competition, valueLeague],
  );
  const allItem = inValue
    ? { id: null, key: "all", label: "Sve lige", count: levelValues.length, active: valueLeague === "all" }
    : { id: null, key: "all", label: "Sve", count: inMissing ? missingTotal : board?.matches.length || 0,
        active: competition === "all" };

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
  const onCalls = useCallback((n) => setCallsToday(n), [setCallsToday]);

  return (
    <div className="shell">
      <SideMenu
        sport={sport}
        onSport={onSport}
        alerts={alertsTab}
        sportCounts={sportCounts}
        groups={menuGroups}
        all={allItem}
        onPick={(item) => (inValue
          ? setValueLeague((cur) => (item.id == null || cur === String(item.id) ? "all" : String(item.id)))
          : setCompetition(item.key))}
        label={inValue ? "Value po takmičenjima" : "Takmičenja"}
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
          </div>
          {inValue && (
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
                  {cfg.valueGroups.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                </select>
              </label>
              <ValueRange min={evMin} max={evMax} setMin={setEvMin} setMax={setEvMax} topOnly={topOnly} setTopOnly={setTopOnly} />
              {cfg.modeled && (
                <>
                  <label className="auto" title="Linije koje Pinnacle nema; fer kvota je procena modelom">
                    <input type="checkbox" checked={showModeled} onChange={(e) => setShowModeled(e.target.checked)} />
                    modelirano
                  </label>
                  <label className="auto" title="Samo ishodi na strani koju favorizuje razlika glavnih linija (MerkurXtip kasni)">
                    <input type="checkbox" checked={onlyStale} onChange={(e) => setOnlyStale(e.target.checked)} />
                    samo kasni
                  </label>
                </>
              )}
            </>
          )}
          <div className="segmented">
            {DAY_FILTERS.map(([key, label]) => (
              <button key={key} type="button" className={dayFilter === key ? "active" : ""} onClick={() => setDayFilter(key)}>
                {label}
              </button>
            ))}
          </div>
          <input className="search" type="search" placeholder="Pretraga timova…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <span className="legend mc-legend">
            <span className="mc-cell mx-fair">MX ≥ fer</span>
            <span className="mc-cell mx-above">MX &gt; Pinnacle</span>
          </span>
        </div>
        <main className="workspace">
          <section className="board-wrap">
            {error && <p className="state error" role="alert">{error}</p>}
            {!board && loading && <p className="state">Učitavam ponudu…</p>}
            {board && !inValue && !filtered.length && (
              <p className="state">
                {inMissing ? missingEmpty(missingTotal, competition !== "all", () => setCompetition("all")) : "Nema mečeva za izabrani filter."}
              </p>
            )}
            {inMissing && !!filtered.length && <MissingTable matches={filtered} competitions={competitions} sport={sport} />}
            {view === "compare" && groups.map((group) => (
              <div key={group.key} className="bb-day">
                <h3 className="bb-day-title">{group.title} <span>{group.matches.length}</span></h3>
                <SportCompareTable sport={sport} matches={group.matches} competitions={competitions} selectedId={oddsId} onOpen={setOddsId} />
              </div>
            ))}
            {board && inValue && !shownValues.length && <p className="state">Nema ishoda za izabrane filtere.</p>}
            {board && inValue && !!shownValues.length && (
              <ValueTable
                values={shownValues}
                matchesById={matchesById}
                competitions={competitions}
                selectedId={oddsId}
                onOdds={setOddsId}
                onSelect={setOddsId}
              />
            )}
          </section>
        </main>
        {oddsId && (
          <SportOddsModal
            key={oddsId}
            sport={sport}
            matchId={oddsId}
            boardMatch={matchesById.get(Number(oddsId)) || matchesById.get(oddsId)}
            onClose={() => setOddsId("")}
            onCalls={onCalls}
          />
        )}
      </div>
    </div>
  );
}

// Board of a sport served from /api/<sport>/board; the football board keeps its own loader.
export function useSportBoard(sport, setCallsToday, setApiKeySet) {
  const [board, setBoard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async (mode) => {
    setLoading(true);
    setError("");
    try {
      const suffix = mode === "full" ? "?full=1" : mode === "refresh" ? "?refresh=1" : "";
      const data = await requestJson(`/api/${sport}/board${suffix}`);
      setBoard(data);
      setCallsToday(data.callsToday);
    } catch (err) {
      setError(err.message);
      if (err.message.includes("ključ")) setApiKeySet(false);
    } finally {
      setLoading(false);
    }
  }, [sport, setCallsToday, setApiKeySet]);
  const reset = useCallback(() => {
    setBoard(null);
    setError("");
  }, []);
  return { board, loading, error, load, reset };
}

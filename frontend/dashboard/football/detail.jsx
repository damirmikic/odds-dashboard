// Football match detail panel and odds modal.
import { useEffect, useState } from "react";
import { requestJson } from "../api.js";
import { clockFmt, dayLabel, evClass, fmtEv, fmtLimit, fmtLine, fmtMargins, fmtOdds, fmtPct, marketLine, merkurClass, timeFmt } from "../format.js";
import { CompBadge, DerivedTag, KickoffWarning, ML_SIDES, Price } from "../ui.jsx";
import { PriceChart, Sparkline, histKey, usePriceHistory } from "../priceHistory.jsx";

function MerkurComparison({ merkur, periodKey, home, away, history }) {
  const [open, setOpen] = useState("");
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
              <th>Fer</th>
              <th>PIN</th>
              <th>MX</th>
              <th title="MerkurXtip kvota / Pinnacle fer kvota − 1">Razlika</th>
              <th title="Pinnacle limit (max bet) tržišta">Max bet</th>
              <th title="Kretanje kvota: Pinnacle (plavo) i MerkurXtip (narandžasto). Klik za grafikon.">Kretanje</th>
            </tr>
          </thead>
          {rows.map((row, i) => {
            const opened = row.outcomes.find((o) => histKey(periodKey, row.group, row.line, o.key) === open);
            return (
            <tbody key={`${row.group}-${row.line}`} className={i > 0 && rows[i - 1].group !== row.group ? "mx-group-start" : ""}>
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
                  <td className="mx-fair-cell">{fmtOdds(o.fair)}</td>
                  <td>{fmtOdds(o.pinnacle)}</td>
                  <td>
                    <span className={`mc-cell ${merkurClass(o.merkur, o.pinnacle, o.ev)}`}><b>{fmtOdds(o.merkur)}</b></span>
                  </td>
                  <td><span className={`ev-chip ${evClass(o.ev)}`}>{fmtEv(o.ev)}</span></td>
                  {index === 0 && (
                    <td rowSpan={row.outcomes.length} className="mx-maxbet">{fmtLimit(row.maxBet) || "—"}</td>
                  )}
                  <td>
                    <Sparkline
                      points={history?.get(histKey(periodKey, row.group, row.line, o.key))}
                      active={opened === o}
                      onToggle={() => {
                        const k = histKey(periodKey, row.group, row.line, o.key);
                        setOpen((current) => (current === k ? "" : k));
                      }}
                    />
                  </td>
                </tr>
              ))}
              {opened && (
                <tr className="hist-row">
                  <td colSpan={8}>
                    <PriceChart
                      points={history.get(open)}
                      label={`${row.group}${row.line != null ? ` ${marketLine(row.group, row.line)}` : ""} · ${sideLabel(row.group, opened.label)}`}
                    />
                  </td>
                </tr>
              )}
            </tbody>
            );
          })}
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

export function DetailPanel({ matchId, boardMatch, competition, onClose, onCalls }) {
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
  const history = usePriceHistory("football", matchId, detail?.fetchedAt);

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

      {detail && (
        <MerkurComparison merkur={detail.merkur} periodKey={periodKey} home={match.home} away={match.away} history={history} />
      )}

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

export function OddsModal({ matchId, boardMatch, onClose, onCalls }) {
  const [detail, setDetail] = useState(null);
  const [periodKey, setPeriodKey] = useState("ft");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    requestJson(`/api/match/${matchId}`, { signal: controller.signal })
      .then((data) => {
        setDetail(data);
        onCalls(data.callsToday);
      })
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [matchId, onCalls]);
  const history = usePriceHistory("football", matchId);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const match = detail?.match || boardMatch;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Uporedne kvote" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <div>
            <h2>{match?.home} <span>–</span> {match?.away}</h2>
            {match?.starts && <p>Fudbal · {dayLabel(new Date(match.starts))}, {timeFmt.format(new Date(match.starts))}{match.leagueName ? ` · ${match.leagueName}` : ""}</p>}
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Zatvori">✕</button>
        </header>
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
        {error && <p className="state error" role="alert">{error}</p>}
        {!detail && !error && <p className="state">Učitavam kvote…</p>}
        {detail && (
          <MerkurComparison merkur={detail.merkur} periodKey={periodKey} home={match.home} away={match.away} history={history} />
        )}
      </div>
    </div>
  );
}

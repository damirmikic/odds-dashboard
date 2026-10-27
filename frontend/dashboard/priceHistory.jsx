// Line movement: stored price history, sparklines and the chart in the odds modals (price_history.py).
import { useEffect, useRef, useState } from "react";
import { requestJson } from "./api.js";
import { fmt2, fmtOdds, fmtWhen } from "./format.js";

export const histKey = (period, group, line, key) => `${period}|${group}|${line ?? ""}|${key}`;

// Stored prices of one board match (recorded at every board, see price_history.py):
// Map histKey -> [[epoch s, pinnacle, merkur, fair]], null until loaded or when the store is off.
export function usePriceHistory(sport, matchId, reloadKey) {
  const [history, setHistory] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    requestJson(`/api/history?sport=${sport}&id=${matchId}`, { signal: controller.signal })
      .then((data) => setHistory(new Map(data.series.map((s) => [histKey(s.period, s.group, s.line, s.key), s.points]))))
      .catch(() => {}); // the charts are optional, the odds stay usable without them
    return () => controller.abort();
  }, [sport, matchId, reloadKey]);
  return history;
}

// Scales over the price columns `columns` of `points`, time from the first point to `end`.
function chartScales(points, columns, width, height, pad, end) {
  const values = points.flatMap((p) => columns.map((c) => p[c])).filter((v) => v != null);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (hi - lo < 0.02) {
    lo -= 0.01;
    hi += 0.01;
  }
  const t0 = points[0][0];
  const span = Math.max(1, end - t0);
  return {
    lo,
    hi,
    x: (t) => pad.left + ((t - t0) / span) * (width - pad.left - pad.right),
    y: (v) => pad.top + (1 - (v - lo) / (hi - lo)) * (height - pad.top - pad.bottom),
  };
}

// A price holds until the next change, so the line is drawn in steps, up to `end`.
function stepPath(points, column, scales, end) {
  let d = "";
  for (const p of points) {
    if (p[column] == null) continue;
    d += d ? `H${scales.x(p[0])}V${scales.y(p[column])}` : `M${scales.x(p[0])},${scales.y(p[column])}`;
  }
  return d && `${d}H${scales.x(end)}`;
}

export function Sparkline({ points, active, onToggle }) {
  if (!points) return <span className="spark-none">—</span>;
  const first = points[0];
  if (points.length < 2) {
    return <span className="spark-none" title={`Bez promene od ${fmtWhen(new Date(first[0] * 1000))}`}>—</span>;
  }
  const last = points[points.length - 1];
  const end = Math.max(Date.now() / 1000, last[0]);
  const scales = chartScales(points, [1, 2], 64, 20, { top: 2, right: 1, bottom: 2, left: 1 }, end);
  return (
    <button
      type="button"
      className={`spark${active ? " active" : ""}`}
      onClick={onToggle}
      aria-expanded={active}
      title={`PIN ${fmtOdds(first[1])} → ${fmtOdds(last[1])} · MX ${fmt2(first[2])} → ${fmt2(last[2])} · `
        + `${points.length - 1} promena od ${fmtWhen(new Date(first[0] * 1000))}. Klik za grafikon.`}
    >
      <svg viewBox="0 0 64 20" width="64" height="20" aria-hidden="true">
        <path className="spark-pin" d={stepPath(points, 1, scales, end)} />
        <path className="spark-mx" d={stepPath(points, 2, scales, end)} />
      </svg>
    </button>
  );
}

const CHART_H = 170;

const CHART_PAD = { top: 12, right: 44, bottom: 22, left: 40 };

export function PriceChart({ points, label }) {
  const [hover, setHover] = useState(null); // epoch s under the pointer
  // drawn at the real pixel width, so the axis text keeps its size in the narrow panel and the wide modal
  const figure = useRef(null);
  const [width, setWidth] = useState(560);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.round(entry.contentRect.width))));
    observer.observe(figure.current);
    return () => observer.disconnect();
  }, []);
  const last = points[points.length - 1];
  const end = Math.max(Date.now() / 1000, last[0]);
  const t0 = points[0][0];
  const scales = chartScales(points, [1, 2, 3], width, CHART_H, CHART_PAD, end);
  const ticks = [scales.lo, (scales.lo + scales.hi) / 2, scales.hi];
  const onMove = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - box.left) / box.width) * width;
    const frac = (x - CHART_PAD.left) / (width - CHART_PAD.left - CHART_PAD.right);
    setHover(t0 + Math.min(1, Math.max(0, frac)) * (end - t0));
  };
  const at = hover == null ? null : points.findLast((p) => p[0] <= hover) || points[0];
  // end labels sit at the last price of each book, pushed apart when they would overlap
  let pinY = scales.y(last[1]);
  let mxY = scales.y(last[2]);
  if (Math.abs(pinY - mxY) < 11) {
    const mid = (pinY + mxY) / 2;
    const up = pinY <= mxY ? -1 : 1;
    pinY = mid + up * 5.5;
    mxY = mid - up * 5.5;
  }
  return (
    <figure className="price-chart" ref={figure}>
      <figcaption>
        <b>{label}</b>
        <span className="legend">
          <span><i className="lg-pin" />Pinnacle</span>
          <span><i className="lg-mx" />MerkurXtip</span>
          <span><i className="lg-fair" />Pinnacle fer</span>
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${width} ${CHART_H}`}
        role="img"
        aria-label={`Kretanje kvota: ${label}`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line className="grid" x1={CHART_PAD.left} x2={width - CHART_PAD.right} y1={scales.y(v)} y2={scales.y(v)} />
            <text className="axis" x={CHART_PAD.left - 6} y={scales.y(v)} dy="0.32em" textAnchor="end">{v.toFixed(2)}</text>
          </g>
        ))}
        <text className="axis" x={CHART_PAD.left} y={CHART_H - 5}>{fmtWhen(new Date(t0 * 1000))}</text>
        <text className="axis" x={width - CHART_PAD.right} y={CHART_H - 5} textAnchor="end">sada</text>
        <path className="line-fair" d={stepPath(points, 3, scales, end)} />
        <path className="line-pin" d={stepPath(points, 1, scales, end)} />
        <path className="line-mx" d={stepPath(points, 2, scales, end)} />
        <text className="end-label" x={width - CHART_PAD.right + 5} y={pinY} dy="0.32em">{fmtOdds(last[1])}</text>
        <text className="end-label" x={width - CHART_PAD.right + 5} y={mxY} dy="0.32em">{fmt2(last[2])}</text>
        {at && (
          <g>
            <line className="crosshair" x1={scales.x(hover)} x2={scales.x(hover)} y1={CHART_PAD.top} y2={CHART_H - CHART_PAD.bottom} />
            <circle className="dot-pin" cx={scales.x(hover)} cy={scales.y(at[1])} r="4" />
            <circle className="dot-mx" cx={scales.x(hover)} cy={scales.y(at[2])} r="4" />
          </g>
        )}
      </svg>
      {at && (
        <div className="chart-tip" style={{ left: `${(scales.x(hover) / width) * 100}%` }}>
          <span>{fmtWhen(new Date(at[0] * 1000))}</span>
          <i style={{ background: "var(--pin-line)" }} />PIN <b>{fmtOdds(at[1])}</b>
          <i style={{ background: "var(--mx-line)" }} />MX <b>{fmt2(at[2])}</b>
          <span> · fer {fmtOdds(at[3])}</span>
        </div>
      )}
    </figure>
  );
}

// Value list: when each book last moved this price (board refreshes, so at most one refresh late).
export function ChangeTimes({ value }) {
  const seen = value.seenAt ? `Prati se od ${fmtWhen(new Date(value.seenAt))}` : "Istorija kvota nije dostupna";
  return (
    <div title={seen}>
      {[["MX", value.mxChangedAt], ["PIN", value.pinChangedAt]].map(([book, at]) => (
        <div key={book} className={at && Date.now() - Date.parse(at) < 15 * 60000 ? "recent" : ""}>
          <small>{book}</small> {at ? fmtWhen(new Date(at)) : "—"}
        </div>
      ))}
    </div>
  );
}

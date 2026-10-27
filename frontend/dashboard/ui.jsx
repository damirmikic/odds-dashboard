// Small components shared by every sport: competition badge, price, tags and kickoff warning.
import { fmtOdds, movement } from "./format.js";

export const ML_SIDES = [["home", "1"], ["draw", "X"], ["away", "2"]];

export function CompBadge({ competition }) {
  return <i className={`comp-badge ${competition.badge || competition.key}`} aria-hidden="true">{competition.code}</i>;
}

const DERIVED_HINT =
  "Izvedeno: MerkurXtip nema ovu liniju kao dvosmernu igru. Kvota je iz 1X2, dvostruke šanse ili evropskog hendikepa, pa nema marže.";

export function DerivedTag() {
  return <i className="derived-tag" title={DERIVED_HINT}>izv.</i>;
}

export function ModeledTag() {
  return (
    <i className="derived-tag" title="Pinnacle nema ovu liniju. Fer kvota je procenjena modelom iz Pinnacle lestvice linija.">
      model
    </i>
  );
}

export function StaleTag({ gap }) {
  const text = `${gap > 0 ? "+" : "−"}${Math.abs(gap)}`;
  return (
    <i className="stale-tag" title={`Glavna linija MerkurXtip se razlikuje od Pinnacle za ${text}: ponuda kasni.`}>
      kasni {text}
    </i>
  );
}

export function Price({ odds, fair, prev, open, compact }) {
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

export function KickoffWarning({ diff }) {
  if (!diff) return null;
  return (
    <span className="kickoff-warn" title="Vreme početka u MerkurXtip ponudi se razlikuje od Pinnacle-a">
      ⏱ MX {diff > 0 ? "+" : "−"}{Math.abs(diff)} min
    </span>
  );
}

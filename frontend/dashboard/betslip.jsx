// Betslip ("Tiket") state, live board price sync, and floating comparison drawer (Pinnacle vs MerkurXtip total odds).
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { readStored, writeStored } from "./api.js";
import { evClass, fmt2, fmtEv, fmtKickoffShort, fmtLine, fmtOdds } from "./format.js";
import { SportIcon } from "./menu.jsx";

const SLIP_KEY = "pb.betslip";
const STAKE_KEY = "pb.betslipStake";

const BetslipContext = createContext(null);

export function betId(sport, matchId, period, group, line, outcomeKey) {
  return `${sport}:${matchId}:${period || "ft"}:${group}:${line ?? ""}:${outcomeKey}`;
}

function findLiveQuote(boards, item) {
  const board = boards?.[item.sport];
  if (!board) return null;
  const match = (board.matches || []).find((m) => String(m.id) === String(item.matchId));
  if (!match) return null;

  // Board-level main markets (always ft)
  if ((item.period || "ft") === "ft") {
    if (item.group === "1X2" || item.group === "Pobednik") {
      const p = match.ml?.[item.outcomeKey];
      const mx = match.merkur?.ml?.[item.outcomeKey];
      if (p || mx) {
        return {
          pinnacle: p?.odds ?? item.pinnacle,
          fair: p?.fair ?? item.fair,
          merkur: mx?.odds ?? null,
          ev: mx?.ev ?? null,
        };
      }
    }
    if (item.sport === "football" && item.group === "Ukupno golova" && match.goals && match.goals.line === item.line) {
      return {
        pinnacle: match.goals.pinnacle?.[item.outcomeKey] ?? item.pinnacle,
        fair: match.goals.fair?.[item.outcomeKey] ?? item.fair,
        merkur: match.goals.merkur?.[item.outcomeKey] ?? null,
        ev: match.goals.ev?.[item.outcomeKey] ?? null,
      };
    }
    if (item.sport !== "football") {
      if (item.group.startsWith("Hendikep") && match.spread && match.spread.line === item.line) {
        return {
          pinnacle: match.spread.pinnacle?.[item.outcomeKey] ?? item.pinnacle,
          fair: match.spread.fair?.[item.outcomeKey] ?? item.fair,
          merkur: match.spread.merkur?.[item.outcomeKey] ?? null,
          ev: match.spread.ev?.[item.outcomeKey] ?? null,
        };
      }
      if (item.group.startsWith("Ukupno") && match.total && match.total.line === item.line) {
        return {
          pinnacle: match.total.pinnacle?.[item.outcomeKey] ?? item.pinnacle,
          fair: match.total.fair?.[item.outcomeKey] ?? item.fair,
          merkur: match.total.merkur?.[item.outcomeKey] ?? null,
          ev: match.total.ev?.[item.outcomeKey] ?? null,
        };
      }
    }
  }

  // Fallback to board.values for any value outcome
  const val = (board.values || []).find(
    (v) =>
      String(v.matchId) === String(item.matchId)
      && (v.period || "ft") === (item.period || "ft")
      && v.group === item.group
      && (v.line ?? null) === (item.line ?? null)
      && v.key === item.outcomeKey,
  );
  if (val) {
    return {
      pinnacle: val.pinnacle ?? item.pinnacle,
      fair: val.fair ?? item.fair,
      merkur: val.merkur ?? item.merkur,
      ev: val.ev ?? item.ev,
    };
  }
  return null;
}

export function BetslipProvider({ boards, children }) {
  const [items, setItems] = useState(() => {
    const stored = readStored(SLIP_KEY, []);
    return Array.isArray(stored) ? stored : [];
  });
  const [open, setOpen] = useState(false);

  useEffect(() => writeStored(SLIP_KEY, items), [items]);
  useEffect(() => {
    document.body.classList.toggle("slip-picking", open);
    return () => document.body.classList.remove("slip-picking");
  }, [open]);

  const toggle = useCallback((leg) => {
    if (!(leg.pinnacle > 0) && !(leg.merkur > 0)) return;
    const id = betId(leg.sport, leg.matchId, leg.period, leg.group, leg.line, leg.outcomeKey);
    const matchKey = `${leg.sport}:${leg.matchId}`;
    setItems((current) => {
      if (current.some((x) => x.id === id)) {
        return current.filter((x) => x.id !== id);
      }
      const nextItem = {
        ...leg,
        id,
        matchKey,
        period: leg.period || "ft",
        line: leg.line ?? null,
      };
      const idx = current.findIndex((x) => x.matchKey === matchKey);
      if (idx >= 0) {
        const copy = [...current];
        copy[idx] = nextItem;
        return copy;
      }
      return [...current, nextItem];
    });
  }, []);

  const remove = useCallback((id) => {
    setItems((current) => current.filter((x) => x.id !== id));
  }, []);

  const clear = useCallback(() => {
    setItems([]);
  }, []);

  const resolvedItems = useMemo(
    () => items.map((item) => {
      const live = findLiveQuote(boards, item);
      if (!live) return item;
      return { ...item, ...live };
    }),
    [items, boards],
  );

  const idSet = useMemo(() => new Set(resolvedItems.map((x) => x.id)), [resolvedItems]);
  const has = useCallback((id) => idSet.has(id), [idSet]);

  const totals = useMemo(() => {
    if (!resolvedItems.length) {
      return { pinTotal: null, mxTotal: null, fairTotal: null, mxVsPin: null, mxVsFair: null, missingMx: 0, missingPin: 0 };
    }
    const missingMx = resolvedItems.filter((x) => !(x.merkur > 0)).length;
    const missingPin = resolvedItems.filter((x) => !(x.pinnacle > 0)).length;
    const missingFair = resolvedItems.filter((x) => !(x.fair > 0)).length;
    const pinTotal = missingPin === 0 ? resolvedItems.reduce((acc, x) => acc * x.pinnacle, 1) : null;
    const mxTotal = missingMx === 0 ? resolvedItems.reduce((acc, x) => acc * x.merkur, 1) : null;
    const fairTotal = missingFair === 0 ? resolvedItems.reduce((acc, x) => acc * x.fair, 1) : null;
    const mxVsPin = mxTotal && pinTotal ? mxTotal / pinTotal - 1 : null;
    const mxVsFair = mxTotal && fairTotal ? mxTotal / fairTotal - 1 : null;
    return { pinTotal, mxTotal, fairTotal, mxVsPin, mxVsFair, missingMx, missingPin };
  }, [resolvedItems]);

  const value = useMemo(
    () => ({
      items: resolvedItems,
      open,
      setOpen,
      pickMode: open,
      toggle,
      remove,
      clear,
      has,
      ...totals,
    }),
    [resolvedItems, open, toggle, remove, clear, has, totals],
  );

  return <BetslipContext.Provider value={value}>{children}</BetslipContext.Provider>;
}

export function useBetslip() {
  return useContext(BetslipContext);
}

export function BetslipTopButton() {
  const slip = useBetslip();
  if (!slip) return null;
  const count = slip.items.length;
  const title = count && slip.pinTotal && slip.mxTotal
    ? `Tiket (${count}): PIN ${fmtOdds(slip.pinTotal)} vs MX ${fmtOdds(slip.mxTotal)} (${fmtEv(slip.mxVsPin)})`
    : "Tiket za poređenje ukupnih kvota (Pinnacle vs MerkurXtip)";
  return (
    <button
      type="button"
      className={`button ${slip.open ? "primary" : "ghost"} betslip-toggle`}
      onClick={() => slip.setOpen((v) => !v)}
      aria-pressed={slip.open}
      title={title}
    >
      Tiket{count > 0 && <span className="view-count">{count}</span>}
    </button>
  );
}

function fmtMarketLabel(item) {
  const signed = item.group.startsWith("Hendikep");
  const line = item.line != null ? ` ${fmtLine(item.line, signed)}` : "";
  const period = item.period && item.period !== "ft" && item.periodLabel ? ` (${item.periodLabel})` : "";
  return `${item.group}${line}${period}`;
}

export function BetslipDrawer({ onOpenMatch }) {
  const slip = useBetslip();
  const [stake, setStake] = useState(() => readStored(STAKE_KEY, ""));
  useEffect(() => writeStored(STAKE_KEY, stake), [stake]);

  if (!slip || !slip.open) return null;

  const stakeNum = Number(stake);
  const validStake = stake !== "" && Number.isFinite(stakeNum) && stakeNum > 0;
  const pinReturn = validStake && slip.pinTotal ? stakeNum * slip.pinTotal : null;
  const mxReturn = validStake && slip.mxTotal ? stakeNum * slip.mxTotal : null;
  const diffReturn = pinReturn != null && mxReturn != null ? mxReturn - pinReturn : null;

  return (
    <aside className="betslip" aria-label="Tiket">
      <header className="betslip-head">
        <div>
          <strong>Tiket <span className="view-count">{slip.items.length}</span></strong>
          <small>Klikni na kvotu u tabeli ili modalu da dodaš/ukloniš</small>
        </div>
        <div className="betslip-head-actions">
          {slip.items.length > 0 && (
            <button type="button" className="button ghost small" onClick={slip.clear}>
              Obriši sve
            </button>
          )}
          <button type="button" className="icon-button" onClick={() => slip.setOpen(false)} aria-label="Zatvori tiket">
            ✕
          </button>
        </div>
      </header>

      <div className="betslip-body">
        {!slip.items.length ? (
          <p className="betslip-empty">
            Tiket je prazan. Dok je otvoren, klik na bilo koju kvotu u tabeli dodaje par na tiket.
          </p>
        ) : (
          <ul className="betslip-list">
            {slip.items.map((item) => (
              <li key={item.id} className="betslip-item">
                <div className="betslip-item-top">
                  <button
                    type="button"
                    className="betslip-match-btn"
                    onClick={() => onOpenMatch?.({ sport: item.sport, matchId: item.matchId })}
                    title="Otvori sve kvote za meč"
                  >
                    <SportIcon sport={item.sport} />
                    <span>
                      <b>{item.home} – {item.away}</b>
                      {item.starts && <small>{fmtKickoffShort(new Date(item.starts))}</small>}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="icon-button betslip-rm"
                    onClick={() => slip.remove(item.id)}
                    aria-label={`Ukloni ${item.home} – ${item.away}`}
                  >
                    ✕
                  </button>
                </div>
                <div className="betslip-item-pick">
                  <span>{fmtMarketLabel(item)}</span>
                  <strong>{item.label}</strong>
                </div>
                <div className="betslip-item-odds">
                  <span>PIN <b>{fmtOdds(item.pinnacle)}</b></span>
                  <span>
                    MX{" "}
                    <b className={item.ev != null && item.ev >= 0 ? "mx-fair-txt" : item.merkur && item.pinnacle && item.merkur > item.pinnacle ? "mx-above-txt" : ""}>
                      {item.merkur ? fmt2(item.merkur) : "—"}
                    </b>
                  </span>
                  {item.fair ? <span className="muted">Fer {fmtOdds(item.fair)}</span> : null}
                  {item.ev != null && (
                    <span className={`ev-chip ${evClass(item.ev)}`}>{fmtEv(item.ev)}</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {slip.items.length > 0 && (
        <footer className="betslip-foot">
          {(slip.missingMx > 0 || slip.missingPin > 0) && (
            <p className="betslip-warn">
              {slip.missingMx > 0 && `MerkurXtip nema kvotu za ${slip.missingMx} ${slip.missingMx === 1 ? "par" : "para"}. `}
              {slip.missingPin > 0 && `Pinnacle nema kvotu za ${slip.missingPin} ${slip.missingPin === 1 ? "par" : "para"}.`}
            </p>
          )}
          <div className="betslip-totals">
            <div className="betslip-total-box">
              <span>Pinnacle ukupno</span>
              <strong>{slip.pinTotal ? fmtOdds(slip.pinTotal) : "—"}</strong>
            </div>
            <div className="betslip-total-box">
              <span>MerkurXtip ukupno</span>
              <strong className={slip.mxVsFair != null && slip.mxVsFair >= 0 ? "mx-fair-txt" : slip.mxVsPin != null && slip.mxVsPin > 0 ? "mx-above-txt" : ""}>
                {slip.mxTotal ? fmtOdds(slip.mxTotal) : "—"}
              </strong>
            </div>
            <div className="betslip-total-box">
              <span>Fer ukupno</span>
              <strong className="muted">{slip.fairTotal ? fmtOdds(slip.fairTotal) : "—"}</strong>
            </div>
          </div>

          <div className="betslip-diffs">
            <div>
              <span>MX vs PIN:</span>
              <b className={slip.mxVsPin != null && slip.mxVsPin > 0 ? "edge-pos-txt" : slip.mxVsPin != null && slip.mxVsPin < 0 ? "edge-neg-txt" : ""}>
                {fmtEv(slip.mxVsPin)}
              </b>
            </div>
            <div>
              <span>MX vs fer:</span>
              <span className={`ev-chip ${evClass(slip.mxVsFair)}`}>{fmtEv(slip.mxVsFair)}</span>
            </div>
          </div>

          <div className="betslip-stake">
            <label>
              Ulog
              <input
                type="number"
                min="0"
                step="any"
                placeholder="npr. 1000"
                value={stake}
                onChange={(e) => setStake(e.target.value)}
              />
            </label>
            {validStake && (
              <div className="betslip-payouts">
                <span>PIN: <b>{pinReturn != null ? pinReturn.toFixed(2) : "—"}</b></span>
                <span>MX: <b>{mxReturn != null ? mxReturn.toFixed(2) : "—"}</b></span>
                {diffReturn != null && (
                  <span className={diffReturn >= 0 ? "edge-pos-txt" : "edge-neg-txt"}>
                    ({diffReturn >= 0 ? "+" : "−"}{Math.abs(diffReturn).toFixed(2)})
                  </span>
                )}
              </div>
            )}
          </div>
        </footer>
      )}
    </aside>
  );
}

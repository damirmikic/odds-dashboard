// Closing line value page (Alerti → CLV).
import { useEffect, useState } from "react";
import { readStored, requestJson, writeStored } from "./api.js";
import { LOCALE, evClass, fmtEv, fmtLine, fmtOdds } from "./format.js";

const CLV_SPORTS = { football: "Fudbal", basketball: "Košarka", tennis: "Tenis", hockey: "Hokej" };

const CLV_PERIODS = { ft: "", ht: "1. pol. ", q1: "1. čet. ", s1: "1. set ", p1: "1. per. ", p2: "2. per. ", p3: "3. per. " };

const clvDateFmt = new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

function ClvTable({ title, rows }) {
  if (!rows.length) return null;
  return (
    <div className="board-scroll">
      <table className="board clv-table">
        <thead>
          <tr><th>{title}</th><th>Signala</th><th>Prosečan CLV</th><th>CLV &gt; 0</th><th>Prednost pri signalu</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td className="col-match"><b>{CLV_SPORTS[r.name] || r.name}</b></td>
              <td>{r.n}</td>
              <td><span className={`ev-chip ${evClass(r.clv)}`}>{fmtEv(r.clv)}</span></td>
              <td>{r.positive != null ? `${Math.round(r.positive * 100)}%` : "—"}</td>
              <td>{fmtEv(r.ev)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Closing line value of the value outcomes the dashboard flagged (server: clv.py): MerkurXtip price at the signal
// against Pinnacle's last fair price before kickoff.
export function ClvPage() {
  const [days, setDays] = useState(() => readStored("pb.clvDays", 30));
  const [sport, setSport] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => writeStored("pb.clvDays", days), [days]);
  useEffect(() => {
    let stop = false;
    const load = () => requestJson(`/api/clv?days=${days}${sport ? `&sport=${sport}` : ""}`)
      .then((d) => { if (!stop) { setData(d); setError(""); } })
      .catch((err) => { if (!stop) setError(err.message); });
    load();
    const timer = setInterval(load, 30000);
    return () => { stop = true; clearInterval(timer); };
  }, [days, sport]);
  if (error) return <p className="state error">{error}</p>;
  if (!data) return <p className="state">Učitavanje…</p>;
  const total = data.total;
  return (
    <div className="alerts-page">
      <div className="filters">
        <label className="auto">
          Period
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90, 365].map((d) => <option key={d} value={d}>{d} dana</option>)}
          </select>
        </label>
        <div className="segmented">
          {[["", "Svi"], ["football", "Fudbal"], ["basketball", "Košarka"], ["tennis", "Tenis"], ["hockey", "Hokej"]].map(([key, label]) => (
            <button key={key} type="button" className={sport === key ? "active" : ""} onClick={() => setSport(key)}>{label}</button>
          ))}
        </div>
      </div>
      <p className="state clv-summary">
        Signal je ishod gde je MerkurXtip kvota bar {fmtEv(data.minEv)} iznad Pinnacle fer kvote kad ga je dashboard prvi put video.
        CLV = kvota pri signalu / poslednja Pinnacle fer kvota pre početka − 1. Zatvorenih: <b>{total.n}</b>
        {total.n > 0 && <> · prosečan CLV <span className={`ev-chip ${evClass(total.clv)}`}>{fmtEv(total.clv)}</span> · pozitivnih {Math.round(total.positive * 100)}%</>}
        {" "}· čeka početak meča: {data.pending}
        {data.unclosed > 0 && <> · bez zatvaranja (nije viđen u poslednjih 30 min pre početka): {data.unclosed}</>}
      </p>
      <ClvTable title="Sport" rows={data.bySport} />
      <ClvTable title="Tržište" rows={data.byGroup} />
      <ClvTable title="Liga" rows={data.byLeague} />
      {data.recent.length > 0 && (
        <div className="board-scroll">
          <table className="board clv-table">
            <thead>
              <tr><th>Viđeno</th><th>Meč</th><th>Tržište</th><th>Merkur</th><th>Fer pri signalu</th><th>Zatvaranje</th><th>CLV</th></tr>
            </thead>
            <tbody>
              {data.recent.map((r) => (
                <tr key={r.sig}>
                  <td>{clvDateFmt.format(new Date(r.seen_at))}</td>
                  <td className="col-match">
                    <b>{r.home} – {r.away}</b>
                    <span className="row-league">{r.league} · {clvDateFmt.format(new Date(r.starts))}</span>
                  </td>
                  <td>{CLV_PERIODS[r.period]}{r.grp}{r.line != null ? ` ${fmtLine(r.line, r.grp.startsWith("Hendikep"))}` : ""} <b>{r.label}</b></td>
                  <td><b>{fmtOdds(r.merkur)}</b></td>
                  <td>{fmtOdds(r.fair)}</td>
                  <td>{r.close_fair != null ? fmtOdds(r.close_fair) : "—"}</td>
                  <td>{r.clv != null ? <span className={`ev-chip ${evClass(r.clv)}`}>{fmtEv(r.clv)}</span> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

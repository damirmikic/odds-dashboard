// Search across every sport: the team search box with a dropdown of hits from all loaded boards.
import { useState } from "react";
import { evClass, fmtEv, fmtKickoffShort } from "./format.js";
import { CompBadge } from "./ui.jsx";
import { SPORTS, SportIcon } from "./menu.jsx";

const MAX_SHOWN = 12;

// Pinnacle and MerkurXtip names, so either spelling finds the match
export function matchesQuery(m, q) {
  return !q || `${m.home} ${m.away} ${m.merkur?.home || ""} ${m.merkur?.away || ""}`.toLocaleLowerCase().includes(q);
}

// boards: {sport: board}; hit counts per sport and every hit by kickoff
export function searchAll(boards, query) {
  const q = query.trim().toLocaleLowerCase();
  const counts = {};
  const hits = [];
  if (!q) return { counts, hits };
  for (const { key } of SPORTS) {
    const board = boards[key];
    if (!board) continue;
    const comps = new Map((board.competitions || []).map((c) => [c.id, c]));
    const found = board.matches.filter((m) => matchesQuery(m, q));
    counts[key] = found.length;
    for (const m of found) hits.push({ sport: key, match: m, competition: comps.get(m.leagueId) });
  }
  hits.sort((a, b) => new Date(a.match.starts) - new Date(b.match.starts));
  return { counts, hits };
}

export function GlobalSearch({ query, setQuery, hits, onOpen }) {
  const [open, setOpen] = useState(false);
  const shown = hits.slice(0, MAX_SHOWN);
  const pick = (hit) => {
    setOpen(false);
    onOpen(hit);
  };
  return (
    <div className="search-wrap">
      <input
        className="search"
        type="search"
        placeholder="Pretraga timova…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "Enter" && shown.length) pick(shown[0]);
        }}
      />
      {open && query.trim() && (
        <div className="search-hits" role="listbox">
          {!shown.length && <p className="search-empty">Nema mečeva ni u jednom sportu.</p>}
          {shown.map((hit) => {
            const m = hit.match;
            const ev = m.merkur?.best?.ev;
            return (
              <button
                type="button"
                key={`${hit.sport}:${m.id}`}
                className="search-hit"
                role="option"
                // mousedown would blur the input and close the list before the click lands
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(hit)}
              >
                <SportIcon sport={hit.sport} />
                {hit.competition && <CompBadge competition={hit.competition} />}
                <span className="search-teams">{m.home} – {m.away}</span>
                <span className="search-time">{fmtKickoffShort(new Date(m.starts))}</span>
                {m.merkur
                  ? <span className={`search-ev ${evClass(ev)}`}>{fmtEv(ev)}</span>
                  : <span className="search-ev muted">nije u MX</span>}
              </button>
            );
          })}
          {hits.length > shown.length && <p className="search-empty">još {hits.length - shown.length}…</p>}
        </div>
      )}
    </div>
  );
}

// Side menu: sport icons with match counts and competitions grouped by country, favourites on top.
import { useState } from "react";
import { readStored, writeStored } from "./api.js";
import { evClass, fmtEv } from "./format.js";
import { CompBadge } from "./ui.jsx";

export const SPORTS = [
  { key: "football", label: "Fudbal", live: true },
  { key: "basketball", label: "Košarka", live: true },
  { key: "tennis", label: "Tenis", live: true },
  { key: "hockey", label: "Hokej", live: true },
  { key: "mma", label: "MMA", live: true },
];

// Line icons (24px grid, currentColor); the `sport-*` classes drive the hover animations in dashboard.css.
export function SportIcon({ sport }) {
  const shape = {
    football: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path className="ball-core" d="M12 8.2l3.6 2.6-1.4 4.2H9.8l-1.4-4.2z" />
        <path d="M12 8.2V3M15.6 10.8l4.8-1.6M14.2 15l2.8 4.4M9.8 15L7 19.4M8.4 10.8L3.6 9.2" />
      </>
    ),
    basketball: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3v18M3 12h18M5.6 5.6c3.4 3.4 3.4 9.4 0 12.8M18.4 5.6c-3.4 3.4-3.4 9.4 0 12.8" />
      </>
    ),
    value: (
      <>
        <path d="M4 20h16M6 16l4-5 3 3 5-7" />
        <path d="M15 7h3v3" />
      </>
    ),
    alerts: (
      <>
        <path d="M6 16V11a6 6 0 0 1 12 0v5l1.6 2H4.4z" />
        <path d="M10 21h4" />
      </>
    ),
    tennis: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M5.2 5.2c4.3 3.3 4.3 10.3 0 13.6M18.8 5.2c-4.3 3.3-4.3 10.3 0 13.6" />
      </>
    ),
    hockey: (
      <>
        <path d="M7 3l6 13h6" />
        <ellipse cx="8" cy="20" rx="4" ry="1.6" />
      </>
    ),
    mma: (
      <>
        <path d="M7 11V7.5a3.5 3.5 0 0 1 3.5-3.5h3A3.5 3.5 0 0 1 17 7.5V14a4 4 0 0 1-4 4h-2a4 4 0 0 1-4-4z" />
        <path d="M7 11h5.5M8 18v3h8v-3" />
      </>
    ),
  }[sport];
  return (
    <svg className={`sport-icon sport-${sport}`} viewBox="0 0 24 24" width="24" height="24" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {shape}
    </svg>
  );
}

const FAVORITES_KEY = "pb.favoriteLeagues";
const byName = (a, b) => a.localeCompare(b, "sr", { sensitivity: "base" });

// Countries and their leagues alphabetically; starred leagues (per sport, kept in this browser) move to "Omiljene".
function sortedGroups(groups, favorites) {
  const visible = groups.map((group) => group.items.filter((item) => item.count !== 0 || item.active)).flat();
  const starred = visible.filter((item) => favorites.has(item.key));
  const rest = groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => (item.count !== 0 || item.active) && !favorites.has(item.key))
        .sort((a, b) => byName(a.comp.name, b.comp.name)),
    }))
    .filter((group) => group.items.length)
    .sort((a, b) => byName(a.title, b.title));
  const favoriteGroup = { title: "Omiljene", items: starred.sort((a, b) => byName(a.comp.name, b.comp.name)) };
  return starred.length ? [favoriteGroup, ...rest] : rest;
}

// `searching`: sportCounts are the search hits per sport, not the match counts
// `valueTab`: the all-sports Value screen ({count, active, onOpen}), shown before the alerts
export function SideMenu({ sport, onSport, sportCounts, searching, groups, all, onPick, label, alerts, valueTab }) {
  const [favoriteMap, setFavoriteMap] = useState(() => readStored(FAVORITES_KEY, {}) || {});
  const favorites = new Set(favoriteMap[sport] || []);
  const toggleFavorite = (key) => {
    setFavoriteMap((current) => {
      const keys = current[sport] || [];
      const next = { ...current, [sport]: keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key] };
      writeStored(FAVORITES_KEY, next);
      return next;
    });
  };
  return (
    <aside className="sidebar">
      <div className="sport-switch" role="tablist" aria-label="Sport">
        {SPORTS.map((item) => (
          <button
            type="button"
            key={item.key}
            role="tab"
            aria-selected={sport === item.key}
            className={`sport-btn${sport === item.key ? " active" : ""}`}
            disabled={!item.live}
            onClick={() => onSport(item.key)}
            title={item.live ? (searching ? `${item.label}: ${sportCounts?.[item.key] ?? 0} pogodaka pretrage` : item.label) : `${item.label} — uskoro`}
          >
            {sportCounts?.[item.key] != null && (
              <b className={`sport-count${searching ? " hits" : ""}`}>{sportCounts[item.key]}</b>
            )}
            <SportIcon sport={item.key} />
            <span>{item.label}</span>
          </button>
        ))}
        {valueTab && (
          <button
            type="button"
            role="tab"
            aria-selected={valueTab.active}
            className={`sport-btn${valueTab.active ? " active" : ""}`}
            onClick={valueTab.onOpen}
            title={`Value iz svih sportova: ${valueTab.count} ishoda gde je MX ≥ fer`}
          >
            {valueTab.count > 0 && <b className="sport-count">{valueTab.count}</b>}
            <SportIcon sport="value" />
            <span>Value</span>
          </button>
        )}
        {alerts && (
          <button
            type="button"
            role="tab"
            aria-selected={alerts.active}
            className={`sport-btn${alerts.active ? " active" : ""}`}
            onClick={alerts.onOpen}
            title="Padovi Pinnacle kvota"
          >
            {alerts.count > 0 && <b className="sport-count">{alerts.count}</b>}
            <SportIcon sport="alerts" />
            <span>Alerti</span>
          </button>
        )}
      </div>
      {all && <nav aria-label={label}>
        <button type="button" className={`side-item${all.active ? " active" : ""}`} onClick={() => onPick(all)}>
          <b>{all.label}</b> <span>{all.count}</span>
        </button>
        {sortedGroups(groups || [], favorites).map((group) => (
          <div className={`side-group${group.title === "Omiljene" ? " favorites" : ""}`} key={group.title}>
            <h3>{group.title}</h3>
            {group.items.map((item) => {
              const starred = favorites.has(item.key);
              return (
                <div className="side-row" key={item.key}>
                  <button
                    type="button"
                    className={`side-item${item.active ? " active" : ""}`}
                    onClick={() => onPick(item)}
                    disabled={item.disabled}
                    title={item.title}
                  >
                    <CompBadge competition={item.comp} /> <b>{item.comp.name}</b>
                    {item.extra && <em className={item.extraClass}>{item.extra}</em>}
                    <span>{item.count}</span>
                  </button>
                  <button
                    type="button"
                    className={`side-star${starred ? " on" : ""}`}
                    aria-pressed={starred}
                    aria-label={starred ? `Ukloni ${item.comp.name} iz omiljenih` : `Dodaj ${item.comp.name} u omiljene`}
                    title={starred ? "Ukloni iz omiljenih" : "Dodaj u omiljene"}
                    onClick={() => toggleFavorite(item.key)}
                  >
                    {starred ? "★" : "☆"}
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </nav>}
    </aside>
  );
}

// Competitions grouped by country for the side menu; with `valueSummary` the counts are value outcomes.
export function buildMenuGroups({ competitions, valueSummary, activeKey, activeLeague }) {
  const map = new Map();
  for (const c of competitions) {
    if (!map.has(c.country)) map.set(c.country, { title: c.country, items: [] });
    const row = valueSummary ? valueSummary.get(c.id) : null;
    map.get(c.country).items.push({
      id: c.id,
      key: c.key,
      comp: c,
      count: valueSummary ? (row ? row.count : 0) : c.count,
      extra: row ? fmtEv(row.best) : null,
      extraClass: row ? evClass(row.best) : "",
      disabled: valueSummary ? !row : !c.count,
      active: valueSummary ? activeLeague === String(c.id) : activeKey === c.key,
      title: row ? `${row.count} ishoda na ${row.matches.size} mečeva, najveća razlika vs fer ${fmtEv(row.best)}` : undefined,
    });
  }
  return [...map.values()];
}

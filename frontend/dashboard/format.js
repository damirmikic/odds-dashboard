// Formatting of odds, lines, percentages and times, and the colour classes of price cells.
export const LOCALE = "sr-Latn-RS";

export const timeFmt = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" });

export const clockFmt = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

const dayFmt = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" });

export const DAY_FILTERS = [
  ["all", "Sve"],
  ["today", "Danas"],
  ["tomorrow", "Sutra"],
  ["week", "7 dana"],
];

export function dayKey(date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

export function dayLabel(date) {
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  if (dayKey(date) === dayKey(today)) return "Danas";
  if (dayKey(date) === dayKey(tomorrow)) return "Sutra";
  const label = dayFmt.format(date);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function inDayFilter(date, filter) {
  if (filter === "all") return true;
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const days = (date - start) / 86400000;
  if (filter === "today") return days < 1;
  if (filter === "tomorrow") return days >= 1 && days < 2;
  return days < 7;
}

// Pinnacle quotes up to 3 decimals (1.578); show them as given, at least 2 decimals.
export function fmtOdds(value) {
  if (!value) return "—";
  const fixed = Number(value).toFixed(3);
  return fixed.endsWith("0") ? fixed.slice(0, -1) : fixed;
}

export function fmtLine(line, signed) {
  if (line == null) return "—";
  if (!signed) return String(line);
  if (line === 0) return "0";
  return line > 0 ? `+${line}` : `−${Math.abs(line)}`;
}

// Handicap/total line label; AH 0 is MerkurXtip "X vraća ulog" (draw no bet).
export function marketLine(group, line) {
  if (line == null) return "";
  if (group === "Hendikep" && line === 0) return "0 · X vraća ulog";
  return fmtLine(line, group.startsWith("Hendikep"));
}

export function fmtMargins(mx, pin) {
  const fmt = (value) => (value != null ? `${value.toFixed(1)}%` : "—");
  return `${fmt(mx)} / ${fmt(pin)}`;
}

export function fmtPct(value, digits = 1) {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

export function movement(current, previous) {
  if (!current || !previous || current === previous) return "";
  return current > previous ? "up" : "down";
}

// ev = MerkurXtip odds / Pinnacle fair odds - 1; above zero the Merkur price beats the fair price.
export function fmtEv(ev) {
  if (ev == null) return "—";
  const pct = ev * 100;
  return `${pct > 0 ? "+" : pct < 0 ? "−" : ""}${Math.abs(pct).toFixed(1)}%`;
}

export function evClass(ev) {
  if (ev == null) return "";
  if (ev >= 0) return "edge-pos";
  if (ev >= -0.02) return "edge-near";
  return "edge-neg";
}

export function fmt2(value) {
  return value ? Number(value).toFixed(2) : "—";
}

export function fmtKickoffShort(date) {
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}. ${timeFmt.format(date)}`;
}

export function fmtLimit(value) {
  if (!value) return null;
  if (value >= 1e6) return `€${+(value / 1e6).toFixed(1)}M`;
  if (value >= 1000) return `€${Math.round(value / 1000)}K`;
  return `€${Math.round(value)}`;
}

export function pinnacleClass(odds, prev) {
  const move = movement(odds, prev);
  return move === "up" ? "pin-up" : move === "down" ? "pin-down" : "";
}

// MerkurXtip cell: red = at/above Pinnacle fair, amber = above the Pinnacle price, purple = MX price changed.
export function merkurClass(odds, pinnacle, ev, prev) {
  const classes = [];
  if (ev != null && ev >= 0) classes.push("mx-fair");
  else if (odds && pinnacle && odds > pinnacle) classes.push("mx-above");
  if (prev && odds && prev !== odds) classes.push("mx-moved");
  return classes.join(" ");
}

export function merkurTitle(odds, pinnacle, fair, ev, prev) {
  return [
    `Pinnacle ${fmtOdds(pinnacle)}`,
    `fer ${fmtOdds(fair)}`,
    `razlika ${fmtEv(ev)}`,
    prev && prev !== odds ? `prethodna MX ${fmtOdds(prev)}` : null,
  ].filter(Boolean).join(" · ");
}

// today as a clock time, earlier days with the date
export function fmtWhen(date) {
  return dayKey(date) === dayKey(new Date()) ? timeFmt.format(date) : fmtKickoffShort(date);
}

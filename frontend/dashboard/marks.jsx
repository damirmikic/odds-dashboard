// Value marks: what was done about a value outcome, stored on the server and shared by every user (polled).
import { useState, useSyncExternalStore } from "react";
import { requestJson } from "./api.js";
import { fmt2 } from "./format.js";

export const MARK_STATUSES = [
  ["done", "Urađeno"],
  ["deposit", "Ostavljeno zbog uplate"],
  ["blocked", "Blokiran u ponudi"],
  ["nochange", "Ne povlači promene"],
  ["custom", "Ostalo…"],
];
const STATUS_LABEL = Object.fromEntries(MARK_STATUSES);
const POLL_MS = 15000;

let marks = {};
const listeners = new Set();
let timer = null;

function emit() {
  listeners.forEach((listener) => listener());
}

async function load() {
  try {
    const result = await requestJson("/api/marks");
    marks = result.marks || {};
  } catch {
    /* server down: the boards show that; the next poll retries */
  }
  emit();
}

const store = {
  subscribe(listener) {
    listeners.add(listener);
    if (listeners.size === 1) {
      load();
      timer = setInterval(load, POLL_MS);
    }
    return () => {
      listeners.delete(listener);
      if (!listeners.size) clearInterval(timer);
    };
  },
  get: () => marks,
};

export function useMarks() {
  return useSyncExternalStore(store.subscribe, store.get);
}

// The same outcome across refreshes: sport, match, period, market, line, outcome.
export function markKey(sport, v) {
  return [sport, v.matchId, v.period || "ft", v.group, v.line ?? "", v.key].join("|");
}

async function saveMark(body) {
  const before = marks;
  marks = { ...marks };
  if (body.status) marks[body.key] = { status: body.status, note: body.note || "", merkur: body.merkur, user: "", at: new Date().toISOString() };
  else delete marks[body.key];
  emit();
  try {
    const result = await requestJson("/api/marks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    marks = { ...marks };
    if (result.mark) marks[body.key] = result.mark;
    emit();
  } catch (err) {
    marks = before;
    emit();
    window.alert(`Oznaka nije sačuvana: ${err.message}`);
  }
}

export function markLabel(mark) {
  return mark.status === "custom" ? mark.note : STATUS_LABEL[mark.status] || mark.status;
}

// Status picker in a Value row: the fixed statuses, or "Ostalo…" with a note of one's own.
// Render it with key={markKey(...) + mark status/note} so a mark changed by someone else resets the local draft.
export function MarkCell({ sport, value, match, mark }) {
  const [custom, setCustom] = useState(mark?.status === "custom");
  const [note, setNote] = useState(mark?.status === "custom" ? mark.note : "");
  const key = markKey(sport, value);
  const save = (status, text = "") =>
    saveMark({ key, sport, starts: match?.starts, status, note: text, merkur: value.merkur });
  const onSelect = (event) => {
    const status = event.target.value;
    if (status === "custom") {
      setCustom(true);
      return;
    }
    setCustom(false);
    save(status);
  };
  const saveNote = () => {
    const text = note.trim();
    if (text && text !== mark?.note) save("custom", text);
    if (!text && !mark) setCustom(false);
  };
  const moved = mark && mark.merkur != null && value.merkur != null && Math.abs(mark.merkur - value.merkur) > 1e-9;
  const title = mark
    ? `${markLabel(mark)} · ${new Date(mark.at).toLocaleString("sr-RS")}${mark.user ? ` · ${mark.user}` : ""}` +
      (mark.merkur != null ? ` · MX kvota pri označavanju ${fmt2(mark.merkur)}` : "")
    : "Označi šta je urađeno sa ovim ishodom (vide svi korisnici)";
  return (
    <div className="mark-cell" title={title} onClick={(event) => event.stopPropagation()}>
      <select value={custom ? "custom" : mark?.status || ""} onChange={onSelect}
        className={mark ? `mark-select mark-${mark.status}` : "mark-select"}>
        <option value="">—</option>
        {MARK_STATUSES.map(([status, label]) => <option key={status} value={status}>{label}</option>)}
      </select>
      {custom && (
        <input className="mark-note" value={note} maxLength={200} placeholder="Napomena…" autoFocus={!mark}
          onChange={(event) => setNote(event.target.value)} onBlur={saveNote}
          onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()} />
      )}
      {moved && <small className="mark-moved">MX kvota promenjena ({fmt2(mark.merkur)} → {fmt2(value.merkur)})</small>}
    </div>
  );
}

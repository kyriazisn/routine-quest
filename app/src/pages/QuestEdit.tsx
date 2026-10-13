/** C2 — Επεξεργασία quest */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../App";
import { AppBar, Button, Content, Field, Note, Screen } from "../components";
import type { Routine, RoutineIn } from "../types";
import { BUTTON_COLORS, BUTTON_NAMES, DAY_LABELS, TEMPLATES, hhmm, parseHhmm } from "../util";

interface Slot {
  on: boolean;
  icon: string;
  label: string;
}

export function QuestEdit() {
  const { child } = useApp();
  const { id } = useParams();
  const nav = useNavigate();
  const [all, setAll] = useState<Routine[]>();
  const [r, setR] = useState<RoutineIn>();
  const [slots, setSlots] = useState<Slot[]>([]);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.routines(child.id).then((list) => {
      setAll(list);
      const existing = list.find((x) => String(x.id) === id);
      const base: RoutineIn = existing ?? { ...TEMPLATES[list.length % 2], name: "Νέο quest" };
      setR(base);
      setSlots([0, 1, 2, 3].map((b) => {
        const s = base.steps.find((x) => x.button === b);
        return { on: !!s, icon: s?.icon ?? "⭐", label: s?.label ?? "" };
      }));
    }, (e) => setError(String(e.message ?? e)));
  }, [child.id, id]);

  if (!r || !all) return <Screen><AppBar title="Quest" back /><Content>{error ? <Note tone="error">{error}</Note> : <p aria-busy="true">…</p>}</Content></Screen>;

  async function save() {
    if (!r || !all) return;
    setBusy(true);
    setError(undefined);
    const steps = slots.flatMap((s, button) => (s.on ? [{ button, icon: s.icon || "⭐", label: s.label.trim() || BUTTON_NAMES[button] }] : []));
    const edited: RoutineIn = { ...r, steps };
    const others = all.filter((x) => String(x.id) !== id);
    try {
      await api.putRoutines(child.id, [...others, edited].map((x) => ({ ...x, steps: x.steps.map(({ button, icon, label }) => ({ button, icon, label })) })));
      nav("/settings");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const set = (patch: Partial<RoutineIn>) => setR({ ...r, ...patch });
  return (
    <Screen>
      <AppBar title={r.name || "Quest"} back />
      <Content>
        <Field label="Όνομα" value={r.name} onChange={(name) => set({ name })} name="name" />
        <div className="row2">
          <Field label="Από" type="time" value={hhmm(r.start_min)} onChange={(v) => set({ start_min: parseHhmm(v) })} name="start" />
          <Field label="Έως" type="time" value={hhmm(r.end_min % 1440)} onChange={(v) => set({ end_min: parseHhmm(v) || 1440 })} name="end" />
        </div>
        <span className="field-label">Ημέρες</span>
        <div className="days" role="group" aria-label="Ημέρες">
          {DAY_LABELS.map((d, i) => {
            const on = (r.days_mask >> i) & 1;
            return (
              <button key={i} className={`day${on ? " on" : ""}`} aria-pressed={!!on}
                aria-label={["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"][i]}
                onClick={() => set({ days_mask: r.days_mask ^ (1 << i) || r.days_mask })}>{d}</button>
            );
          })}
        </div>
        <span className="field-label">Βήματα · κουμπί → εικονίδιο (έως 4)</span>
        {slots.map((s, b) => (
          <div key={b} className={`slot${s.on ? "" : " off"}`}>
            <input type="checkbox" checked={s.on} aria-label={`Κουμπί ${b + 1} ενεργό`}
              onChange={(e) => setSlots(slots.map((x, j) => (j === b ? { ...x, on: e.target.checked } : x)))} />
            <span className="slot-dot" style={{ background: BUTTON_COLORS[b] }} aria-hidden />
            <input className="slot-icon" value={s.icon} maxLength={4} aria-label={`Εικονίδιο κουμπιού ${b + 1}`}
              onChange={(e) => setSlots(slots.map((x, j) => (j === b ? { ...x, icon: e.target.value } : x)))} />
            <input className="slot-label" value={s.label} placeholder={`Κουμπί ${b + 1} · ${BUTTON_NAMES[b]}`}
              aria-label={`Βήμα κουμπιού ${b + 1}`}
              onChange={(e) => setSlots(slots.map((x, j) => (j === b ? { ...x, label: e.target.value } : x)))} />
          </div>
        ))}
        <p className="small muted">Το εικονίδιο ταιριάζει με το μισό αυτοκόλλητο ☀️/🌙 του κουμπιού.</p>
        {error && <Note tone="error">{error}</Note>}
        <Button onClick={save} disabled={busy || !slots.some((s) => s.on) || !r.name.trim()}>Αποθήκευση</Button>
      </Content>
    </Screen>
  );
}

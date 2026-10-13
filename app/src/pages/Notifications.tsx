/** C3 — Ειδοποιήσεις */
import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import { AppBar, Button, Card, Content, Field, ListRow, Note, Screen } from "../components";
import { type PushState, enablePush, pushState } from "../push";
import type { NotifyMode, Routine } from "../types";
import { hhmm, parseHhmm } from "../util";

const MODES: [NotifyMode, string, string, string][] = [
  ["each_step", "🔔", "Κάθε βήμα", "Ειδοποίηση σε κάθε πάτημα"],
  ["complete_only", "🏁", "Μόνο ολοκλήρωση", "Προτεινόμενο"],
  ["mute", "🔕", "Σίγαση", "Καμία ειδοποίηση"],
];

export function Notifications() {
  const { child, me, refresh } = useApp();
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [push, setPush] = useState<PushState>();
  const [qs, setQs] = useState(me.parent.quiet_start_min !== null ? hhmm(me.parent.quiet_start_min) : "");
  const [qe, setQe] = useState(me.parent.quiet_end_min !== null ? hhmm(me.parent.quiet_end_min) : "");
  const [msg, setMsg] = useState<string>();

  useEffect(() => {
    void api.routines(child.id).then(setRoutines);
    void pushState().then(setPush);
  }, [child.id]);

  async function patch(r: Routine, b: { notify_mode?: NotifyMode; notify_expired?: boolean }) {
    const updated = await api.patchNotifications(r.id, b);
    setRoutines(routines.map((x) => (x.id === r.id ? updated : x)));
  }

  async function saveQuiet() {
    await api.patchMe({ quiet_start_min: qs ? parseHhmm(qs) : null, quiet_end_min: qe ? parseHhmm(qe) : null });
    await refresh();
    setMsg("Αποθηκεύτηκε");
  }

  return (
    <Screen>
      <AppBar title="Ειδοποιήσεις" back="/settings" />
      <Content>
        {push !== "subscribed" && (
          <Card title="Οι ειδοποιήσεις είναι ανενεργές σε αυτή τη συσκευή">
            <Button onClick={() => enablePush().then(setPush, (e) => setMsg(String(e.message ?? e)))}>Ενεργοποίηση</Button>
          </Card>
        )}
        {routines.map((r) => (
          <div key={r.id} className="stack">
            <span className="field-label">{r.icon} {r.name}</span>
            {MODES.map(([mode, icon, title, sub]) => (
              <ListRow key={mode} icon={icon} title={title} subtitle={sub} trailing={r.notify_mode === mode ? "●" : "○"}
                onClick={() => patch(r, { notify_mode: mode })} />
            ))}
            <ListRow icon="⏰" title="Αν δεν ολοκληρωθεί" subtitle="Στη λήξη του παραθύρου"
              trailing={r.notify_expired ? "On" : "Off"} onClick={() => patch(r, { notify_expired: !r.notify_expired })} />
          </div>
        ))}
        <span className="field-label">Ώρες ησυχίας (μόνο για εσένα)</span>
        <div className="row2">
          <Field label="Από" type="time" value={qs} onChange={setQs} name="quiet-start" />
          <Field label="Έως" type="time" value={qe} onChange={setQe} name="quiet-end" />
        </div>
        <Button variant="secondary" onClick={saveQuiet}>Αποθήκευση ωρών ησυχίας</Button>
        {msg && <Note tone="ok">{msg}</Note>}
        <Card title="Προεπισκόπηση">
          <p className="muted">🎉 {child.nickname} ολοκλήρωσε: {routines[0]?.name ?? "Πρωινό quest"}!</p>
        </Card>
      </Content>
    </Screen>
  );
}

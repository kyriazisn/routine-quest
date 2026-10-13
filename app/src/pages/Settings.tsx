/** C6 — Ρυθμίσεις */
import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../App";
import { AppBar, Button, Card, Content, Field, ListRow, Note, Screen, TabBar } from "../components";
import type { Routine, Today } from "../types";
import { hhmm } from "../util";

export function Settings() {
  const { child, me } = useApp();
  const nav = useNavigate();
  const [t, setT] = useState<Today>();
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [invite, setInvite] = useState("");
  const [confirmDelete, setConfirmDelete] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string }>();

  const load = () => {
    void api.today(child.id).then(setT);
    void api.routines(child.id).then(setRoutines);
  };
  useEffect(load, [child.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const device = t?.devices[0];

  async function togglePause() {
    if (!t) return;
    await (t.paused ? api.unpause(child.id, t.date) : api.pause(child.id, t.date));
    load();
  }

  async function sendInvite(e: FormEvent) {
    e.preventDefault();
    await api.invite(invite.trim());
    setMsg({ tone: "ok", text: `Στάλθηκε πρόσκληση στο ${invite.trim()}.` });
    setInvite("");
  }

  async function exportData() {
    const data = await api.exportData();
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "routine-quest-export.json" });
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Screen tabs>
      <AppBar title="Ρυθμίσεις" leading="⚙️" />
      <Content>
        {device ? (
          <Card title={`📟 Συσκευή ${device.device_id.slice(-4).toUpperCase()}`}>
            <p className="muted">{device.online ? "Online" : "Offline"} · FW {device.fw_version ?? "?"}</p>
            <div className="row2">
              <label className="field"><span className="field-label">Ένταση</span>
                <select value={device.volume} onChange={(e) => api.patchDevice(device.id, { volume: Number(e.target.value) }).then(load)}>
                  {["Σίγαση", "Χαμηλή", "Μεσαία", "Δυνατή"].map((l, i) => <option key={i} value={i}>{l}</option>)}
                </select>
              </label>
              <label className="field"><span className="field-label">Φωτεινότητα</span>
                <select value={device.brightness} onChange={(e) => api.patchDevice(device.id, { brightness: Number(e.target.value) }).then(load)}>
                  {["Ελάχιστη", "Χαμηλή", "Μεσαία", "Υψηλή"].map((l, i) => <option key={i} value={i}>{l}</option>)}
                </select>
              </label>
            </div>
            <Button variant="secondary" onClick={() => {
              if (window.confirm("Αποσύνδεση της συσκευής; Θα χρειαστεί νέα σύνδεση (κουμπιά 1+4 για 10″).")) {
                void api.revokeDevice(device.id).then(load);
              }
            }}>Αποσύνδεση συσκευής</Button>
          </Card>
        ) : (
          <ListRow icon="📟" title="Σύνδεση συσκευής" subtitle="Δεν υπάρχει συνδεδεμένη συσκευή" trailing="›" onClick={() => nav("/setup/pair")} />
        )}

        <span className="field-label">Quests</span>
        {routines.map((r) => (
          <ListRow key={r.id} icon={r.icon} title={r.name} subtitle={`${hhmm(r.start_min)}–${hhmm(r.end_min)} · ${r.steps.length} βήματα`}
            trailing="›" onClick={() => nav(`/quests/${r.id}`)} />
        ))}
        {routines.length < 2 && <Button variant="secondary" onClick={() => nav("/quests/new")}>+ Νέο quest</Button>}

        <ListRow icon="⏸️" title="Ημέρα εκτός" subtitle={t?.paused ? "Σήμερα είναι ημέρα εκτός — πάτα για αναίρεση" : "Παύση σήμερα χωρίς να σπάσει το streak"}
          trailing={t?.paused ? "On" : "Off"} onClick={togglePause} />
        <ListRow icon="🔔" title="Ειδοποιήσεις" subtitle="Ανά quest · ώρες ησυχίας" trailing="›" onClick={() => nav("/notifications")} />

        <span className="field-label">Γονείς</span>
        <p className="small muted">{me.parent.email}</p>
        <form className="stack" onSubmit={sendInvite}>
          <Field label="Πρόσκληση δεύτερου γονέα (email)" type="email" value={invite} onChange={setInvite} name="invite" />
          <Button variant="secondary" type="submit" disabled={!invite.includes("@")}>Αποστολή πρόσκλησης</Button>
        </form>

        <span className="field-label">Απόρρητο</span>
        <ListRow icon="📦" title="Λήψη δεδομένων" subtitle="Export JSON" trailing="›" onClick={exportData} />
        <ListRow icon="🚪" title="Αποσύνδεση" trailing="›" onClick={() => api.logout().then(() => location.assign("/"))} />
        <Card title="🗑️ Διαγραφή λογαριασμού & δεδομένων">
          <p className="muted small">Μη αναστρέψιμο. Διαγράφει παιδί, ιστορικό και συσκευές. Γράψε «ΔΙΑΓΡΑΦΗ».</p>
          <Field label="Επιβεβαίωση" value={confirmDelete} onChange={setConfirmDelete} name="confirm-delete" />
          <Button variant="danger" disabled={confirmDelete !== "ΔΙΑΓΡΑΦΗ"}
            onClick={() => api.deleteAccount().then(() => location.assign("/"))}>Οριστική διαγραφή</Button>
        </Card>
        {msg && <Note tone={msg.tone}>{msg.text}</Note>}
      </Content>
      <TabBar />
    </Screen>
  );
}

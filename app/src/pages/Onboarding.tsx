import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useMe } from "../App";
import { AppBar, Button, Card, Content, Field, ListRow, Note, Screen, Spacer } from "../components";
import { type PushState, enablePush, isIos, isStandalone, pushState } from "../push";
import { AVATARS, TEMPLATES, hhmm } from "../util";

/** O5 — Παιδί & πρώτα quests (moved before pairing: the claim code belongs to a child) */
export function ChildSetup() {
  const { refresh } = useMe();
  const nav = useNavigate();
  const [nickname, setNickname] = useState("");
  const [avatar, setAvatar] = useState(AVATARS[0]);
  const [use, setUse] = useState([true, true]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function save() {
    setBusy(true);
    setError(undefined);
    try {
      const child = await api.createChild(nickname.trim(), avatar);
      const chosen = TEMPLATES.filter((_, i) => use[i]);
      if (chosen.length) await api.putRoutines(child.id, chosen);
      await refresh();
      nav("/setup/push", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Screen>
      <AppBar title="Ο ήρωάς μας" />
      <Content>
        <Field label="Ψευδώνυμο παιδιού" value={nickname} onChange={setNickname} placeholder="π.χ. Λένα" name="nickname" />
        <span className="field-label">Avatar</span>
        <div className="avatars" role="radiogroup" aria-label="Avatar">
          {AVATARS.map((a) => (
            <button key={a} role="radio" aria-checked={a === avatar} className={`avatar${a === avatar ? " on" : ""}`}
              onClick={() => setAvatar(a)}>
              {a}
            </button>
          ))}
        </div>
        <span className="field-label">Ξεκίνα με έτοιμα quests (αλλάζουν μετά)</span>
        {TEMPLATES.map((t, i) => (
          <ListRow key={t.name} icon={t.icon} title={`${t.name} · ${hhmm(t.start_min)}–${hhmm(t.end_min)}`}
            subtitle={t.steps.map((s) => s.label).join(" · ")} trailing={use[i] ? "✓" : "○"}
            onClick={() => setUse(use.map((u, j) => (j === i ? !u : u)))} />
        ))}
        <p className="small muted">
          Κρατάμε μόνο ψευδώνυμο και avatar — χωρίς ημερομηνία γέννησης, φωτογραφία ή επώνυμο.
        </p>
        {error && <Note tone="error">{error}</Note>}
        <Spacer />
        <Button onClick={save} disabled={busy || !nickname.trim()}>{busy ? "…" : "Συνέχεια"}</Button>
      </Content>
    </Screen>
  );
}

/** O2 — Εγκατάσταση & ειδοποιήσεις */
export function PushSetup() {
  const nav = useNavigate();
  const [state, setState] = useState<PushState>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    void pushState().then(setState);
  }, []);

  async function enable() {
    try {
      setState(await enablePush());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <Screen>
      <AppBar title="Ειδοποιήσεις" />
      <Content>
        <p className="lead">Για να σε ενημερώνουμε όταν τελειώνει ένα quest:</p>
        {isIos() && !isStandalone() && (
          <Card title="1 · Πρόσθεσε στην αρχική οθόνη">
            <p className="muted">Πάτα Κοινοποίηση ⬆️ → «Προσθήκη στην οθόνη Αφετηρίας» και άνοιξε την εφαρμογή από εκεί.</p>
          </Card>
        )}
        <Card title={isIos() && !isStandalone() ? "2 · Επίτρεψε ειδοποιήσεις" : "Επίτρεψε ειδοποιήσεις"}>
          <p className="muted">Στέλνουμε μόνο ειδοποιήσεις quest. Αλλάζουν όποτε θέλεις.</p>
        </Card>
        {state === "subscribed" && <Note tone="ok">✓ Οι ειδοποιήσεις είναι ενεργές.</Note>}
        {state === "denied" && <Note tone="error">Οι ειδοποιήσεις είναι μπλοκαρισμένες στις ρυθμίσεις του browser.</Note>}
        {state === "unsupported" && <Note>Αυτός ο browser δεν υποστηρίζει ειδοποιήσεις.</Note>}
        {error && <Note tone="error">{error}</Note>}
        <Spacer />
        {state !== "subscribed" && state !== "needs-install" && state !== "unsupported" && (
          <Button onClick={enable}>Ενεργοποίηση ειδοποιήσεων</Button>
        )}
        <Button variant="secondary" onClick={() => nav("/setup/pair")}>
          {state === "subscribed" ? "Συνέχεια" : "Αργότερα"}
        </Button>
      </Content>
    </Screen>
  );
}

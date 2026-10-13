/** O3 + O4 — Σύνδεση συσκευής (BLE provisioning) και Wi-Fi */
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../App";
import { AppBar, Button, Card, Content, Field, ListRow, Note, Screen, Spacer } from "../components";
import type { WifiNetwork } from "../provisioning/messages";
import { ProvisioningClient } from "../provisioning/provision";
import { BleTransport, HttpTransport, type Transport, bleSupported } from "../provisioning/transport";

type Phase = "intro" | "pop" | "wifi" | "working" | "waiting" | "done";

// Test/dev hook: ?sim=<url> uses the HTTP device simulator. Only compiled in when VITE_ALLOW_SIM=1.
const simUrl = (): string | null =>
  import.meta.env.VITE_ALLOW_SIM === "1" ? new URLSearchParams(location.search).get("sim") : null;

const FAIL_TEXT: Record<string, string> = {
  auth_error: "Λάθος κωδικός Wi-Fi.",
  network_not_found: "Η συσκευή δεν βρίσκει αυτό το δίκτυο. Είναι 2.4 GHz και κοντά;",
};

export function Pair() {
  const { child } = useApp();
  const nav = useNavigate();
  const [phase, setPhase] = useState<Phase>("intro");
  const [pop, setPop] = useState("");
  const [nets, setNets] = useState<WifiNetwork[]>([]);
  const [ssid, setSsid] = useState("");
  const [pass, setPass] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string>();
  const transport = useRef<Transport | null>(null);
  const client = useRef<ProvisioningClient | null>(null);
  const deviceName = useRef("");

  useEffect(() => () => void client.current?.close(), []);

  async function connectDevice() {
    setError(undefined);
    try {
      const sim = simUrl();
      if (sim) {
        transport.current = new HttpTransport(sim);
        deviceName.current = "RQ-SIM";
      } else {
        const t = await BleTransport.request();
        transport.current = t;
        deviceName.current = t.deviceName;
      }
      setPhase("pop");
    } catch (e) {
      if (e instanceof DOMException && e.name === "NotFoundError") return; // user closed the chooser
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function startSession(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    setStatus("Ασφαλής σύνδεση με τη συσκευή…");
    try {
      client.current = await ProvisioningClient.connect(transport.current!, pop.trim());
      setStatus("Αναζήτηση δικτύων…");
      const found = await client.current.scan().catch(() => []);
      setNets(found);
      setSsid(found[0]?.ssid ?? "");
      setStatus("");
      setPhase("wifi");
    } catch (err) {
      setStatus("");
      const code = (err as { code?: string }).code;
      setError(code === "pop" || code === "device_status" ? "Λάθος κωδικός συσκευής. Δες το αυτοκόλλητο κάτω από τη συσκευή." : String(err));
    }
  }

  async function sendWifi(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    setPhase("working");
    try {
      setStatus("Σύνδεση της συσκευής με τον λογαριασμό σου…");
      const { code } = await api.claimCode(child.id);
      await client.current!.sendClaimCode(code);
      setStatus("Αποστολή στοιχείων Wi-Fi στη συσκευή…");
      await client.current!.setWifi(ssid, pass);
      setStatus("Η συσκευή συνδέεται στο Wi-Fi…");
      const r = await client.current!.waitConnected();
      if (!r.ok) {
        setError(FAIL_TEXT[r.reason ?? ""] ?? "Η συσκευή δεν συνδέθηκε. Ξαναδοκίμασε.");
        setPhase("wifi");
        return;
      }
      await client.current!.close();
      setPhase("waiting");
      setStatus("Περιμένουμε τη συσκευή να εμφανιστεί online…");
      for (let i = 0; i < 60; i++) {
        const t = await api.today(child.id);
        if (t.devices.length > 0) {
          setPhase("done");
          return;
        }
        await new Promise((res) => setTimeout(res, 2000));
      }
      setError("Η συσκευή συνδέθηκε στο Wi-Fi αλλά δεν απάντησε ακόμα. Έλεγξε τη σύνδεση internet και ξαναδοκίμασε.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("wifi");
    }
  }

  return (
    <Screen>
      <AppBar title={phase === "wifi" || phase === "working" ? "Wi-Fi σπιτιού" : "Βρες τη συσκευή"} back="/" />
      <Content>
        {phase === "intro" && (
          <>
            <Card title="Σύνδεσε τη συσκευή στο ρεύμα">
              <p className="muted">Όταν το δαχτυλίδι αναβοσβήνει πορτοκαλί, είναι έτοιμη για σύνδεση.</p>
            </Card>
            {!bleSupported() && !simUrl() ? (
              <Note tone="error">
                Αυτός ο browser δεν υποστηρίζει Bluetooth. Χρησιμοποίησε Chrome σε Android ή υπολογιστή.
              </Note>
            ) : (
              <>
                <Spacer />
                <Button onClick={connectDevice}>Αναζήτηση συσκευής</Button>
              </>
            )}
          </>
        )}

        {phase === "pop" && (
          <form className="stack" onSubmit={startSession}>
            <ListRow icon="📟" title={`Routine Quest · ${deviceName.current}`} subtitle="Βρέθηκε" />
            <Field label="Κωδικός συσκευής (αυτοκόλλητο κάτω από τη συσκευή)" value={pop} onChange={setPop}
              name="pop" autoComplete="off" />
            {status && <p className="muted" aria-busy="true">{status}</p>}
            <Button type="submit" disabled={!pop.trim() || !!status}>Σύνδεση</Button>
          </form>
        )}

        {(phase === "wifi" || phase === "working") && (
          <form className="stack" onSubmit={sendWifi}>
            {nets.length > 0 ? (
              <label className="field">
                <span className="field-label">Δίκτυο</span>
                <select value={ssid} onChange={(e) => setSsid(e.target.value)} name="ssid">
                  {nets.map((n) => (
                    <option key={n.ssid} value={n.ssid}>
                      {n.ssid} {n.auth === 0 ? "(ανοιχτό)" : "🔒"}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <Field label="Δίκτυο (όνομα)" value={ssid} onChange={setSsid} name="ssid" />
            )}
            <Field label="Κωδικός Wi-Fi" type="password" value={pass} onChange={setPass} name="wifi-password"
              autoComplete="off" />
            <Card title="🔒 Μένει μόνο στη συσκευή">
              <p className="muted">Τα στοιχεία Wi-Fi πηγαίνουν κρυπτογραφημένα απευθείας στη συσκευή. Δεν αποθηκεύονται στο cloud.</p>
            </Card>
            {status && <p className="muted" aria-busy="true">{status}</p>}
            <Button type="submit" disabled={phase === "working" || !ssid}>Σύνδεση</Button>
          </form>
        )}

        {phase === "waiting" && <p className="muted" aria-busy="true">{status}</p>}

        {phase === "done" && (
          <>
            <Note tone="ok">🎉 Η συσκευή είναι online και συνδεδεμένη με τον λογαριασμό σου.</Note>
            <Spacer />
            <Button onClick={() => nav("/", { replace: true })}>Ξεκινάμε! 🚀</Button>
          </>
        )}

        {error && <Note tone="error">{error}</Note>}
      </Content>
    </Screen>
  );
}

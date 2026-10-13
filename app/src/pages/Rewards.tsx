/** C5 — Rewards */
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import { AppBar, Button, Card, Content, Field, ListRow, Note, Progress, Screen, TabBar } from "../components";
import type { Rewards } from "../types";

const IDEAS = ["📖 Διαλέγει το παραμύθι", "🛝 Βόλτα στην παιδική χαρά", "🍝 Διαλέγει το βραδινό", "🎲 Επιτραπέζιο με τον γονιό"];

export function RewardsPage() {
  const { child } = useApp();
  const [r, setR] = useState<Rewards>();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [icon, setIcon] = useState("🎁");
  const [cost, setCost] = useState("5");
  const [repeatable, setRepeatable] = useState(false);
  const [error, setError] = useState<string>();

  const load = useCallback(() => api.rewards(child.id).then(setR, (e) => setError(String(e.message ?? e))), [child.id]);
  useEffect(() => {
    void load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      setR(await api.createReward(child.id, { name: name.trim(), icon: icon || "🎁", cost: Number(cost), repeatable }));
      setAdding(false);
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const active = r?.rewards.find((x) => x.id === r.active_reward_id);
  const next = r?.rewards.filter((x) => x.id !== r.active_reward_id) ?? [];
  return (
    <Screen tabs>
      <AppBar title="Rewards" leading="🎁" />
      <Content>
        {error && <Note tone="error">{error}</Note>}
        {r && <ListRow icon="⭐" title={`Πορτοφόλι: ${r.stars} ${r.stars === 1 ? "αστέρι" : "αστέρια"}`} />}
        {active && r && (
          <>
            <span className="field-label">Ενεργός θησαυρός</span>
            <Card title={`${active.icon} ${active.name}`}>
              <p className="muted">
                {Math.min(r.stars, active.cost)} / {active.cost} ⭐
                {r.stars >= active.cost ? " — έτοιμο!" : ` — ακόμα ${active.cost - r.stars}`}
              </p>
              <Progress value={r.stars} max={active.cost} />
              <Button variant={r.stars >= active.cost ? "primary" : "secondary"} disabled={r.stars < active.cost}
                onClick={() => api.giveReward(active.id).then(setR, (e) => setError(String(e.message ?? e)))}>
                Δόθηκε ✓
              </Button>
            </Card>
          </>
        )}
        {next.length > 0 && <span className="field-label">Επόμενα</span>}
        {next.map((x) => (
          <ListRow key={x.id} icon={x.icon} title={x.name} subtitle={`${x.cost} ⭐ · ${x.repeatable ? "επαναλαμβανόμενο" : "μία φορά"}`}
            trailing="✕" onClick={() => api.archiveReward(x.id).then(setR)} />
        ))}
        {adding ? (
          <form className="stack" onSubmit={add}>
            <div className="row2">
              <Field label="Εικονίδιο" value={icon} onChange={setIcon} name="reward-icon" />
              <Field label="Κόστος ⭐" type="number" value={cost} onChange={setCost} name="reward-cost" />
            </div>
            <Field label="Τι θα κερδίσει" value={name} onChange={setName} name="reward-name" />
            <label className="check"><input type="checkbox" checked={repeatable} onChange={(e) => setRepeatable(e.target.checked)} /> Επαναλαμβανόμενο</label>
            <div className="chips">
              {IDEAS.map((idea) => (
                <button type="button" key={idea} className="chip" onClick={() => { setIcon(idea.split(" ")[0]); setName(idea.slice(idea.indexOf(" ") + 1)); }}>
                  {idea}
                </button>
              ))}
            </div>
            <Button type="submit" disabled={!name.trim() || !(Number(cost) >= 1)}>Προσθήκη</Button>
          </form>
        ) : (
          <Button variant="secondary" onClick={() => setAdding(true)}>+ Νέο reward</Button>
        )}
        <p className="small muted">Ένα ενεργό reward τη φορά. Προτίμησε ανταμοιβές με χρόνο μαζί, όχι πράγματα.</p>
      </Content>
      <TabBar />
    </Screen>
  );
}

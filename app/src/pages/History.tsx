/** C4 — Ιστορικό */
import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import { AppBar, Card, Content, ListRow, Note, Progress, Screen, TabBar } from "../components";
import type { HistoryDay, Today } from "../types";

const LEVEL_COLORS = ["λευκό", "πράσινο", "μπλε", "μωβ", "χρυσό"];

function dayIcon(d: HistoryDay): string {
  if (d.paused) return "⏸️";
  if (d.quests.length === 0) return "·";
  return d.quests.every((q) => q.status === "complete") ? "✅" : "◐";
}

export function History() {
  const { child } = useApp();
  const [days, setDays] = useState<HistoryDay[]>();
  const [t, setT] = useState<Today>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    Promise.all([api.history(child.id, 7), api.today(child.id)]).then(([h, td]) => {
      setDays(h);
      setT(td);
    }, (e) => setError(String(e.message ?? e)));
  }, [child.id]);

  return (
    <Screen tabs>
      <AppBar title="Ιστορικό" leading="📈" />
      <Content>
        {error && <Note tone="error">{error}</Note>}
        {t && (
          <Card title={`Level ${t.level} · ${t.xp} XP`}>
            <p className="muted">
              {t.xp_next_level - t.xp} XP ακόμα για Level {t.level + 1} ({LEVEL_COLORS[Math.min(t.level, 4)]})
            </p>
            <Progress value={t.xp} max={t.xp_next_level} />
          </Card>
        )}
        {t && (
          <ListRow icon="🔥" title={`Streak ${t.streak_days} ${t.streak_days === 1 ? "ημέρα" : "ημέρες"}`}
            subtitle={`🛡️ ${t.shields_left} ασπίδα διαθέσιμη αυτή την εβδομάδα`} />
        )}
        {days && (
          <>
            <span className="field-label">Τελευταίες 7 ημέρες</span>
            <div className="week">
              {[...days].reverse().map((d) => (
                <div key={d.date} className="week-day">
                  <span aria-hidden>{dayIcon(d)}</span>
                  <span className="small">{new Date(`${d.date}T12:00:00`).toLocaleDateString("el-GR", { weekday: "narrow" })}</span>
                </div>
              ))}
            </div>
            <span className="field-label">Δραστηριότητα</span>
            {days.flatMap((d) =>
              d.quests.map((q) => (
                <ListRow key={`${d.date}-${q.routine_id}`} icon={q.status === "complete" ? "✅" : q.status === "expired" ? "⏰" : "◐"}
                  title={`${new Date(`${d.date}T12:00:00`).toLocaleDateString("el-GR", { weekday: "short" })} · ${q.routine_name}`}
                  subtitle={`${q.done}/${q.total}${q.fast ? " · ⚡ γρήγορο quest" : ""}${q.status === "expired" ? " · έληξε" : ""}`}
                  trailing={q.xp > 0 ? `+${q.xp}` : ""} />
              )),
            )}
            <p className="small muted">⚡ = πληροφορία για κουβέντα με το παιδί, όχι ποινή.</p>
          </>
        )}
      </Content>
      <TabBar />
    </Screen>
  );
}

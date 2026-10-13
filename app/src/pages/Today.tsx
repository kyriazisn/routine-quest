/** C1 — Σήμερα */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../App";
import { AppBar, Button, Card, Content, ListRow, Note, Progress, Screen, StepDot, TabBar } from "../components";
import type { QuestToday, Today } from "../types";
import { greekDate, hhmm, popcount } from "../util";

const POLL_MS = 15_000;

function statusText(q: QuestToday): string {
  const done = popcount(q.done_mask);
  const n = q.routine.steps.length;
  switch (q.status) {
    case "upcoming":
      return `Ξεκινά στις ${hhmm(q.routine.start_min)}`;
    case "active":
      return "Σε εξέλιξη · κανένα βήμα ακόμα";
    case "in_progress":
      return `Σε εξέλιξη · ${done} από ${n} βήματα`;
    case "complete":
      return `Ολοκληρώθηκε 🎉${q.fast ? " · ⚡ γρήγορο" : ""}`;
    case "expired":
      return `Έκλεισε · ${done}/${n}`;
    case "paused":
      return "Ημέρα εκτός ⏸️";
    default:
      return "Όχι σήμερα";
  }
}

export function TodayPage() {
  const { child } = useApp();
  const nav = useNavigate();
  const [t, setT] = useState<Today>();
  const [error, setError] = useState<string>();

  const load = useCallback(() => {
    api.today(child.id).then((d) => {
      setT(d);
      setError(undefined);
    }, (e) => setError(String(e.message ?? e)));
  }, [child.id]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  const device = t?.devices[0];
  return (
    <Screen tabs>
      <AppBar title={`${child.nickname}${t ? ` · ${greekDate(t.date)}` : ""}`} leading={child.avatar} />
      <Content>
        {error && <Note tone="error">{error}</Note>}
        {!t && !error && <p className="muted" aria-busy="true">Φόρτωση…</p>}
        {t && t.quests.length === 0 && (
          <Card title="Δεν υπάρχουν quests">
            <Button onClick={() => nav("/settings")}>Ρύθμιση quests</Button>
          </Card>
        )}
        {t?.quests.map((q) => (
          <Card key={q.routine.id} className={`quest ${q.status}`}
            title={`${q.routine.icon} ${q.routine.name} · ${hhmm(q.routine.start_min)}–${hhmm(q.routine.end_min)}`}>
            <p className="muted" data-testid={`quest-status-${q.routine.id}`}>{statusText(q)}</p>
            {q.scheduled_today && (
              <>
                <div className="steps">
                  {q.routine.steps.map((s, i) => (
                    <StepDot key={s.button} icon={s.icon} label={s.label} button={s.button}
                      done={(q.done_mask & (1 << i)) !== 0} />
                  ))}
                </div>
                <Progress value={popcount(q.done_mask)} max={q.routine.steps.length} />
              </>
            )}
          </Card>
        ))}
        {t && (
          <ListRow icon="⭐" title={`Level ${t.level} · ⭐ ${t.stars} στο πορτοφόλι`}
            subtitle={`🔥 Streak ${t.streak_days} ${t.streak_days === 1 ? "ημέρα" : "ημέρες"}`} trailing="›"
            onClick={() => nav("/history")} />
        )}
        {t && (device ? (
          <ListRow icon={device.online ? "🟢" : "⚪"} title={device.online ? "Συσκευή online" : "Συσκευή offline"}
            subtitle={device.last_seen_at ? `Τελευταίο σήμα: ${new Date(device.last_seen_at).toLocaleTimeString("el-GR")}` : "—"}
            trailing="›" onClick={() => nav("/settings")} />
        ) : (
          <ListRow icon="📟" title="Σύνδεσε τη συσκευή" subtitle="Bluetooth · 2 λεπτά" trailing="›"
            onClick={() => nav("/setup/pair")} />
        ))}
      </Content>
      <TabBar />
    </Screen>
  );
}

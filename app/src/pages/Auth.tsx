import { type FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { Button, Content, Field, Note, Screen, Spacer } from "../components";
import type { Me } from "../types";

/** O1 — Καλωσόρισμα / magic link */
export function Login() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [msg, setMsg] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setState("sending");
    try {
      await api.requestMagicLink(email.trim());
      setState("sent");
    } catch (err) {
      setState("error");
      setMsg(err instanceof ApiError && err.status === 429 ? "Πολλές προσπάθειες. Δοκίμασε σε λίγο." : "Κάτι πήγε στραβά. Ξαναδοκίμασε.");
    }
  }

  return (
    <Screen>
      <Content>
        <Spacer />
        <div className="hero" aria-hidden>🗺️</div>
        <h1 className="title center-text">Routine Quest</h1>
        <p className="muted center-text">Οι ρουτίνες γίνονται quests. Εσύ μαθαίνεις πότε τελείωσαν — χωρίς φωνές.</p>
        <Spacer />
        {state === "sent" ? (
          <Note tone="ok">📬 Σου στείλαμε σύνδεσμο στο <b>{email}</b>. Άνοιξέ τον από αυτή τη συσκευή.</Note>
        ) : (
          <form onSubmit={submit} className="stack">
            <Field label="Email γονέα" type="email" name="email" autoComplete="email" value={email} onChange={setEmail}
              placeholder="you@example.com" />
            <Button type="submit" disabled={state === "sending" || !email.includes("@")}>
              {state === "sending" ? "Αποστολή…" : "Συνέχεια με σύνδεσμο στο email"}
            </Button>
            {state === "error" && <Note tone="error">{msg}</Note>}
          </form>
        )}
        <p className="small muted center-text">Συνεχίζοντας αποδέχεσαι τους Όρους και την Πολιτική απορρήτου.</p>
      </Content>
    </Screen>
  );
}

export function AuthVerify({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [error, setError] = useState<string>();
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return; // magic links are single-use: never verify twice (StrictMode)
    once.current = true;
    const token = params.get("token") ?? "";
    api
      .verify(token)
      .then((me) => {
        onSignedIn(me);
        nav(me.children.length ? "/" : "/setup/child", { replace: true });
      })
      .catch(() => setError("Ο σύνδεσμος έληξε ή έχει ήδη χρησιμοποιηθεί."));
  }, [params, nav, onSignedIn]);

  return (
    <Screen>
      <Content>
        <Spacer />
        {error ? (
          <>
            <Note tone="error">{error}</Note>
            <Button onClick={() => nav("/", { replace: true })}>Νέος σύνδεσμος</Button>
          </>
        ) : (
          <p className="center-text" aria-busy="true">Σύνδεση…</p>
        )}
      </Content>
    </Screen>
  );
}

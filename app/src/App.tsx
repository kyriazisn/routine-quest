import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ApiError, api } from "./api";
import { AuthVerify, Login } from "./pages/Auth";
import { ChildSetup, PushSetup } from "./pages/Onboarding";
import { Pair } from "./pages/Pair";
import { History } from "./pages/History";
import { Notifications } from "./pages/Notifications";
import { QuestEdit } from "./pages/QuestEdit";
import { RewardsPage } from "./pages/Rewards";
import { Settings } from "./pages/Settings";
import { TodayPage } from "./pages/Today";
import type { Child, Me } from "./types";

interface AppCtx {
  me: Me;
  child: Child;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AppCtx | null>(null);
const MeCtx = createContext<{ me: Me | null; refresh: () => Promise<void> }>({ me: null, refresh: async () => {} });

export function useApp(): AppCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useApp outside a signed-in route with a child");
  return c;
}

export function useMe() {
  return useContext(MeCtx);
}

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [error, setError] = useState<string>();
  const loc = useLocation();

  const refresh = useCallback(async () => {
    try {
      setMe(await api.me());
      setError(undefined);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
      else setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (loc.pathname !== "/auth") void refresh();
  }, [refresh, loc.pathname === "/auth"]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loc.pathname === "/auth") {
    return (
      <MeCtx.Provider value={{ me: me ?? null, refresh }}>
        <AuthVerify onSignedIn={setMe} />
      </MeCtx.Provider>
    );
  }
  if (error) return <div className="screen center"><p className="note error" role="alert">Σφάλμα σύνδεσης: {error}</p></div>;
  if (me === undefined) return <div className="screen center" aria-busy="true"><span className="loader" /></div>;
  if (me === null) return <Login />;

  const child = me.children[0];
  return (
    <MeCtx.Provider value={{ me, refresh }}>
      <Routes>
        <Route path="/setup/child" element={<ChildSetup />} />
        {!child ? (
          <Route path="*" element={<Navigate to="/setup/child" replace />} />
        ) : (
          <Route
            path="*"
            element={
              <Ctx.Provider value={{ me, child, refresh }}>
                <Routes>
                  <Route path="/" element={<TodayPage />} />
                  <Route path="/setup/push" element={<PushSetup />} />
                  <Route path="/setup/pair" element={<Pair />} />
                  <Route path="/quests/:id" element={<QuestEdit />} />
                  <Route path="/notifications" element={<Notifications />} />
                  <Route path="/history" element={<History />} />
                  <Route path="/rewards" element={<RewardsPage />} />
                  <Route path="/settings" element={<Settings />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Ctx.Provider>
            }
          />
        )}
      </Routes>
    </MeCtx.Provider>
  );
}

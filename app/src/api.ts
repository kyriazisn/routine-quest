import type { Child, Device, HistoryDay, Me, Rewards, Routine, RoutineIn, NotifyMode, Today } from "./types";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/v1${path}`, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, msg);
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

export const api = {
  requestMagicLink: (email: string) => req<{ status: string }>("POST", "/auth/magic-link", { email }),
  verify: (token: string) => req<Me>("POST", "/auth/verify", { token }),
  logout: () => req<void>("POST", "/auth/logout"),

  me: () => req<Me>("GET", "/me"),
  patchMe: (b: { quiet_start_min?: number | null; quiet_end_min?: number | null; family_tz?: string }) =>
    req<Me>("PATCH", "/me", b),
  exportData: () => req<unknown>("GET", "/me/export"),
  deleteAccount: () => req<void>("DELETE", "/me", { confirm: "ΔΙΑΓΡΑΦΗ" }),
  invite: (email: string) => req<{ status: string }>("POST", "/family/invites", { email }),

  createChild: (nickname: string, avatar: string) => req<Child>("POST", "/children", { nickname, avatar }),
  today: (childId: string) => req<Today>("GET", `/children/${childId}/today`),
  history: (childId: string, days = 7) => req<HistoryDay[]>("GET", `/children/${childId}/history?days=${days}`),
  routines: (childId: string) => req<Routine[]>("GET", `/children/${childId}/routines`),
  putRoutines: (childId: string, routines: RoutineIn[]) =>
    req<Routine[]>("PUT", `/children/${childId}/routines`, { routines }),
  patchNotifications: (routineId: number, b: { notify_mode?: NotifyMode; notify_expired?: boolean }) =>
    req<Routine>("PATCH", `/routines/${routineId}/notifications`, b),
  pause: (childId: string, date: string) => req<void>("PUT", `/children/${childId}/pause`, { date }),
  unpause: (childId: string, date: string) => req<void>("DELETE", `/children/${childId}/pause`, { date }),

  rewards: (childId: string) => req<Rewards>("GET", `/children/${childId}/rewards`),
  createReward: (childId: string, b: { name: string; icon: string; cost: number; repeatable: boolean }) =>
    req<Rewards>("POST", `/children/${childId}/rewards`, b),
  archiveReward: (id: string) => req<Rewards>("DELETE", `/rewards/${id}`),
  giveReward: (id: string) => req<Rewards>("POST", `/rewards/${id}/give`),

  claimCode: (childId: string) => req<{ code: string; expires_at: string }>("POST", `/children/${childId}/claim-codes`),
  patchDevice: (id: string, b: { volume?: number; brightness?: number }) => req<Device>("PATCH", `/devices/${id}`, b),
  revokeDevice: (id: string) => req<void>("DELETE", `/devices/${id}`),

  vapidKey: () => req<{ key: string }>("GET", "/push/vapid-public-key"),
  subscribePush: (sub: PushSubscriptionJSON) => req<unknown>("POST", "/push/subscriptions", sub),
};

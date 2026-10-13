import type { RoutineIn } from "./types";

export const BUTTON_COLORS = ["#ef4444", "#3b82f6", "#22c55e", "#facc15"] as const; // = firmware feedback.c
export const BUTTON_NAMES = ["Κόκκινο", "Μπλε", "Πράσινο", "Κίτρινο"] as const;
export const DAY_LABELS = ["Δ", "Τ", "Τ", "Π", "Π", "Σ", "Κ"] as const; // bit0 = Monday

export function hhmm(min: number): string {
  const m = Math.max(0, Math.min(min, 1440)); // 1440 → "24:00" (end of day)
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

export function parseHhmm(s: string): number {
  const [h, m] = s.split(":").map(Number);
  return h * 60 + m;
}

export function popcount(n: number): number {
  let c = 0;
  for (let x = n; x; x >>= 1) c += x & 1;
  return c;
}

export function greekDate(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("el-GR", { weekday: "long", day: "numeric", month: "numeric" });
}

/** Starter quests from wireframe O5. Decision (β): each button has a ☀️/🌙 two-half sticker. */
export const TEMPLATES: RoutineIn[] = [
  {
    name: "Πρωινό quest", icon: "🌅", start_min: 7 * 60, end_min: 8 * 60 + 15, days_mask: 0b0011111,
    notify_mode: "complete_only", notify_expired: true,
    steps: [
      { button: 0, icon: "🪥", label: "Δόντια" },
      { button: 1, icon: "👕", label: "Ντύσιμο" },
      { button: 2, icon: "🥣", label: "Πρωινό" },
      { button: 3, icon: "🎒", label: "Τσάντα" },
    ],
  },
  {
    name: "Βραδινό quest", icon: "🌙", start_min: 19 * 60 + 30, end_min: 20 * 60 + 30, days_mask: 0b1111111,
    notify_mode: "complete_only", notify_expired: true,
    steps: [
      { button: 0, icon: "🛁", label: "Μπάνιο" },
      { button: 1, icon: "🩳", label: "Πιτζάμες" },
      { button: 2, icon: "🪥", label: "Δόντια" },
      { button: 3, icon: "📖", label: "Παραμύθι" },
    ],
  },
];

export const AVATARS = ["🦊", "🐻", "🦄", "🐸", "🚀", "🐱", "🦖", "🐼"];

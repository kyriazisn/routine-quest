// Mirrors backend/app/schemas.py (parent API).

export interface Parent {
  id: string;
  email: string;
  quiet_start_min: number | null;
  quiet_end_min: number | null;
}

export interface Child {
  id: string;
  nickname: string;
  avatar: string;
  level: number;
}

export interface Me {
  parent: Parent;
  family_tz: string;
  children: Child[];
}

export interface Step {
  position?: number;
  button: number;
  icon: string;
  label: string;
}

export type NotifyMode = "each_step" | "complete_only" | "mute";

export interface Routine {
  id: number;
  name: string;
  icon: string;
  start_min: number;
  end_min: number;
  days_mask: number;
  notify_mode: NotifyMode;
  notify_expired: boolean;
  steps: Step[];
}

export type RoutineIn = Omit<Routine, "id"> & { id?: number };

export type QuestStatus = "upcoming" | "active" | "in_progress" | "complete" | "expired" | "paused" | "not_today";

export interface QuestToday {
  routine: Routine;
  scheduled_today: boolean;
  status: QuestStatus;
  done_mask: number;
  fast: boolean;
}

export interface Device {
  id: string;
  device_id: string;
  fw_version: string | null;
  volume: number;
  brightness: number;
  last_seen_at: string | null;
  online: boolean;
}

export interface Today {
  child: Child;
  date: string;
  paused: boolean;
  quests: QuestToday[];
  xp: number;
  level: number;
  xp_next_level: number;
  stars: number;
  week_stars: number;
  streak_days: number;
  shields_left: number;
  devices: Device[];
}

export interface HistoryQuest {
  routine_id: number;
  routine_name: string;
  status: string;
  done: number;
  total: number;
  fast: boolean;
  xp: number;
}

export interface HistoryDay {
  date: string;
  paused: boolean;
  quests: HistoryQuest[];
}

export interface Reward {
  id: string;
  name: string;
  icon: string;
  cost: number;
  repeatable: boolean;
  position: number;
  archived: boolean;
}

export interface Rewards {
  stars: number;
  active_reward_id: string | null;
  rewards: Reward[];
}

/* Components = the Figma wireframe library (AppBar, TabBar, ListRow, Field, Card, StepDot, Button). */
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { BUTTON_COLORS } from "./util";

export function Screen({ children, tabs = false }: { children: ReactNode; tabs?: boolean }) {
  return <div className={`screen${tabs ? " with-tabs" : ""}`}>{children}</div>;
}

export function AppBar({ title, back, leading }: { title: string; back?: boolean | string; leading?: string }) {
  const nav = useNavigate();
  return (
    <header className="appbar">
      {back ? (
        <button className="appbar-back" aria-label="Πίσω" onClick={() => (typeof back === "string" ? nav(back) : nav(-1))}>
          ←
        </button>
      ) : (
        leading && <span className="appbar-leading" aria-hidden>{leading}</span>
      )}
      <h1>{title}</h1>
    </header>
  );
}

export function TabBar() {
  const tabs = [
    ["/", "🏠", "Σήμερα"],
    ["/history", "📈", "Ιστορικό"],
    ["/rewards", "🎁", "Rewards"],
    ["/settings", "⚙️", "Ρυθμίσεις"],
  ] as const;
  return (
    <nav className="tabbar" aria-label="Κύρια πλοήγηση">
      {tabs.map(([to, icon, label]) => (
        <NavLink key={to} to={to} end className={({ isActive }) => (isActive ? "tab active" : "tab")}>
          <span aria-hidden>{icon}</span>
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

export function Content({ children }: { children: ReactNode }) {
  return <main className="content">{children}</main>;
}

export function Card({ title, children, className = "" }: { title?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {title && <h2 className="card-title">{title}</h2>}
      {children}
    </section>
  );
}

export function ListRow(props: {
  icon: string;
  title: ReactNode;
  subtitle?: ReactNode;
  trailing?: ReactNode;
  onClick?: () => void;
  danger?: boolean;
}) {
  const inner = (
    <>
      <span className="row-icon" aria-hidden>{props.icon}</span>
      <span className="row-text">
        <span className={`row-title${props.danger ? " danger" : ""}`}>{props.title}</span>
        {props.subtitle && <span className="row-sub">{props.subtitle}</span>}
      </span>
      {props.trailing !== undefined && <span className="row-trailing">{props.trailing}</span>}
    </>
  );
  return props.onClick ? (
    <button className="row" onClick={props.onClick}>{inner}</button>
  ) : (
    <div className="row">{inner}</div>
  );
}

export function Field(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  autoComplete?: string;
  name?: string;
}) {
  return (
    <label className="field">
      <span className="field-label">{props.label}</span>
      <input
        name={props.name}
        type={props.type ?? "text"}
        value={props.value}
        placeholder={props.placeholder}
        autoComplete={props.autoComplete}
        onChange={(e) => props.onChange(e.target.value)}
      />
    </label>
  );
}

export function Button(props: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={props.type ?? "button"}
      className={`btn ${props.variant ?? "primary"}`}
      onClick={props.onClick}
      disabled={props.disabled}
    >
      {props.children}
    </button>
  );
}

export function StepDot({ icon, label, button, done }: { icon: string; label: string; button: number; done: boolean }) {
  return (
    <div className={`stepdot${done ? " done" : ""}`} title={label}>
      <span className="stepdot-circle" style={{ background: BUTTON_COLORS[button] }} aria-hidden>
        {icon}
      </span>
      <span className="stepdot-label">
        {label}
        {done ? " ✓" : ""}
      </span>
    </div>
  );
}

export function Progress({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="progress" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Note({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "error" | "ok" }) {
  return <p className={`note ${tone}`} role={tone === "error" ? "alert" : "status"}>{children}</p>;
}

export function Spacer() {
  return <div className="spacer" />;
}

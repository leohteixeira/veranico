import type { ReactNode } from "react";

import "./common.css";

export type StateTone = "neutral" | "pending" | "ok" | "bad";

interface StateBadgeProps {
  tone?: StateTone;
  /** An `Icon` or a `Spinner`, shown before the label. */
  icon?: ReactNode;
  /** The translated state; colour never carries the state alone. */
  children: ReactNode;
}

/** The state of a quote, an approval or a delivery. */
export function StateBadge({ tone = "neutral", icon, children }: StateBadgeProps) {
  return (
    <span className={tone === "neutral" ? "state" : `state state--${tone}`} data-tone={tone}>
      {icon}
      {children}
    </span>
  );
}

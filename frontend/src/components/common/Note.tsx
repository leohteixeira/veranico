import type { HTMLAttributes, ReactNode } from "react";

import "./common.css";

export type NoteTone = "neutral" | "warn" | "wait" | "ok" | "danger";

interface NoteProps extends HTMLAttributes<HTMLDivElement> {
  tone?: NoteTone;
  /** An `Icon` or a `Spinner`, shown before the text. */
  icon?: ReactNode;
}

/** A statement placed next to the result it qualifies. The caller sets `role` when it is live. */
export function Note({ tone = "neutral", icon, className, children, ...rest }: NoteProps) {
  const classes = ["note"];
  if (tone !== "neutral") classes.push(`note--${tone}`);
  if (className !== undefined) classes.push(className);
  return (
    <div className={classes.join(" ")} {...rest}>
      {icon !== undefined && <span className="note__icon">{icon}</span>}
      <div className="note__body">{children}</div>
    </div>
  );
}

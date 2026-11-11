import type { HTMLAttributes } from "react";

import "./common.css";

interface CardProps extends HTMLAttributes<HTMLElement> {
  /** A card that names a region of the screen is a `section` with a label; otherwise a `div`. */
  as?: "div" | "section" | "aside";
}

/** A working panel that sits on the map like an index card. */
export function Card({ as: Element = "div", className, ...rest }: CardProps) {
  return <Element className={className === undefined ? "card" : `card ${className}`} {...rest} />;
}

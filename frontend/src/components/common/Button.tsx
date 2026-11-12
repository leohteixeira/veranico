import type { ButtonHTMLAttributes } from "react";

import "./common.css";

export type ButtonVariant = "primary" | "ghost" | "approve" | "reject" | "link";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "md" | "sm";
}

export function Button({
  variant = "primary",
  size = "md",
  type = "button",
  className,
  ...rest
}: ButtonProps) {
  const classes = ["btn"];
  if (variant !== "primary") classes.push(`btn--${variant}`);
  if (size === "sm") classes.push("btn--sm");
  if (className !== undefined) classes.push(className);
  return <button type={type} className={classes.join(" ")} {...rest} />;
}

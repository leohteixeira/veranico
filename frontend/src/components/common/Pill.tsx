import type { ReactNode } from "react";

import "./common.css";

export interface PillOption<T extends string> {
  value: T;
  label: ReactNode;
}

interface PillProps<T extends string> {
  /** Names the group for assistive technology (for example "Basemap"). */
  label: string;
  options: ReadonlyArray<PillOption<T>>;
  value: T;
  onChange: (value: T) => void;
  /** `floating` sits on the map; `inset` sits inside a card. */
  variant?: "floating" | "inset";
}

/** A segmented switch between a few named options; exactly one is pressed. */
export function Pill<T extends string>({
  label,
  options,
  value,
  onChange,
  variant = "floating",
}: PillProps<T>) {
  return (
    <div
      role="group"
      aria-label={label}
      className={variant === "inset" ? "pill pill--inset" : "pill"}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="pill__option"
          aria-pressed={option.value === value}
          onClick={() => {
            if (option.value !== value) onChange(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

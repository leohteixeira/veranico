import "./common.css";

// One authored set on a 16 by 16 grid, drawn with a single stroke (see `.icon`).
// `check`, `warn`, `clock` and `send` are the icons of the approved preview.
const PATHS = {
  check: ["M3 8.6l3.2 3L13 4.6"],
  warn: ["M8 2.2 14.6 13.6H1.4Z", "M8 6.6v3.2M8 11.6v.2"],
  clock: ["M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2Z", "M8 4.6V8l2.4 1.6"],
  send: ["M8 13V3.4M3.6 7.6 8 3.2l4.4 4.4"],
  close: ["M4 4l8 8M12 4l-8 8"],
  chevron: ["M6 3.6 10.4 8 6 12.4"],
  download: ["M8 2.6v7.6M4.8 7.2 8 10.4l3.2-3.2", "M3 13.2h10"],
  copy: ["M5.6 5.6h7v7h-7Z", "M3.4 10.4V3.4h7"],
  key: ["M9.6 6.4a2.6 2.6 0 1 0 0-.01Z", "M7.8 8.2 3 13M4.6 11.4l1.6 1.6"],
  refresh: ["M13 8a5 5 0 1 1-1.6-3.7", "M13.2 2.6v2.6h-2.6"],
  play: ["M5.4 3.6 12 8l-6.6 4.4Z"],
  pin: ["M8 14s4.2-4 4.2-7.2a4.2 4.2 0 0 0-8.4 0C3.8 10 8 14 8 14Z", "M8 6.6v.2"],
  sun: [
    "M8 5.4a2.6 2.6 0 1 0 0 5.2 2.6 2.6 0 0 0 0-5.2Z",
    "M8 1.8v1.4M8 12.8v1.4M1.8 8h1.4M12.8 8h1.4M3.6 3.6l1 1M11.4 11.4l1 1M3.6 12.4l1-1M11.4 4.6l1-1",
  ],
  moon: ["M13 9.4A5.4 5.4 0 0 1 6.6 3a5.4 5.4 0 1 0 6.4 6.4Z"],
} as const;

export type IconName = keyof typeof PATHS;

export const ICON_NAMES = Object.keys(PATHS) as IconName[];

interface IconProps {
  name: IconName;
  /** Icons are decorative by default; a title makes one an image with a name. */
  title?: string;
  className?: string;
}

export function Icon({ name, title, className }: IconProps) {
  const classes = className === undefined ? "icon" : `icon ${className}`;
  return (
    <svg
      className={classes}
      viewBox="0 0 16 16"
      data-icon={name}
      {...(title === undefined ? { "aria-hidden": true } : { role: "img", "aria-label": title })}
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

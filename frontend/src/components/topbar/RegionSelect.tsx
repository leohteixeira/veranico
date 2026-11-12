import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import type { components } from "../../api/schema";
import { translate, useI18n } from "../../i18n";
import { translateValue } from "../../i18n/coded";
import { Icon } from "../common/Icon";

type Region = components["schemas"]["Region"];

interface RegionSelectProps {
  regions: readonly Region[];
  /** The region in view; `null` while regions load or when the point lies outside all of them. */
  regionId: string | null;
  /** The view shows a point that no showcase region contains. */
  outside: boolean;
  onChange: (regionId: string) => void;
}

/**
 * The showcase region in view. Choosing one opens it with its example cover.
 *
 * A select-only combobox (WAI-ARIA Authoring Practices): the button keeps the focus and names the
 * highlighted option through `aria-activedescendant`, so the list is the application's own card
 * instead of the browser's.
 */
export function RegionSelect({ regions, regionId, outside, onChange }: RegionSelectProps) {
  const { locale } = useI18n();
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const label = (region: Region): string =>
    translate(locale, "region.option", {
      name: region.name,
      crop: translateValue("crop", region.crop, locale),
    });
  const selected = regions.findIndex((region) => region.region_id === regionId);
  const current = regions[selected];
  const value =
    current !== undefined && !outside
      ? label(current)
      : outside
        ? translate(locale, "region.outside")
        : "";

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent): void => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const show = (index: number): void => {
    setActive(Math.min(Math.max(index, 0), regions.length - 1));
    setOpen(true);
  };
  const choose = (index: number): void => {
    const region = regions[index];
    setOpen(false);
    if (region !== undefined && region.region_id !== regionId) onChange(region.region_id);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
    const start = selected >= 0 ? selected : 0;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      show(open ? active + step : start);
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      show(event.key === "Home" ? 0 : regions.length - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open) choose(active);
      else show(start);
    } else if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
        setOpen(false);
      }
    } else if (event.key === "Tab") {
      setOpen(false);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      // Type a letter to reach the next region that starts with it.
      const letter = event.key.toLocaleLowerCase(locale);
      const from = open ? active + 1 : start + 1;
      const order = regions.map((_, index) => (from + index) % regions.length);
      const match = order.find((index) =>
        label(regions[index] as Region)
          .toLocaleLowerCase(locale)
          .startsWith(letter),
      );
      if (match !== undefined) show(match);
    }
  };

  return (
    <div className="region-select" ref={root} data-open={open}>
      <span id={`${id}-label`} className="sr-only">
        {translate(locale, "region.label")}
      </span>
      <button
        type="button"
        role="combobox"
        className="region-select__control"
        data-value={outside ? "" : (regionId ?? "")}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-labelledby={`${id}-label ${id}-value`}
        aria-activedescendant={open ? `${id}-option-${active}` : undefined}
        disabled={regions.length === 0}
        onClick={() => (open ? setOpen(false) : show(selected >= 0 ? selected : 0))}
        onKeyDown={onKeyDown}
      >
        <span id={`${id}-value`} className="region-select__value">
          {value}
        </span>
        <Icon name="chevron" className="region-select__chevron" />
      </button>
      <ul
        id={`${id}-list`}
        role="listbox"
        className="region-select__list"
        aria-labelledby={`${id}-label`}
        hidden={!open}
      >
        {regions.map((region, index) => (
          <li
            key={region.region_id}
            id={`${id}-option-${index}`}
            role="option"
            className="region-select__option"
            aria-selected={index === selected && !outside}
            data-active={index === active}
            onPointerMove={() => setActive(index)}
            onClick={() => choose(index)}
          >
            <span>{label(region)}</span>
            <Icon name="check" className="region-select__check" />
          </li>
        ))}
      </ul>
    </div>
  );
}

import { useId } from "react";

import type { components } from "../../api/schema";
import { translate, useI18n } from "../../i18n";
import { translateValue } from "../../i18n/coded";

type Region = components["schemas"]["Region"];

interface RegionSelectProps {
  regions: readonly Region[];
  /** The region in view; `null` while regions load or when the point lies outside all of them. */
  regionId: string | null;
  /** The view shows a point that no showcase region contains. */
  outside: boolean;
  onChange: (regionId: string) => void;
}

const OUTSIDE = "";

/** The showcase region in view. Choosing one opens it with its example cover. */
export function RegionSelect({ regions, regionId, outside, onChange }: RegionSelectProps) {
  const { locale } = useI18n();
  const id = useId();
  return (
    <div className="region-select">
      <label htmlFor={id} className="sr-only">
        {translate(locale, "region.label")}
      </label>
      <select
        id={id}
        value={regionId ?? OUTSIDE}
        disabled={regions.length === 0}
        onChange={(event) => {
          if (event.target.value !== OUTSIDE) onChange(event.target.value);
        }}
      >
        {(regionId === null || outside) && (
          <option value={OUTSIDE} disabled>
            {outside ? translate(locale, "region.outside") : ""}
          </option>
        )}
        {regions.map((region) => (
          <option key={region.region_id} value={region.region_id}>
            {translate(locale, "region.option", {
              name: region.name,
              crop: translateValue("crop", region.crop, locale),
            })}
          </option>
        ))}
      </select>
    </div>
  );
}

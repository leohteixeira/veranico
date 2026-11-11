import type { BasemapId } from "../../config";
import { translate, useI18n } from "../../i18n";
import { Pill } from "../common/Pill";

interface BasemapSwitchProps {
  /** The basemap on screen, already resolved from the theme and the visitor's choice. */
  basemap: BasemapId;
  onChange: (basemap: BasemapId) => void;
}

export function BasemapSwitch({ basemap, onChange }: BasemapSwitchProps) {
  const { locale } = useI18n();
  return (
    <Pill
      label={translate(locale, "basemap.label")}
      value={basemap}
      onChange={onChange}
      options={[
        { value: "relief", label: translate(locale, "basemap.relief") },
        { value: "satellite", label: translate(locale, "basemap.satellite") },
      ]}
    />
  );
}

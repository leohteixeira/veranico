import { translate, useI18n } from "../../i18n";
import type { RenderMode } from "../../state/view";
import { Pill } from "../common/Pill";

interface RenderSwitchProps {
  render: RenderMode;
  onChange: (render: RenderMode) => void;
}

/** The risk layer as a smoothed surface, or as the cells the data is made of. */
export function RenderSwitch({ render, onChange }: RenderSwitchProps) {
  const { locale } = useI18n();
  return (
    <Pill
      label={translate(locale, "render.label")}
      value={render}
      onChange={onChange}
      options={[
        { value: "surface", label: translate(locale, "render.surface") },
        { value: "cells", label: translate(locale, "render.cells") },
      ]}
    />
  );
}

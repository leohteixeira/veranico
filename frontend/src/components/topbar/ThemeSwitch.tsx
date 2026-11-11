import type { Theme } from "../../design/theme";
import { translate, useI18n } from "../../i18n";
import { Icon } from "../common/Icon";
import { Pill } from "../common/Pill";

interface ThemeSwitchProps {
  theme: Theme;
  onChange: (theme: Theme) => void;
}

export function ThemeSwitch({ theme, onChange }: ThemeSwitchProps) {
  const { locale } = useI18n();
  const option = (value: Theme) => ({
    value,
    label: (
      <>
        <Icon name={value === "light" ? "sun" : "moon"} />
        <span className="sr-only">{translate(locale, `theme.${value}`)}</span>
      </>
    ),
  });
  return (
    <Pill
      label={translate(locale, "theme.label")}
      value={theme}
      onChange={onChange}
      options={[option("light"), option("dark")]}
    />
  );
}

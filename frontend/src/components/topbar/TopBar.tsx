import type { components } from "../../api/schema";
import { config, type BasemapId } from "../../config";
import type { Theme } from "../../design/theme";
import { translate, useI18n } from "../../i18n";
import type { RenderMode } from "../../state/view";
import { BasemapSwitch } from "./BasemapSwitch";
import { LanguageSwitch } from "./LanguageSwitch";
import { RegionSelect } from "./RegionSelect";
import { RenderSwitch } from "./RenderSwitch";
import { ThemeSwitch } from "./ThemeSwitch";

import "./topbar.css";

interface TopBarProps {
  regions: readonly components["schemas"]["Region"][];
  regionId: string | null;
  /** The view shows a point outside every showcase region. */
  outside: boolean;
  onRegion: (regionId: string) => void;
  basemap: BasemapId;
  onBasemap: (basemap: BasemapId) => void;
  render: RenderMode;
  onRender: (render: RenderMode) => void;
  theme: Theme;
  onTheme: (theme: Theme) => void;
  className?: string;
}

/**
 * The top row: the wordmark, then the region, the basemap, how the risk layer is drawn, the
 * language and the theme, in that order for the eye and for the keyboard.
 */
export function TopBar({
  regions,
  regionId,
  outside,
  onRegion,
  basemap,
  onBasemap,
  render,
  onRender,
  theme,
  onTheme,
  className,
}: TopBarProps) {
  const { locale } = useI18n();
  return (
    <header className={className === undefined ? "topbar" : `topbar ${className}`}>
      {/* The wordmark leads to the project's page on the portfolio, in the active language. The
          heading stays inside the link so its name is the product's name alone. */}
      <a
        className="topbar__brand"
        href={config.landingUrls[locale]}
        aria-label={translate(locale, "app.about")}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <path
            d="M12 6.2c2.6 3 3.9 5 3.9 6.9a3.9 3.9 0 0 1-7.8 0c0-1.9 1.3-3.9 3.9-6.9Z"
            fill="var(--accent)"
          />
        </svg>
        <h1 className="topbar__name">{translate(locale, "app.name")}</h1>
      </a>
      <RegionSelect regions={regions} regionId={regionId} outside={outside} onChange={onRegion} />
      <span className="topbar__space" />
      <div className="topbar__controls" role="group" aria-label={translate(locale, "top.label")}>
        <BasemapSwitch basemap={basemap} onChange={onBasemap} />
        <RenderSwitch render={render} onChange={onRender} />
        <LanguageSwitch />
        <ThemeSwitch theme={theme} onChange={onTheme} />
      </div>
    </header>
  );
}

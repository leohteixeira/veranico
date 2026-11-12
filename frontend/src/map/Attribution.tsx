import type { BasemapConfig } from "../config";
import { useI18n } from "../i18n";
import "./map.css";

interface AttributionProps {
  /** The basemap on screen: its provider's attribution and licence are the ones shown. */
  basemap: BasemapConfig;
  /**
   * The weather of the region on screen is synthetic (`Region.synthetic`, or a dataset source of
   * `synthetic`). The weather line then says so, and credits ERA5 only for what it still applies
   * to: a point outside the showcase regions. Synthetic data is never credited to a real source.
   */
  synthetic?: boolean;
  className?: string;
}

function LinkOrText({ text, url }: { text: string; url: string | undefined }) {
  if (url === undefined) return <>{text}</>;
  return (
    <a href={url} target="_blank" rel="noreferrer">
      {text}
    </a>
  );
}

/**
 * The sources and licences that must stay legible next to the map: the active basemap's
 * attribution and licence, the weather data's, the non-commercial notice and the pricing
 * disclaimer. The provider's attribution is its own wording and is not translated.
 */
export function Attribution({ basemap, synthetic = false, className }: AttributionProps) {
  const { t } = useI18n();
  return (
    <p
      className={className === undefined ? "attribution" : `attribution ${className}`}
      aria-label={t("attribution.label")}
    >
      <span className="attribution__item">
        {t("attribution.basemap")}{" "}
        <LinkOrText text={basemap.attribution} url={basemap.attributionUrl} />
        {basemap.licenceNote !== "" && (
          <>
            {" ("}
            <LinkOrText text={basemap.licenceNote} url={basemap.licenceUrl} />
            {")"}
          </>
        )}
      </span>
      <span className="attribution__item" data-weather={synthetic ? "synthetic" : "reanalysis"}>
        {t(synthetic ? "app.weather_attribution_synthetic" : "app.weather_attribution")}
      </span>
      <span className="attribution__item">{t("app.non_commercial")}</span>
      <span className="attribution__item">{t("app.disclaimer")}</span>
    </p>
  );
}

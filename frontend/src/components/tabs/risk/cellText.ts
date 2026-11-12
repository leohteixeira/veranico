import type { components } from "../../../api/schema";
import type { Locale } from "../../../i18n";
import { formatFraction } from "../../../i18n/format";

type Metric = components["schemas"]["CellGrid"]["metric"];

/**
 * A cell value as the Risk tab writes it: a share of seasons for the trigger frequency, a signed
 * share for a season's anomaly. The value is the API's; only its notation is chosen here.
 */
export function cellValueText(value: number, metric: Metric, locale: Locale, digits = 0): string {
  return formatFraction(value, locale, { digits, signed: metric === "season_anomaly" });
}

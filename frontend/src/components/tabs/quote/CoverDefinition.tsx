import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { translateValue } from "../../../i18n/coded";
import { formatIndexValue, formatMoney, formatNumber, formatWindow } from "../../../i18n/format";
import { FieldList, type Field } from "../FieldList";

type Schemas = components["schemas"];

interface CoverDefinitionProps {
  cover: Schemas["CoverDefinition"];
  /** The priced location; a recording has none. */
  location?: Schemas["QuoteLocation"] | null;
  datasetId?: string | null;
  highlight: string | null;
}

/** The cover that was priced: where, on which data, and the index, trigger, exit and limit. */
export function CoverDefinition({
  cover,
  location = null,
  datasetId = null,
  highlight,
}: CoverDefinitionProps) {
  const { locale } = useI18n();
  const { index, limit } = cover;
  const fields: Field[] = [];
  if (location !== null) {
    const coordinates = [location.lat, location.lon]
      .map((value) => formatNumber(value, locale, { maximumFractionDigits: 4 }))
      .join(locale === "en" ? ", " : "; ");
    fields.push({
      field: "location",
      label: translate(locale, "quote.location"),
      value: `${location.label} · ${coordinates}`,
    });
  }
  // The dataset in words: a regional cube cell or a point's own history, never the raw id.
  const kind = datasetId?.split(":", 1)[0];
  if (kind === "cube" || kind === "point") {
    fields.push({
      field: "dataset",
      label: translate(locale, "quote.dataset"),
      value: translate(locale, `quote.dataset.${kind}`),
    });
  }
  fields.push(
    {
      field: "index",
      label: translate(locale, "quote.index"),
      value: translateValue("index", index.index_type, locale),
    },
    {
      field: "window",
      label: translate(locale, "quote.window"),
      value: formatWindow(index.window, locale),
    },
    {
      field: "trigger",
      label: translate(locale, "quote.trigger"),
      value: formatIndexValue(index.trigger, index.index_type, locale),
    },
    {
      field: "exit",
      label: translate(locale, "quote.exit"),
      value: formatIndexValue(index.exit, index.index_type, locale),
    },
    {
      field: "limit",
      label: translate(locale, "quote.limit"),
      value: formatMoney(limit.amount_cents, locale),
    },
  );
  return (
    <section className="quote__section">
      <h4>{translate(locale, "quote.cover")}</h4>
      <FieldList highlight={highlight} fields={fields} />
    </section>
  );
}

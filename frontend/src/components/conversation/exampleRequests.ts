import type { ExampleCover } from "../../config";
import { translate, type Locale } from "../../i18n";
import { formatIndexValue, formatMoney, formatMonthDay } from "../../i18n/format";

/** A request the first run offers: one click sends its text. */
export interface ExampleRequest {
  id: string;
  /** A place name, shown as data. */
  title: string;
  text: string;
}

/** The example covers of the configuration written as requests in the visitor's language. */
export function exampleRequests(
  covers: Readonly<Record<string, ExampleCover>>,
  locale: Locale,
): ExampleRequest[] {
  return Object.entries(covers).map(([id, example]) => {
    const { index, limit } = example.cover;
    return {
      id,
      title: example.label,
      text: translate(locale, `chat.example.${index.index_type}`, {
        label: example.label,
        start: formatMonthDay(index.window.start, locale),
        end: formatMonthDay(index.window.end, locale),
        trigger: formatIndexValue(index.trigger, index.index_type, locale),
        exit: formatIndexValue(index.exit, index.index_type, locale),
        limit: formatMoney(limit.amount_cents, locale),
      }),
    };
  });
}

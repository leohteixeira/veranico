import type { components } from "../api/schema";
import { formatMoney, formatMonthDay, formatNumber, formatRate } from "./format";
import { interpolate, lookup, placeholders, type Locale } from "./index";

/**
 * Text for people arrives from the API as a code plus parameters and is translated here. An
 * unknown code is shown as the code itself: the API's English prose is never shown.
 */

type Coded = components["schemas"]["Coded"];

const CODED_NAMESPACES = ["tool.", "audit.", "assumption.", "warning."];

// The first variant whose parameters are all present is used, so a code still reads well when an
// optional parameter is absent.
const VARIANTS = ["", ".alt", ".plain"];

// Parameters whose value is itself a code or an enumerated value of the API.
const VALUE_NAMESPACE: Readonly<Record<string, string>> = {
  index_type: "index",
  method: "method",
  direction: "direction",
  source: "source",
  locale: "language",
  metric: "metric",
};

const GROUPED_COUNTS = new Set(["n"]);

/** A value of an API enumeration (`status.quote`, `actor`, `crop`, ...), or the value itself. */
export function translateValue(namespace: string, value: string, locale: Locale): string {
  return lookup(locale, `${namespace}.${value}`) ?? value;
}

/** A problem or tool error code as a sentence; an unknown code is shown as the code. */
export function translateProblem(code: string, locale: Locale): string {
  return lookup(locale, `problem.${code}`) ?? code;
}

function formatParam(name: string, value: string | number, locale: Locale): string {
  if (typeof value === "number") {
    if (name.endsWith("_cents")) return formatMoney(value, locale);
    return formatNumber(value, locale, { useGrouping: GROUPED_COUNTS.has(name) });
  }
  if (name.endsWith("_rate")) return formatRate(value, locale);
  if (name === "error_code") return translateProblem(value, locale);
  if (name === "start" || name === "end") return formatMonthDay(value, locale);
  const namespace = VALUE_NAMESPACE[name];
  return namespace === undefined ? value : translateValue(namespace, value, locale);
}

/**
 * A `Coded` text in the active language. A parameter ending in `_cents` is formatted as money and
 * one ending in `_rate` as a percentage, as the contract's naming rule says.
 */
export function translateCoded(coded: Coded, locale: Locale): string {
  if (!CODED_NAMESPACES.some((namespace) => coded.code.startsWith(namespace))) return coded.code;
  const params = coded.params ?? {};
  for (const variant of VARIANTS) {
    const template = lookup(locale, `${coded.code}${variant}`);
    if (template === undefined) continue;
    const names = placeholders(template);
    if (!names.every((name) => Object.hasOwn(params, name))) continue;
    const formatted: Record<string, string> = {};
    for (const name of names) {
      const value = params[name];
      if (value !== undefined) formatted[name] = formatParam(name, value, locale);
    }
    return interpolate(template, formatted);
  }
  return coded.code;
}

import type { components } from "../api/schema";
import { translate, type Locale } from "./index";

/**
 * Formatters. They change how a figure is written for a locale and never its value: money is laid
 * out from the integer centavos by digit placement, and a rate from its six-decimal string.
 */

type IndexType = components["schemas"]["IndexDefinition"]["index_type"];
type Window = components["schemas"]["Window"];

const SEPARATORS: Record<Locale, { group: string; decimal: string }> = {
  en: { group: ",", decimal: "." },
  "pt-BR": { group: ".", decimal: "," },
};

const INTL_TAG: Record<Locale, string> = { en: "en-US", "pt-BR": "pt-BR" };

const NBSP = " ";

function groupDigits(digits: string, separator: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, separator);
}

/** Integer BRL centavos as an amount, for example `R$ 12,345.67`. No arithmetic on the value. */
export function formatMoney(cents: number, locale: Locale): string {
  // The API only sends integers; anything else is shown as it came instead of being rounded.
  if (!Number.isSafeInteger(cents)) return String(cents);
  const digits = Math.abs(cents).toString().padStart(3, "0");
  const { group, decimal } = SEPARATORS[locale];
  const amount = `${groupDigits(digits.slice(0, -2), group)}${decimal}${digits.slice(-2)}`;
  return `${cents < 0 ? "-" : ""}R$${NBSP}${amount}`;
}

const RATE = /^(-?)(\d+)\.(\d{6})$/;

/**
 * A six-decimal rate string as a percentage. Without `digits` every digit of the string is kept
 * (trailing zeros dropped): `0.123456` is `12.3456%`. With `digits` (0 to 4) the percentage is
 * rounded half up to that many decimals on the decimal digits themselves, never through a float.
 */
export function formatRate(rate: string, locale: Locale, digits?: number): string {
  const match = RATE.exec(rate);
  if (match === null) return rate;
  const negative = match[1] === "-";
  // Millionths of one are ten-thousandths of a percent: the same digits, four decimals.
  let scaled = BigInt(`${match[2] ?? ""}${match[3] ?? ""}`);
  let decimals = 4;
  if (digits !== undefined && digits < 4) {
    decimals = Math.max(0, Math.trunc(digits));
    const divisor = 10n ** BigInt(4 - decimals);
    scaled = (scaled + divisor / 2n) / divisor;
  }
  const text = scaled.toString().padStart(decimals + 1, "0");
  const whole = text.slice(0, text.length - decimals);
  let fraction = decimals > 0 ? text.slice(-decimals) : "";
  if (digits === undefined) fraction = fraction.replace(/0+$/, "");
  const { group, decimal } = SEPARATORS[locale];
  const sign = negative && scaled !== 0n ? "-" : "";
  return `${sign}${groupDigits(whole, group)}${fraction === "" ? "" : decimal + fraction}%`;
}

interface NumberOptions {
  minimumFractionDigits?: number;
  maximumFractionDigits?: number;
  useGrouping?: boolean;
}

/** A plain number with the locale's separators. By default no digit the API sent is dropped. */
export function formatNumber(value: number, locale: Locale, options: NumberOptions = {}): string {
  return new Intl.NumberFormat(INTL_TAG[locale], {
    minimumFractionDigits: options.minimumFractionDigits ?? 0,
    maximumFractionDigits: options.maximumFractionDigits ?? 6,
    useGrouping: options.useGrouping ?? true,
  }).format(value);
}

/** Millimetres, which the API sends with one decimal place. */
export function formatMm(value: number, locale: Locale): string {
  const text = formatNumber(value, locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return translate(locale, "unit.mm", { value: text });
}

/** Days, which the API sends with at most one decimal place. */
export function formatDays(value: number, locale: Locale): string {
  const text = formatNumber(value, locale, { maximumFractionDigits: 1 });
  return translate(locale, value === 1 ? "unit.day" : "unit.days", { value: text });
}

/** An index value in the unit of its index type: millimetres or days. */
export function formatIndexValue(value: number, indexType: IndexType, locale: Locale): string {
  return indexType === "rainfall_below" ? formatMm(value, locale) : formatDays(value, locale);
}

/** A geometric distance on the map (one of the two display derivations the SPEC allows). */
export function formatKm(value: number, locale: Locale): string {
  const text = formatNumber(value, locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return translate(locale, "unit.km", { value: text });
}

/** A duration the API reports in milliseconds, shown in milliseconds. */
export function formatMs(value: number, locale: Locale): string {
  return translate(locale, "unit.ms", { value: formatNumber(value, locale) });
}

/** A fraction between 0 and 1 (a cell value) written as a percentage. */
export function formatFraction(
  value: number,
  locale: Locale,
  options: { digits?: number; signed?: boolean } = {},
): string {
  return new Intl.NumberFormat(INTL_TAG[locale], {
    style: "percent",
    maximumFractionDigits: options.digits ?? 0,
    signDisplay: options.signed === true ? "exceptZero" : "auto",
  }).format(value);
}

interface DateOptions {
  style?: "datetime" | "date" | "time";
  /** Defaults to the visitor's time zone. */
  timeZone?: string;
}

/** An ISO date-time from the API in the locale's notation. */
export function formatDate(iso: string, locale: Locale, options: DateOptions = {}): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const style = options.style ?? "datetime";
  return new Intl.DateTimeFormat(INTL_TAG[locale], {
    ...(style === "time" ? {} : { dateStyle: "medium" }),
    ...(style === "date" ? {} : { timeStyle: "short" }),
    ...(options.timeZone === undefined ? {} : { timeZone: options.timeZone }),
  }).format(date);
}

/** A season is labelled by its start year, written without a thousands separator. */
export function formatSeason(season: number): string {
  return String(season);
}

const MONTH_DAY = /^(\d{2})-(\d{2})$/;

/** A window boundary (`MM-DD`) as a day and a month, for example `Sep 1` or `1 de set.`. */
export function formatMonthDay(monthDay: string, locale: Locale): string {
  const match = MONTH_DAY.exec(monthDay);
  if (match === null) return monthDay;
  // A leap year, so 02-29 is a real day.
  const date = new Date(Date.UTC(2000, Number(match[1]) - 1, Number(match[2])));
  return new Intl.DateTimeFormat(INTL_TAG[locale], {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}

/** A coverage window, for example `Sep 1 – Oct 31`. */
export function formatWindow(window: Window, locale: Locale): string {
  return `${formatMonthDay(window.start, locale)} – ${formatMonthDay(window.end, locale)}`;
}

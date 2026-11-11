import { describe, expect, it } from "vitest";

import {
  formatDate,
  formatDays,
  formatFraction,
  formatIndexValue,
  formatKm,
  formatMm,
  formatMoney,
  formatMonthDay,
  formatMs,
  formatNumber,
  formatRate,
  formatSeason,
  formatWindow,
} from "./format";
import { LOCALES } from "./index";

const digitsOf = (text: string) => text.replace(/\D/g, "");

describe("money", () => {
  it("[R-12-2] [R-13-4] money_digits_equal_the_integer_centavos_in_both_locales", () => {
    const amounts = [
      0, 1, 9, 10, 99, 100, 101, 12_345, 1_234_567, 30_000_000, 999_999_999_999,
      123_456_789_012_345, -1, -100, -12_345, -30_000_000,
    ];
    for (const locale of LOCALES) {
      for (const cents of amounts) {
        const text = formatMoney(cents, locale);
        // Stripping every separator gives back the integer the API sent (left-padded to 3 digits).
        expect(digitsOf(text), `${cents} ${locale}`).toBe(
          Math.abs(cents).toString().padStart(3, "0"),
        );
        expect(text.startsWith("-"), `${cents} ${locale}`).toBe(cents < 0);
        expect(text).toContain("R$");
      }
    }
  });

  it("[R-13-4] money follows the separators of the locale", () => {
    expect(formatMoney(1_234_567, "en")).toBe("R$ 12,345.67");
    expect(formatMoney(1_234_567, "pt-BR")).toBe("R$ 12.345,67");
    expect(formatMoney(30_000_000, "pt-BR")).toBe("R$ 300.000,00");
    expect(formatMoney(5, "en")).toBe("R$ 0.05");
    expect(formatMoney(-12_345, "pt-BR")).toBe("-R$ 123,45");
  });

  it("[R-12-2] a value that is not an integer is shown as it came, never rounded", () => {
    expect(formatMoney(12.5, "en")).toBe("12.5");
  });
});

describe("rates", () => {
  it("[R-12-2] rate_string_is_shown_as_percent_without_changing_digits_beyond_the_requested_precision", () => {
    // Without a precision every digit of the six-decimal string is kept.
    const lossless: Array<[string, string]> = [
      ["0.123456", "12.3456%"],
      ["0.300000", "30%"],
      ["0.150000", "15%"],
      ["0.000001", "0.0001%"],
      ["1.000000", "100%"],
      ["0.000000", "0%"],
      ["-0.012340", "-1.234%"],
      ["12.345678", "1,234.5678%"],
    ];
    for (const [rate, expected] of lossless) {
      expect(formatRate(rate, "en"), rate).toBe(expected);
      // At four decimals the percentage carries exactly the digits of the string.
      expect(digitsOf(formatRate(rate, "en", 4)).replace(/^0+/, ""), rate).toBe(
        digitsOf(rate).replace(/^0+/, ""),
      );
    }
    // With a precision the percentage is rounded half up at that digit, on the decimal digits.
    const rounded: Array<[string, number, string]> = [
      ["0.123456", 2, "12.35%"],
      ["0.123456", 1, "12.3%"],
      ["0.123456", 0, "12%"],
      ["0.123450", 3, "12.345%"],
      ["0.123450", 4, "12.3450%"],
      ["0.999999", 2, "100.00%"],
      ["0.000001", 1, "0.0%"],
      ["-0.000001", 1, "0.0%"],
      ["-0.125550", 1, "-12.6%"],
      ["0.070000", 1, "7.0%"],
      // 0.2845 as a float is 28.449999...; the decimal digits round to 28.5.
      ["0.284500", 1, "28.5%"],
    ];
    for (const [rate, digits, expected] of rounded) {
      expect(formatRate(rate, "en", digits), `${rate} at ${digits}`).toBe(expected);
    }
  });

  it("[R-13-4] rates follow the separators of the locale", () => {
    expect(formatRate("0.123456", "pt-BR")).toBe("12,3456%");
    expect(formatRate("0.123456", "pt-BR", 2)).toBe("12,35%");
    expect(formatRate("12.345678", "pt-BR", 1)).toBe("1.234,6%");
  });

  it("[R-12-2] a string that is not a six-decimal rate is shown as it came", () => {
    expect(formatRate("0.12", "en")).toBe("0.12");
    expect(formatRate("n/a", "pt-BR", 2)).toBe("n/a");
  });
});

describe("physical quantities, dates and seasons", () => {
  it("[R-13-4] millimetres_and_days_use_locale_separators", () => {
    expect(formatMm(1234.5, "en")).toBe("1,234.5 mm");
    expect(formatMm(1234.5, "pt-BR")).toBe("1.234,5 mm");
    expect(formatMm(150, "pt-BR")).toBe("150,0 mm");
    expect(formatDays(23, "en")).toBe("23 days");
    expect(formatDays(1, "en")).toBe("1 day");
    expect(formatDays(1, "pt-BR")).toBe("1 dia");
    expect(formatDays(12.5, "pt-BR")).toBe("12,5 dias");
    expect(formatIndexValue(75, "rainfall_below", "en")).toBe("75.0 mm");
    expect(formatIndexValue(18, "dry_spell_above", "pt-BR")).toBe("18 dias");
    expect(formatKm(11.13, "pt-BR")).toBe("11,1 km");
    expect(formatMs(1240, "en")).toBe("1,240 ms");
  });

  it("[R-12-2] plain numbers keep the digits the API sent", () => {
    expect(formatNumber(-12.5, "pt-BR")).toBe("-12,5");
    expect(formatNumber(100000, "en")).toBe("100,000");
    expect(formatNumber(1950, "en", { useGrouping: false })).toBe("1950");
    expect(formatSeason(1998)).toBe("1998");
  });

  it("[R-13-4] cell fractions are written as percentages", () => {
    expect(formatFraction(0.18, "en")).toBe("18%");
    expect(formatFraction(0.125, "pt-BR", { digits: 1 })).toBe("12,5%");
    expect(formatFraction(-0.2, "en", { signed: true })).toBe("-20%");
    expect(formatFraction(0.2, "en", { signed: true })).toBe("+20%");
  });

  it("[R-13-4] dates follow the active locale", () => {
    const iso = "2026-11-10T14:05:00Z";
    expect(formatDate(iso, "en", { timeZone: "UTC" })).toMatch(/Nov 10, 2026/);
    expect(formatDate(iso, "en", { timeZone: "UTC" })).toMatch(/2:05/);
    expect(formatDate(iso, "pt-BR", { timeZone: "UTC" })).toMatch(/10 de nov\. de 2026/);
    expect(formatDate(iso, "pt-BR", { timeZone: "UTC" })).toMatch(/14:05/);
    expect(formatDate(iso, "pt-BR", { style: "date", timeZone: "UTC" })).not.toMatch(/14:05/);
    expect(formatDate("not a date", "en")).toBe("not a date");
  });

  it("[R-13-4] window boundaries are written as a day and a month", () => {
    expect(formatMonthDay("09-01", "en")).toBe("Sep 1");
    expect(formatMonthDay("09-01", "pt-BR")).toBe("1 de set.");
    expect(formatMonthDay("02-29", "en")).toBe("Feb 29");
    expect(formatWindow({ start: "11-15", end: "02-15" }, "en")).toBe("Nov 15 – Feb 15");
    expect(formatMonthDay("soon", "en")).toBe("soon");
  });
});

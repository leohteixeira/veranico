import { act, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { en } from "./en";
import {
  I18nProvider,
  LOCALES,
  LOCALE_STORAGE_KEY,
  interpolate,
  placeholders,
  resolveLocale,
  translate,
  useI18n,
} from "./index";
import { ptBR } from "./pt-BR";

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
  document.documentElement.lang = "";
});

describe("locale resolution", () => {
  it("[R-13-1] locale_from_query_then_stored_then_browser", () => {
    expect(resolveLocale("?lang=pt-BR", "en", ["en-US"])).toBe("pt-BR");
    expect(resolveLocale("?lang=en", "pt-BR", ["pt-BR"])).toBe("en");
    expect(resolveLocale("", "pt-BR", ["en-US"])).toBe("pt-BR");
    expect(resolveLocale("?code=abc", null, ["pt-PT", "en-US"])).toBe("pt-BR");
    expect(resolveLocale("", null, ["en-GB", "pt-BR"])).toBe("en");
  });

  it("[R-13-1] unsupported_language_falls_back_to_english", () => {
    expect(resolveLocale("?lang=fr", null, ["de-DE", "es"])).toBe("en");
    expect(resolveLocale("?lang=fr", "zz", ["fr-FR", "pt-BR"])).toBe("pt-BR");
    expect(resolveLocale("", null, [])).toBe("en");
  });
});

describe("catalogue", () => {
  it("[R-13-1] both languages define the same keys and none is empty", () => {
    expect(Object.keys(ptBR).sort()).toEqual(Object.keys(en).sort());
    for (const catalogue of [en, ptBR]) {
      for (const [key, text] of Object.entries(catalogue)) {
        expect(text.trim(), key).not.toBe("");
      }
    }
  });

  it("[R-13-1] a translation uses the same parameters as the English text", () => {
    for (const key of Object.keys(en) as Array<keyof typeof en>) {
      expect(placeholders(ptBR[key]).sort(), key).toEqual(placeholders(en[key]).sort());
    }
  });

  it("fills parameters and leaves a missing one visible", () => {
    expect(translate("en", "unit.mm", { value: "12.5" })).toBe("12.5 mm");
    expect(translate("pt-BR", "unit.days", { value: "3" })).toBe("3 dias");
    expect(interpolate("{a} and {b}", { a: 1 })).toBe("1 and {b}");
  });
});

describe("I18nProvider", () => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <I18nProvider>{children}</I18nProvider>
  );

  it("[R-13-1] html_lang_follows_the_locale", () => {
    const { result } = renderHook(() => useI18n(), { wrapper });
    expect(document.documentElement.lang).toBe(result.current.locale);

    act(() => result.current.setLocale("pt-BR"));
    expect(document.documentElement.lang).toBe("pt-BR");

    act(() => result.current.setLocale("en"));
    expect(document.documentElement.lang).toBe("en");
  });

  it("[R-13-1] the query string chooses the language and a switch is stored for the next visit", () => {
    window.history.replaceState(null, "", "/?lang=pt-BR");
    const { result } = renderHook(() => useI18n(), { wrapper });
    expect(result.current.locale).toBe("pt-BR");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBeNull();

    act(() => result.current.setLocale("en"));
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
  });

  it("[R-13-1] switching the language re-renders the text", () => {
    function Probe() {
      const { t, locale, setLocale } = useI18n();
      const other = LOCALES.find((candidate) => candidate !== locale) ?? locale;
      return <button onClick={() => setLocale(other)}>{t("step.price")}</button>;
    }
    render(
      <I18nProvider locale="en">
        <Probe />
      </I18nProvider>,
    );
    const button = screen.getByRole("button", { name: "Price" });

    act(() => button.click());

    expect(screen.getByRole("button", { name: "Preço" })).toBeInTheDocument();
  });

  it("useI18n fails loudly without a provider", () => {
    expect(() => renderHook(() => useI18n())).toThrow(/I18nProvider/);
  });
});

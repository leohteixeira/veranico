import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { components } from "../api/schema";
import { en, type MessageKey, type Messages } from "./en";
import { ptBR } from "./pt-BR";

export type { MessageKey } from "./en";

/** The two interface languages, as the API names them. */
export type Locale = components["schemas"]["ChatRequest"]["locale"];

export const LOCALES: readonly Locale[] = ["en", "pt-BR"];

/** One of the three things the application keeps in local storage (with theme and conversation). */
export const LOCALE_STORAGE_KEY = "veranico.locale";

const CATALOGUES: Record<Locale, Messages> = { en, "pt-BR": ptBR };

export type Params = Readonly<Record<string, string | number>>;

const PLACEHOLDER = /\{(\w+)\}/g;

/** The parameter names a template uses. */
export function placeholders(template: string): string[] {
  return [...template.matchAll(PLACEHOLDER)].map((match) => match[1] ?? "");
}

/** Fills `{name}` parameters; a parameter that was not given stays visible as `{name}`. */
export function interpolate(template: string, params: Params = {}): string {
  return template.replace(PLACEHOLDER, (whole, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : whole,
  );
}

export function translate(locale: Locale, key: MessageKey, params?: Params): string {
  return interpolate(CATALOGUES[locale][key], params);
}

/** The template of a key built at run time (an API code), or `undefined` when there is none. */
export function lookup(locale: Locale, key: string): string | undefined {
  const catalogue: Readonly<Record<string, string>> = CATALOGUES[locale];
  return Object.hasOwn(catalogue, key) ? catalogue[key] : undefined;
}

function matchLocale(tag: string | null | undefined): Locale | null {
  if (tag === null || tag === undefined) return null;
  const lower = tag.trim().toLowerCase();
  if (lower === "en" || lower.startsWith("en-")) return "en";
  if (lower === "pt" || lower.startsWith("pt-")) return "pt-BR";
  return null;
}

/**
 * The language of the interface: `?lang`, then the stored preference, then the first browser
 * language that is supported, then English.
 */
export function resolveLocale(
  search: string,
  stored: string | null,
  navigatorLanguages: readonly string[],
): Locale {
  const fromQuery = matchLocale(new URLSearchParams(search).get("lang"));
  if (fromQuery !== null) return fromQuery;
  const fromStorage = matchLocale(stored);
  if (fromStorage !== null) return fromStorage;
  for (const language of navigatorLanguages) {
    const fromBrowser = matchLocale(language);
    if (fromBrowser !== null) return fromBrowser;
  }
  return "en";
}

function readStoredLocale(): string | null {
  try {
    return window.localStorage.getItem(LOCALE_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** The language for this page view, from the URL, the stored preference and the browser. */
export function detectLocale(): Locale {
  return resolveLocale(window.location.search, readStoredLocale(), window.navigator.languages);
}

export interface I18n {
  locale: Locale;
  /** An explicit switch: stored as the preference for the next visit. */
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, params?: Params) => string;
}

const I18nContext = createContext<I18n | null>(null);

interface I18nProviderProps {
  /** The starting language; without it the language is detected. */
  locale?: Locale;
  children: ReactNode;
}

export function I18nProvider({ locale: initial, children }: I18nProviderProps) {
  const [locale, setLocaleState] = useState<Locale>(() => initial ?? detectLocale());

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {
      // The switch still holds for this page view.
    }
    setLocaleState(next);
  }, []);

  const value = useMemo<I18n>(
    () => ({
      locale,
      setLocale,
      t: (key, params) => translate(locale, key, params),
    }),
    [locale, setLocale],
  );

  return createElement(I18nContext.Provider, { value }, children);
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (value === null) throw new Error("useI18n needs an I18nProvider above it");
  return value;
}

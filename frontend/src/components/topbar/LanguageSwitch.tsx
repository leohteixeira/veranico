import { translate, useI18n, type Locale } from "../../i18n";
import { Pill } from "../common/Pill";

const SHORT: Record<Locale, string> = { en: "EN", "pt-BR": "PT" };

/** English or Brazilian Portuguese; the choice is stored and every text and number follows it. */
export function LanguageSwitch() {
  const { locale, setLocale } = useI18n();
  const option = (value: Locale) => ({
    value,
    label: (
      <>
        <span aria-hidden="true">{SHORT[value]}</span>
        {/* Each language is named in its own language, whatever the active one. */}
        <span className="sr-only" lang={value}>
          {translate(value, `language.${value}`)}
        </span>
      </>
    ),
  });
  return (
    <Pill
      label={translate(locale, "language.label")}
      value={locale}
      onChange={setLocale}
      options={[option("en"), option("pt-BR")]}
    />
  );
}

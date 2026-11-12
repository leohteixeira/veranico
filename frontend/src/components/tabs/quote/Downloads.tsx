import { LOCALES, translate, useI18n } from "../../../i18n";
import { Icon } from "../../common/Icon";

interface DownloadsProps {
  quoteId: string;
  /** The audit trail records that the term sheet was rendered. */
  termSheetRendered: boolean;
}

/** The API path of a term sheet in one language (SPEC 11.2). */
export function termSheetPath(quoteId: string, language: string): string {
  return `/api/v1/quotes/${encodeURIComponent(quoteId)}/term-sheet.pdf?lang=${encodeURIComponent(language)}`;
}

/** The API path of the evidence file of a quote. */
export function evidencePath(quoteId: string): string {
  return `/api/v1/quotes/${encodeURIComponent(quoteId)}/evidence.nc`;
}

/**
 * The files of a quote, as plain links to the API: the term sheet in each language and the
 * evidence. The term sheet links stay disabled until the agent has drafted it.
 */
export function Downloads({ quoteId, termSheetRendered }: DownloadsProps) {
  const { locale } = useI18n();
  return (
    <section className="quote__section">
      <h4>{translate(locale, "quote.downloads")}</h4>
      <ul className="downloads">
        {LOCALES.map((language) => {
          const label = translate(locale, "quote.term_sheet", {
            language: translate(locale, `language.${language}`),
          });
          return (
            <li key={language}>
              {termSheetRendered ? (
                <a className="downloads__link" href={termSheetPath(quoteId, language)} download>
                  <Icon name="download" />
                  {label}
                </a>
              ) : (
                // A link without a target is announced as disabled and takes no focus.
                <a className="downloads__link" role="link" aria-disabled="true">
                  <Icon name="download" />
                  {label}
                </a>
              )}
            </li>
          );
        })}
        <li>
          <a className="downloads__link" href={evidencePath(quoteId)} download>
            <Icon name="download" />
            {translate(locale, "quote.evidence")}
          </a>
        </li>
      </ul>
      {!termSheetRendered && (
        <p className="downloads__hint">{translate(locale, "quote.term_sheet_pending")}</p>
      )}
    </section>
  );
}

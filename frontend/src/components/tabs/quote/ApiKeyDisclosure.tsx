import { useState } from "react";

import type { components } from "../../../api/schema";
import { useApiKey } from "../../../hooks/useApiKey";
import { translate, useI18n } from "../../../i18n";
import { translateProblem } from "../../../i18n/coded";
import { formatDate } from "../../../i18n/format";
import { Button } from "../../common/Button";
import { Icon } from "../../common/Icon";
import { Note } from "../../common/Note";
import { Spinner } from "../../common/Spinner";
import { exampleRequest } from "./apiExample";

interface ApiKeyDisclosureProps {
  /** The quote the example request prices again. */
  quote: components["schemas"]["QuoteView"];
  /** Where the API is served; defaults to this page's origin. */
  origin?: string;
}

function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * Creates an API key for the workspace and shows it once, with a ready-to-run request. The secret
 * lives only in this component's mutation state: it is never written to storage, and hiding it or
 * leaving the tab drops it for good.
 */
export function ApiKeyDisclosure({ quote, origin }: ApiKeyDisclosureProps) {
  const { locale } = useI18n();
  const key = useApiKey();
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [copied, setCopied] = useState<"key" | "request" | null>(null);

  const create = () => {
    setCopied(null);
    setIdempotencyKey(newIdempotencyKey());
    key.mutate();
  };

  const hide = () => {
    key.reset();
    setIdempotencyKey(null);
    setCopied(null);
  };

  const copy = (what: "key" | "request", text: string) => {
    // Without clipboard access the text stays on screen to be selected by hand.
    void globalThis.navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(what);
      },
      () => {
        setCopied(null);
      },
    );
  };

  const issued = key.data;
  const request =
    issued === undefined || idempotencyKey === null
      ? null
      : exampleRequest({
          origin: origin ?? window.location.origin,
          secret: issued.secret,
          idempotencyKey,
          quote,
        });

  return (
    <section className="quote__section api-key">
      <h4>{translate(locale, "quote.api.title")}</h4>
      {issued === undefined || request === null ? (
        <>
          <p className="api-key__body">{translate(locale, "quote.api.body")}</p>
          {key.isError && (
            <p className="api-key__error" role="alert">
              {translateProblem(key.error.code, locale)}
            </p>
          )}
          <div>
            <Button variant="ghost" size="sm" onClick={create} disabled={key.isPending}>
              {key.isPending ? <Spinner /> : <Icon name="key" />}
              {translate(locale, key.isPending ? "quote.api.creating" : "quote.api.create")}
            </Button>
          </div>
        </>
      ) : (
        <>
          <Note tone="warn" icon={<Icon name="warn" />}>
            {translate(locale, "quote.api.once")}
          </Note>
          <div className="api-key__field">
            <span className="api-key__label">{translate(locale, "quote.api.secret")}</span>
            <code className="api-key__secret" data-secret="true">
              {issued.secret}
            </code>
            <span className="api-key__meta">
              {translate(locale, "quote.api.expires", {
                date: formatDate(issued.expires_at, locale),
              })}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                copy("key", issued.secret);
              }}
            >
              <Icon name={copied === "key" ? "check" : "copy"} />
              {translate(locale, copied === "key" ? "quote.api.copied" : "quote.api.copy")}
            </Button>
          </div>
          <div className="api-key__field">
            <span className="api-key__label">{translate(locale, "quote.api.example")}</span>
            <pre className="api-key__request" tabIndex={0}>
              {request}
            </pre>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                copy("request", request);
              }}
            >
              <Icon name={copied === "request" ? "check" : "copy"} />
              {translate(
                locale,
                copied === "request" ? "quote.api.copied" : "quote.api.copy_example",
              )}
            </Button>
          </div>
          <div>
            <Button variant="link" onClick={hide}>
              {translate(locale, "quote.api.hide")}
            </Button>
          </div>
          <span className="sr-only" role="status">
            {copied === null ? "" : translate(locale, "quote.api.copied")}
          </span>
        </>
      )}
    </section>
  );
}

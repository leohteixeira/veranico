import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { Icon } from "../../common/Icon";
import { Note } from "../../common/Note";
import { StateBadge, type StateTone } from "../../common/StateBadge";
import { TabEmpty, TabState, type DataStatus } from "../TabState";
import { ApiKeyDisclosure } from "./ApiKeyDisclosure";
import { Assumptions } from "./Assumptions";
import { AuditTrail } from "./AuditTrail";
import { CoverDefinition } from "./CoverDefinition";
import { Downloads } from "./Downloads";
import { Premium } from "./Premium";
import { Simulation } from "./Simulation";

import "../tabs.css";

type Schemas = components["schemas"];

/** The priced cover of a recording: what the recorded `price_cover` returned. */
export interface RecordedQuote {
  quoteId: string;
  priced: Schemas["PricedCover"];
}

interface QuoteTabProps {
  /** `GET /quotes/{id}` for the quote in view, or `null` when there is none (or not yet). */
  quote: Schemas["QuoteView"] | null;
  /**
   * In replay mode: the recorded quote. It is shown read-only and labelled as a recording, with no
   * downloads, no audit trail and no API key, because it does not exist in the workspace.
   */
  recorded?: RecordedQuote | null;
  status?: DataStatus;
  onRetry?: () => void;
  /** The field a figure link asked the tab to highlight. */
  highlight?: string | null;
  /** Where the API is served, for the example request; defaults to this page's origin. */
  origin?: string;
  /** Carrier id to the directory's name, so the audit trail names the carrier. */
  carrierNames?: ReadonlyMap<string, string>;
}

const TONE: Record<Schemas["QuoteView"]["status"], StateTone> = {
  draft: "neutral",
  pending_approval: "pending",
  approved: "pending",
  rejected: "bad",
  submitted: "ok",
};

const TERM_SHEET_RENDERED = "audit.term_sheet_rendered";

/**
 * The Quote tab: premium and rate on line first, then the simulation, the cover, the assumptions,
 * the downloads, the audit trail and the API key. Every figure is the API's value in the locale's
 * notation.
 */
export function QuoteTab({
  quote,
  recorded = null,
  status = "ready",
  onRetry,
  highlight = null,
  origin,
  carrierNames,
}: QuoteTabProps) {
  const { locale } = useI18n();

  if (recorded !== null) {
    const { priced } = recorded;
    return (
      <div className="quote" data-recording="true">
        <Note tone="wait" icon={<Icon name="play" />} data-note="recording">
          {translate(locale, "quote.recording")}
        </Note>
        <div className="quote__head">
          <h3 className="quote__id num">{recorded.quoteId}</h3>
        </div>
        <Premium premium={priced.premium} highlight={highlight} />
        <Simulation simulation={priced.simulation} highlight={highlight} />
        <CoverDefinition cover={priced.backtest.cover} highlight={highlight} />
        <Assumptions assumptions={priced.assumptions} />
      </div>
    );
  }

  if (quote === null) {
    return status === "ready" ? (
      <TabEmpty>{translate(locale, "quote.empty")}</TabEmpty>
    ) : (
      <TabState status={status} onRetry={onRetry} />
    );
  }

  const { priced } = quote;
  return (
    <div className="quote" data-quote={quote.quote_id}>
      <div className="quote__head">
        <h3 className="quote__id num">{quote.quote_id}</h3>
        <StateBadge
          tone={TONE[quote.status]}
          icon={quote.status === "submitted" ? <Icon name="check" /> : undefined}
        >
          {translate(locale, `status.quote.${quote.status}`)}
        </StateBadge>
      </div>
      <Premium premium={priced.premium} highlight={highlight} />
      <Simulation simulation={priced.simulation} highlight={highlight} />
      <CoverDefinition
        cover={quote.cover}
        location={quote.location}
        datasetId={quote.dataset_id}
        highlight={highlight}
      />
      <Assumptions assumptions={priced.assumptions} />
      <Downloads
        quoteId={quote.quote_id}
        termSheetRendered={quote.audit.some((entry) => entry.action.code === TERM_SHEET_RENDERED)}
      />
      <AuditTrail audit={quote.audit} carrierNames={carrierNames} />
      <ApiKeyDisclosure quote={quote} origin={origin} />
    </div>
  );
}

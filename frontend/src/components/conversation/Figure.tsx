import { translate, useI18n } from "../../i18n";
import type { TabId } from "../../state/view";
import type { FigureKey, Segment } from "./figures";

export type OpenFigure = (tab: TabId, key: FigureKey | null) => void;

interface FigureProps {
  segment: Exclude<Segment, { kind: "text" }>;
  onOpen: OpenFigure;
}

/**
 * A figure of an answer. One with a source is a button that opens the tab holding it and
 * highlights the field; one the grounding check flagged is marked and is not a link.
 */
export function Figure({ segment, onOpen }: FigureProps) {
  const { locale } = useI18n();
  if (segment.kind === "flagged") {
    return (
      <mark className="fig fig--flagged" data-flagged="true">
        {segment.text}
        <span className="sr-only"> ({translate(locale, "chat.figure.flagged")})</span>
      </mark>
    );
  }
  const { tab, key, text } = segment;
  const label = translate(locale, "chat.figure.open", {
    value: text,
    tab: translate(locale, `tab.${tab}`),
  });
  return (
    <button
      type="button"
      className="fig"
      title={label}
      aria-label={label}
      data-tab={tab}
      data-key={key ?? ""}
      onClick={() => {
        onOpen(tab, key);
      }}
    >
      {text}
    </button>
  );
}

import { useId, useState, type FormEvent, type KeyboardEvent } from "react";

import type { components } from "../../api/schema";
import { translate, useI18n } from "../../i18n";
import { translateProblem } from "../../i18n/coded";
import { formatNumber } from "../../i18n/format";
import type { SessionProblem } from "../../state/session";
import { Icon } from "../common/Icon";

type GridPoint = components["schemas"]["GridPoint"];

interface ComposerProps {
  /** A turn is in progress: nothing can be sent until it ends. */
  locked: boolean;
  /** The last request was refused before any event; shown here, next to the text it refused. */
  problem: SessionProblem | null;
  /** The text of the refused request, handed back for editing. */
  rejectedText: string | null;
  /** A point the visitor marked on the map: it prefills a request and is sent with it. */
  mapPoint: GridPoint | null;
  onClearMapPoint: () => void;
  onSend: (text: string, mapPoint: GridPoint | null) => void;
}

export function Composer({
  locked,
  problem,
  rejectedText,
  mapPoint,
  onClearMapPoint,
  onSend,
}: ComposerProps) {
  const { locale } = useI18n();
  const [draft, setDraft] = useState("");
  const errorId = useId();
  const hintId = useId();

  const coordinates =
    mapPoint === null
      ? null
      : {
          lat: formatNumber(mapPoint.lat, locale, { maximumFractionDigits: 4 }),
          lon: formatNumber(mapPoint.lon, locale, { maximumFractionDigits: 4 }),
        };

  // A refused request comes back to the composer; a marked point prefills an empty one. Both are
  // adjusted while rendering, when the property changes, so no effect writes state.
  const [seenRejected, setSeenRejected] = useState<string | null>(null);
  const [seenPoint, setSeenPoint] = useState<GridPoint | null>(null);
  if (rejectedText !== seenRejected || mapPoint !== seenPoint) {
    let next = draft;
    if (rejectedText !== seenRejected && rejectedText !== null) next = rejectedText;
    if (mapPoint !== seenPoint && coordinates !== null && next.trim() === "") {
      next = translate(locale, "chat.map_point_request", coordinates);
    }
    setSeenRejected(rejectedText);
    setSeenPoint(mapPoint);
    if (next !== draft) setDraft(next);
  }

  const text = draft.trim();
  const canSend = !locked && text !== "";

  const submit = () => {
    if (!canSend) return;
    onSend(text, mapPoint);
    setDraft("");
    if (mapPoint !== null) onClearMapPoint();
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  };

  return (
    <form className="composer" onSubmit={onSubmit}>
      {coordinates !== null && (
        <p className="composer__point">
          <Icon name="pin" />
          <span>{translate(locale, "chat.map_point", coordinates)}</span>
          <button
            type="button"
            className="composer__point-remove"
            aria-label={translate(locale, "chat.map_point_remove")}
            onClick={onClearMapPoint}
          >
            <Icon name="close" />
          </button>
        </p>
      )}
      <div className="composer__row">
        <textarea
          className="composer__input"
          rows={2}
          value={draft}
          readOnly={locked}
          aria-label={translate(locale, "chat.input")}
          aria-describedby={problem === null ? hintId : `${errorId} ${hintId}`}
          aria-invalid={problem === null ? undefined : true}
          placeholder={translate(locale, "chat.placeholder")}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
          onKeyDown={onKeyDown}
        />
        <button
          type="submit"
          className="composer__send"
          disabled={!canSend}
          aria-label={translate(locale, "chat.send")}
        >
          <Icon name="send" />
        </button>
      </div>
      {problem !== null && (
        <p id={errorId} className="composer__error" role="alert" data-problem={problem.code}>
          <Icon name="warn" />
          <span>
            {translateProblem(problem.code, locale)}
            {problem.traceId !== null && (
              <span className="composer__reference">
                {" "}
                {translate(locale, "error.reference", { trace_id: problem.traceId })}
              </span>
            )}
          </span>
        </p>
      )}
      <small id={hintId} className="composer__hint">
        {translate(locale, "chat.hint")}
      </small>
    </form>
  );
}

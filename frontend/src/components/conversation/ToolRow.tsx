import { useId, useState } from "react";

import { translate, useI18n } from "../../i18n";
import { translateCoded, translateValue } from "../../i18n/coded";
import { formatMs } from "../../i18n/format";
import type { ToolRow as ToolRowState } from "../../state/session";
import { Icon } from "../common/Icon";
import { Spinner } from "../common/Spinner";

interface ToolRowProps {
  row: ToolRowState;
}

/**
 * One tool call: the tool's identifier and name, the translated summary of what it returned, its
 * status and duration. The row opens to the arguments the agent passed, when they are known (a
 * restored conversation keeps results, not arguments).
 */
export function ToolRow({ row }: ToolRowProps) {
  const { locale } = useI18n();
  const [open, setOpen] = useState(false);
  const panelId = useId();

  let summary: string | null = null;
  if (row.status === "error") {
    const code = row.error?.error_code;
    summary = translateCoded(
      { code: "tool.error", params: code === undefined ? {} : { error_code: code } },
      locale,
    );
  } else if (row.summary !== null) {
    summary = translateCoded(row.summary, locale);
  }

  const head = (
    <>
      <span className="tool__mark">
        {row.status === "running" && <Spinner />}
        {row.status === "ok" && <Icon name="check" />}
        {row.status === "error" && <Icon name="warn" />}
      </span>
      <span className="tool__what">
        <span className="tool__id">{row.tool}</span>
        <span className="tool__name">{translateValue("toolname", row.tool, locale)}</span>
        {summary !== null && <span className="tool__summary">{summary}</span>}
      </span>
      <span className="tool__status">
        {row.status === "running" && translate(locale, "chat.tool.running")}
        {row.status === "ok" && (
          <span className="sr-only">{translate(locale, "chat.tool.ok")}</span>
        )}
        {row.status === "error" && translate(locale, "chat.tool.failed")}
        {row.durationMs !== null && (
          <span className="tool__duration">{formatMs(row.durationMs, locale)}</span>
        )}
      </span>
    </>
  );

  return (
    <li className="tool" data-tool={row.tool} data-status={row.status}>
      {row.arguments === null ? (
        <div className="tool__head">{head}</div>
      ) : (
        <>
          <button
            type="button"
            className="tool__head tool__head--toggle"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => {
              setOpen((value) => !value);
            }}
          >
            {head}
          </button>
          <div id={panelId} className="tool__panel" hidden={!open}>
            <p className="tool__panel-title">{translate(locale, "chat.tool.arguments")}</p>
            <pre className="tool__arguments">{JSON.stringify(row.arguments, null, 1)}</pre>
          </div>
        </>
      )}
    </li>
  );
}

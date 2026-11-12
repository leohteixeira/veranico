import { useId, useState } from "react";

import type { components } from "../../../api/schema";
import { translate, useI18n } from "../../../i18n";
import { formatIndexValue, formatMoney, formatSeason } from "../../../i18n/format";
import { Button } from "../../common/Button";
import { pays, type SeasonResult } from "./chart";

type IndexType = components["schemas"]["IndexDefinition"]["index_type"];

interface SeasonTableProps {
  seasons: readonly SeasonResult[];
  indexType: IndexType;
  selected: number | null;
  onSelect: (season: number) => void;
}

/**
 * The table view of the two panels: every season with its index value and its payout, for anyone
 * who cannot or would rather not read the bars. It opens on request so the tab stays short.
 */
export function SeasonTable({ seasons, indexType, selected, onSelect }: SeasonTableProps) {
  const { locale } = useI18n();
  const [open, setOpen] = useState(false);
  const tableId = useId();

  return (
    <div className="season-table">
      <Button
        variant="link"
        aria-expanded={open}
        aria-controls={tableId}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        {translate(locale, open ? "history.table.hide" : "history.table.show")}
      </Button>
      <div id={tableId} className="season-table__scroll" hidden={!open}>
        <table>
          <caption className="sr-only">{translate(locale, "history.table.caption")}</caption>
          <thead>
            <tr>
              <th scope="col">{translate(locale, "history.table.season")}</th>
              <th scope="col">{translate(locale, "history.table.index")}</th>
              <th scope="col">{translate(locale, "history.table.payout")}</th>
            </tr>
          </thead>
          <tbody>
            {seasons.map((season) => (
              <tr
                key={season.season}
                data-season={season.season}
                data-selected={selected === season.season ? "true" : undefined}
                data-pays={pays(season) ? "true" : undefined}
              >
                <th scope="row" className="num">
                  <button
                    type="button"
                    className="season-table__season"
                    aria-pressed={selected === season.season}
                    onClick={() => {
                      onSelect(season.season);
                    }}
                  >
                    {formatSeason(season.season)}
                  </button>
                </th>
                <td className="num">{formatIndexValue(season.index_value, indexType, locale)}</td>
                <td className="num">
                  {pays(season) && season.payout !== null ? (
                    formatMoney(season.payout.amount_cents, locale)
                  ) : (
                    <>
                      <span aria-hidden="true">–</span>
                      <span className="sr-only">{translate(locale, "history.no_payout")}</span>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

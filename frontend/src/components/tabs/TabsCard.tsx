import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

import { translate, useI18n } from "../../i18n";
import type { TabId } from "../../state/view";
import { Card } from "../common/Card";

import "./tabs.css";

export const TAB_ORDER: readonly TabId[] = ["risk", "history", "quote", "approvals"];

interface TabsCardProps {
  tab: TabId;
  onTab: (tab: TabId) => void;
  /** The content of each tab; only the open one is rendered. */
  panels: Readonly<Record<TabId, ReactNode>>;
  /** A count shown on a tab (pending approvals). Zero and absent show nothing. */
  badges?: Readonly<Partial<Record<TabId, number>>>;
  className?: string;
}

/**
 * The tabs card: Risk, History, Quote, Approvals. It follows the ARIA tabs pattern with automatic
 * activation: one tab stop, arrow keys (and Home and End) move to a tab and open it.
 */
export function TabsCard({ tab, onTab, panels, badges, className }: TabsCardProps) {
  const { locale } = useI18n();
  const baseId = useId();
  const list = useRef<HTMLDivElement>(null);
  const tabId = (id: TabId) => `${baseId}-tab-${id}`;
  const panelId = `${baseId}-panel`;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const at = TAB_ORDER.indexOf(tab);
    let next: number;
    if (event.key === "ArrowRight") next = (at + 1) % TAB_ORDER.length;
    else if (event.key === "ArrowLeft") next = (at - 1 + TAB_ORDER.length) % TAB_ORDER.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = TAB_ORDER.length - 1;
    else return;
    event.preventDefault();
    const target = TAB_ORDER[next];
    if (target === undefined) return;
    onTab(target);
    list.current?.querySelector<HTMLElement>(`[data-tab="${target}"]`)?.focus();
  };

  return (
    <Card
      as="section"
      className={className === undefined ? "tabs" : `tabs ${className}`}
      aria-label={translate(locale, "tabs.label")}
      data-tab={tab}
    >
      <div
        ref={list}
        className="tabs__list"
        role="tablist"
        aria-label={translate(locale, "tabs.label")}
        onKeyDown={onKeyDown}
      >
        {TAB_ORDER.map((id) => {
          const selected = id === tab;
          const badge = badges?.[id] ?? 0;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              id={tabId(id)}
              className="tabs__tab"
              data-tab={id}
              aria-selected={selected}
              aria-controls={selected ? panelId : undefined}
              tabIndex={selected ? 0 : -1}
              onClick={() => {
                if (!selected) onTab(id);
              }}
            >
              {translate(locale, `tab.${id}`)}
              {badge > 0 && (
                <span className="tabs__badge num" data-count={badge}>
                  <span aria-hidden="true">{badge}</span>
                  <span className="sr-only">
                    {" "}
                    {translate(locale, badge === 1 ? "tabs.badge.one" : "tabs.badge.other", {
                      count: badge,
                    })}
                  </span>
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div
        id={panelId}
        className="tabs__panel"
        role="tabpanel"
        aria-labelledby={tabId(tab)}
        tabIndex={0}
      >
        {panels[tab]}
      </div>
    </Card>
  );
}

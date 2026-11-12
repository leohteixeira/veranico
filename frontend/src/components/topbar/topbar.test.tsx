import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider, type Locale } from "../../i18n";
import { REGIONS } from "../../test/fixtures/bodies";
import { TopBar } from "./TopBar";

function handlers() {
  return {
    onRegion: vi.fn(),
    onBasemap: vi.fn(),
    onRender: vi.fn(),
    onTheme: vi.fn(),
  };
}

function renderTop(overrides: Partial<Parameters<typeof TopBar>[0]> = {}, locale: Locale = "en") {
  const calls = handlers();
  render(
    <I18nProvider locale={locale}>
      <TopBar
        regions={REGIONS}
        regionId="sul-de-minas"
        outside={false}
        basemap="relief"
        render="surface"
        theme="light"
        {...calls}
        {...overrides}
      />
    </I18nProvider>,
  );
  return calls;
}

/** The controls in the order the Tab key visits them: document order, none taken out of it. */
function tabStops(): HTMLElement[] {
  const stops = [...document.querySelectorAll<HTMLElement>("button, select, a[href], input")];
  for (const stop of stops) {
    expect(stop).not.toHaveAttribute("tabindex");
    expect(stop).toBeEnabled();
  }
  return stops;
}

describe("top row [R-12.1-2]", () => {
  it("top_row_controls_are_reachable_by_keyboard_in_order [R-12.1-2]", () => {
    renderTop();
    expect(screen.getByRole("heading", { level: 1, name: "Veranico" })).toBeInTheDocument();

    const names = tabStops().map((stop) => {
      if (stop instanceof HTMLAnchorElement) return `Link:${stop.getAttribute("aria-label") ?? ""}`;
      const group = stop.closest('[role="group"][aria-label]:not(.topbar__controls)');
      const own = stop instanceof HTMLSelectElement ? "" : (stop.textContent ?? "");
      return `${group?.getAttribute("aria-label") ?? "Region"}:${own}`;
    });
    expect(names).toEqual([
      "Link:Veranico, about the project",
      "Region:",
      "Basemap:Relief",
      "Basemap:Satellite",
      "Risk layer:Surface",
      "Risk layer:Cells",
      "Language:ENEnglish",
      "Language:PTPortuguês",
      "Theme:Light",
      "Theme:Dark",
    ]);

    // Native controls: Enter and Space press a button, the arrow keys move a select.
    expect(screen.getByRole("combobox", { name: "Region" }).tagName).toBe("SELECT");
    expect(screen.getByRole("group", { name: "View settings" })).toBeInTheDocument();
  });

  it("each switch says which option is on and reports the other", () => {
    const calls = renderTop();

    const basemap = within(screen.getByRole("group", { name: "Basemap" }));
    expect(basemap.getByRole("button", { name: "Relief" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(basemap.getByRole("button", { name: "Satellite" }));
    expect(calls.onBasemap).toHaveBeenCalledWith("satellite");

    const layer = within(screen.getByRole("group", { name: "Risk layer" }));
    expect(layer.getByRole("button", { name: "Surface" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(layer.getByRole("button", { name: "Cells" }));
    expect(calls.onRender).toHaveBeenCalledWith("cells");

    const theme = within(screen.getByRole("group", { name: "Theme" }));
    expect(theme.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(theme.getByRole("button", { name: "Dark" }));
    expect(calls.onTheme).toHaveBeenCalledWith("dark");
  });

  it("the region selector lists every region with its crop and reports a choice", () => {
    const calls = renderTop();
    const select = screen.getByRole("combobox", { name: "Region" });
    expect(select).toHaveValue("sul-de-minas");
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Sul de Minas · Coffee", "Sorriso · Soybean", "Ribeirão Preto · Sugarcane"]);

    fireEvent.change(select, { target: { value: "sorriso" } });
    expect(calls.onRegion).toHaveBeenCalledWith("sorriso");
  });

  it("a point outside every region is named in the selector [R-12.4-6]", () => {
    renderTop({ regionId: null, outside: true });
    const select = screen.getByRole("combobox", { name: "Region" });
    expect(select).toHaveDisplayValue("Outside the showcase regions");
    // It is a state, not a choice.
    expect(
      within(select).getByRole("option", { name: "Outside the showcase regions" }),
    ).toBeDisabled();
  });

  it("the region selector is the styled native control, with the chevron drawn beside it", () => {
    renderTop();
    const select = screen.getByRole("combobox", { name: "Region" });
    expect(select).toHaveClass("region-select__control");
    const chevron = select.parentElement?.querySelector(".region-select__chevron");
    expect(chevron).toHaveAttribute("aria-hidden", "true");
  });

  it("the selector waits for the regions", () => {
    renderTop({ regions: [], regionId: null });
    expect(screen.getByRole("combobox", { name: "Region" })).toBeDisabled();
  });

  it.each([
    ["en", "Veranico, about the project", "https://leohteixeira.com/en/projects/veranico"],
    ["pt-BR", "Veranico, sobre o projeto", "https://leohteixeira.com/pt/projects/veranico"],
  ] as const)(
    "the wordmark links to the project page in the active language (%s)",
    (locale, name, href) => {
      renderTop({}, locale);
      const link = screen.getByRole("link", { name });
      expect(link).toHaveAttribute("href", href);
      // Same tab: the visitor goes to the presentation page, not to a second window.
      expect(link).not.toHaveAttribute("target");
      expect(within(link).getByRole("heading", { level: 1, name: "Veranico" })).toBeVisible();
    },
  );

  it("the wordmark follows a change of language", () => {
    renderTop();
    fireEvent.click(screen.getByRole("button", { name: /Português/ }));
    expect(screen.getByRole("link", { name: "Veranico, sobre o projeto" })).toHaveAttribute(
      "href",
      "https://leohteixeira.com/pt/projects/veranico",
    );
  });

  it("the language switch names each language in its own language", () => {
    renderTop({}, "pt-BR");
    const language = within(screen.getByRole("group", { name: "Idioma" }));
    const english = language.getByRole("button", { name: /English/ });
    const portuguese = language.getByRole("button", { name: /Português/ });
    expect(english).toHaveAttribute("aria-pressed", "false");
    expect(portuguese).toHaveAttribute("aria-pressed", "true");
    expect(english.querySelector("[lang]")).toHaveAttribute("lang", "en");

    fireEvent.click(english);
    expect(screen.getByRole("group", { name: "Language" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Risk layer" })).toBeInTheDocument();
  });
});

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";
import { Card } from "./Card";
import { ICON_NAMES, Icon } from "./Icon";
import { Note } from "./Note";
import { Pill } from "./Pill";
import { Spinner } from "./Spinner";
import { StateBadge } from "./StateBadge";

// Read from disk: Vitest does not process stylesheets, so a `?raw` import of one is empty.
const commonCss = readFileSync(join(import.meta.dirname, "common.css"), "utf8");

describe("primitives", () => {
  it("[R-16.7-1] no primitive removes the focus ring", () => {
    expect(commonCss).toContain(".btn");
    expect(commonCss).not.toMatch(/outline(-style)?\s*:\s*(0|none)\b/);
  });

  it("[R-16.7-1] Card renders its content in the element asked for", () => {
    render(
      <Card as="section" aria-label="Conversation" className="chat">
        body
      </Card>,
    );

    const card = screen.getByRole("region", { name: "Conversation" });
    expect(card).toHaveClass("card", "chat");
    expect(card).toHaveTextContent("body");
  });

  it("[R-16.7-1] Button is a keyboard-focusable button that never submits by default", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={onClick}>Approve</Button>);

    const button = screen.getByRole("button", { name: "Approve" });
    expect(button).toHaveAttribute("type", "button");

    await user.tab();
    expect(button).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("[R-16.7-1] Button variants and sizes map to classes, and a disabled button does not fire", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <Button variant="reject" size="sm" disabled onClick={onClick}>
        Reject
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Reject" });
    expect(button).toHaveClass("btn", "btn--reject", "btn--sm");
    await user.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("[R-16.7-1] Pill presses exactly one option and reports a change", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Pill
        label="Basemap"
        value="relief"
        onChange={onChange}
        options={[
          { value: "relief", label: "Relief" },
          { value: "satellite", label: "Satellite" },
        ]}
      />,
    );

    const group = screen.getByRole("group", { name: "Basemap" });
    const relief = within(group).getByRole("button", { name: "Relief" });
    const satellite = within(group).getByRole("button", { name: "Satellite" });
    expect(relief).toHaveAttribute("aria-pressed", "true");
    expect(satellite).toHaveAttribute("aria-pressed", "false");

    await user.tab();
    expect(relief).toHaveFocus();
    await user.click(relief);
    expect(onChange).not.toHaveBeenCalled();

    await user.tab();
    await user.keyboard(" ");
    expect(onChange).toHaveBeenCalledExactlyOnceWith("satellite");
  });

  it("[R-16.7-1] Note shows its icon and text, with the tone as a class and the role it is given", () => {
    render(
      <Note tone="warn" role="alert" icon={<Icon name="warn" />}>
        The trend is significant.
      </Note>,
    );

    const note = screen.getByRole("alert");
    expect(note).toHaveClass("note", "note--warn");
    expect(note).toHaveTextContent("The trend is significant.");
    expect(note.querySelector('[data-icon="warn"]')).not.toBeNull();
  });

  it("[R-16.7-1] StateBadge carries the state as text, not only as colour", () => {
    render(<StateBadge tone="ok">Approved</StateBadge>);

    const badge = screen.getByText("Approved");
    expect(badge).toHaveClass("state", "state--ok");
    expect(badge).toHaveAttribute("data-tone", "ok");
  });

  it("[R-16.7-1] Spinner is a named status with a label and decorative without one", () => {
    const { container, rerender } = render(<Spinner label="Running" />);
    expect(screen.getByRole("status")).toHaveTextContent("Running");

    rerender(<Spinner />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(container.querySelector(".spin")).toHaveAttribute("aria-hidden", "true");
  });

  it("[R-16.7-1] Icon is decorative unless it is given a title, and every name draws", () => {
    const { container, rerender } = render(<Icon name="check" />);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");

    rerender(<Icon name="check" title="Delivered" />);
    expect(screen.getByRole("img", { name: "Delivered" })).toBeInTheDocument();

    for (const name of ICON_NAMES) {
      rerender(<Icon name={name} />);
      expect(container.querySelectorAll("svg path").length, name).toBeGreaterThan(0);
    }
  });
});

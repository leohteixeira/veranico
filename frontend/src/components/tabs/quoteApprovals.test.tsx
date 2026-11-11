import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientProvider, createApiClient } from "../../api/client";
import type { components } from "../../api/schema";
import { DELIVERY_POLL_MS } from "../../hooks/useApprovals";
import { I18nProvider } from "../../i18n";
import { formatMoney, formatRate } from "../../i18n/format";
import { createMockState, handle, type MockState } from "../../test/mocks/handlers";
import {
  API_KEY,
  CARRIER_NAME,
  DATASET_ID,
  POINT_LABEL,
  QUOTE_ID,
  RECEIPT_ID,
  SUBMISSION_ID,
  approvalView,
  pendingQuote,
  pricedCover,
  problem,
  quoteView,
} from "../../test/fixtures/bodies";
import { ApprovalItem, NOTE_MAX } from "./approvals/ApprovalItem";
import { ApprovalsTab, pendingCount } from "./approvals/ApprovalsTab";
import { createQuoteBody } from "./quote/apiExample";
import { QuoteTab } from "./quote/QuoteTab";
import { readRecordedQuote } from "./quote/recorded";
import { TabsCard } from "./TabsCard";

type Schemas = components["schemas"];
type Transport = (request: Request) => Promise<Response>;

const BASE_URL = "http://veranico.test";
const ORIGIN = "https://veranico.example";

function plain(text: string | null | undefined): string {
  return (text ?? "").replaceAll(" ", " ");
}

function money(value: Schemas["Money"]): string {
  return plain(formatMoney(value.amount_cents, "en"));
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": status >= 400 ? "application/problem+json" : "application/json" },
  });
}

function is(request: Request, method: string, path: string): boolean {
  return request.method === method && new URL(request.url).pathname === path;
}

interface Harness {
  calls: string[];
  bodies: unknown[];
  state: MockState;
}

function renderWithApi(children: ReactNode, transport?: (state: MockState) => Transport): Harness {
  const state = createMockState("happy");
  const calls: string[] = [];
  const bodies: unknown[] = [];
  const answer = transport?.(state) ?? ((request: Request) => handle(request, state));
  const client = createApiClient({
    baseUrl: BASE_URL,
    fetch: async (request) => {
      calls.push(`${request.method} ${new URL(request.url).pathname}`);
      if (request.method === "POST") {
        const text = await request.clone().text();
        bodies.push(text === "" ? null : JSON.parse(text));
      }
      return answer(request);
    },
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ApiClientProvider client={client}>
        <I18nProvider locale="en">{children}</I18nProvider>
      </ApiClientProvider>
    </QueryClientProvider>,
  );
  return { calls, bodies, state };
}

function field(name: string, root: ParentNode = document): string {
  return plain(root.querySelector(`[data-field="${name}"] dd`)?.textContent);
}

function count(calls: readonly string[], call: string): number {
  return calls.filter((candidate) => candidate === call).length;
}

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("quote tab [R-12.3-3]", () => {
  it("premium_and_rate_come_first [R-12.3-3]", () => {
    renderWithApi(<QuoteTab quote={quoteView()} origin={ORIGIN} />);
    const fields = [...document.querySelectorAll(".quote [data-field]")].map((element) =>
      element.getAttribute("data-field"),
    );
    expect(fields.slice(0, 3)).toEqual(["premium", "rate_on_line", "expected_loss"]);
    expect(screen.getByRole("heading", { name: QUOTE_ID })).toBeVisible();
    expect(screen.getByText("Draft")).toBeVisible();
    // Then, in order: simulation, cover, assumptions, downloads, audit trail, API key.
    const sections = screen.getAllByRole("heading", { level: 4 }).map((item) => item.textContent);
    expect(sections).toEqual([
      "Simulation",
      "Cover",
      "Assumptions",
      "Downloads",
      "Audit trail",
      "Use the API",
    ]);
  });

  it("every_figure_is_the_api_value_formatted [R-12-2]", () => {
    const quote = quoteView();
    const { premium, simulation } = quote.priced;
    renderWithApi(<QuoteTab quote={quote} origin={ORIGIN} highlight="payout_1_in_100" />);
    expect(field("premium")).toBe(money(premium.premium));
    expect(field("rate_on_line")).toBe(formatRate(premium.rate_on_line, "en"));
    expect(field("expected_loss")).toBe(money(simulation.expected_loss));
    expect(field("std_dev")).toBe(money(simulation.std_dev));
    expect(field("probability_of_payout")).toBe(formatRate(simulation.probability_of_payout, "en"));
    expect(field("payout_1_in_10")).toBe(money(simulation.payout_1_in_10));
    expect(field("payout_1_in_100")).toBe(money(simulation.payout_1_in_100));
    expect(field("gap_to_burn_cost")).toBe(money(simulation.gap_to_burn_cost));
    expect(field("limit")).toBe(money(quote.cover.limit));
    expect(field("trigger")).toBe("105.0 mm");
    expect(field("exit")).toBe("70.0 mm");
    expect(field("window")).toBe("Sep 1 – Oct 31");
    expect(field("index")).toBe("rainfall below a trigger");
    expect(field("dataset")).toBe(DATASET_ID);
    expect(field("location")).toBe(`${POINT_LABEL} · -21.3667, -45.5125`);
    // The field a figure link asked for is highlighted, and only that one.
    const highlighted = [...document.querySelectorAll('[data-highlight="true"]')];
    expect(highlighted.map((element) => element.getAttribute("data-field"))).toEqual([
      "payout_1_in_100",
    ]);
  });

  it("assumptions_and_audit_actions_are_translated [R-12.3-3]", () => {
    renderWithApi(<QuoteTab quote={pendingQuote()} origin={ORIGIN} />);
    const assumptions = [...document.querySelectorAll("[data-assumption]")].map(
      (item) => item.textContent,
    );
    expect(assumptions).toEqual([
      "Index: rainfall below a trigger.",
      "Coverage window from Sep 1 to Oct 31; a season is labelled by its start year.",
      "76 seasons used, 1950 to 2025.",
      "Gamma distribution fitted to the seasonal totals; 100,000 simulated seasons; seed 42.",
      "Risk load of 30% on the standard deviation; expense load of 15% on the expected loss.",
      "Weather data: ERA5-Land, Copernicus Climate Change Service.",
    ]);
    const actions = [...document.querySelectorAll(".audit__action")].map(
      (item) => item.textContent,
    );
    expect(actions).toEqual([
      "Quote created as a draft",
      "Term sheet rendered (English)",
      "Submission requested for carrier-1",
    ]);
    const entry = document.querySelector('[data-action="audit.quote_created"]');
    expect(entry?.querySelector("[data-actor]")).toHaveTextContent("Agent");
    expect(entry?.querySelector("time")).toHaveAttribute("datetime", "2026-11-11T22:58:20Z");
    expect(screen.getByText("Pending approval")).toBeVisible();
  });

  it("downloads_link_to_the_api_paths [R-12.3-3]", () => {
    renderWithApi(<QuoteTab quote={pendingQuote()} origin={ORIGIN} />);
    expect(screen.getByRole("link", { name: "Term sheet, English (PDF)" })).toHaveAttribute(
      "href",
      `/api/v1/quotes/${QUOTE_ID}/term-sheet.pdf?lang=en`,
    );
    expect(screen.getByRole("link", { name: "Term sheet, Português (PDF)" })).toHaveAttribute(
      "href",
      `/api/v1/quotes/${QUOTE_ID}/term-sheet.pdf?lang=pt-BR`,
    );
    expect(screen.getByRole("link", { name: "Evidence (NetCDF)" })).toHaveAttribute(
      "href",
      `/api/v1/quotes/${QUOTE_ID}/evidence.nc`,
    );
  });

  it("term_sheet_disabled_until_rendered [R-12.3-3]", () => {
    // The draft the agent has just priced: no term sheet in its audit trail yet.
    renderWithApi(<QuoteTab quote={quoteView()} origin={ORIGIN} />);
    for (const name of ["Term sheet, English (PDF)", "Term sheet, Português (PDF)"]) {
      const link = screen.getByRole("link", { name });
      expect(link).toHaveAttribute("aria-disabled", "true");
      expect(link).not.toHaveAttribute("href");
    }
    expect(
      screen.getByText("The term sheet is available once the agent has drafted it."),
    ).toBeVisible();
    // The evidence does not wait for the term sheet.
    expect(screen.getByRole("link", { name: "Evidence (NetCDF)" })).toHaveAttribute("href");
  });

  it("api_key_secret_is_shown_once_and_not_stored [R-10.2-1]", async () => {
    const { calls } = renderWithApi(<QuoteTab quote={quoteView()} origin={ORIGIN} />);
    expect(document.body).not.toHaveTextContent(API_KEY.secret);
    fireEvent.click(screen.getByRole("button", { name: "Create an API key" }));

    const secret = await waitFor(() => {
      const element = document.querySelector('[data-secret="true"]');
      if (element === null) throw new Error("the key is not shown yet");
      return element;
    });
    expect(secret).toHaveTextContent(API_KEY.secret);
    expect(
      screen.getByText("Copy it now. It is shown this once and cannot be shown again."),
    ).toBeVisible();
    // Nothing of it is written to the browser's storage.
    for (const storage of [window.localStorage, window.sessionStorage]) {
      for (let at = 0; at < storage.length; at += 1) {
        expect(storage.getItem(storage.key(at) ?? "")).not.toContain(API_KEY.secret);
      }
      expect(storage.length).toBe(0);
    }
    expect(document.cookie).not.toContain(API_KEY.secret);

    // Hiding it drops it: it cannot be shown again, only replaced by a new key.
    fireEvent.click(screen.getByRole("button", { name: "Done, hide the key" }));
    expect(document.body).not.toHaveTextContent(API_KEY.secret);
    expect(screen.getByRole("button", { name: "Create an API key" })).toBeEnabled();
    expect(count(calls, "POST /api/v1/workspace/api-keys")).toBe(1);
  });

  it("example_request_uses_the_issued_key_and_an_idempotency_key [R-12.3-3]", async () => {
    renderWithApi(<QuoteTab quote={quoteView()} origin={ORIGIN} />);
    fireEvent.click(screen.getByRole("button", { name: "Create an API key" }));
    const request = await waitFor(() => {
      const element = document.querySelector(".api-key__request");
      if (element === null) throw new Error("no example request yet");
      return element.textContent ?? "";
    });
    expect(request).toContain(`curl -X POST '${ORIGIN}/api/v1/quotes'`);
    expect(request).toContain(`-H 'Authorization: Bearer ${API_KEY.secret}'`);
    expect(request).toMatch(
      /-H 'Idempotency-Key: [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'/,
    );
    expect(request).toContain("-H 'Content-Type: application/json'");
  });

  it("example_request_body_is_a_create_quote_without_dataset_id [R-12.3-3]", async () => {
    const quote = quoteView();
    renderWithApi(<QuoteTab quote={quote} origin={ORIGIN} />);
    fireEvent.click(screen.getByRole("button", { name: "Create an API key" }));
    const request = await waitFor(() => {
      const element = document.querySelector(".api-key__request");
      if (element === null) throw new Error("no example request yet");
      return element.textContent ?? "";
    });
    const start = request.indexOf("-d '") + 4;
    const body: unknown = JSON.parse(request.slice(start, request.lastIndexOf("'")));
    expect(body).toEqual({
      location: {
        lat: quote.location.lat,
        lon: quote.location.lon,
        label: quote.location.label,
        admin_region: quote.location.admin_region,
      },
      cover: quote.cover,
      simulation: { n: quote.priced.simulation.n, seed: quote.priced.simulation.seed },
    });
    expect(body).toEqual(createQuoteBody(quote));
    expect(JSON.stringify(body)).not.toContain("dataset_id");
    expect(JSON.stringify(body)).not.toContain("h3_cell");
  });

  it("replay_quote_is_read_only_and_labelled [R-9.6-2]", () => {
    const recorded = readRecordedQuote({ quote_id: QUOTE_ID, priced: pricedCover() });
    if (recorded === null) throw new Error("the recorded result was not read");
    renderWithApi(<QuoteTab quote={null} recorded={recorded} origin={ORIGIN} />);
    expect(document.querySelector('[data-note="recording"]')).toHaveTextContent(
      /^Recording\. This quote was priced when the conversation was recorded\./,
    );
    expect(screen.getByRole("heading", { name: QUOTE_ID })).toBeVisible();
    expect(field("premium")).toBe(money(pricedCover().premium.premium));
    expect(field("limit")).toBe(money(pricedCover().backtest.cover.limit));
    // No downloads, no audit trail, no key, no state: the quote does not exist in the workspace.
    expect(screen.queryAllByRole("link")).toEqual([]);
    expect(screen.queryAllByRole("button")).toEqual([]);
    expect(screen.queryByText("Downloads")).toBeNull();
    expect(screen.queryByText("Audit trail")).toBeNull();
    expect(screen.queryByText("Draft")).toBeNull();

    expect(readRecordedQuote({ quote_id: QUOTE_ID })).toBeNull();
    expect(readRecordedQuote({ quote_id: QUOTE_ID, priced: { premium: {} } })).toBeNull();
  });

  it("quote_states_for_loading_and_failed [R-12.4-12]", () => {
    const onRetry = vi.fn();
    renderWithApi(<QuoteTab quote={null} status="failed" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("This did not load.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe("approvals tab [R-12.3-4]", () => {
  function item(overrides: Partial<Parameters<typeof ApprovalItem>[0]> = {}) {
    const props = {
      approval: approvalView(),
      busy: false,
      problem: null,
      onDecide: vi.fn(),
      onRedeliver: vi.fn(),
      onOpenQuote: vi.fn(),
      ...overrides,
    };
    render(
      <I18nProvider locale="en">
        <ul>
          <ApprovalItem {...props} />
        </ul>
      </I18nProvider>,
    );
    return props;
  }

  it("empty_states_for_no_quote_and_no_approval [R-12.3-4]", async () => {
    renderWithApi(
      <>
        <QuoteTab quote={null} />
        <ApprovalsTab onOpenQuote={vi.fn()} />
      </>,
    );
    expect(screen.getByText(/^No quote yet\./)).toBeVisible();
    expect(await screen.findByText(/^Nothing to approve\./)).toBeVisible();
  });

  it("pending_approval_offers_approve_and_reject_with_note [R-12.4-7]", async () => {
    const onOpenQuote = vi.fn();
    const { calls, bodies, state } = renderWithApi(
      <ApprovalsTab onOpenQuote={onOpenQuote} />,
      (mock) => {
        mock.stage = "pending";
        return (request) => handle(request, mock);
      },
    );
    const approve = await screen.findByRole("button", { name: "Approve" });
    const entry = document.querySelector(`[data-approval="${SUBMISSION_ID}"]`);
    if (entry === null) throw new Error("no approval item");
    expect(screen.getByText("Pending")).toBeVisible();
    expect(field("carrier", entry)).toBe(CARRIER_NAME);
    expect(field("location", entry)).toBe(POINT_LABEL);
    expect(field("limit", entry)).toBe(money(approvalView().limit));
    expect(field("premium", entry)).toBe(money(approvalView().premium));
    expect(
      screen.getByText(
        "The agent requested this submission and cannot approve it. The decision is yours.",
      ),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: `${QUOTE_ID}: open the quote` }));
    expect(onOpenQuote).toHaveBeenCalledExactlyOnceWith(QUOTE_ID);

    fireEvent.change(screen.getByRole("textbox", { name: "Note (optional)" }), {
      target: { value: "  Checked with the client.  " },
    });
    fireEvent.click(approve);
    await waitFor(() => {
      expect(state.stage).toBe("approved");
    });
    expect(bodies).toEqual([{ approve: true, note: "Checked with the client." }]);
    expect(count(calls, `POST /api/v1/approvals/${SUBMISSION_ID}/decision`)).toBe(1);
    // The decision controls are gone once the item is decided.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    });
  });

  it("note_over_500_characters_is_refused [R-12.3-4]", () => {
    const props = item();
    const note = screen.getByRole("textbox", { name: "Note (optional)" });
    fireEvent.change(note, { target: { value: "a".repeat(NOTE_MAX) } });
    expect(screen.getByText("500 of 500 characters")).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();

    fireEvent.change(note, { target: { value: "a".repeat(NOTE_MAX + 1) } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The note has more than 500 characters. Shorten it.",
    );
    expect(note).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(props.onDecide).not.toHaveBeenCalled();

    fireEvent.change(note, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(props.onDecide).toHaveBeenCalledExactlyOnceWith(false, null);
  });

  it("approved_shows_delivering_then_delivered_with_receipt [R-12.4-8] [R-12.4-9]", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { state } = renderWithApi(<ApprovalsTab onOpenQuote={vi.fn()} />, (mock) => {
      mock.stage = "pending";
      return (request) => handle(request, mock);
    });
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(document.querySelector("[data-delivery]")).not.toBeNull();
    });
    expect(screen.getByText("Delivering")).toBeVisible();
    expect(document.querySelector("[data-delivery]")).toHaveTextContent(
      "Approved. Delivering to the carrier.",
    );

    // The queue is polled while the delivery is in progress: a failed attempt, then the receipt.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DELIVERY_POLL_MS + 50);
    });
    await waitFor(() => {
      expect(document.querySelector('[data-delivery="delivering"]')).toHaveTextContent(
        "Approved. Delivering to the carrier. 1 attempt so far. Last error: http_503.",
      );
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DELIVERY_POLL_MS + 50);
    });
    await waitFor(() => {
      expect(document.querySelector('[data-delivery="delivered"]')).toHaveTextContent(
        `Delivered. The carrier's receipt is ${RECEIPT_ID}.`,
      );
    });
    expect(screen.getByText("Delivered")).toBeVisible();
    expect(state.stage).toBe("approved");
    // Delivered is final: the polling stops.
    const reads = state.deliveryReads;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DELIVERY_POLL_MS * 3);
    });
    expect(state.deliveryReads).toBe(reads);
  });

  it("rejected_closes_the_item [R-12.4-10]", async () => {
    const { bodies } = renderWithApi(<ApprovalsTab onOpenQuote={vi.fn()} />, (mock) => {
      mock.stage = "pending";
      return (request) => handle(request, mock);
    });
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    expect(await screen.findByText("Rejected. Nothing was sent to the carrier.")).toBeVisible();
    expect(bodies).toEqual([{ approve: false, note: null }]);
    expect(screen.getByText("Rejected")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(document.querySelector("[data-delivery]")).toBeNull();
  });

  it("abandoned_delivery_offers_redelivery [R-12.4-11]", async () => {
    let redelivered = false;
    const { calls } = renderWithApi(<ApprovalsTab onOpenQuote={vi.fn()} />, () => (request) => {
      if (is(request, "POST", `/api/v1/approvals/${SUBMISSION_ID}/redeliver`)) {
        redelivered = true;
        return Promise.resolve(json(approvalView("approved", "delivered")));
      }
      return Promise.resolve(
        json([approvalView("approved", redelivered ? "delivered" : "abandoned")]),
      );
    });
    const again = await screen.findByRole("button", { name: "Deliver again" });
    expect(document.querySelector('[data-delivery="abandoned"]')).toHaveTextContent(
      "The delivery was abandoned after 5 attempts. Last error: http_503.",
    );
    expect(screen.getByText("Delivery abandoned")).toBeVisible();

    fireEvent.click(again);
    await waitFor(() => {
      expect(document.querySelector('[data-delivery="delivered"]')).not.toBeNull();
    });
    expect(count(calls, `POST /api/v1/approvals/${SUBMISSION_ID}/redeliver`)).toBe(1);
    expect(screen.queryByRole("button", { name: "Deliver again" })).toBeNull();
  });

  it("decision_conflict_reloads_the_queue [R-12.3-4]", async () => {
    let decided = false;
    const { calls } = renderWithApi(<ApprovalsTab onOpenQuote={vi.fn()} />, () => (request) => {
      if (is(request, "POST", `/api/v1/approvals/${SUBMISSION_ID}/decision`)) {
        // Another tab decided first.
        decided = true;
        return Promise.resolve(json(problem("invalid_state", 409), 409));
      }
      return Promise.resolve(
        json([decided ? approvalView("approved", "delivered") : approvalView()]),
      );
    });
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The quote is not in a state that allows this.",
    );
    // The queue was read again, so the item shows what really happened.
    await waitFor(() => {
      expect(document.querySelector('[data-delivery="delivered"]')).not.toBeNull();
    });
    expect(count(calls, "GET /api/v1/approvals")).toBe(2);
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("pending_badge_counts_pending_items [R-12.3-4]", () => {
    const approvals = [
      approvalView(),
      { ...approvalView(), approval_id: "S-OTHER" },
      approvalView("approved", "delivered"),
      approvalView("rejected"),
    ];
    expect(pendingCount(approvals)).toBe(2);
    expect(pendingCount([approvalView("rejected")])).toBe(0);
    expect(pendingCount(undefined)).toBe(0);

    render(
      <I18nProvider locale="en">
        <TabsCard
          tab="risk"
          onTab={vi.fn()}
          badges={{ approvals: pendingCount(approvals) }}
          panels={{ risk: null, history: null, quote: null, approvals: null }}
        />
      </I18nProvider>,
    );
    const tab = screen.getByRole("tab", { name: /^Approvals\s*2 pending$/ });
    expect(within(tab).getByText("2")).toBeVisible();
    expect(document.querySelectorAll(".tabs__badge")).toHaveLength(1);
  });

  it("failed_queue_can_be_retried [R-12.4-12]", async () => {
    let fail = true;
    renderWithApi(
      <ApprovalsTab onOpenQuote={vi.fn()} />,
      () => () => Promise.resolve(fail ? json(problem("unknown", 500), 500) : json([])),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("This did not load.");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/^Nothing to approve\./)).toBeVisible();
  });
});

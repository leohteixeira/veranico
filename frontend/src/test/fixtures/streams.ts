import type { components } from "../../api/schema";
import { serialiseEvent, type AgentEvent } from "../../api/sse";
import type { Locale } from "../../i18n";
import { formatMm, formatMoney, formatRate, formatWindow } from "../../i18n/format";
import {
  CARRIER_ID,
  CARRIER_NAME,
  CONVERSATION_ID,
  COVER,
  DATASET_ID,
  FIRST_SEASON,
  INDEX,
  LAST_SEASON,
  LIMIT_CENTS,
  POINT,
  POINT_LABEL,
  PREMIUM_CENTS,
  QUOTE_ID,
  SUBMISSION_ID,
  backtestResult,
  pricedCover,
  submission,
} from "./bodies";

/**
 * The agent stream fixtures, written as typed event objects and serialised to the `.sse` files of
 * this folder in the wire format (`fixtures.test.ts` keeps the files in step with this module).
 * Authored, not recorded: Task 13 of the web plan replaces the happy path with the recordings of
 * the assistant plan when they exist. All figures are SYNTHETIC.
 *
 * Two shapes are assumptions until the assistant plan fixes them: the `price_cover` result is
 * `{quote_id, priced}` and the `draft_term_sheet` result is `{documents}`.
 */

type Schemas = components["schemas"];

export const PROMPT_VERSION = "fixture-1";

type Record_ = Record<string, unknown>;

/** Splits a text into the small pieces a model stream delivers. */
function deltas(text: string): AgentEvent[] {
  const words = text.split(" ");
  const events: AgentEvent[] = [];
  for (let at = 0; at < words.length; at += 4) {
    const piece = words.slice(at, at + 4).join(" ");
    events.push({
      type: "text_delta",
      data: { text: at + 4 < words.length ? `${piece} ` : piece },
    });
  }
  return events;
}

function tool(
  callId: string,
  name: string,
  args: Record_,
  durationMs: number,
  summary: Schemas["Coded"],
  result: Record_,
): AgentEvent[] {
  return [
    { type: "tool_started", data: { call_id: callId, tool: name, arguments: args } },
    {
      type: "tool_finished",
      data: {
        call_id: callId,
        tool: name,
        status: "ok",
        duration_ms: durationMs,
        summary,
        result,
        error: null,
      },
    },
  ];
}

function turn(
  messageId: string,
  body: AgentEvent[],
  stopReason: Schemas["Done"]["stop_reason"] = "end_turn",
): AgentEvent[] {
  return [
    { type: "started", data: { conversation_id: CONVERSATION_ID, message_id: messageId } },
    ...body,
    {
      type: "done",
      data: {
        conversation_id: CONVERSATION_ID,
        message_id: messageId,
        stop_reason: stopReason,
        prompt_version: PROMPT_VERSION,
      },
    },
  ];
}

const INDEX_ARGUMENTS = {
  index_type: INDEX.index_type,
  window_start: INDEX.window.start,
  window_end: INDEX.window.end,
  trigger: INDEX.trigger,
  exit: INDEX.exit,
  limit_cents: LIMIT_CENTS,
};

interface Copy {
  requests: [string, string, string, string];
  backtest: (values: {
    n: number;
    window: string;
    trigger: string;
    frequency: string;
    burn: string;
    max: string;
    maxSeason: number;
  }) => string;
  priced: (values: {
    el: string;
    q10: string;
    q100: string;
    premium: string;
    rol: string;
    trigger: string;
    exit: string;
    n: number;
  }) => string;
  termSheet: string;
  submission: string;
  flagged: (value: string) => string;
  interrupted: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    requests: [
      "Coffee farm near Três Pontas, MG. The client worries about a dry spell during flowering, 1 Sep to 31 Oct. Pay when rainfall is below 150 mm, in full at 75 mm. Limit R$ 300,000.",
      "Yes, price it.",
      "Draft the term sheet.",
      `Request submission to ${CARRIER_NAME}.`,
    ],
    backtest: (v) =>
      `Over ${v.n} seasons, ${FIRST_SEASON} to ${LAST_SEASON}, the ${v.window} total at this grid point fell below ${v.trigger} in ${v.frequency} of them. The average historical payout is ${v.burn} and the largest is ${v.max}, in ${v.maxSeason}. The index has a significant falling trend, so history may misstate current risk. The weather data for this region is synthetic. Shall I price this structure?`,
    priced: (v) =>
      `Quote ${QUOTE_ID} is a draft. Expected loss ${v.el}; one-in-ten payout ${v.q10}; one-in-a-hundred payout ${v.q100}. The indicative premium is ${v.premium}, a rate on line of ${v.rol}. Assumptions: rainfall below ${v.trigger} pays linearly down to ${v.exit}, ${v.n} seasons used, gamma fit, synthetic weather data. Pricing is illustrative.`,
    termSheet: `The term sheet for ${QUOTE_ID} is rendered in English and Portuguese. It is in the Quote tab.`,
    submission: `Submission ${SUBMISSION_ID} to ${CARRIER_NAME} is waiting for approval. I can request it but I cannot approve it: a person decides in the Approvals tab.`,
    flagged: (value) => `That is roughly ${value} a month over the season.`,
    interrupted: "I found the place and I am loading",
  },
  "pt-BR": {
    requests: [
      "Fazenda de café perto de Três Pontas, MG. O cliente teme um veranico na florada, de 1º de setembro a 31 de outubro. Pagar quando a chuva ficar abaixo de 150 mm, integral em 75 mm. Limite de R$ 300.000.",
      "Sim, pode precificar.",
      "Gere o term sheet.",
      `Solicite a submissão para a ${CARRIER_NAME}.`,
    ],
    backtest: (v) =>
      `Em ${v.n} safras, de ${FIRST_SEASON} a ${LAST_SEASON}, o total de ${v.window} neste ponto de grade ficou abaixo de ${v.trigger} em ${v.frequency} delas. O pagamento histórico médio é de ${v.burn} e o maior é de ${v.max}, em ${v.maxSeason}. O índice tem tendência significativa de queda, então o histórico pode distorcer o risco atual. Os dados de clima desta região são sintéticos. Posso precificar essa estrutura?`,
    priced: (v) =>
      `A cotação ${QUOTE_ID} é um rascunho. Perda esperada de ${v.el}; pagamento de 1 em 10 de ${v.q10}; pagamento de 1 em 100 de ${v.q100}. O prêmio indicativo é de ${v.premium}, uma taxa sobre o limite de ${v.rol}. Premissas: chuva abaixo de ${v.trigger} paga linearmente até ${v.exit}, ${v.n} safras usadas, ajuste gama, dados de clima sintéticos. O preço é ilustrativo.`,
    termSheet: `O term sheet da ${QUOTE_ID} foi gerado em inglês e português. Está na aba Cotação.`,
    submission: `A submissão ${SUBMISSION_ID} para a ${CARRIER_NAME} aguarda aprovação. Eu posso solicitá-la, mas não aprová-la: uma pessoa decide na aba Aprovações.`,
    flagged: (value) => `Isso dá cerca de ${value} por mês ao longo da safra.`,
    interrupted: "Encontrei o local e estou carregando",
  },
};

export interface HappyPath {
  /** One list of events per turn, each from `started` to `done`. */
  turns: AgentEvent[][];
  /** The request that opens each turn. */
  requests: string[];
}

/** The full flow in four turns: backtest, price, term sheet, submission request. */
export function happyPath(locale: Locale): HappyPath {
  const copy = COPY[locale];
  const backtest = backtestResult();
  const priced = pricedCover();
  const moneyText = (value: Schemas["Money"]) => formatMoney(value.amount_cents, locale);

  const located = tool(
    "call-1",
    "resolve_location",
    { query: POINT_LABEL },
    412,
    {
      code: "tool.resolve_location",
      params: { label: POINT_LABEL, lat: POINT.lat, lon: POINT.lon },
    },
    {
      label: POINT_LABEL,
      lat: POINT.lat,
      lon: POINT.lon,
      h3_cell: "86a8a0c57ffffff",
      admin_region: "Minas Gerais",
      country_code: "BR",
    },
  );
  const history = tool(
    "call-2",
    "get_weather_history",
    { lat: POINT.lat, lon: POINT.lon },
    968,
    {
      code: "tool.get_weather_history",
      params: {
        dataset_id: DATASET_ID,
        first_year: FIRST_SEASON,
        last_year: LAST_SEASON + 1,
        source: "synthetic",
      },
    },
    {
      dataset_id: DATASET_ID,
      kind: "cube",
      region_id: "sul-de-minas",
      grid_point: { lat: -21.4, lon: -45.5 },
      first_year: FIRST_SEASON,
      last_year: LAST_SEASON + 1,
      days: 27394,
      missing_days: 0,
      source: "synthetic",
    },
  );
  const backtested = tool(
    "call-3",
    "backtest_index",
    { dataset_id: DATASET_ID, ...INDEX_ARGUMENTS },
    131,
    {
      code: "tool.backtest_index",
      params: {
        seasons_used: backtest.seasons_used,
        trigger_frequency_rate: backtest.trigger_frequency,
      },
    },
    { ...backtest },
  );
  const pricedTool = tool(
    "call-4",
    "price_cover",
    {
      lat: POINT.lat,
      lon: POINT.lon,
      label: POINT_LABEL,
      admin_region: "Minas Gerais",
      ...INDEX_ARGUMENTS,
      n: 100_000,
      seed: 42,
    },
    1840,
    { code: "tool.price_cover", params: { quote_id: QUOTE_ID, premium_cents: PREMIUM_CENTS } },
    { quote_id: QUOTE_ID, priced },
  );
  const drafted = tool(
    "call-5",
    "draft_term_sheet",
    { quote_id: QUOTE_ID },
    655,
    { code: "tool.draft_term_sheet", params: {} },
    {
      documents: (["en", "pt-BR"] as const).map((language) => ({
        quote_id: QUOTE_ID,
        kind: "term_sheet",
        locale: language,
        content_type: "application/pdf",
        size_bytes: 48_213,
        path: `/api/v1/quotes/${QUOTE_ID}/term-sheet.pdf?lang=${language}`,
      })),
    },
  );
  const requested = tool(
    "call-6",
    "request_submission",
    { quote_id: QUOTE_ID, carrier_id: CARRIER_ID },
    208,
    {
      code: "tool.request_submission",
      params: { submission_id: SUBMISSION_ID, carrier_id: CARRIER_ID },
    },
    { ...submission() },
  );

  return {
    requests: [...copy.requests],
    turns: [
      turn("m-0002", [
        ...located,
        ...history,
        ...backtested,
        ...deltas(
          copy.backtest({
            n: backtest.seasons_used,
            window: formatWindow(COVER.index.window, locale),
            trigger: formatMm(INDEX.trigger, locale),
            frequency: formatRate(backtest.trigger_frequency, locale, 2),
            burn: moneyText(backtest.burn_cost),
            max: moneyText(backtest.max_payout),
            maxSeason: backtest.max_payout_season ?? FIRST_SEASON,
          }),
        ),
      ]),
      turn("m-0004", [
        ...pricedTool,
        ...deltas(
          copy.priced({
            el: moneyText(priced.simulation.expected_loss),
            q10: moneyText(priced.simulation.payout_1_in_10),
            q100: moneyText(priced.simulation.payout_1_in_100),
            premium: moneyText(priced.premium.premium),
            rol: formatRate(priced.premium.rate_on_line, locale, 2),
            trigger: formatMm(INDEX.trigger, locale),
            exit: formatMm(INDEX.exit, locale),
            n: backtest.seasons_used,
          }),
        ),
      ]),
      turn("m-0006", [...drafted, ...deltas(copy.termSheet)]),
      turn("m-0008", [
        ...requested,
        { type: "approval_required", data: { approval_id: SUBMISSION_ID, quote_id: QUOTE_ID } },
        ...deltas(copy.submission),
      ]),
    ],
  };
}

/** What `POST /chat` streams over the whole flow: the turns, one after another. */
export function chatEvents(locale: Locale): AgentEvent[] {
  return happyPath(locale).turns.flat();
}

/** What `GET /replays/{locale}` streams: each turn with its recorded request after `started`. */
export function replayEvents(locale: Locale): AgentEvent[] {
  const { turns, requests } = happyPath(locale);
  return turns.flatMap((events, at) => {
    const [started, ...rest] = events;
    if (started === undefined) return [];
    const request: AgentEvent = { type: "user_message", data: { text: requests[at] ?? "" } };
    return [started, request, ...rest];
  });
}

/** One stored message from the events of one turn, as `GET /conversations/{id}` returns it. */
function assistantMessage(
  events: readonly AgentEvent[],
  createdAt: string,
): Schemas["MessageView"] {
  const message: Schemas["MessageView"] = {
    message_id: "",
    role: "assistant",
    created_at: createdAt,
    text: "",
    tools: [],
    flagged: [],
  };
  for (const event of events) {
    if (event.type === "started") message.message_id = event.data.message_id;
    if (event.type === "text_delta") message.text += event.data.text;
    if (event.type === "tool_finished") message.tools.push(event.data);
    if (event.type === "grounding_flagged") message.flagged.push(...event.data.values);
  }
  return message;
}

/**
 * The stored conversation after the first `turnCount` turns of the happy path. User messages take
 * the identifier before their answer's (`m-0001` before `m-0002`).
 */
export function conversationView(locale: Locale, turnCount = 4): Schemas["ConversationView"] {
  const { turns, requests } = happyPath(locale);
  const messages: Schemas["MessageView"][] = [];
  turns.slice(0, turnCount).forEach((events, at) => {
    const minute = String(5 + at).padStart(2, "0");
    messages.push({
      message_id: `m-${String(at * 2 + 1).padStart(4, "0")}`,
      role: "user",
      created_at: `2026-11-10T14:${minute}:00Z`,
      text: requests[at] ?? "",
      tools: [],
      flagged: [],
    });
    messages.push(assistantMessage(events, `2026-11-10T14:${minute}:20Z`));
  });
  return { conversation_id: CONVERSATION_ID, messages };
}

/** The figure the grounding check does not find in any tool output. */
export const FLAGGED_VALUE = "R$ 2,070.00";

/** One turn whose answer carries a figure the grounding check flags. */
export function flaggedEvents(): AgentEvent[] {
  return turn("m-0010", [
    ...deltas(COPY.en.flagged(FLAGGED_VALUE)),
    { type: "grounding_flagged", data: { message_id: "m-0010", values: [FLAGGED_VALUE] } },
  ]);
}

/** One turn in which the model fails after the first tool: `error`, then `done`. */
export function errorEvents(): AgentEvent[] {
  const [started, finished] = tool(
    "call-1",
    "resolve_location",
    { query: POINT_LABEL },
    412,
    {
      code: "tool.resolve_location",
      params: { label: POINT_LABEL, lat: POINT.lat, lon: POINT.lon },
    },
    { label: POINT_LABEL, lat: POINT.lat, lon: POINT.lon },
  );
  return turn(
    "m-0002",
    [
      ...(started === undefined || finished === undefined ? [] : [started, finished]),
      ...deltas(COPY.en.interrupted),
      { type: "error", data: { code: "model_unavailable", completed: ["resolve_location"] } },
    ],
    "error",
  );
}

export function serialise(events: readonly AgentEvent[]): string {
  return events.map(serialiseEvent).join("");
}

/** File name in this folder to its content. */
export const STREAM_FIXTURES: Readonly<Record<string, () => string>> = {
  "chat-happy-path.en.sse": () => serialise(chatEvents("en")),
  "chat-happy-path.pt-BR.sse": () => serialise(chatEvents("pt-BR")),
  "replay-happy-path.en.sse": () => serialise(replayEvents("en")),
  "replay-happy-path.pt-BR.sse": () => serialise(replayEvents("pt-BR")),
  "chat-flagged.sse": () => serialise(flaggedEvents()),
  "chat-error.sse": () => serialise(errorEvents()),
};

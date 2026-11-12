import type { components } from "../../../api/schema";

type Schemas = components["schemas"];

/**
 * The `CreateQuote` body that prices the quote in view again over the public API: its location,
 * cover and simulation options, as the API returned them. There is no `dataset_id`: the service
 * resolves the weather data from the location (contracts, section 5).
 */
export function createQuoteBody(quote: Schemas["QuoteView"]): Schemas["CreateQuote"] {
  const { location, cover, priced } = quote;
  return {
    location: {
      lat: location.lat,
      lon: location.lon,
      label: location.label,
      admin_region: location.admin_region,
    },
    cover,
    simulation: { n: priced.simulation.n, seed: priced.simulation.seed },
  };
}

/** A value inside single quotes of a POSIX shell. */
function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

interface ExampleInput {
  /** Where the API is served, for example `https://veranico.example`. */
  origin: string;
  secret: string;
  idempotencyKey: string;
  quote: Schemas["QuoteView"];
}

/** A ready-to-run `POST /api/v1/quotes` with the issued key and an idempotency key. */
export function exampleRequest({ origin, secret, idempotencyKey, quote }: ExampleInput): string {
  return [
    `curl -X POST ${shellQuote(`${origin}/api/v1/quotes`)} \\`,
    `  -H ${shellQuote(`Authorization: Bearer ${secret}`)} \\`,
    `  -H ${shellQuote(`Idempotency-Key: ${idempotencyKey}`)} \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d ${shellQuote(JSON.stringify(createQuoteBody(quote)))}`,
  ].join("\n");
}

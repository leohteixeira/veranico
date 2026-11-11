import createClient, { type Client, type ClientOptions } from "openapi-fetch";

import type { paths } from "./schema";

export type ApiClient = Client<paths>;

/** A typed client for the Veranico API. Paths carry their `/api/v1` prefix. */
export function createApiClient(options: ClientOptions = {}): ApiClient {
  return createClient<paths>(options);
}

/** The client of the application: same origin, so the workspace cookie travels. */
export const api = createApiClient();

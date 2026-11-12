import createClient, { type Client, type ClientOptions } from "openapi-fetch";
import { createContext, createElement, useContext, type ReactNode } from "react";

import type { paths } from "./schema";

export type ApiClient = Client<paths>;

/** A typed client for the Veranico API. Paths carry their `/api/v1` prefix. */
export function createApiClient(options: ClientOptions = {}): ApiClient {
  return createClient<paths>(options);
}

/** The client of the application: same origin, so the workspace cookie travels. */
export const api = createApiClient({
  // Looked up at call time, so whatever replaces `fetch` on the page (a test) is the one used.
  fetch: (request) => globalThis.fetch(request),
});

const ApiClientContext = createContext<ApiClient>(api);

interface ApiClientProviderProps {
  client: ApiClient;
  children: ReactNode;
}

/** Hooks take their client from here, so a test or the embed route can supply another one. */
export function ApiClientProvider({ client, children }: ApiClientProviderProps) {
  return createElement(ApiClientContext.Provider, { value: client }, children);
}

export function useApiClient(): ApiClient {
  return useContext(ApiClientContext);
}

import createClient, { type Client, type ClientOptions } from "openapi-fetch";
import { createContext, createElement, useContext, type ReactNode } from "react";

import type { paths } from "./schema";

export type ApiClient = Client<paths>;

/** A typed client for the Veranico API. Paths carry their `/api/v1` prefix. */
export function createApiClient(options: ClientOptions = {}): ApiClient {
  return createClient<paths>(options);
}

type Transport = (request: Request) => Promise<Response>;

let transport: Transport | null = null;

/**
 * Replaces how the application's client reaches the API. Used only by the development mock
 * layer (`VITE_API_MOCK=1`); `null` restores the browser's `fetch`.
 */
export function setApiTransport(next: Transport | null): void {
  transport = next;
}

/** The client of the application: same origin, so the workspace cookie travels. */
export const api = createApiClient({
  fetch: (request) => (transport ?? globalThis.fetch)(request),
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

import { describe, expect, it } from "vitest";

import { DEFAULT_API_PROXY_TARGET, ENV_API_PROXY_TARGET, apiProxyTarget } from "../vite.config";

describe("development proxy", () => {
  it("the proxy target comes from VERANICO_API_PROXY_TARGET, or is the local API role", () => {
    expect(ENV_API_PROXY_TARGET).toBe("VERANICO_API_PROXY_TARGET");
    // Not a `VITE_` variable: Vite would expose that prefix to the bundle.
    expect(ENV_API_PROXY_TARGET.startsWith("VITE_")).toBe(false);

    expect(apiProxyTarget({})).toBe("http://127.0.0.1:8500");
    expect(apiProxyTarget({ [ENV_API_PROXY_TARGET]: "" })).toBe(DEFAULT_API_PROXY_TARGET);
    expect(apiProxyTarget({ [ENV_API_PROXY_TARGET]: "  " })).toBe(DEFAULT_API_PROXY_TARGET);
    expect(apiProxyTarget({ [ENV_API_PROXY_TARGET]: "http://api:8500" })).toBe("http://api:8500");
  });
});

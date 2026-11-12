import { describe, expect, expectTypeOf, it } from "vitest";

import { createApiClient } from "./client";
import type { components } from "./schema";

type Region = components["schemas"]["Region"];
type Problem = components["schemas"]["Problem"];

describe("typed API client", () => {
  it("calls GET /regions with the types of the OpenAPI document", async () => {
    const requested: string[] = [];
    const client = createApiClient({
      baseUrl: "http://veranico.test",
      fetch: (request) => {
        requested.push(`${request.method} ${request.url}`);
        return Promise.resolve(Response.json([]));
      },
    });

    const { data, error } = await client.GET("/api/v1/regions");

    expectTypeOf(data).toEqualTypeOf<Region[] | undefined>();
    expectTypeOf(error).toEqualTypeOf<Problem | undefined>();
    expect(requested).toEqual(["GET http://veranico.test/api/v1/regions"]);
    expect(data).toEqual([]);
    expect(error).toBeUndefined();
  });

  it("types the events of the chat stream", () => {
    expectTypeOf<components["schemas"]["Done"]["stop_reason"]>().toEqualTypeOf<
      "end_turn" | "tool_limit" | "budget" | "error"
    >();
    expectTypeOf<components["schemas"]["Started"]>().toHaveProperty("conversation_id");
  });
});

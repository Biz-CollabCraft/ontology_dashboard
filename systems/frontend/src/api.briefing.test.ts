import { afterEach, describe, expect, it, vi } from "vitest";
import { createOperationsAgentReviewSummary } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("briefing request identity", () => {
  const input = { assetId: "CNC-S01-L01-01", eventId: "FILE#demo#observation" };
  function mockTransport() {
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ summary: null }) });
    vi.stubGlobal("fetch", fetch);
    return fetch;
  }

  it("sends a POST on HTTP when randomUUID is unavailable", async () => {
    const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto);
    vi.stubGlobal("crypto", { getRandomValues });
    const fetch = mockTransport();
    await createOperationsAgentReviewSummary(input);
    await createOperationsAgentReviewSummary(input);
    const keys = fetch.mock.calls.map((call) => (call[1].headers as Headers).get("Idempotency-Key"));
    expect(keys[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(keys[0]).not.toBe(keys[1]);
    expect(fetch.mock.calls[0][1].method).toBe("POST");
    expect(fetch.mock.calls[0][0]).toContain("event_id=FILE%23demo%23observation");
  });

  it("keeps the native UUID path on HTTPS", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => "native-request-id" });
    const fetch = mockTransport();
    await createOperationsAgentReviewSummary(input);
    expect((fetch.mock.calls[0][1].headers as Headers).get("Idempotency-Key")).toBe("native-request-id");
  });
});

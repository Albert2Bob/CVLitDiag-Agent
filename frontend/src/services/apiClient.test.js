import { afterEach, expect, it, vi } from "vitest";
import { request } from "./apiClient";
afterEach(() => vi.unstubAllGlobals());
it("surfaces backend response.message for unavailable model credentials", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ message: "Model API key is not configured" }),
    }),
  );
  await expect(
    request("/api/runs", { method: "POST", body: { question: "q" } }),
  ).rejects.toThrow("Model API key is not configured");
});
it.each([null, { message: {} }, { message: "" }])(
  "uses the HTTP status when no usable message exists: %j",
  async (payload) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => payload,
      }),
    );
    await expect(request("/health")).rejects.toThrow("503");
  },
);
it("handles non-JSON gateway errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error("Invalid JSON");
      },
    }),
  );
  await expect(request("/api/projects")).rejects.toThrow("502");
});

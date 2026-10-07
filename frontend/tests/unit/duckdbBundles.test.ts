import { describe, expect, it } from "vitest";
import { localBundles } from "../../lib/duckdb";

describe("localBundles", () => {
  it("points both bundles at this origin, with absolute URLs (the worker starts from a blob:)", () => {
    const bundles = localBundles("https://app.example.com");
    expect(bundles.mvp.mainModule).toBe("https://app.example.com/duckdb/duckdb-mvp.wasm");
    expect(bundles.eh?.mainWorker).toBe("https://app.example.com/duckdb/duckdb-browser-eh.worker.js");
    for (const bundle of [bundles.mvp, bundles.eh]) {
      expect(bundle?.mainModule).not.toContain("jsdelivr");
      expect(bundle?.mainWorker).toMatch(/^https:\/\/app\.example\.com\/duckdb\//);
    }
  });
});

import { describe, expect, it } from "vitest";
import { describeOutcome } from "../../lib/approvalResult";

describe("describeOutcome", () => {
  it("is nothing while nobody has decided", () => {
    expect(describeOutcome({ state: "pending" })).toBeNull();
  });

  it("calls a successful execution approved and shows its text", () => {
    expect(describeOutcome({ state: "done", result: { status: "success", response: "3 rows" } })).toEqual({ decision: "approved", text: "3 rows" });
  });

  it("ends the card on a rejection or a failed execution, with the message", () => {
    expect(describeOutcome({ state: "done", result: { status: "rejected", message: "no" } })).toEqual({ decision: "rejected", text: "no" });
    expect(describeOutcome({ state: "done", result: { status: "error", message: "boom" } })).toEqual({ decision: "rejected", text: "boom" });
    expect(describeOutcome({ state: "done" })).toEqual({ decision: "rejected", text: "" });
  });
});

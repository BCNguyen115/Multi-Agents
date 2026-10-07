import { describe, expect, it } from "vitest";
import { findEmptyChat } from "../../lib/newChat";
import type { ChatMessage } from "../../lib/types";

const user = { role: "user" } as ChatMessage;
const bot = { role: "assistant" } as ChatMessage;
const ids = [{ id: "a" }, { id: "b" }, { id: "c" }];

describe("findEmptyChat", () => {
  it("stays on the open conversation while nobody has written in it", () => {
    expect(findEmptyChat(ids, { a: [], b: [], c: [user] }, "b")).toBe("b");
  });

  it("goes back to an existing empty conversation instead of creating another", () => {
    expect(findEmptyChat(ids, { a: [user], b: [user, bot], c: [] }, "a")).toBe("c");
  });

  it("is null when every conversation has a user prompt, so a new one is created", () => {
    expect(findEmptyChat(ids, { a: [user], b: [user], c: [user, bot] }, "a")).toBeNull();
  });

  it("does not treat a greeting without a user prompt as written-in, nor an unknown one as empty", () => {
    expect(findEmptyChat(ids, { a: [bot], b: [user], c: [user] }, "b")).toBe("a");
    expect(findEmptyChat(ids, { a: [user], b: [user] }, "a")).toBeNull(); // "c" has no entry: unknown, not empty
  });
});

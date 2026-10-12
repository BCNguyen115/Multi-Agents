import { describe, expect, it } from "vitest";
import { emptyFirst, findEmptyChat, isUnwritten } from "../../lib/newChat";
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

  it("knows an unwritten conversation from a written or an unknown one", () => {
    expect(isUnwritten([])).toBe(true);
    expect(isUnwritten([bot])).toBe(true);
    expect(isUnwritten([user])).toBe(false);
    expect(isUnwritten(undefined)).toBe(false);
  });

  it("puts the unwritten conversation above the ones the server sent back, and keeps the rest in order", () => {
    // sign-in: the empty chat made here, then the server's conversations prepended in front of it
    const sidebar = [{ id: "old1" }, { id: "old2" }, { id: "new" }];
    expect(emptyFirst(sidebar, { old1: [user], old2: [user, bot], new: [] }).map((s) => s.id)).toEqual(["new", "old1", "old2"]);
    expect(emptyFirst(sidebar, { old1: [user], old2: [user], new: [user] })).toBe(sidebar); // nothing to move: same array
    expect(emptyFirst(sidebar, { old1: [user], old2: [user] }).map((s) => s.id)).toEqual(["old1", "old2", "new"]); // unknown stays put
  });

  it("does not treat a greeting without a user prompt as written-in, nor an unknown one as empty", () => {
    expect(findEmptyChat(ids, { a: [bot], b: [user], c: [user] }, "b")).toBe("a");
    expect(findEmptyChat(ids, { a: [user], b: [user] }, "a")).toBeNull(); // "c" has no entry: unknown, not empty
  });
});

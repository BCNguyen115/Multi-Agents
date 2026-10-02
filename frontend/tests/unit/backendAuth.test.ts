import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { authHeaders } from "../../lib/backendAuth";

const request = (headers: Record<string, string> = {}) => new NextRequest("http://localhost/api/chat", { method: "POST", headers });

describe("authHeaders", () => {
  it("passes the caller's bearer token on to the backend unchanged", () => {
    expect(authHeaders(request({ authorization: "Bearer abc.def.ghi" }))).toEqual({ Authorization: "Bearer abc.def.ghi" });
  });

  it("adds nothing when the caller sent no token (AUTH_MODE=off)", () => {
    expect(authHeaders(request())).toEqual({});
  });

  it("turns the login cookie into the bearer header", () => {
    expect(authHeaders(request({ cookie: "theme=dark; access_token=abc.def.ghi" }))).toEqual({ Authorization: "Bearer abc.def.ghi" });
  });

  it("prefers an explicit Authorization header over the cookie", () => {
    expect(authHeaders(request({ authorization: "Bearer from-proxy", cookie: "access_token=from-cookie" }))).toEqual({
      Authorization: "Bearer from-proxy",
    });
  });
});

import type { NextRequest } from "next/server";
import { en } from "./locales/en";
import { vi } from "./locales/vi";
import type { MessageKey } from "./locales/vi";

/** Interface text for route handlers (server side): the language is the one the browser announced in `X-UI-Lang`. */
export function serverMsg(req: NextRequest, key: MessageKey): string {
  return (req.headers.get("x-ui-lang") === "en" ? en : vi)[key];
}

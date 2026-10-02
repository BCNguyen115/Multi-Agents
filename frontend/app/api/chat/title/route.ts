import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  let query = "";
  let sessionId = "";

  try {
    const body = await req.json();
    query = (body.query || "").trim();
    sessionId = body.session_id || "";
  } catch {
    return NextResponse.json({ title: serverMsg(req, 'chat.newTitle') });
  }

  if (!query) {
    return NextResponse.json({ title: serverMsg(req, 'chat.newTitle') });
  }

  const candidateUrls = [
    process.env.API_URL ? `${process.env.API_URL}/api/chat/title` : null,
    'http://backend:8000/api/chat/title',
    'http://127.0.0.1:8000/api/chat/title',
    'http://localhost:8000/api/chat/title',
  ].filter(Boolean) as string[];

  // Try candidate backend URLs with a quick 6s timeout
  for (const backendUrl of candidateUrls) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);

    try {
      const response = await fetch(backendUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(req) },
        body: JSON.stringify({ query, session_id: sessionId }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (response.ok) {
        const data = await response.json();
        if (data && data.title && typeof data.title === 'string' && data.title.trim()) {
          return NextResponse.json({ title: data.title.trim() });
        }
      }
    } catch {
      clearTimeout(timeoutId);
      // continue to next candidate if available
    }
  }

  // Fallback to raw query string (toàn bộ chuỗi, KHÔNG cắt ...)
  return NextResponse.json({ title: query });
}

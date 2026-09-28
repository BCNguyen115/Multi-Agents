import { NextRequest } from "next/server";

export const maxDuration = 300;
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const candidateUrls = [
      process.env.API_URL ? `${process.env.API_URL}/api/chat/stream` : null,
      'http://backend:8000/api/chat/stream',
      'http://127.0.0.1:8000/api/chat/stream',
      'http://localhost:8000/api/chat/stream',
    ].filter(Boolean) as string[];

    let lastError: any = null;

    for (const backendUrl of candidateUrls) {
      try {
        const response = await fetch(backendUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
          },
          body: JSON.stringify(body),
        });

        if (!response.ok) {
          return new Response(response.body, {
            status: response.status,
            headers: {
              "Content-Type": response.headers.get("Content-Type") || "application/json",
            },
          });
        }

        // Return direct unbuffered stream with required SSE anti-buffering headers
        return new Response(response.body, {
          status: 200,
          headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
          },
        });
      } catch (err: any) {
        lastError = err;
        continue;
      }
    }

    return new Response(
      JSON.stringify({ error: lastError?.message || "Failed to connect to backend stream" }),
      {
        status: 502,
        headers: { "Content-Type": "application/json" },
      }
    );
  } catch (error: any) {
    return new Response(
      JSON.stringify({ error: error.message || "Proxy connection error" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
}

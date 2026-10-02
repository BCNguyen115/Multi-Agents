import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";

export const dynamic = 'force-dynamic';

/** A cited page of a stored PDF as a PNG (the passage highlighted). Binary body, so it is not handled by the JSON proxies. */
export async function GET(req: NextRequest) {
  const url = `${process.env.API_URL || 'http://backend:8000'}/api/knowledge/page${req.nextUrl.search}`;
  try {
    const response = await fetch(url, { headers: authHeaders(req), cache: 'no-store' });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      return NextResponse.json(data, { status: response.status });
    }
    return new NextResponse(await response.arrayBuffer(), {
      status: 200,
      headers: {
        'Content-Type': 'image/png',
        'Cache-Control': response.headers.get('cache-control') || 'private, max-age=300',
        'X-Highlighted': response.headers.get('x-highlighted') || '0',
        'X-Page-Count': response.headers.get('x-page-count') || '',
      },
    });
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || "Proxy connection error" }, { status: 502 });
  }
}

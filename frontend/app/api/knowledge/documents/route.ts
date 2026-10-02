import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";

export const dynamic = 'force-dynamic';

const backend = (query: string) => `${process.env.API_URL || 'http://backend:8000'}/api/knowledge/documents${query}`;

async function forward(req: NextRequest, method: 'GET' | 'DELETE'): Promise<NextResponse> {
  try {
    const response = await fetch(backend(req.nextUrl.search), { method, headers: authHeaders(req), cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || "Proxy connection error" }, { status: 502 });
  }
}

/** The documents stored in the knowledge base. */
export const GET = (req: NextRequest) => forward(req, 'GET');

/** Remove one document (`?doc_key=category/file.pdf`); the backend checks the caller's role. */
export const DELETE = (req: NextRequest) => forward(req, 'DELETE');

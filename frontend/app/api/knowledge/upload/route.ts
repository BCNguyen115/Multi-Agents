import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const maxDuration = 300; // chunking + embedding of a long document can take a while
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 300000);

  try {
    const formData = await req.formData();
    const backendUrl = process.env.API_URL
      ? `${process.env.API_URL}/api/knowledge/upload`
      : 'http://backend:8000/api/knowledge/upload';

    const response = await fetch(backendUrl, {
      method: "POST",
      headers: authHeaders(req), // no Content-Type: fetch sets the multipart boundary itself
      body: formData,
      signal: controller.signal,
    });

    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    if (error.name === 'AbortError') {
      return NextResponse.json({ detail: serverMsg(req, 'proxy.uploadTimeout') }, { status: 504 });
    }
    return NextResponse.json({ detail: error.message || "Proxy connection error" }, { status: 500 });
  } finally {
    clearTimeout(timeoutId);
  }
}

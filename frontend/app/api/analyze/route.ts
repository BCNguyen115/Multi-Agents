import { NextRequest, NextResponse } from "next/server";

export const maxDuration = 300; // Cho phép route chạy tối đa 5 phút
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  const controller = new AbortController();
  // Set timeout cho fetch lên 300,000 ms (5 phút)
  const timeoutId = setTimeout(() => controller.abort(), 300000);

  try {
    const formData = await req.formData();
    const backendUrl = process.env.API_URL
      ? `${process.env.API_URL}/api/analyze`
      : 'http://backend:8000/api/analyze';

    const response = await fetch(backendUrl, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      return NextResponse.json(
        { error: "Request timeout after 5 minutes" },
        { status: 504 }
      );
    }
    return NextResponse.json(
      { error: error.message || "Proxy connection error" },
      { status: 500 }
    );
  }
}

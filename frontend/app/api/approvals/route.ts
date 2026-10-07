import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

/** The approvals inbox (two-person approval): other people's pending sensitive actions this approver may decide. */
export async function GET(req: NextRequest) {
  const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/approvals` : 'http://backend:8000/api/approvals';
  try {
    const response = await fetch(backendUrl, { headers: authHeaders(req), cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}

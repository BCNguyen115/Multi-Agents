import { NextResponse } from "next/server";

export const dynamic = 'force-dynamic';

/** What the sign-in dialog may offer (public, no secrets). If the backend cannot be reached nothing is offered. */
export async function GET() {
  const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/auth/config` : 'http://backend:8000/api/auth/config';
  try {
    const response = await fetch(backendUrl, { cache: 'no-store' });
    if (!response.ok) return NextResponse.json({ login_enabled: false, registration_enabled: false });
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json({ login_enabled: false, registration_enabled: false });
  }
}

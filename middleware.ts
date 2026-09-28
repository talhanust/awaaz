import { NextResponse, type NextRequest } from 'next/server';

/** Basic auth for the authority dashboard and its APIs (pilot-grade; use real SSO for production). */
export function middleware(req: NextRequest) {
  const user = process.env.DASHBOARD_USER, pass = process.env.DASHBOARD_PASSWORD;
  if (!user || !pass) return new NextResponse('Dashboard credentials are not configured', { status: 503 });
  const header = req.headers.get('authorization') ?? '';
  const [scheme, encoded] = header.split(' ');
  if (scheme === 'Basic' && encoded) {
    const [u, p] = atob(encoded).split(':');
    if (u === user && p === pass) return NextResponse.next();
  }
  return new NextResponse('Authentication required', { status: 401, headers: { 'WWW-Authenticate': 'Basic realm="Awaaz authority"' } });
}

export const config = { matcher: ['/dashboard/:path*', '/reports/:path*', '/api/authority/:path*', '/api/reports/:path*'] };

import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { env } from '@/lib/env';
import { tickIssue } from '@/lib/lifecycle';
import type { Issue } from '@/lib/types';

export const runtime = 'nodejs';
export const maxDuration = 300;

/** Daily job (vercel.json): check-ins, reminders, verification timeouts. Vercel sends `Authorization: Bearer $CRON_SECRET`. */
export async function GET(req: Request) {
  if (req.headers.get('authorization') !== `Bearer ${env('CRON_SECRET')}`) return new NextResponse('Unauthorized', { status: 401 });
  const { data, error } = await db().from('issues').select('*').not('status', 'in', '(resolved,closed_unverified)');
  if (error) throw error;
  const results: Record<string, number> = {};
  for (const issue of (data ?? []) as Issue[]) {
    try {
      const r = await tickIssue(issue);
      if (r) results[r] = (results[r] ?? 0) + 1;
    } catch (e) {
      console.error('tick failed', issue.issue_id, e);
      results.errors = (results.errors ?? 0) + 1;
    }
  }
  return NextResponse.json({ checked: data?.length ?? 0, ...results });
}

import { NextResponse } from 'next/server';
import { authorityAction } from '@/lib/lifecycle';

export const runtime = 'nodejs';
const ACTIONS = ['acknowledge', 'in_progress', 'fixed'] as const;

/** Authority dashboard actions (protected by middleware basic auth). */
export async function PATCH(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const body = (await req.json().catch(() => ({}))) as { action?: string };
  const action = ACTIONS.find(a => a === body.action);
  if (!action) return NextResponse.json({ error: `action must be one of ${ACTIONS.join(', ')}` }, { status: 400 });
  await authorityAction(id, action);
  return NextResponse.json({ ok: true });
}

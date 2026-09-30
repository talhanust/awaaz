import { NextResponse } from 'next/server';
import { writeNeighborhoodReport, type Cluster } from '@/lib/agents/analyst';
import { db, getAuthority } from '@/lib/db';

export const runtime = 'nodejs';
export const maxDuration = 60;

/** Agent 5: (re)write the Neighborhood Report for one cluster. Protected by middleware. */
export async function POST(req: Request) {
  const { cluster_key } = (await req.json().catch(() => ({}))) as { cluster_key?: string };
  if (!cluster_key) return NextResponse.json({ error: 'cluster_key is required' }, { status: 400 });
  const { data, error } = await db().from('clusters_30d').select('*').eq('cluster_key', cluster_key).maybeSingle();
  if (error) throw error;
  if (!data) return NextResponse.json({ error: 'No cluster with that key in the last 30 days' }, { status: 404 });
  const cluster = data as Cluster;
  const authority = await getAuthority(cluster.authority_id);
  const r = await writeNeighborhoodReport(cluster, authority.name);
  await db().from('neighborhood_reports').upsert({ cluster_key, headline: r.headline_stat, report_en: r.report_en, report_ur: r.report_ur, created_at: new Date().toISOString() });
  return NextResponse.json(r);
}

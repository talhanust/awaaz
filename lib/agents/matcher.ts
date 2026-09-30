import { z } from 'zod';
import { askJSON, MODELS } from '../claude';
import { db } from '../db';
import type { Category } from '../types';

const SYSTEM = `You are Awaaz's Matcher. A citizen has just described a civic problem. You are given their summary and up to 6 nearby open Issues: some in the same category, and some found by meaning similarity that may be filed under a different category (e.g. a leaking pipe filed as water vs. sanitation). Decide whether the new report describes the SAME physical problem as one of the candidates.

Same problem = same physical object or outage (the same pothole, the same overflowing drain, the same street's power cut). Different problem = a different object nearby, even if the category matches.

If unsure, choose "new". A wrong merge hides a real problem; a missed merge only creates a duplicate the dashboard can merge later.

Respond ONLY with JSON:
{"decision":"match|new","issue_id":"AWZ-... or null","confidence":0.0,"reason":"one short sentence"}`;

const MatchResult = z.object({
  decision: z.enum(['match', 'new']),
  issue_id: z.string().nullable(),
  confidence: z.number().min(0).max(1),
  reason: z.string(),
});

export type Candidate = { issue_id: string; summary: string; sector: string; report_count: number; status: string; distance_m: number; category?: string; similarity?: number };
export type MatchOutcome = { decision: 'new' } | { decision: 'match'; issue: Candidate; reason: string };

export async function findMatch(input: {
  city: string; category: Category; lat: number; lng: number; summary: string; areaText: string; embedding?: number[] | null;
}): Promise<MatchOutcome> {
  // 1) Same category within a category-specific radius (PostGIS).
  const geo = await db().rpc('match_candidates', { p_city: input.city, p_category: input.category, p_lat: input.lat, p_lng: input.lng });
  if (geo.error) throw geo.error;
  // 2) RAG: similar meaning within 300 m in ANY category, so a mis-categorized duplicate is still found.
  let semantic: Candidate[] = [];
  if (input.embedding) {
    const r = await db().rpc('semantic_candidates', { p_city: input.city, p_embedding: input.embedding, p_lat: input.lat, p_lng: input.lng });
    if (r.error) console.error('semantic_candidates failed', r.error); else semantic = (r.data ?? []) as Candidate[];
  }
  const merged = new Map<string, Candidate>();
  for (const c of [...((geo.data ?? []) as Candidate[]), ...semantic]) merged.set(c.issue_id, { ...merged.get(c.issue_id), ...c });
  const candidates = [...merged.values()].slice(0, 6);
  if (!candidates.length) return { decision: 'new' };

  const out = await askJSON({
    system: SYSTEM,
    model: MODELS.fast,
    schema: MatchResult,
    input: {
      new_report: { summary: input.summary, category: input.category, location: input.areaText },
      candidates: candidates.map(c => ({ issue_id: c.issue_id, summary: c.summary, category: c.category ?? input.category, sector: c.sector, distance_m: Math.round(c.distance_m), meaning_similarity: c.similarity != null ? Number(c.similarity.toFixed(2)) : null, residents: c.report_count })),
    },
  });
  const hit = candidates.find(c => c.issue_id === out.issue_id);
  if (out.decision === 'match' && out.confidence >= 0.75 && hit) return { decision: 'match', issue: hit, reason: out.reason };
  return { decision: 'new' };
}

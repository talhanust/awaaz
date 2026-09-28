import { db } from './db';
import { embedOne } from './embeddings';
import { keywordQuery } from './kb';

export type Passage = { chunk_id: string; doc_id: string; title: string; heading: string | null; content: string; verified: boolean; source: string | null; score: number };

/**
 * Hybrid retrieval over the jurisdiction knowledge base: vector similarity (if embeddings are configured)
 * fused with keyword search via reciprocal rank fusion inside Postgres (see match_kb in 0002_rag.sql).
 */
export async function retrieve(city: string, query: string, opts: { k?: number; authorityIds?: string[] } = {}): Promise<Passage[]> {
  const embedding = await embedOne(query, 'query');
  const { data, error } = await db().rpc('match_kb', {
    p_city: city,
    p_query: keywordQuery(query),
    p_embedding: embedding,
    p_k: opts.k ?? 6,
    p_authority_ids: opts.authorityIds ?? null,
  });
  if (error) {
    console.error('KB retrieval failed; continuing without passages', error);
    return [];
  }
  return (data ?? []) as Passage[];
}

/** Compact passages for a prompt. Unverified passages are labeled so the model treats them as guidance. */
export const toPromptPassages = (ps: Passage[]) =>
  ps.map(p => ({ id: p.chunk_id, title: p.title, section: p.heading, verified: p.verified, text: p.content }));

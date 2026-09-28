import { optionalEnv } from './env';

/**
 * Embeddings via Voyage AI (Anthropic doesn't offer an embedding model; its docs point to Voyage).
 * voyage-4 is multilingual with 1024 dimensions by default, matching vector(1024) in the schema.
 * Returns null when no key is set: retrieval then falls back to keyword search only.
 */
export const EMBEDDING_DIM = 1024;
const MODEL = () => optionalEnv('VOYAGE_MODEL') ?? 'voyage-4';

export const embeddingsEnabled = () => !!optionalEnv('VOYAGE_API_KEY');

export async function embed(texts: string[], inputType: 'query' | 'document'): Promise<number[][] | null> {
  const key = optionalEnv('VOYAGE_API_KEY');
  if (!key || !texts.length) return null;
  const res = await fetch('https://api.voyageai.com/v1/embeddings', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ input: texts, model: MODEL(), input_type: inputType, output_dimension: EMBEDDING_DIM }),
    signal: AbortSignal.timeout(15_000),
  });
  if (!res.ok) throw new Error(`Voyage embeddings failed: ${res.status} ${await res.text()}`);
  const json = (await res.json()) as { data: { embedding: number[]; index: number }[] };
  return json.data.sort((a, b) => a.index - b.index).map(d => d.embedding);
}

export async function embedOne(text: string, inputType: 'query' | 'document'): Promise<number[] | null> {
  try {
    return (await embed([text], inputType))?.[0] ?? null;
  } catch (e) {
    console.error('embedding failed, continuing without it', e);
    return null;
  }
}

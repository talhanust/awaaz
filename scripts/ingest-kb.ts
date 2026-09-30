/**
 * Load kb/<city>/*.md into Supabase: parse, chunk, embed (if VOYAGE_API_KEY is set), upsert.
 * Run:  npx tsx --env-file=.env.local scripts/ingest-kb.ts
 * Re-run after editing any KB file; chunks for changed docs are replaced.
 */
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { db } from '../lib/db';
import { embed, embeddingsEnabled } from '../lib/embeddings';
import { parseKbMarkdown } from '../lib/kb';

async function main() {
  const root = path.join(process.cwd(), 'kb');
  const cities = await readdir(root);
  let total = 0;
  for (const cityDir of cities) {
    for (const file of (await readdir(path.join(root, cityDir))).filter(f => f.endsWith('.md'))) {
      const docId = `${cityDir}/${file.replace(/\.md$/, '')}`;
      const doc = parseKbMarkdown(docId, await readFile(path.join(root, cityDir, file), 'utf8'));
      const vectors = await embed(doc.chunks.map(c => `${doc.title}. ${c.heading}. ${c.content}`), 'document');

      const { error: e1 } = await db().from('kb_documents').upsert({
        doc_id: doc.doc_id, city: doc.city, title: doc.title, source: doc.source, source_type: doc.source_type,
        verified: doc.verified, updated_at: new Date().toISOString(),
      });
      if (e1) throw e1;
      const { error: e2 } = await db().from('kb_chunks').delete().eq('doc_id', doc.doc_id);
      if (e2) throw e2;
      const { error: e3 } = await db().from('kb_chunks').insert(doc.chunks.map((c, i) => ({
        chunk_id: c.chunk_id, doc_id: doc.doc_id, city: doc.city, authority_ids: doc.authority_ids,
        heading: c.heading, content: c.content, embedding: vectors?.[i] ?? null,
      })));
      if (e3) throw e3;
      total += doc.chunks.length;
      console.log(`✓ ${doc.doc_id}: ${doc.chunks.length} chunks${doc.verified ? '' : ' (unverified)'}`);
    }
  }
  console.log(`Done: ${total} chunks. Embeddings ${embeddingsEnabled() ? 'on' : 'OFF (keyword search only; set VOYAGE_API_KEY)'}.`);
}

main().catch(e => { console.error(e); process.exit(1); });

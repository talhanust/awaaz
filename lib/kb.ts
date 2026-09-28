/** Parse and chunk knowledge-base markdown files (front matter + "## " sections). Pure functions, no I/O. */
export type KbDoc = {
  doc_id: string; city: string; title: string; source: string; source_type: string; verified: boolean; authority_ids: string[];
  chunks: { chunk_id: string; heading: string; content: string }[];
};

const MAX_CHARS = 1200;

export function parseKbMarkdown(docId: string, raw: string): KbDoc {
  const m = raw.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!m) throw new Error(`${docId}: missing front matter`);
  const meta: Record<string, string> = {};
  for (const line of m[1].split('\n')) {
    const i = line.indexOf(':');
    if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  for (const k of ['title', 'city']) if (!meta[k]) throw new Error(`${docId}: front matter needs "${k}"`);

  const sections = m[2].split(/^## +/m).map(s => s.trim()).filter(Boolean);
  const chunks: KbDoc['chunks'] = [];
  for (const s of sections) {
    const nl = s.indexOf('\n');
    const heading = nl === -1 ? s : s.slice(0, nl).trim();
    const body = nl === -1 ? '' : s.slice(nl + 1).trim();
    // Long sections are split on paragraph boundaries so each chunk stays focused.
    let buf = '';
    for (const para of body.split(/\n\s*\n/)) {
      if (buf && buf.length + para.length > MAX_CHARS) { chunks.push({ chunk_id: '', heading, content: buf.trim() }); buf = ''; }
      buf += para + '\n\n';
    }
    if (buf.trim()) chunks.push({ chunk_id: '', heading, content: buf.trim() });
  }
  chunks.forEach((c, i) => (c.chunk_id = `${docId}#${i + 1}`));
  return {
    doc_id: docId, city: meta.city, title: meta.title, source: meta.source ?? '', source_type: meta.source_type ?? 'demo',
    verified: meta.verified === 'true',
    authority_ids: (meta.authorities ?? '').split(',').map(s => s.trim()).filter(Boolean),
    chunks,
  };
}

/** Turn free text into an OR keyword query for websearch_to_tsquery (keyword half of hybrid search). */
export function keywordQuery(text: string): string {
  const STOP = new Set(['the', 'a', 'an', 'is', 'are', 'in', 'on', 'at', 'of', 'to', 'and', 'or', 'for', 'with', 'hai', 'hain', 'ka', 'ki', 'ke', 'mein', 'se', 'pe', 'par', 'ko', 'yeh', 'woh']);
  const words = [...new Set(text.toLowerCase().normalize('NFKC').match(/[\p{L}\p{N}]{3,}/gu) ?? [])].filter(w => !STOP.has(w));
  return words.slice(0, 24).join(' or ');
}

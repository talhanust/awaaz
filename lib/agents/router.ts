import { z } from 'zod';
import { askJSON, MODELS } from '../claude';
import { retrieve, toPromptPassages, type Passage } from '../rag';
import type { Authority } from '../types';
import type { Classification } from './classifier';

const SYSTEM = `You are Awaaz's Jurisdiction Router. Agent 1 has classified a civic complaint and suggested a default department from the category alone. Your job is to decide which department is actually responsible, using ONLY the retrieved knowledge-base passages and the list of departments.

Rules:
- Choose authority_id from DEPARTMENTS only. Never invent one.
- Base the decision on the passages. Put the ids of the passages you relied on in "sources". If no passage is relevant, keep the default department, set sources to [] and say so in the explanation.
- Passages marked "verified": false are unverified guidance. You may use them, but lower your confidence.
- If the passages say responsibility depends on something the input does not tell you (for example whether the spot is inside a cantonment or a private housing society), set needs_clarification to ONE short question in the citizen's language and script (citizen_language). Otherwise null.
- explanation: one plain English sentence a resident would understand, e.g. "Street lights in city areas are maintained by municipal street lighting, not LESCO."
- explanation_local: the same sentence in the citizen's language and script.

Respond ONLY with JSON:
{"authority_id":"...","confidence":0.0,"sources":["..."],"needs_clarification":null,"explanation":"...","explanation_local":"..."}`;

const Routing = z.object({
  authority_id: z.string(),
  confidence: z.number().min(0).max(1),
  sources: z.array(z.string()),
  needs_clarification: z.string().nullable(),
  explanation: z.string(),
  explanation_local: z.string(),
});

export type RoutingDecision = {
  authority_id: string;
  changed: boolean;                 // true if RAG overrode the category default
  needs_clarification: string | null;
  explanation: string;
  explanation_local: string;
  sources: { chunk_id: string; title: string; verified: boolean }[];
};

export async function routeWithKnowledge(args: {
  c: Classification; city: string; areaText: string; authorities: Authority[];
}): Promise<RoutingDecision> {
  const fallback: RoutingDecision = {
    authority_id: args.c.authority_id, changed: false, needs_clarification: null,
    explanation: 'Routed by complaint category (no matching guidance in the knowledge base).', explanation_local: '', sources: [],
  };
  const query = `${args.c.category}: ${args.c.summary_en}. Location: ${args.areaText}`;
  const passages: Passage[] = await retrieve(args.city, query, { k: 6 });
  if (!passages.length) return fallback;

  const out = await askJSON({
    system: SYSTEM,
    model: MODELS.fast,
    schema: Routing,
    input: {
      complaint: { summary: args.c.summary_en, category: args.c.category, severity: args.c.severity, location: args.areaText },
      default_department: args.c.authority_id,
      citizen_language: args.c.language,
      DEPARTMENTS: args.authorities.map(a => ({ authority_id: a.authority_id, name: a.name, categories: a.categories })),
      passages: toPromptPassages(passages),
    },
  }).catch(err => { console.error('router failed; using category default', err); return null; });
  if (!out) return fallback;

  // Guardrails: department must exist; cited sources must be passages we actually retrieved.
  const valid = args.authorities.some(a => a.authority_id === out.authority_id);
  const byId = new Map(passages.map(p => [p.chunk_id, p]));
  const cited = out.sources.map(id => byId.get(id)).filter((p): p is Passage => !!p);
  if (!valid || (out.authority_id !== args.c.authority_id && !cited.length)) return fallback; // no override without evidence

  return {
    authority_id: out.confidence >= 0.6 ? out.authority_id : args.c.authority_id,
    changed: out.confidence >= 0.6 && out.authority_id !== args.c.authority_id,
    needs_clarification: out.needs_clarification,
    explanation: out.explanation,
    explanation_local: out.explanation_local,
    sources: cited.map(p => ({ chunk_id: p.chunk_id, title: p.title, verified: p.verified })),
  };
}

/** Department-specific guidance for drafting and escalation (e.g. required fields, escalation channels). */
export async function departmentGuidance(city: string, authorityId: string, topic: string) {
  const passages = await retrieve(city, `${authorityId} ${topic}`, { k: 3, authorityIds: [authorityId] });
  return toPromptPassages(passages);
}

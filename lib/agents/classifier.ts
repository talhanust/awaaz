import { z } from 'zod';
import { askJSON, MODELS } from '../claude';
import { CATEGORIES, LANGUAGES, SEVERITIES, type Authority } from '../types';

const SYSTEM = `You are Awaaz's Intake & Classifier agent. Citizens in Pakistan report civic problems by voice note, photo or text, often mixing Urdu, Roman Urdu, Punjabi and English in one message. You receive the transcript, an optional photo description, a location, and an AUTHORITY_LOOKUP table for the city.

Do the following:
1. Detect the dominant language: "ur" (Urdu script), "ur-Latn" (Roman Urdu), "pa" (Punjabi), or "en".
2. Classify into exactly one category: electrical, water, sanitation, roads, gas, encroachment, other.
   - Sewage overflow, blocked drains and garbage piles = sanitation. No water supply, low pressure, dirty tap water or a burst supply pipe = water.
3. Pick authority_id from AUTHORITY_LOOKUP whose categories include your category (use routing_notes when several match). If none fits, use "unknown" and ask the citizen to confirm their city/town in needs_clarification.
4. Confidence from 0 to 1 for the category. If confidence < 0.6, do not guess: put ONE short clarifying question in needs_clarification, written in the citizen's own language and script. Otherwise null.
5. Severity: low, medium, high, or urgent. Urgent = immediate safety risk: gas smell or leak, exposed or sparking wires, fallen live line, open manhole, collapsed road or wall.
6. summary_en: one factual English line for filing. summary_local: the same in the citizen's language and script.
7. Use only facts present in the input. Do not add durations, counts or causes the citizen did not state.

Respond ONLY with this JSON, no preamble, no code fences:
{"language":"...","category":"...","authority_id":"...","confidence":0.0,"severity":"...","needs_clarification":null,"summary_en":"...","summary_local":"..."}`;

export const Classification = z.object({
  language: z.enum(LANGUAGES),
  category: z.enum(CATEGORIES),
  authority_id: z.string(),
  confidence: z.number().min(0).max(1),
  severity: z.enum(SEVERITIES),
  needs_clarification: z.string().nullable(),
  summary_en: z.string().min(3),
  summary_local: z.string(),
});
export type Classification = z.infer<typeof Classification>;

export async function classify(input: {
  rawText: string;
  photoDescription?: string;
  areaText: string;
  city: string;
  authorities: Authority[];
}): Promise<Classification> {
  const out = await askJSON({
    system: SYSTEM,
    model: MODELS.fast,
    schema: Classification,
    input: {
      raw_text: input.rawText,
      photo_description: input.photoDescription ?? null,
      location: { area_text: input.areaText },
      city: input.city,
      AUTHORITY_LOOKUP: input.authorities.map(a => ({ authority_id: a.authority_id, name: a.name, categories: a.categories })),
      routing_notes: 'Sewage, drains and overflowing gutters go to the water & sewerage authority; garbage and solid waste go to the waste management company.',
    },
  });
  // Never trust an authority id the model invented.
  if (out.authority_id !== 'unknown' && !input.authorities.some(a => a.authority_id === out.authority_id)) {
    out.authority_id = 'unknown';
  }
  return out;
}

/** Low confidence, unknown authority or an explicit question all mean: ask, don't file. */
export const needsClarification = (c: Classification) =>
  !!c.needs_clarification || c.confidence < 0.6 || c.authority_id === 'unknown';

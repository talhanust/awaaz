import Anthropic from '@anthropic-ai/sdk';
import type { z } from 'zod';

let client: Anthropic | null = null;
const anthropic = () => (client ??= new Anthropic()); // reads ANTHROPIC_API_KEY

export const MODELS = {
  fast: process.env.CLAUDE_MODEL_FAST ?? 'claude-haiku-4-5-20251001',
  smart: process.env.CLAUDE_MODEL_SMART ?? 'claude-sonnet-5',
};

const stripFences = (s: string) => s.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();

type ImageInput = { mediaType: 'image/jpeg' | 'image/png' | 'image/gif' | 'image/webp'; base64: string };

/**
 * Ask Claude for JSON matching `schema`. The system prompt carries the agent's rules;
 * the input is sent as JSON. One corrective retry, then throws — callers decide the fallback.
 */
export async function askJSON<T>(opts: {
  system: string;
  input: unknown;
  schema: z.ZodType<T>;
  model?: string;
  maxTokens?: number;
}): Promise<T> {
  let lastError = '';
  for (let attempt = 0; attempt < 2; attempt++) {
    const msg = await anthropic().messages.create({
      model: opts.model ?? MODELS.fast,
      max_tokens: opts.maxTokens ?? 1024,
      system: opts.system,
      messages: [{
        role: 'user',
        content: `INPUT:\n${JSON.stringify(opts.input, null, 2)}` +
          (attempt ? `\n\nYour previous reply was invalid (${lastError}). Reply with ONLY the JSON object.` : ''),
      }],
    });
    const text = msg.content.filter((b): b is Anthropic.TextBlock => b.type === 'text').map(b => b.text).join('');
    try {
      const parsed = opts.schema.safeParse(JSON.parse(stripFences(text)));
      if (parsed.success) return parsed.data;
      lastError = parsed.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ').slice(0, 300);
    } catch {
      lastError = 'not valid JSON';
    }
  }
  throw new Error(`Claude output failed validation: ${lastError}`);
}

/** Describe a complaint photo in one factual sentence (vision pass for photo-only reports). */
export async function describeImage(image: ImageInput): Promise<string> {
  const msg = await anthropic().messages.create({
    model: MODELS.fast,
    max_tokens: 200,
    messages: [{
      role: 'user',
      content: [
        { type: 'image', source: { type: 'base64', media_type: image.mediaType, data: image.base64 } },
        { type: 'text', text: 'A citizen sent this photo as a civic complaint. In one factual English sentence, describe the visible civic problem (e.g. pothole, sewage overflow, exposed wires, garbage pile). Do not guess the location or cause. If no civic problem is visible, say so.' },
      ],
    }],
  });
  return msg.content.filter((b): b is Anthropic.TextBlock => b.type === 'text').map(b => b.text).join('').trim();
}

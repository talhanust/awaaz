import { describeImage } from './claude';
import { optionalEnv } from './env';
import { fetchTwilioMedia } from './whatsapp';

/** Voice note → text with OpenAI Whisper (Claude doesn't take audio). Returns null if unavailable or unclear. */
export async function transcribe(mediaUrl: string): Promise<string | null> {
  const key = optionalEnv('OPENAI_API_KEY');
  if (!key) return null;
  const { buffer, contentType } = await fetchTwilioMedia(mediaUrl);
  const form = new FormData();
  form.append('file', new Blob([new Uint8Array(buffer)], { type: contentType }), 'voice.ogg');
  form.append('model', 'whisper-1');
  form.append('prompt', 'Civic complaint from Pakistan, may mix Urdu, Punjabi and English. Words: gutter, gaddha, bijli, pani, sadak, kachra.');
  const res = await fetch('https://api.openai.com/v1/audio/transcriptions', { method: 'POST', headers: { Authorization: `Bearer ${key}` }, body: form });
  if (!res.ok) return null;
  const text = ((await res.json()) as { text?: string }).text?.trim() ?? '';
  return text.split(/\s+/).length >= 3 ? text : null;
}

const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'] as const;

/** Photo → one factual sentence via Claude vision. */
export async function describePhoto(mediaUrl: string): Promise<string | null> {
  const { buffer, contentType } = await fetchTwilioMedia(mediaUrl);
  const mediaType = IMAGE_TYPES.find(t => contentType.startsWith(t));
  if (!mediaType || buffer.length > 5_000_000) return null;
  return describeImage({ mediaType, base64: buffer.toString('base64') });
}

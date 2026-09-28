import { createHmac, timingSafeEqual } from 'node:crypto';
import { env, optionalEnv } from './env';

const twilioAuth = () => 'Basic ' + Buffer.from(`${env('TWILIO_ACCOUNT_SID')}:${env('TWILIO_AUTH_TOKEN')}`).toString('base64');

/**
 * Send a WhatsApp message. Free-form text only works within 24 h of the citizen's last message;
 * outside that window WhatsApp requires a pre-approved template (pass contentSid + variables).
 */
export async function sendWhatsApp(to: string, body: string, template?: { contentSid?: string; variables?: Record<string, string> }) {
  const form = new URLSearchParams({ From: env('TWILIO_WHATSAPP_FROM'), To: to.startsWith('whatsapp:') ? to : `whatsapp:${to}` });
  if (template?.contentSid) {
    form.set('ContentSid', template.contentSid);
    if (template.variables) form.set('ContentVariables', JSON.stringify(template.variables));
  } else {
    form.set('Body', body.slice(0, 1600)); // WhatsApp body limit
  }
  const res = await fetch(`https://api.twilio.com/2010-04-01/Accounts/${env('TWILIO_ACCOUNT_SID')}/Messages.json`, {
    method: 'POST',
    headers: { Authorization: twilioAuth(), 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  });
  if (!res.ok) throw new Error(`Twilio send failed: ${res.status} ${await res.text()}`);
}

/** Split long text (e.g. a formatted complaint) into WhatsApp-sized messages. */
export async function sendLong(to: string, text: string) {
  for (let i = 0; i < text.length; i += 1500) await sendWhatsApp(to, text.slice(i, i + 1500));
}

/** Validate X-Twilio-Signature (HMAC-SHA1 over URL + sorted POST params). */
export function validTwilioSignature(signature: string | null, params: Record<string, string>): boolean {
  if (!signature) return false;
  const url = env('TWILIO_WEBHOOK_URL');
  const data = url + Object.keys(params).sort().map(k => k + params[k]).join('');
  const expected = createHmac('sha1', env('TWILIO_AUTH_TOKEN')).update(data, 'utf8').digest('base64');
  const a = Buffer.from(expected), b = Buffer.from(signature);
  return a.length === b.length && timingSafeEqual(a, b);
}

/** Download a media file Twilio received (voice note / photo). */
export async function fetchTwilioMedia(url: string): Promise<{ buffer: Buffer; contentType: string }> {
  const res = await fetch(url, { headers: { Authorization: twilioAuth() }, redirect: 'follow' });
  if (!res.ok) throw new Error(`Media download failed: ${res.status}`);
  return { buffer: Buffer.from(await res.arrayBuffer()), contentType: res.headers.get('content-type') ?? 'application/octet-stream' };
}

export const templates = {
  checkin: () => optionalEnv('TWILIO_TEMPLATE_CHECKIN_SID'),
  reminder: () => optionalEnv('TWILIO_TEMPLATE_REMINDER_SID'),
};

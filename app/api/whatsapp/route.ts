import { after, NextResponse } from 'next/server';
import { handleInbound } from '@/lib/flow';
import { validTwilioSignature } from '@/lib/whatsapp';

export const runtime = 'nodejs';
export const maxDuration = 60; // agent calls run after the response; see `after()` below

const EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>';

/** Twilio WhatsApp webhook. Acknowledge immediately (Twilio times out at 15 s), then process in the background. */
export async function POST(req: Request) {
  const form = await req.formData();
  const params: Record<string, string> = {};
  form.forEach((v, k) => { if (typeof v === 'string') params[k] = v; });

  if (!validTwilioSignature(req.headers.get('x-twilio-signature'), params)) {
    return new NextResponse('Invalid signature', { status: 403 });
  }

  const lat = params.Latitude ? Number(params.Latitude) : NaN;
  const lng = params.Longitude ? Number(params.Longitude) : NaN;
  const numMedia = Number(params.NumMedia ?? 0);

  after(() => handleInbound({
    from: params.From,
    body: params.Body ?? '',
    media: numMedia > 0 ? { url: params.MediaUrl0, contentType: params.MediaContentType0 ?? '' } : undefined,
    location: Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng, address: params.Address || params.Label || undefined } : undefined,
  }));

  return new NextResponse(EMPTY_TWIML, { headers: { 'Content-Type': 'text/xml' } });
}

/**
 * WhatsApp conversation orchestrator: routes each inbound message through the agents.
 * Agent 1 (classify) → Agent 2 (match) → Agent 3 (draft & file); replies drive Agent 4 via lifecycle.ts.
 */
import { classify, needsClarification, type Classification } from './agents/classifier';
import { draftComplaint } from './agents/drafter';
import { findMatch } from './agents/matcher';
import { departmentGuidance, routeWithKnowledge, type RoutingDecision } from './agents/router';
import { embedOne } from './embeddings';
import { addEvent, db, getAuthorities, getIssue, getOrCreateCitizen, getSession, setCitizenLanguage, setSession, updateIssue, type Citizen } from './db';
import { reverseGeocode } from './geocode';
import { t, yesNo } from './i18n';
import { onCheckinReply, onConsent, onFixConfirmation, proposeEscalation } from './lifecycle';
import { describePhoto, transcribe } from './media';
import { fileComplaint } from './outbound';
import { daysBetween, type GeoPoint } from './types';
import { sendWhatsApp } from './whatsapp';

export type Inbound = {
  from: string;                                   // "whatsapp:+923001234567"
  body: string;
  media?: { url: string; contentType: string };
  location?: GeoPoint;                            // WhatsApp location share (current or picked on the map)
};

const LOCATION_TTL_MS = 30 * 60_000;              // a shared location applies to complaints in the next 30 min
const publicUrl = (id: string) => `${process.env.PUBLIC_BASE_URL ?? ''}/i/${id}`;

type Pending = { text: string; photoDescription?: string; photoUrl?: string; inputType: 'voice' | 'photo' | 'text'; routerAsked?: boolean };

export async function handleInbound(msg: Inbound): Promise<void> {
  const phone = msg.from.replace(/^whatsapp:/, '');
  const citizen = await getOrCreateCitizen(phone);
  const say = (text: string) => sendWhatsApp(phone, text);
  try {
    await route(msg, citizen, say);
  } catch (err) {
    console.error('handleInbound failed', err);
    await say(t(citizen.language, 'error'));
  }
}

async function route(msg: Inbound, citizen: Citizen, say: (s: string) => Promise<void>) {
  const session = await getSession(citizen.citizen_hash);
  const lang = citizen.language;

  // 1) Location share: completes a waiting complaint, or is remembered for the next one.
  if (msg.location) {
    if (session.state === 'awaiting_location') {
      await setSession(citizen.citizen_hash, 'idle');
      return processComplaint(citizen, session.payload.pending as Pending, msg.location, say);
    }
    await setSession(citizen.citizen_hash, 'idle', { last_location: msg.location, location_at: Date.now() });
    return say(t(lang, 'locationSaved'));
  }

  // 2) Normalize the message to text.
  let text = msg.body.trim();
  let inputType: Pending['inputType'] = 'text';
  let photoDescription: string | undefined, photoUrl: string | undefined;
  if (msg.media?.contentType.startsWith('audio/')) {
    const tr = await transcribe(msg.media.url);
    if (!tr) return say(t(lang, 'cantHear'));
    text = tr; inputType = 'voice';
  } else if (msg.media?.contentType.startsWith('image/')) {
    photoDescription = (await describePhoto(msg.media.url)) ?? undefined;
    photoUrl = msg.media.url; inputType = text ? 'text' : 'photo';
  }

  // 3) Replies to a question Awaaz asked.
  const answer = yesNo(text);
  const issueId = session.payload.issue_id as string | undefined;
  switch (session.state) {
    case 'awaiting_match': {
      if (!answer) return say(t(lang, 'pickOne'));
      const p = session.payload as { issue_id: string; c: Classification; loc: GeoPoint; pending: Pending; sector: string; landmark: string; city: string; routing?: RoutingDecision; embedding?: number[] | null };
      await setSession(citizen.citizen_hash, 'idle');
      return answer === 'yes' ? addVoice(citizen, p, say) : fileNew(citizen, p.c, p.loc, p.pending, p.city, p.sector, p.landmark, say, p.routing ?? null, p.embedding ?? null);
    }
    case 'awaiting_checkin':
      if (answer && issueId) return onCheckinReply(issueId, citizen.citizen_hash, answer);
      break;
    case 'awaiting_consent':
      if (answer && issueId) return onConsent(issueId, citizen.citizen_hash, answer === 'yes');
      break;
    case 'awaiting_fix_confirm':
      if ((answer || photoUrl) && issueId) return onFixConfirmation(issueId, citizen.citizen_hash, answer ?? 'yes', photoUrl);
      break;
    case 'awaiting_clarification': {
      const prev = session.payload as { pending: Pending; loc: GeoPoint };
      await setSession(citizen.citizen_hash, 'idle');
      return processComplaint(citizen, { ...prev.pending, text: `${prev.pending.text}. ${text}`, routerAsked: prev.pending.routerAsked || session.payload.byRouter }, prev.loc, say);
    }
    case 'awaiting_location': {
      const prev = session.payload.pending as Pending;
      await setSession(citizen.citizen_hash, 'awaiting_location', { pending: { ...prev, text: `${prev.text}. ${text}`.trim() } });
      return say(t(lang, 'whereIs'));
    }
  }

  // "escalate" restarts a declined escalation on the citizen's most recent open Issue.
  if (/^escalate$/i.test(text)) {
    const { data } = await db().from('issues').select('*').eq('tracker_hash', citizen.citizen_hash)
      .not('status', 'in', '(resolved,closed_unverified)').order('first_reported_at', { ascending: false }).limit(1);
    const issue = data?.[0];
    if (issue && issue.escalation_tier < 3) return proposeEscalation(issue, citizen.citizen_hash, issue.escalation_tier + 1);
  }

  // 4) A new complaint.
  if (!text && !photoDescription) return say(t(lang, 'welcome'));
  const pending: Pending = { text, photoDescription, photoUrl, inputType };
  const recent = session.payload.last_location && Date.now() - (session.payload.location_at ?? 0) < LOCATION_TTL_MS;
  if (!recent) {
    await setSession(citizen.citizen_hash, 'awaiting_location', { pending });
    return say(t(lang, 'whereIs'));
  }
  await setSession(citizen.citizen_hash, 'idle');
  return processComplaint(citizen, pending, session.payload.last_location as GeoPoint, say);
}

async function processComplaint(citizen: Citizen, pending: Pending, loc: GeoPoint, say: (s: string) => Promise<void>) {
  const place = await reverseGeocode(loc);
  const city = place.city ?? 'Lahore';
  const authorities = await getAuthorities(city);
  const c = await classify({
    rawText: pending.text || '(photo only)',
    photoDescription: pending.photoDescription,
    areaText: `${place.landmark}, ${place.sector}, ${city}`,
    city,
    authorities,
  });
  if (c.language !== citizen.language) { await setCitizenLanguage(citizen.citizen_hash, c.language); citizen.language = c.language; }

  if (needsClarification(c)) {
    await setSession(citizen.citizen_hash, 'awaiting_clarification', { pending, loc });
    return say(c.needs_clarification ?? t(c.language, 'whereIs'));
  }
  // RAG: decide the responsible department from the jurisdiction knowledge base, with cited passages.
  const areaText = `${place.landmark}, ${place.sector}, ${city}`;
  const routing = await routeWithKnowledge({ c, city, areaText, authorities });
  if (routing.needs_clarification && !pending.routerAsked) {
    await setSession(citizen.citizen_hash, 'awaiting_clarification', { pending: { ...pending, routerAsked: true }, loc, byRouter: true });
    return say(routing.needs_clarification);
  }
  c.authority_id = routing.authority_id;
  const authority = authorities.find(a => a.authority_id === c.authority_id)!;
  if (c.severity === 'urgent') await say(t(c.language, 'urgent', { helpline: authority.helpline ? `${authority.name} ${authority.helpline}` : undefined }));

  const embedding = await embedOne(`${c.category}: ${c.summary_en}`, 'document');
  const m = await findMatch({ city, category: c.category, lat: loc.lat, lng: loc.lng, summary: c.summary_en, areaText: place.landmark, embedding });
  if (m.decision === 'match') {
    await setSession(citizen.citizen_hash, 'awaiting_match', { issue_id: m.issue.issue_id, c, loc, pending, sector: place.sector, landmark: place.landmark, city, routing, embedding });
    const issue = await getIssue(m.issue.issue_id);
    return say(t(c.language, 'match', { n: m.issue.report_count, id: m.issue.issue_id, d: issue ? daysBetween(issue.first_reported_at) : 1 }));
  }
  return fileNew(citizen, c, loc, pending, city, place.sector, place.landmark, say, routing, embedding);
}

async function addVoice(citizen: Citizen, p: { issue_id: string; c: Classification; loc: GeoPoint; pending: Pending }, say: (s: string) => Promise<void>) {
  const { data, error } = await db().rpc('add_voice', {
    p_issue_id: p.issue_id, p_citizen_hash: citizen.citizen_hash, p_language: p.c.language, p_input_type: p.pending.inputType,
    p_raw_text: p.pending.text, p_photo_url: p.pending.photoUrl ?? null, p_lat: p.loc.lat, p_lng: p.loc.lng,
  });
  if (error) throw error;
  if (data === -1) return say(t(citizen.language, 'alreadyAdded', { id: p.issue_id }));
  return say(t(citizen.language, 'added', { id: p.issue_id, n: data as number, url: publicUrl(p.issue_id) }));
}

async function fileNew(
  citizen: Citizen, c: Classification, loc: GeoPoint, pending: Pending, city: string, sector: string, landmark: string,
  say: (s: string) => Promise<void>, routing: RoutingDecision | null, embedding: number[] | null,
) {
  const { data: issueId, error } = await db().rpc('create_issue', {
    p_city: city, p_sector: sector, p_category: c.category, p_severity: c.severity, p_authority_id: c.authority_id,
    p_summary: c.summary_en, p_lat: loc.lat, p_lng: loc.lng, p_citizen_hash: citizen.citizen_hash, p_language: c.language,
    p_input_type: pending.inputType, p_raw_text: pending.text, p_photo_url: pending.photoUrl ?? null,
  });
  if (error) throw error;
  const issue = (await getIssue(issueId as string))!;
  const authority = (await getAuthorities(city)).find(a => a.authority_id === c.authority_id)!;
  const guidance = await departmentGuidance(city, authority.authority_id, `${c.category} complaint required details`);
  const draft = await draftComplaint(issue, authority, landmark, c.language, guidance);
  await updateIssue(issue.issue_id, {
    formatted_complaint: draft.formatted_complaint, filing_channel: draft.filing_channel,
    summary_embedding: embedding, routing_basis: routing ? { authority_id: routing.authority_id, changed: routing.changed, explanation: routing.explanation, sources: routing.sources } : null,
  });
  await addEvent(issue.issue_id, 'drafted', 'system', { missing_fields: draft.missing_fields });
  const why = routing?.changed && routing.explanation_local ? `\n${routing.explanation_local}` : '';
  await say(`${draft.citizen_confirmation}${why}\n${publicUrl(issue.issue_id)}`);
  await fileComplaint(issue, authority, { subject: draft.email_subject, text: draft.formatted_complaint }, citizen.phone, c.language);
}

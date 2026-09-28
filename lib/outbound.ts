import { addEvent } from './db';
import { optionalEnv } from './env';
import { t } from './i18n';
import type { Authority, EscalationDraft, Issue } from './types';
import { sendLong, sendWhatsApp } from './whatsapp';

async function sendEmail(to: string[], subject: string, text: string, cc: string[] = []): Promise<boolean> {
  const key = optionalEnv('RESEND_API_KEY'), from = optionalEnv('FILING_FROM_EMAIL');
  if (!key || !from || !to.length) return false;
  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ from, to, cc: cc.length ? cc : undefined, subject, text }),
  });
  return res.ok;
}

const isEmail = (s: string | null | undefined): s is string => !!s && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s);

/**
 * File a new complaint. Real submission where a channel exists (email via Resend today; plug portal
 * APIs in here as they become available). Otherwise "assisted": the citizen gets the ready text.
 */
export async function fileComplaint(issue: Issue, authority: Authority, doc: { subject?: string | null; text: string }, citizenPhone: string, lang: string) {
  if (authority.filing_channel === 'email' && isEmail(authority.filing_target) &&
      await sendEmail([authority.filing_target], doc.subject ?? `Complaint ${issue.issue_id}`, doc.text)) {
    await addEvent(issue.issue_id, 'filed_email', 'system', { to: authority.filing_target });
    return 'sent' as const;
  }
  await sendWhatsApp(citizenPhone, t(lang, 'assisted', { target: authority.filing_target ?? authority.name }));
  await sendLong(citizenPhone, doc.text);
  await addEvent(issue.issue_id, 'filed_assisted', 'system', { channel: authority.filing_channel });
  return 'assisted' as const;
}

/** Deliver an approved escalation. Tier 3 is always handed to the citizen: Awaaz never posts. */
export async function deliverEscalation(issue: Issue, authority: Authority, draft: EscalationDraft, citizenPhone: string, lang: string) {
  if (draft.tier === 3) {
    await sendWhatsApp(citizenPhone, t(lang, 'postReady'));
    await sendWhatsApp(citizenPhone, draft.short_post ?? draft.body.slice(0, 280));
    return 'handed_to_citizen' as const;
  }
  const cc = draft.tier === 2 ? authority.escalation_contacts[issue.sector]?.email : undefined;
  if (isEmail(authority.filing_target) && await sendEmail([authority.filing_target], draft.subject, draft.body, isEmail(cc) ? [cc] : [])) {
    return 'sent' as const;
  }
  await sendWhatsApp(citizenPhone, t(lang, 'assisted', { target: [authority.name, cc].filter(Boolean).join(' + ') }));
  await sendLong(citizenPhone, `${draft.subject}\n\n${draft.body}`);
  return 'assisted' as const;
}

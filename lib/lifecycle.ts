/**
 * Tracker & Escalator (Agent 4) plus resolution verification (Agent 2, step F).
 * Deterministic state machine — the LLM only writes escalation text.
 */
import { draftEscalation } from './agents/escalator';
import { departmentGuidance } from './agents/router';
import { addEvent, getAuthority, getCitizen, getIssue, getSession, getTimeline, otherReporter, setSession, updateIssue } from './db';
import { t } from './i18n';
import { deliverEscalation } from './outbound';
import { daysBetween, type Issue } from './types';
import { sendWhatsApp, templates } from './whatsapp';

const DAY = 86_400_000;
const inDays = (n: number) => new Date(Date.now() + n * DAY).toISOString();

/** Daily tick for one Issue: check-in at the due date, one reminder after 3 days, verification timeout. */
export async function tickIssue(issue: Issue): Promise<string | null> {
  const now = Date.now();
  if (issue.verification_requested_at && now - Date.parse(issue.verification_requested_at) > 5 * DAY) {
    await updateIssue(issue.issue_id, { status: 'closed_unverified', resolved_at: new Date().toISOString(), verification_requested_at: null });
    await addEvent(issue.issue_id, 'closed_unverified', 'system');
    return 'closed_unverified';
  }
  if (!issue.tracker_hash || issue.pending_escalation || issue.verification_requested_at) return null;
  const citizen = await getCitizen(issue.tracker_hash);
  if (!citizen) return null;
  const session = await getSession(citizen.citizen_hash);
  if (session.state !== 'idle' && session.state !== 'awaiting_checkin') return null; // don't interrupt another conversation; retry tomorrow

  if (!issue.checkin_sent_at && now >= Date.parse(issue.expected_by)) {
    const tpl = templates.checkin();
    await sendWhatsApp(citizen.phone, t(citizen.language, 'checkin', { id: issue.issue_id }), tpl ? { contentSid: tpl, variables: { 1: issue.issue_id } } : undefined);
    await updateIssue(issue.issue_id, { checkin_sent_at: new Date().toISOString(), reminder_sent: false });
    await setSession(citizen.citizen_hash, 'awaiting_checkin', { issue_id: issue.issue_id });
    await addEvent(issue.issue_id, 'checkin_sent', 'system');
    return 'checkin';
  }
  if (issue.checkin_sent_at && !issue.reminder_sent && now - Date.parse(issue.checkin_sent_at) >= 3 * DAY) {
    const tpl = templates.reminder();
    await sendWhatsApp(citizen.phone, t(citizen.language, 'reminder', { id: issue.issue_id }), tpl ? { contentSid: tpl, variables: { 1: issue.issue_id } } : undefined);
    await updateIssue(issue.issue_id, { reminder_sent: true });
    await addEvent(issue.issue_id, 'reminder_sent', 'system');
    return 'reminder';
  }
  return null; // no response after the reminder → pause; never escalate without a "No"
}

/** Citizen answered the check-in. */
export async function onCheckinReply(issueId: string, citizenHash: string, answer: 'yes' | 'no') {
  const issue = await getIssue(issueId);
  const citizen = await getCitizen(citizenHash);
  if (!issue || !citizen) return;
  await updateIssue(issueId, { checkin_sent_at: null, reminder_sent: false });
  if (answer === 'yes') return requestVerification(issue, citizenHash);
  await addEvent(issueId, 'citizen_no', citizenHash);
  if (issue.escalation_tier >= 3) {
    await setSession(citizenHash, 'idle');
    await sendWhatsApp(citizen.phone, t(citizen.language, 'finalTier', { id: issueId }));
    return;
  }
  await proposeEscalation(issue, citizenHash, (issue.escalation_tier + 1) as 1 | 2 | 3);
}

export async function proposeEscalation(issue: Issue, citizenHash: string, tier: 1 | 2 | 3) {
  const [authority, citizen, timeline, guidance] = await Promise.all([
    getAuthority(issue.authority_id), getCitizen(citizenHash), getTimeline(issue.issue_id),
    departmentGuidance(issue.city, issue.authority_id, 'escalation channels unresolved complaint councilor portal right to information'),
  ]);
  if (!citizen) return;
  const draft = await draftEscalation({
    issue, authority, tier, citizenLanguage: citizen.language, guidance,
    timeline: timeline.map(e => ({ at: new Date(e.created_at).toDateString(), type: e.type })),
  });
  await updateIssue(issue.issue_id, { pending_escalation: draft });
  await addEvent(issue.issue_id, 'escalation_drafted', 'system', { tier });
  await setSession(citizenHash, 'awaiting_consent', { issue_id: issue.issue_id });
  const preview = tier === 3 ? draft.short_post ?? draft.body : `${draft.subject}\nTo: ${draft.recipients.join(', ')}\n\n${draft.body}`;
  await sendWhatsApp(citizen.phone, `Tier ${tier}:\n\n${preview}`.slice(0, 1500));
  await sendWhatsApp(citizen.phone, `${draft.consent_prompt}\n${t(citizen.language, 'consent', { tier })}`);
}

/** Consent is explicit: nothing leaves Awaaz without a "1". */
export async function onConsent(issueId: string, citizenHash: string, approve: boolean) {
  const issue = await getIssue(issueId);
  const citizen = await getCitizen(citizenHash);
  if (!issue?.pending_escalation || !citizen) return;
  await setSession(citizenHash, 'idle');
  const draft = issue.pending_escalation;
  if (!approve) {
    await updateIssue(issueId, { pending_escalation: null });
    await addEvent(issueId, 'escalation_declined', citizenHash, { tier: draft.tier });
    await sendWhatsApp(citizen.phone, t(citizen.language, 'declined'));
    return;
  }
  const authority = await getAuthority(issue.authority_id);
  const how = await deliverEscalation(issue, authority, draft, citizen.phone, citizen.language);
  await updateIssue(issueId, {
    pending_escalation: null, escalation_tier: draft.tier, status: `escalated_t${draft.tier}`, expected_by: inDays(7),
  });
  await addEvent(issueId, 'escalation_approved', citizenHash, { tier: draft.tier, delivery: how });
  if (draft.tier < 3) await sendWhatsApp(citizen.phone, t(citizen.language, 'sent', { tier: draft.tier, id: issueId }));
  if (draft.citizen_tip) await sendWhatsApp(citizen.phone, draft.citizen_tip);
}

/** Someone says it's fixed → ask a different reporter to confirm (or accept the sole reporter's word). */
export async function requestVerification(issue: Issue, claimedBy: string) {
  const claimer = await getCitizen(claimedBy);
  const confirmerHash = await otherReporter(issue.issue_id, claimedBy);
  await addEvent(issue.issue_id, 'fix_claimed', claimedBy);
  if (!confirmerHash) return resolveIssue(issue, claimedBy, null);
  const confirmer = await getCitizen(confirmerHash);
  if (!confirmer) return resolveIssue(issue, claimedBy, null);
  await updateIssue(issue.issue_id, { verification_requested_at: new Date().toISOString() });
  await setSession(confirmerHash, 'awaiting_fix_confirm', { issue_id: issue.issue_id });
  await sendWhatsApp(confirmer.phone, t(confirmer.language, 'confirmFix', { id: issue.issue_id, summary: issue.summary }));
  if (claimer) { await setSession(claimedBy, 'idle'); await sendWhatsApp(claimer.phone, t(claimer.language, 'waitVerify')); }
}

export async function onFixConfirmation(issueId: string, confirmerHash: string, answer: 'yes' | 'no', photoUrl?: string) {
  const issue = await getIssue(issueId);
  const confirmer = await getCitizen(confirmerHash);
  await setSession(confirmerHash, 'idle');
  if (!issue || !confirmer) return;
  if (answer === 'yes') return resolveIssue(issue, confirmerHash, photoUrl ?? null);
  await updateIssue(issueId, { verification_requested_at: null, status: issue.escalation_tier ? `escalated_t${issue.escalation_tier}` : 'in_progress' });
  await addEvent(issueId, 'fix_disputed', confirmerHash);
  await sendWhatsApp(confirmer.phone, t(confirmer.language, 'stillThere', { id: issueId }));
}

async function resolveIssue(issue: Issue, confirmedBy: string, proof: string | null) {
  await updateIssue(issue.issue_id, {
    status: 'resolved', resolved_at: new Date().toISOString(), verification_requested_at: null,
    pending_escalation: null, checkin_sent_at: null, resolution_proof: proof,
  });
  await addEvent(issue.issue_id, 'resolved', confirmedBy, { proof });
  const tracker = issue.tracker_hash ? await getCitizen(issue.tracker_hash) : null;
  if (tracker) {
    await setSession(tracker.citizen_hash, 'idle');
    await sendWhatsApp(tracker.phone, t(tracker.language, 'resolved', { id: issue.issue_id, d: daysBetween(issue.first_reported_at) }));
  }
}

/** Authority dashboard actions. "fixed" never closes an Issue by itself: a resident must confirm. */
export async function authorityAction(issueId: string, action: 'acknowledge' | 'in_progress' | 'fixed') {
  const issue = await getIssue(issueId);
  if (!issue || issue.status === 'resolved') return;
  if (action === 'acknowledge' || action === 'in_progress') {
    const status = action === 'acknowledge' ? 'acknowledged' : 'in_progress';
    await updateIssue(issueId, issue.escalation_tier ? {} : { status });
    await addEvent(issueId, status, issue.authority_id);
    return;
  }
  await addEvent(issueId, 'authority_marked_fixed', issue.authority_id);
  const tracker = issue.tracker_hash ? await getCitizen(issue.tracker_hash) : null;
  if (!tracker) return;
  const authority = await getAuthority(issue.authority_id);
  await updateIssue(issueId, { verification_requested_at: new Date().toISOString() });
  await setSession(tracker.citizen_hash, 'awaiting_fix_confirm', { issue_id: issueId });
  await sendWhatsApp(tracker.phone, t(tracker.language, 'authFixed', { id: issueId, auth: authority.name }));
}

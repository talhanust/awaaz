import { z } from 'zod';
import { askJSON, MODELS } from '../claude';
import { daysBetween, type Authority, type EscalationDraft, type Issue } from '../types';

const SYSTEM = `You are Awaaz's Escalator. Given an Issue's record and full event timeline, write the next escalation at the requested tier.

Tier 1 — Formal re-complaint to the same authority. Cite the original reference id, the filing date, days elapsed, and number of citizen reports. Firm, respectful, English.
Tier 2 — Same letter, addressed to the authority and CC'd to the contact in cc_contact. Add one sentence asking that office to follow up. If cc_contact is null, list it in missing_contacts and do not invent one.
Tier 3 — A short public post the citizen will review and post themselves: short_post max 280 characters, body is a longer version with the timeline. State only what the record shows: issue, sector (not exact address), reference id, days unresolved, number of residents who reported it, and the authority's name. No insults, no accusations of intent or corruption, no claims about individuals, no hashtags that name individuals.

consent_prompt: one line in the citizen's language (citizen_language) asking them to approve.
citizen_tip: using ONLY the retrieved guidance passages, one optional sentence in the citizen's language about a parallel channel they could also use (for example a government complaint portal or a right-to-information request). null if the guidance has nothing relevant. Never invent channels.
Never state or imply that anything has already been sent or posted.

Respond ONLY with JSON:
{"tier":1,"recipients":["..."],"missing_contacts":[],"subject":"...","body":"...","short_post":null,"consent_prompt":"...","citizen_tip":null}`;

const Escalation = z.object({
  tier: z.union([z.literal(1), z.literal(2), z.literal(3)]),
  recipients: z.array(z.string()),
  missing_contacts: z.array(z.string()),
  subject: z.string(),
  body: z.string().min(40),
  short_post: z.string().max(280).nullable(),
  consent_prompt: z.string(),
  citizen_tip: z.string().nullable().optional(),
});

export async function draftEscalation(args: {
  issue: Issue;
  authority: Authority;
  tier: 1 | 2 | 3;
  timeline: { at: string; type: string }[];
  citizenLanguage: string;
  guidance?: unknown[];
}): Promise<EscalationDraft> {
  const cc = args.authority.escalation_contacts[args.issue.sector] ?? null;
  const out = await askJSON({
    system: SYSTEM,
    model: MODELS.smart,
    schema: Escalation,
    maxTokens: 1500,
    input: {
      tier: args.tier,
      issue: {
        reference_id: args.issue.issue_id,
        summary: args.issue.summary,
        category: args.issue.category,
        area: `${args.issue.sector}, ${args.issue.city}`,
        authority: args.authority.name,
        filed: new Date(args.issue.first_reported_at).toDateString(),
        days_unresolved: daysBetween(args.issue.first_reported_at),
        residents: args.issue.report_count,
        prior_tier: args.issue.escalation_tier,
      },
      cc_contact: args.tier === 2 ? cc?.title ?? null : null,
      timeline: args.timeline,
      citizen_language: args.citizenLanguage,
      guidance: args.guidance ?? [],
    },
  });
  if (out.tier !== args.tier) out.tier = args.tier;
  return { ...out, citizen_tip: out.citizen_tip ?? null };
}

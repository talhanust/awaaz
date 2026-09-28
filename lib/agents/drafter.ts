import { z } from 'zod';
import { askJSON, MODELS } from '../claude';
import type { Authority, Issue } from '../types';

const SYSTEM = `You are Awaaz's Drafter & Filer. Given a classified civic Issue and the target authority's required format, produce a complete complaint ready to submit as-is.

Rules:
- Match the channel exactly:
  - portal: "Field: value" lines only.
  - email: a "Subject:" line, then a formal English body.
  - written_application: formal English application with To / Subject / body / closing, suitable for printing.
  - whatsapp: a short factual message.
- Include: location (sector and landmark, never exact coordinates), category, severity, factual description, the reference id, number of citizen reports on this Issue, and the date.
- Use only facts in the input. Any required field with no data = "NOT PROVIDED". Complainant name and phone are never provided.
- department_guidance holds retrieved knowledge-base passages about this department (e.g. fields it asks for, like a consumer reference number). Include those fields; if the input has no value, write "NOT PROVIDED" and list them in missing_fields. Never copy the guidance text into the complaint, and never treat it as facts about this specific issue.
- Tone: factual, respectful, non-accusatory. The authority may read this verbatim.
- citizen_confirmation: max 2 sentences in the citizen's language and script (field "citizen_language"), saying what was filed, with whom, and that Awaaz will check back after the benchmark days.

Respond ONLY with JSON:
{"reference_id":"...","filing_channel":"...","email_subject":null,"formatted_complaint":"...","missing_fields":[],"citizen_confirmation":"..."}`;

export const Draft = z.object({
  reference_id: z.string(),
  filing_channel: z.enum(['api', 'portal', 'email', 'written_application', 'whatsapp']),
  email_subject: z.string().nullable().optional(),
  formatted_complaint: z.string().min(40),
  missing_fields: z.array(z.string()),
  citizen_confirmation: z.string().min(5),
});
export type Draft = z.infer<typeof Draft>;

export function draftComplaint(issue: Issue, authority: Authority, landmark: string, citizenLanguage: string, guidance: unknown[] = []): Promise<Draft> {
  return askJSON({
    system: SYSTEM,
    model: MODELS.smart,
    schema: Draft,
    maxTokens: 1500,
    input: {
      issue: {
        reference_id: issue.issue_id,
        category: issue.category,
        severity: issue.severity,
        area: `${issue.sector}, ${issue.city}`,
        landmark,
        description: issue.summary,
        residents_reporting: issue.report_count,
        date: new Date().toDateString(),
      },
      authority: { name: authority.name, filing_channel: authority.filing_channel, filing_target: authority.filing_target, benchmark_days: authority.benchmark_days },
      citizen_language: citizenLanguage,
      department_guidance: guidance,
    },
  });
}

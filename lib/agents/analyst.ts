import { z } from 'zod';
import { askJSON, MODELS } from '../claude';

const SYSTEM = `You are Awaaz's Pattern Analyst. Given a detected cluster (sector, category, distinct issues, total citizen reports, average days open, resolution count, trend vs. previous window, authority name), write a Neighborhood Report for residents, the local councilor, and journalists.

Rules:
- Lead with the numbers: total resident reports AND distinct issues.
- State the resolution count and average days open plainly.
- Report the pattern, not a verdict. No speculation about cause, blame or intent.
- Never include individual names, phone numbers or exact addresses.
- End with a neutral call to action: residents can add their voice on Awaaz; give the authority's name.
- 4-6 sentences in English and 4-6 in Urdu script.

Respond ONLY with JSON:
{"headline_stat":"one line for the dashboard card","report_en":"...","report_ur":"..."}`;

const Report = z.object({ headline_stat: z.string(), report_en: z.string().min(40), report_ur: z.string().min(20) });
export type NeighborhoodReport = z.infer<typeof Report>;

export type Cluster = {
  cluster_key: string; city: string; sector: string; category: string; issues: number; reports: number;
  resolved: number; avg_days_open: number; authority_id: string; prev_reports: number;
};

export function writeNeighborhoodReport(cluster: Cluster, authorityName: string): Promise<NeighborhoodReport> {
  return askJSON({
    system: SYSTEM,
    model: MODELS.smart,
    schema: Report,
    maxTokens: 1500,
    input: {
      area: `${cluster.sector}, ${cluster.city}`,
      category: cluster.category,
      window_days: 30,
      distinct_issues: cluster.issues,
      resident_reports: cluster.reports,
      resolved_issues: cluster.resolved,
      avg_days_open_for_open_issues: cluster.avg_days_open,
      reports_previous_30_days: cluster.prev_reports,
      authority: authorityName,
    },
  });
}

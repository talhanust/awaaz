export const CATEGORIES = ['electrical', 'water', 'sanitation', 'roads', 'gas', 'encroachment', 'other'] as const;
export const SEVERITIES = ['low', 'medium', 'high', 'urgent'] as const;
export const LANGUAGES = ['ur', 'ur-Latn', 'pa', 'en'] as const;
export type Category = (typeof CATEGORIES)[number];
export type Severity = (typeof SEVERITIES)[number];
export type Language = (typeof LANGUAGES)[number];
export type FilingChannel = 'api' | 'portal' | 'email' | 'written_application' | 'whatsapp';

export type Authority = {
  authority_id: string;
  city: string;
  name: string;
  categories: Category[];
  filing_channel: FilingChannel;
  filing_target: string | null;
  helpline: string | null;
  benchmark_days: number;
  escalation_contacts: Record<string, { title: string; email?: string }>;
};

export type Issue = {
  issue_id: string;
  city: string;
  sector: string;
  category: Category;
  severity: Severity;
  authority_id: string;
  summary: string;
  status: string;
  escalation_tier: number;
  report_count: number;
  confirmations: number;
  tracker_hash: string | null;
  filing_channel: FilingChannel | null;
  formatted_complaint: string | null;
  pending_escalation: EscalationDraft | null;
  checkin_sent_at: string | null;
  reminder_sent: boolean;
  verification_requested_at: string | null;
  first_reported_at: string;
  expected_by: string;
  resolved_at: string | null;
};

export type EscalationDraft = {
  tier: 1 | 2 | 3;
  recipients: string[];
  missing_contacts: string[];
  subject: string;
  body: string;
  short_post: string | null;
  consent_prompt: string;
  citizen_tip?: string | null;
};

export type GeoPoint = { lat: number; lng: number; address?: string };

export const daysBetween = (from: string | Date, to: Date = new Date()) =>
  Math.max(1, Math.floor((to.getTime() - new Date(from).getTime()) / 86_400_000));

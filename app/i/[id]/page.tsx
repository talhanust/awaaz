import { notFound } from 'next/navigation';
import { db } from '@/lib/db';

export const dynamic = 'force-dynamic';

const EVENT_TEXT: Record<string, string> = {
  filed: 'Filed', drafted: 'Complaint drafted for the department', filed_email: 'Sent to the department by email',
  filed_assisted: 'Complaint text given to the resident to submit', report_added: 'Another resident added their voice',
  checkin_sent: 'Resident asked whether it is fixed', reminder_sent: 'Reminder sent', citizen_no: 'Resident reports it is still unresolved',
  escalation_drafted: 'Escalation drafted, waiting for resident approval', escalation_approved: 'Escalation approved by resident',
  escalation_declined: 'Resident chose not to escalate yet', acknowledged: 'Acknowledged by the department', in_progress: 'Department marked work in progress',
  authority_marked_fixed: 'Department marked it fixed', fix_claimed: 'A resident says it is fixed', fix_disputed: 'A resident says it is still there',
  resolved: 'Resolved and confirmed by a resident', closed_unverified: 'Closed without resident confirmation',
};

/** Public Issue page (link in WhatsApp receipts). Shows no personal data and no exact location. */
export default async function IssuePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { data: issue } = await db().from('issues')
    .select('issue_id, sector, city, category, severity, authority_id, summary, status, escalation_tier, report_count, first_reported_at, expected_by, resolved_at, routing_basis')
    .eq('issue_id', id).maybeSingle();
  if (!issue) notFound();
  const { data: events } = await db().from('events').select('type, payload, created_at').eq('issue_id', id).order('created_at', { ascending: false });
  return (
    <main className="wrap" style={{ maxWidth: 760 }}>
      <p className="meta">{issue.category} · {issue.sector}, {issue.city} · {issue.authority_id}</p>
      <h1>{issue.issue_id}</h1>
      <p style={{ fontSize: 17 }}>{issue.summary}</p>
      <div className="kpis">
        <div className="kpi"><b>{issue.report_count}</b>residents reported this</div>
        <div className="kpi"><b>{issue.status === 'resolved' ? 'Fixed' : issue.escalation_tier ? `Tier ${issue.escalation_tier}` : issue.status.replace('_', ' ')}</b>status</div>
        <div className="kpi"><b>{new Date(issue.expected_by).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</b>due date</div>
      </div>
      {issue.routing_basis ? (() => {
        const rb = issue.routing_basis as { explanation: string; sources: { chunk_id: string; title: string; verified: boolean }[] };
        return (
          <section className="card" style={{ margin: '0 0 20px' }}>
            <h2 style={{ fontSize: 16, marginBottom: 6 }}>Why {issue.authority_id}</h2>
            <p style={{ margin: 0 }}>{rb.explanation}</p>
            {rb.sources.length ? <p className="meta" style={{ marginTop: 6 }}>Based on: {rb.sources.map(s => `${s.title}${s.verified ? '' : ' (unverified guidance)'}`).join(' · ')}</p> : null}
          </section>
        );
      })() : null}
      <h2 style={{ fontSize: 18, margin: '8px 0 12px' }}>Timeline</h2>
      <ol className="timeline">
        {(events ?? []).map((e, k) => (
          <li key={k}><time>{new Date(e.created_at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}</time>
            {EVENT_TEXT[e.type] ?? e.type}{e.type === 'escalation_approved' && (e.payload as { tier?: number })?.tier ? ` (Tier ${(e.payload as { tier: number }).tier})` : ''}</li>
        ))}
      </ol>
    </main>
  );
}

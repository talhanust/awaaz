import IssueActions from '@/components/IssueActions';
import MapClient from '@/components/MapClient';
import { db } from '@/lib/db';

export const dynamic = 'force-dynamic';

type Row = {
  issue_id: string; sector: string; category: string; severity: string; authority_id: string; status: string;
  escalation_tier: number; report_count: number; summary: string; days_open: number; priority: number;
  expected_by: string; lat: number; lng: number;
};
type Score = {
  authority_id: string; name: string; benchmark_days: number; resolved_90d: number; median_days: number | null;
  within_benchmark: number | null; open_now: number; escalated_now: number; unverified_90d: number;
};

const statusLabel = (r: Row) => r.escalation_tier ? `Escalated · Tier ${r.escalation_tier}` : r.status.replace('_', ' ');

export default async function Dashboard() {
  const [{ data: queue }, { data: scores }] = await Promise.all([
    db().from('issue_queue').select('*').order('priority', { ascending: false }).limit(50),
    db().from('authority_scorecards').select('*').order('name'),
  ]);
  const rows = (queue ?? []) as Row[];
  const now = Date.now();
  const reports = rows.reduce((s, r) => s + r.report_count, 0);
  const avg = rows.length ? Math.round(rows.reduce((s, r) => s + r.days_open, 0) / rows.length) : 0;
  const within = rows.length ? Math.round((100 * rows.filter(r => Date.parse(r.expected_by) >= now).length) / rows.length) : 0;

  return (
    <main className="wrap">
      <h1>Authority queue</h1>
      <p className="lede">Duplicates are merged into one Issue and ranked by residents × severity × days open. Marking an Issue fixed asks residents to confirm before it closes.</p>
      <div className="kpis">
        <div className="kpi"><b>{rows.length}</b>open Issues</div>
        <div className="kpi"><b>{reports}</b>resident reports behind them</div>
        <div className="kpi"><b>{avg} d</b>average days open</div>
        <div className="kpi"><b>{within}%</b>still within their due date</div>
      </div>
      <div className="grid2">
        <section className="card">
          {rows.length === 0 ? <p>No open Issues. New WhatsApp reports appear here automatically.</p> : (
            <ol className="queue">
              {rows.map((r, k) => (
                <li key={r.issue_id}>
                  <div className="rank">{k + 1}</div>
                  <div>
                    <a href={`/i/${r.issue_id}`}><b>{r.summary}</b></a>
                    <div className="meta"><span>{r.issue_id}</span><span>{r.sector}</span><span>{r.authority_id}</span><span>{r.days_open} days open</span>
                      <span className={`badge ${r.escalation_tier ? 'esc' : ''}`}>{statusLabel(r)}</span></div>
                    <IssueActions issueId={r.issue_id} status={r.status} />
                  </div>
                  <div className="n"><b>{r.report_count}</b><span>residents</span></div>
                </li>
              ))}
            </ol>
          )}
        </section>
        <section className="card">
          <h2 style={{ fontSize: 18, marginBottom: 10 }}>Map</h2>
          <MapClient issues={rows.map(r => ({ issue_id: r.issue_id, summary: r.summary, category: r.category, report_count: r.report_count, lat: r.lat, lng: r.lng }))} />
          <p className="meta" style={{ marginTop: 8 }}>Locations are rounded to about 100 m.</p>
        </section>
      </div>
      <section className="card" style={{ marginTop: 20 }}>
        <h2 style={{ fontSize: 18, marginBottom: 10 }}>Department scorecards (last 90 days)</h2>
        <div className="scroll"><table>
          <thead><tr><th>Department</th><th className="num">Resolved</th><th className="num">Median days</th><th className="num">Target</th><th className="num">Within target</th><th className="num">Unverified closures</th><th className="num">Open</th><th className="num">Escalated</th></tr></thead>
          <tbody>{((scores ?? []) as Score[]).map(s => (
            <tr key={s.authority_id}><td>{s.name}</td><td className="num">{s.resolved_90d}</td>
              <td className="num">{s.median_days != null ? s.median_days.toFixed(1) : '—'}</td><td className="num">{s.benchmark_days}</td>
              <td className="num">{s.resolved_90d >= 10 && s.within_benchmark != null ? `${Math.round(s.within_benchmark * 100)}%` : 'Not enough data'}</td>
              <td className="num">{s.unverified_90d}</td><td className="num">{s.open_now}</td><td className="num">{s.escalated_now}</td></tr>
          ))}</tbody>
        </table></div>
      </section>
    </main>
  );
}

import ReportButton from '@/components/ReportButton';
import { db } from '@/lib/db';

export const dynamic = 'force-dynamic';

type Cluster = { cluster_key: string; sector: string; category: string; issues: number; reports: number; resolved: number; avg_days_open: number; prev_reports: number; authority_id: string };
type Saved = { cluster_key: string; headline: string; report_en: string; report_ur: string; created_at: string };

export default async function Reports() {
  const [{ data: clusters }, { data: saved }] = await Promise.all([
    db().from('clusters_30d').select('*').order('reports', { ascending: false }),
    db().from('neighborhood_reports').select('*'),
  ]);
  const byKey = new Map(((saved ?? []) as Saved[]).map(s => [s.cluster_key, s]));
  const list = (clusters ?? []) as Cluster[];
  return (
    <main className="wrap">
      <h1>Neighborhood reports</h1>
      <p className="lede">A cluster is 3+ Issues or 10+ resident reports in one area and category within 30 days. Reports state the pattern, not a verdict.</p>
      {list.length === 0 ? <p className="card">No clusters in the last 30 days.</p> : list.map(c => {
        const r = byKey.get(c.cluster_key);
        const trend = c.prev_reports ? Math.round((100 * (c.reports - c.prev_reports)) / c.prev_reports) : null;
        return (
          <section key={c.cluster_key} className="card" style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <h2 style={{ fontSize: 19 }}>{c.reports} residents, {c.issues} {c.category} Issues, {c.sector}</h2>
                <div className="meta">{c.resolved} resolved · {c.avg_days_open} days open on average · {trend == null ? 'new this window' : `${trend >= 0 ? '+' : ''}${trend}% vs previous 30 days`} · {c.authority_id}</div>
              </div>
              <div><ReportButton clusterKey={c.cluster_key} hasReport={!!r} /></div>
            </div>
            {r ? (
              <div className="grid2" style={{ marginTop: 12 }}>
                <div><b>{r.headline}</b><p>{r.report_en}</p></div>
                <p className="ur" dir="rtl">{r.report_ur}</p>
              </div>
            ) : null}
          </section>
        );
      })}
    </main>
  );
}

'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

export default function ReportButton({ clusterKey, hasReport }: { clusterKey: string; hasReport: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  return (
    <>
      <button className="btn primary" disabled={busy} onClick={async () => {
        setBusy(true); setErr('');
        const res = await fetch('/api/reports/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cluster_key: clusterKey }) });
        setBusy(false);
        if (!res.ok) setErr('The report couldn’t be written. Try again.'); else router.refresh();
      }}>{busy ? 'Writing…' : hasReport ? 'Rewrite report' : 'Write report'}</button>
      {err ? <span className="meta" role="status"> {err}</span> : null}
    </>
  );
}

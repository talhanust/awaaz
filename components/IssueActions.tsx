'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

const LABELS = { acknowledge: 'Acknowledge', in_progress: 'Mark in progress', fixed: 'Mark fixed' } as const;

export default function IssueActions({ issueId, status }: { issueId: string; status: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState('');
  async function act(action: keyof typeof LABELS) {
    setBusy(action); setMsg('');
    const res = await fetch(`/api/authority/issues/${issueId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) });
    setBusy(null);
    if (!res.ok) { setMsg('That didn’t save. Try again.'); return; }
    setMsg(action === 'fixed' ? 'Sent to residents to confirm the fix.' : 'Saved.');
    router.refresh();
  }
  return (
    <div className="actions">
      {(Object.keys(LABELS) as (keyof typeof LABELS)[]).map(a => (
        <button key={a} className="btn" disabled={!!busy || (a === 'acknowledge' && status !== 'open')} onClick={() => act(a)}>
          {busy === a ? 'Saving…' : LABELS[a]}
        </button>
      ))}
      {msg ? <span className="meta" role="status">{msg}</span> : null}
    </div>
  );
}

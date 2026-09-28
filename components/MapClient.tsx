'use client';
import dynamic from 'next/dynamic';
import type { MapIssue } from './AwaazMap';

const AwaazMap = dynamic(() => import('./AwaazMap'), { ssr: false, loading: () => <p>Loading map…</p> });
export default function MapClient({ issues }: { issues: MapIssue[] }) {
  return <AwaazMap issues={issues} />;
}

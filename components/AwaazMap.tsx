'use client';
import 'leaflet/dist/leaflet.css';
import { CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet';

// Free OpenStreetMap tiles: fine for a pilot. Switch TILE_URL to MapTiler / Stadia / OpenFreeMap before launch.
const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const CAT_HEX: Record<string, string> = {
  roads: '#9A6324', sanitation: '#7A5AA6', water: '#1F7FB8', electrical: '#C28E00', gas: '#D1495B', encroachment: '#4F7A4F', other: '#6B7280',
};

export type MapIssue = { issue_id: string; summary: string; category: string; report_count: number; lat: number; lng: number };

export default function AwaazMap({ issues, center = [31.4697, 74.2728] }: { issues: MapIssue[]; center?: [number, number] }) {
  return (
    <MapContainer center={center} zoom={14} scrollWheelZoom={false} style={{ height: 420, borderRadius: 12 }}>
      <TileLayer url={TILE_URL} attribution={ATTRIBUTION} maxZoom={19} />
      {issues.map(i => (
        <CircleMarker key={i.issue_id} center={[i.lat, i.lng]} radius={6 + 3 * Math.sqrt(i.report_count)}
          pathOptions={{ color: '#fff', weight: 2, fillColor: CAT_HEX[i.category] ?? CAT_HEX.other, fillOpacity: 0.85 }}>
          <Tooltip>{i.summary} · {i.report_count} residents</Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}

import type { GeoPoint } from './types';

export type Place = { city: string | null; sector: string; landmark: string };

/**
 * Reverse-geocode with OpenStreetMap Nominatim (free). Policy: ≤1 request/second and an identifying
 * User-Agent. Fine for a pilot; self-host Nominatim or use a paid geocoder at scale.
 */
export async function reverseGeocode(p: GeoPoint): Promise<Place> {
  const fallback: Place = { city: null, sector: `near ${p.lat.toFixed(4)}, ${p.lng.toFixed(4)}`, landmark: p.address ?? `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}` };
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${p.lat}&lon=${p.lng}&zoom=17&accept-language=en`,
      { headers: { 'User-Agent': 'Awaaz/0.1 (civic complaints pilot; contact: team@awaaz.example)' }, signal: AbortSignal.timeout(5000) },
    );
    if (!res.ok) return fallback;
    const a = ((await res.json()) as { address?: Record<string, string> }).address ?? {};
    const city = a.city ?? a.town ?? a.county ?? null;
    const sector = a.neighbourhood ?? a.quarter ?? a.suburb ?? a.residential ?? fallback.sector;
    const landmark = p.address ?? [a.road, a.neighbourhood ?? a.suburb].filter(Boolean).join(', ') ?? fallback.landmark;
    return { city, sector, landmark: landmark || fallback.landmark };
  } catch {
    return fallback;
  }
}

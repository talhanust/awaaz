import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { createHash } from 'node:crypto';
import { env } from './env';
import type { Authority, Issue } from './types';

let client: SupabaseClient | null = null;
/** Service-role client. Server-only: never import this from a client component. */
export const db = () =>
  (client ??= createClient(env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY'), { auth: { persistSession: false } }));

const must = <T>(r: { data: T | null; error: unknown }): T => {
  if (r.error) throw r.error;
  return r.data as T;
};

export const hashPhone = (phone: string) => createHash('sha256').update(phone + env('CITIZEN_HASH_SALT')).digest('hex');

export type Citizen = { citizen_hash: string; phone: string; language: string };
export async function getOrCreateCitizen(phone: string): Promise<Citizen> {
  const citizen_hash = hashPhone(phone);
  const existing = must(await db().from('citizens').select('*').eq('citizen_hash', citizen_hash).maybeSingle()) as Citizen | null;
  if (existing) return existing;
  return must(await db().from('citizens').insert({ citizen_hash, phone }).select().single()) as Citizen;
}
export async function getCitizen(hash: string): Promise<Citizen | null> {
  return must(await db().from('citizens').select('*').eq('citizen_hash', hash).maybeSingle()) as Citizen | null;
}
export const setCitizenLanguage = async (hash: string, language: string) =>
  must(await db().from('citizens').update({ language }).eq('citizen_hash', hash));

export type Session = { citizen_hash: string; state: SessionState; payload: Record<string, any>; updated_at: string };
export type SessionState =
  | 'idle' | 'awaiting_location' | 'awaiting_clarification' | 'awaiting_match'
  | 'awaiting_checkin' | 'awaiting_consent' | 'awaiting_fix_confirm';

export async function getSession(hash: string): Promise<Session> {
  const s = must(await db().from('sessions').select('*').eq('citizen_hash', hash).maybeSingle()) as Session | null;
  return s ?? { citizen_hash: hash, state: 'idle', payload: {}, updated_at: new Date().toISOString() };
}
export async function setSession(hash: string, state: SessionState, payload: Record<string, any> = {}) {
  must(await db().from('sessions').upsert({ citizen_hash: hash, state, payload, updated_at: new Date().toISOString() }));
}

export async function getAuthorities(city: string): Promise<Authority[]> {
  return must(await db().from('authorities').select('*').eq('city', city)) as Authority[];
}
export async function getAuthority(id: string): Promise<Authority> {
  return must(await db().from('authorities').select('*').eq('authority_id', id).single()) as Authority;
}
export async function getIssue(id: string): Promise<Issue | null> {
  return must(await db().from('issues').select('*').eq('issue_id', id).maybeSingle()) as Issue | null;
}
export async function updateIssue(id: string, patch: Partial<Issue> & Record<string, unknown>) {
  must(await db().from('issues').update(patch).eq('issue_id', id));
}
export async function addEvent(issue_id: string, type: string, actor: string, payload: Record<string, unknown> = {}) {
  must(await db().from('events').insert({ issue_id, type, actor, payload }));
}
export async function getTimeline(issue_id: string) {
  return must(await db().from('events').select('type, payload, created_at').eq('issue_id', issue_id).order('created_at')) as
    { type: string; payload: Record<string, unknown>; created_at: string }[];
}
/** Another reporter (not `exclude`) who can confirm a fix, most recent first. */
export async function otherReporter(issue_id: string, exclude: string): Promise<string | null> {
  const rows = must(await db().from('reports').select('citizen_hash').eq('issue_id', issue_id).neq('citizen_hash', exclude)
    .order('created_at', { ascending: false }).limit(1)) as { citizen_hash: string }[];
  return rows[0]?.citizen_hash ?? null;
}

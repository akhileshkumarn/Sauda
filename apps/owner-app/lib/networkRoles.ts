'use client';
// Role switch and business-contact verification calls for the Trust Network.
import { API_BASE, ApiError, MOCK } from './api';
import { getIdToken } from './auth';
import type { TnBusiness, TnRole } from './types';

async function call<T>(method: string, path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', 'Content-Type': 'application/json' };
  const t = await getIdToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(`${API_BASE}${path}`, { method, headers, cache: 'no-store', body: JSON.stringify(body) });
  if (!res.ok) {
    let code = `HTTP_${res.status}`; let message = res.statusText; let j: unknown;
    try {
      j = await res.json();
      const o = j as Record<string, unknown>;
      const d = (o.detail && typeof o.detail === 'object' ? o.detail : o) as Record<string, unknown>;
      code = (d.code as string) || code;
      message = (d.message as string) || (typeof o.detail === 'string' ? o.detail : '') || message;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, code, message, j);
  }
  return res.json() as Promise<T>;
}

export interface RoleCheck { check_id: string; dim: string; check_type: string; status: string; summary: string }
export interface RoleChangeResult extends TnBusiness {
  role_change?: { added: TnRole[]; removed: TnRole[]; new_checks: RoleCheck[] };
}

export async function changeRoles(bid: string, version: number, roles: TnRole[]): Promise<RoleChangeResult> {
  if (MOCK) {
    await new Promise((r) => setTimeout(r, 400));
    return { bid, roles, version: version + 1, display_name: '', role_change: { added: roles, removed: [], new_checks: [] } } as unknown as RoleChangeResult;
  }
  return call('PATCH', `/tn/businesses/${encodeURIComponent(bid)}`, { version, roles });
}

export type ContactKind = 'phone' | 'email';
export interface ContactVerifyResult {
  check: { check_id: string; status: string; summary: string };
  contact: { kind: ContactKind; masked: string; declared_match: boolean | null };
  attempts_left?: number;
}

export async function submitContactToken(bid: string, kind: ContactKind, idToken: string): Promise<ContactVerifyResult> {
  return call('POST', `/tn/businesses/${encodeURIComponent(bid)}/contact/verify`, { kind, id_token: idToken });
}

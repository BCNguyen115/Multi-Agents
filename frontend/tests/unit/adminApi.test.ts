import { describe, expect, it } from 'vitest';
import { ORG_ID, diffUser, type AdminUser } from '../../lib/adminApi';

describe('ORG_ID', () => {
  it('takes letters, digits and _ . : - up to 64 characters', () => {
    for (const ok of ['acme', 'tenant_1', 'a.b:c-d', 'A'.repeat(64)]) expect(ORG_ID.test(ok)).toBe(true);
  });

  it('refuses empty ids, spaces, accents and anything longer than 64', () => {
    for (const bad of ['', 'a b', 'phòng-ban', 'a/b', 'A'.repeat(65)]) expect(ORG_ID.test(bad)).toBe(false);
  });
});

const bob: AdminUser = {
  username: 'bob', display_name: 'Bob', roles: ['approver'], tenant_id: 'acme', department_id: 'legal',
  disabled: false, created_at: null, source: 'registered', pending: false,
};

describe('diffUser', () => {
  it('sends nothing when the row is as stored', () => {
    expect(diffUser(bob, { tenant_id: 'acme', department_id: 'legal', roles: ['approver'] })).toEqual({});
  });

  it('sends only the fields that changed', () => {
    expect(diffUser(bob, { tenant_id: 'globex', department_id: 'legal', roles: ['approver'] })).toEqual({ tenant_id: 'globex' });
    expect(diffUser(bob, { tenant_id: 'acme', department_id: 'legal', roles: ['admin', 'approver'] })).toEqual({ roles: ['admin', 'approver'] });
  });

  it('ignores the order of roles and blanks in the scope, and can remove every role', () => {
    expect(diffUser({ ...bob, roles: ['admin', 'approver'] }, { tenant_id: ' acme ', department_id: '', roles: ['approver', 'admin'] })).toEqual({});
    expect(diffUser(bob, { tenant_id: 'acme', department_id: 'legal', roles: [] })).toEqual({ roles: [] });
  });
});

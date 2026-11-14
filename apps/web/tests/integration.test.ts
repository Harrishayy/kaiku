import { test } from 'node:test';
import assert from 'node:assert/strict';
import { credentialFor } from '../lib/credentials.ts';

test('credential routing never lends a clinician token to a personal record or another household',()=>{
  const c={home:'alice',person:'alice-secret',clinician:'clinic-secret',admin:'admin-secret'};
  assert.equal(credentialFor('/v1/me?home_id=alice',c),'alice-secret');
  assert.equal(credentialFor('/v1/me?home_id=bob',c),null);
  assert.equal(credentialFor('/v1/patients/alice/consensus',c),'clinic-secret');
  assert.equal(credentialFor('/v1/admin/criteria',c),'admin-secret');
  assert.equal(credentialFor('/v1/companion/session',c),null);
});

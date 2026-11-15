import { test } from 'node:test';
import assert from 'node:assert/strict';
import { credentialFor } from '../lib/credentials.ts';

test('credential routing never lends a care-team or admin token to a person\'s own routes',()=>{
  const c={clinician:'clinic-secret',admin:'admin-secret'};
  assert.equal(credentialFor('/v1/me?home_id=alice',c),null);
  assert.equal(credentialFor('/v1/memories?home_id=alice',c),null);
  assert.equal(credentialFor('/v1/patients/alice/consensus',c),'clinic-secret');
  assert.equal(credentialFor('/v1/admin/criteria',c),'admin-secret');
  assert.equal(credentialFor('/v1/events?home_id=bob&limit=1000',c),'clinic-secret');
  assert.equal(credentialFor('/v1/eval',c),'clinic-secret');
  assert.equal(credentialFor('/v1/eval',{...c,clinician:null}),'admin-secret');
  assert.equal(credentialFor('/v1/companion/session',c),null);
});

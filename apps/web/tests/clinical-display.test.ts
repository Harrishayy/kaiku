import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clockMinutes, durationMinutes, withUnit } from '../lib/clinician.ts';

test('clinical units distinguish elapsed duration from time of day',()=>{
  assert.equal(durationMinutes(450),'7 h 30 min');
  assert.equal(withUnit(357,'min'),'5 h 57 min');
  assert.equal(withUnit(543,'min after midnight'),'09:03');
  assert.equal(withUnit(241,'min from midnight'),'04:01');
  assert.equal(clockMinutes(1500),'01:00');
  assert.equal(clockMinutes(-15),'23:45');
  assert.equal(withUnit(0.37,'ratio'),'37%');
  assert.equal(withUnit(3964.4,'steps'),'3,964 steps');
  assert.equal(withUnit(415.3,'ms'),'415 ms');
});
test('missing measurements are explicit and zero remains a recorded value',()=>{
  assert.equal(withUnit(null,'min'),'Not recorded');
  assert.equal(withUnit(undefined,'min','Not established'),'Not established');
  assert.equal(withUnit(0,'min'),'0 min');
});

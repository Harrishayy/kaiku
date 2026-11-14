import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clockMinutes, durationMinutes, evidenceRows, usualRange, withUnit } from '../lib/clinician.ts';

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
  assert.equal(usualRange({date:'2026-11-14',value:1} as never,'min',true),'Baseline not established');
  assert.equal(usualRange({date:'2026-11-14',value:450,baseline_median:480,band_low:420,band_high:540} as never,'min',true),'8 h (7 h to 9 h)');
});
test('evidence retains the observation date and formats latest/baseline consistently',()=>{
  const c={sources:[{source:'wearable',verdict:'worse',evidence:[{metric:'sleep',direction:'down',days:3,z:-2}]}]} as never;
  const series=[{metric:'sleep',source:'wearable',label:'Sleep duration',unit:'min',worse_when:'down',points:[{date:'2026-11-13',value:357,baseline_median:450,band_low:400,band_high:500},{date:'2026-11-14',value:null}]}] as never;
  const row=evidenceRows(c,series)[0];
  assert.equal(row.date,'2026-11-13');assert.equal(row.today,'5 h 57 min');
  assert.equal(row.usual,'7 h 30 min (6 h 40 min to 8 h 20 min)');
  assert.equal(row.direction,'Lower on 3 recent days');
});

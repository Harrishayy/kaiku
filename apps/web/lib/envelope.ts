import type { Envelope, MessageType, PayloadByType, Source } from '@contracts';

/** RFC 9562 UUIDv7: 48-bit unix ms timestamp + random. Matches kaiku_contracts.uuid7. */
export function uuidv7(): string {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  const ms = Date.now();
  b[0] = Math.floor(ms / 2 ** 40) & 0xff;
  b[1] = Math.floor(ms / 2 ** 32) & 0xff;
  b[2] = (ms >>> 24) & 0xff;
  b[3] = (ms >>> 16) & 0xff;
  b[4] = (ms >>> 8) & 0xff;
  b[5] = ms & 0xff;
  b[6] = (b[6] & 0x0f) | 0x70; // version 7
  b[8] = (b[8] & 0x3f) | 0x80; // variant
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** UTC ISO-8601 with milliseconds and Z, e.g. 2026-11-14T08:12:03.120Z. */
export function isoMs(d: Date = new Date()): string {
  return d.toISOString();
}

export function makeEnvelope<T extends MessageType>(
  type: T,
  payload: PayloadByType[T],
  opts: { source: Source; homeId: string; sim?: boolean; quality?: number },
): Envelope<PayloadByType[T], T> {
  const env: Envelope<PayloadByType[T], T> = {
    v: 1,
    id: uuidv7(),
    ts: isoMs(),
    home_id: opts.homeId,
    source: opts.source,
    type,
    payload,
    sim: opts.sim ?? false,
  };
  if (opts.quality !== undefined) env.quality = opts.quality;
  return env;
}

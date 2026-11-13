/**
 * The garden (look book "Your days"): one sprout per finished interaction in the last 14 days (GET /v1/me garden).
 * Plants grow in stages; when resting, the last pot shows a bud with a blanket. It never wilts.
 */

function plant(x: number, stage: number, resting: boolean, key: number) {
  const base = <ellipse cx={x} cy={96} rx={15} ry={5} style={{ fill: 'var(--k-mascot-shade)' }} />;
  if (resting)
    return (
      <g key={key}>
        {base}
        <path d={`M${x} 94 v-10`} style={{ stroke: 'var(--k-sage)', strokeWidth: 2.5, strokeLinecap: 'round' }} />
        <ellipse cx={x} cy={82} rx={5} ry={6.5} style={{ fill: 'var(--k-sage)' }} />
        <path d={`M${x - 10} 92 q10 -12 20 0 z`} style={{ fill: 'var(--k-clay-soft)' }} />
      </g>
    );
  const h = [8, 18, 30, 40][stage];
  return (
    <g key={key}>
      {base}
      <path
        d={`M${x} 94 C ${x - 2} ${94 - h / 2} ${x + 2} ${94 - h / 2} ${x} ${94 - h}`}
        style={{ fill: 'none', stroke: 'var(--k-sage)', strokeWidth: 2.5, strokeLinecap: 'round' }}
      />
      <path d={`M${x} ${94 - h * 0.45} q-11 -3 -12 -11 q9 0 12 9 z`} style={{ fill: 'var(--k-sage)' }} />
      {stage >= 1 && <path d={`M${x} ${94 - h * 0.7} q11 -3 12 -11 q-9 0 -12 9 z`} style={{ fill: 'var(--k-sage)' }} />}
      {stage >= 2 && (
        <circle
          cx={x}
          cy={94 - h - 4}
          r={stage === 3 ? 7 : 5}
          style={{ fill: stage === 3 ? 'var(--k-mascot-sparkle)' : 'var(--k-clay-soft)' }}
        />
      )}
    </g>
  );
}

/** Seven pots; `plants` sprouts are spread over them (2 sprouts per stage step), oldest pots fullest. */
export function gardenStages(plants: number, pots = 7): number[] {
  const out: number[] = [];
  let left = Math.max(0, Math.round(plants));
  for (let i = 0; i < pots; i++) {
    const take = Math.min(left, 2 * 3 + 1);
    out.push(take === 0 ? -1 : Math.min(3, Math.floor((take - 1) / 2)));
    left -= take;
  }
  return out;
}

export function Garden({ plants, resting, label }: { plants: number; resting: boolean; label: string }) {
  const stages = gardenStages(plants);
  return (
    <div className="k-garden">
      <svg viewBox="0 0 260 104" role="img" aria-label={label}>
        <path d="M0 98 Q130 88 260 98 V104 H0 Z" style={{ fill: 'var(--k-mascot-shade)', opacity: 0.6 }} />
        {stages.map((s, i) => {
          const x = 22 + i * 36;
          const isLast = i === stages.findLastIndex((v) => v >= 0);
          if (s < 0) return <ellipse key={i} cx={x} cy={96} rx={15} ry={5} style={{ fill: 'var(--k-mascot-shade)' }} />;
          return plant(x, s, resting && isLast, i);
        })}
      </svg>
    </div>
  );
}

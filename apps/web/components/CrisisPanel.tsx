/**
 * Deterministic crisis message (handoff.md section 10). Pre-written, never generated.
 * Text mirrors config/safety_phrases.toml [script].
 */

export const CRISIS_SCRIPT_EN =
  "I'm really glad you told me. I'm going to stop what we're doing. You don't have to handle this alone. " +
  'You can call the MIELI Crisis Helpline any time on 09 2525 0111. If you are in immediate danger, call 112. ' +
  "I'm letting your care team know.";

export const CRISIS_SCRIPT_FI =
  'Olen todella iloinen, että kerroit. Lopetan nyt sen, mitä teimme. Sinun ei tarvitse jäädä tämän kanssa yksin. ' +
  'MIELI ry:n kriisipuhelin päivystää numerossa 09 2525 0111. Jos olet välittömässä vaarassa, soita 112. ' +
  'Ilmoitan hoitotiimillesi.';

export function CrisisPanel({ notified }: { notified: 'sending' | 'sent' | 'failed' | 'idle' }) {
  return (
    <section className="crisis" role="alertdialog" aria-labelledby="crisis-title" aria-describedby="crisis-body" tabIndex={-1}>
      <h2 id="crisis-title">You don’t have to handle this alone</h2>
      <p id="crisis-body">{CRISIS_SCRIPT_EN}</p>
      <p className="crisis-fi" lang="fi">
        {CRISIS_SCRIPT_FI}
      </p>
      <div className="crisis-actions">
        <a className="btn btn-crisis" href="tel:+358925250111">
          Call MIELI Crisis Helpline · 09 2525 0111
          <span className="small">24/7, in Finnish</span>
        </a>
        <a className="btn btn-crisis-outline" href="tel:112">
          Emergency · 112
        </a>
      </div>
      <p className="small">
        {notified === 'sending' && 'Letting your care team know…'}
        {notified === 'sent' && 'Your care team has been notified.'}
        {notified === 'failed' &&
          'We could not reach your care team from here. Please call the numbers above — they are always available.'}
      </p>
    </section>
  );
}

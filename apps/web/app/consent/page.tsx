import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = { title: 'Consent & privacy' };

/** Plain-language privacy and consent (handoff §12). Static: no data is fetched or sent from this page. */
export default function ConsentPage() {
  return (
    <section className="card consent prose" aria-labelledby="consent-title">
      <h1 id="consent-title">What Kaiku collects, and what it never does</h1>
      <p className="lede">
        Kaiku notices how you’re doing compared with <em>your own</em> usual, using three independent sources, and tells your care
        team when a check-in is worth it. Here is exactly what that involves.
      </p>
      <h2>Only numbers leave your devices</h2>
      <ul>
        <li>
          Kaiku sends derived measurements — a dial value, drum tempo, heart-rate variability, minutes outside, reaction time —
          never recordings, photos or video.
        </li>
        <li>Demo data marked SIMULATED is synthetic.</li>
      </ul>
      <h2>The three sources</h2>
      <ul>
        <li>
          <strong>Home robot.</strong> Its camera only finds your face so it can turn towards you: frames are processed in memory,
          never stored or sent, and there is a physical shutter. Voice is streamed to Google’s Gemini Live only during a
          conversation you take part in; no audio or transcripts are stored. Speech pace and pauses are measured locally.
        </li>
        <li>
          <strong>Meta glasses.</strong> The walk companion logs outings, time outdoors and steps. It does not see anything — the
          glasses web app has no camera access.
        </li>
        <li>
          <strong>Laptop.</strong> The optional 2-minute session uses your microphone and (if you allow it) your webcam. Both are
          analysed in your browser while the indicator says “on”; only the resulting numbers are sent. The PHQ-9 questionnaire
          every two weeks is the clinical anchor.
        </li>
      </ul>
      <h2>Who decides what</h2>
      <ul>
        <li>
          A fixed, auditable rule combines the three sources. An AI model (Gemma) only writes a plain-language explanation; it
          never decides your state.
        </li>
        <li>Your care team sees changes from your usual, the evidence behind them, and your questionnaire scores.</li>
        <li>Kaiku does not diagnose and does not replace your clinician.</li>
      </ul>
      <h2>If you’re in crisis</h2>
      <p>
        Kaiku is not a crisis service. If a crisis answer or phrase comes up, Kaiku stops, shows a fixed message with the MIELI
        Crisis Helpline <a href="tel:+358925250111">09 2525 0111</a> (24/7, Finnish) and <a href="tel:112">112</a>, and alerts
        your care team. No AI is involved in that path.
      </p>
      <p className="muted small">
        Research prototype built at Junction 2026. You can stop at any time. <Link href="/session/">Start a session</Link> ·{' '}
        <Link href="/phq9/">PHQ-9</Link>
      </p>
    </section>
  );
}

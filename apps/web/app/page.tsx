import Link from 'next/link';

const SOURCES = [
  { name: 'Home robot', body: 'A 3-minute morning ritual: ear dial for mood, energy and sleep; heart rate and HRV around guided breathing; drumming; speech pace.' },
  { name: 'Glasses', body: 'An audio-first walk companion that logs outings, time outdoors, steps and cadence.' },
  { name: 'Apps', body: 'Phone, Mac and web: short games, an optional 2-minute session, usage rhythm and PHQ-9 every two weeks.' },
  { name: 'Watch', body: 'Optional: sleep, resting heart rate, HRV and steps. Without a watch it simply isn’t counted.' },
];

const PAGES = [
  { href: '/me/', title: 'For the person', body: 'Kaiku, your garden, what helps, what Kaiku remembers and saw today, and pairing your phone.' },
  { href: '/clinician/', title: 'For the clinician', body: 'Who needs a call, with each source’s verdict and the evidence behind it.' },
  { href: '/consent/', title: 'Consent & privacy', body: 'What is measured, where it goes, and what never leaves your devices.' },
];

export default function Home() {
  return (
    <>
      <section className="hero">
        <p className="eyebrow">Kaiku · Finnish for “echo”</p>
        <h1 className="hero-title">Hospitals never judge from one measurement. Neither does Kaiku.</h1>
        <p className="lede">
          After TMS treatment ends, the daily clinic view disappears. Up to four independent sources each compare today with the person’s
          own usual, and a fixed, auditable rule combines them into one consensus — stable, worth a check-in, needs a call, or safety — with the
          evidence shown and disagreement never hidden.
        </p>
      </section>
      <ul className="card-grid" aria-label="The sources">
        {SOURCES.map((s) => (
          <li key={s.name} className="card">
            <h2>{s.name}</h2>
            <p className="muted">{s.body}</p>
          </li>
        ))}
      </ul>
      <h2 style={{ marginTop: 28 }}>Open</h2>
      <ul className="card-grid">
        {PAGES.map((p) => (
          <li key={p.href}>
            <Link className="card card-link" href={p.href}>
              <h2>{p.title}</h2>
              <p className="muted">{p.body}</p>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

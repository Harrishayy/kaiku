import Link from 'next/link';

const SOURCES = [
  { name: 'Home robot', body: 'A 3-minute morning ritual: ear dial for mood, energy and sleep; heart rate and HRV around guided breathing; drumming; speech pace.' },
  { name: 'Meta glasses', body: 'An audio-first walk companion that logs outings, time outdoors and steps.' },
  { name: 'Laptop', body: 'An optional 2-minute session (voice, expressivity, reaction time) and PHQ-9 every two weeks.' },
];

const PAGES = [
  { href: '/clinician/', title: 'Clinician dashboard', body: 'Who needs a call, with each source’s verdict and the evidence behind it.' },
  { href: '/me/', title: 'My week', body: 'The person’s own view, in plain language, and what has helped.' },
  { href: '/session/', title: 'Laptop session', body: 'Two minutes: speak, then a reaction game. Analysed in the browser.' },
  { href: '/phq9/', title: 'PHQ-9', body: 'The standard questionnaire every 14 days — the clinical anchor.' },
  { href: '/live/', title: 'Live', body: 'What the robot just sensed — derived numbers only.' },
  { href: '/eval/', title: 'Evaluation', body: 'Simulation on synthetic patients: precision, lead time, losing one source.' },
  { href: '/tune/', title: 'Tune the consensus', body: 'Admin: edit criteria, preview who would change state, apply live, export TOML.' },
  { href: '/health/', title: 'System health', body: 'Heartbeats from every node, uplink queue and last errors.' },
  { href: '/consent/', title: 'Consent & privacy', body: 'What is measured, where it goes, and what never leaves your devices.' },
];

export default function Home() {
  return (
    <>
      <section className="hero">
        <p className="eyebrow">Kaiku · Finnish for “echo”</p>
        <h1 className="hero-title">Hospitals never judge from one measurement. Neither does Kaiku.</h1>
        <p className="lede">
          After TMS treatment ends, the daily clinic view disappears. Three independent sources each compare today with the person’s
          own usual, and a fixed, auditable rule combines them into one consensus — stable, watch, needs a call, or safety — with the
          evidence shown and disagreement never hidden.
        </p>
      </section>
      <ul className="card-grid" aria-label="The three sources">
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

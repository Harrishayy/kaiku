/** Line icons from the look book (24 × 24, 1.8 stroke, currentColor). Decorative: always aria-hidden. */

const P: Record<string, string> = {
  chev: '<path d="M9 6l6 6-6 6"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>',
  breathe: '<path d="M4 12c3-5 13-5 16 0-3 5-13 5-16 0Z"/><circle cx="12" cy="12" r="2"/>',
  memory: '<path d="M12 4a5 5 0 0 0-5 5c0 2 1 3 1 5h8c0-2 1-3 1-5a5 5 0 0 0-5-5zM9.5 18h5M10.5 21h3"/>',
  receipt: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6"/>',
  play: '<path d="M12 3.5l2.1 5.3 5.4.3-4.2 3.5 1.4 5.4L12 15l-4.7 3 1.4-5.4-4.2-3.5 5.4-.3z"/>',
  leaf: '<path d="M5 19c0-8 5-14 14-14 0 9-6 14-14 14zM5 19l7-7"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7"/>',
  phone: '<rect x="7" y="3" width="10" height="18" rx="2.5"/><path d="M11 18h2"/>',
  robot: '<circle cx="12" cy="13" r="7"/><circle cx="9.5" cy="12.5" r="1"/><circle cx="14.5" cy="12.5" r="1"/><path d="M15 6c1-2 3-2.5 4-1.5"/>',
  glasses: '<circle cx="7" cy="14" r="3.5"/><circle cx="17" cy="14" r="3.5"/><path d="M10.5 14h3M3.5 13l1-5M20.5 13l-1-5"/>',
  watch: '<rect x="7" y="6" width="10" height="12" rx="3"/><path d="M9 6l1-3h4l1 3M9 18l1 3h4l1-3M12 10v2l1.5 1"/>',
  mac: '<rect x="3" y="5" width="18" height="11" rx="1.5"/><path d="M2 19h20"/>',
  heart: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
};

export type IconName = keyof typeof P;

export function Icon({ name, size }: { name: IconName; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      dangerouslySetInnerHTML={{ __html: P[name] }}
    />
  );
}

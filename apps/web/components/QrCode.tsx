import { qrPath } from '@/lib/qr.ts';

/** Always dark-on-white (scanners need the contrast), in both themes. */
export function QrCode({ text, label }: { text: string; label: string }) {
  const { size, d } = qrPath(text);
  return (
    <div className="k-qr">
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} shapeRendering="crispEdges">
        <rect width={size} height={size} fill="#ffffff" />
        <path d={d} fill="#2a211c" />
      </svg>
    </div>
  );
}

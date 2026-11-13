/** QR code as one SVG path (pure; rendered client-side, the link never leaves the page). */
import qrcode from 'qrcode-generator';

export function qrPath(text: string, margin = 2): { size: number; d: string } {
  const qr = qrcode(0, 'M');
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  let d = '';
  for (let r = 0; r < n; r++)
    for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c + margin} ${r + margin}h1v1h-1z`;
  return { size: n + margin * 2, d };
}

/** The pairing link a phone or Mac opens (same `?home=&t=` format the care team hands out). */
export function pairingUrl(origin: string, homeId: string, token: string | null): string {
  const u = new URL('/me/', origin);
  u.searchParams.set('home', homeId);
  if (token) u.searchParams.set('t', token);
  return u.toString();
}

import SwiftUI

/// Kaiku reduced to a high-contrast glyph for the tiny Dynamic Island slots (compact / minimal) and Lock Screen
/// accessories, where the full mascot's details would be lost: the round body, the one floppy ear, two big eyes,
/// plus one bold state cue — feet mid-stride (walking), "z z" (sleepy), a breathing ring (breathing), the scarf
/// (cozy). Light body on the black island.
public struct KaikuGlyph: View {
    let state: MascotState
    let size: CGFloat
    var phase: Double = 0     // 0…1: stride / breath (static frames in widgets)
    var tint: Color = KaikuTokens.Colors.mascotBody

    public init(state: MascotState, size: CGFloat = 24, phase: Double = 0, tint: Color = KaikuTokens.Colors.mascotBody) {
        self.state = state; self.size = size; self.phase = phase; self.tint = tint
    }

    public var body: some View {
        Canvas { ctx, sz in
            let s = min(sz.width, sz.height)
            let eye = Color.black
            let walking = state == .walking
            let bw = s * (state == .breathing ? 0.66 + 0.06 * phase : 0.78)
            let bh = bw * 0.80
            let cx = s * 0.47
            let cy = walking ? s * 0.50 - s * 0.03 * phase : s * 0.60
            if state == .breathing {
                let r = s * 0.47
                ctx.stroke(Path(ellipseIn: CGRect(x: s / 2 - r, y: s / 2 - r, width: 2 * r, height: 2 * r)),
                           with: .color(KaikuTokens.Colors.sage), lineWidth: max(1.6, s * 0.07))
            }
            // the floppy ear (top right, flopping outwards)
            let ear = Path(ellipseIn: CGRect(x: -bw * 0.1, y: -bh * 0.27, width: bw * 0.2, height: bh * 0.54))
            let earT = CGAffineTransform(translationX: cx + bw * 0.3, y: cy - bh * 0.5).rotated(by: .pi / 3.2)
            ctx.fill(ear.applying(earT), with: .color(tint))
            // body
            ctx.fill(Path(ellipseIn: CGRect(x: cx - bw / 2, y: cy - bh / 2, width: bw, height: bh)), with: .color(tint))
            // eyes (closed curves when sleepy / breathing)
            let ey = cy - bh * 0.06
            for dir in [-1.0, 1.0] {
                let ex = cx + CGFloat(dir) * bw * 0.17
                if state == .sleepy || state == .breathing {
                    var l = Path()
                    l.move(to: CGPoint(x: ex - bw * 0.08, y: ey))
                    l.addQuadCurve(to: CGPoint(x: ex + bw * 0.08, y: ey), control: CGPoint(x: ex, y: ey + bw * 0.08))
                    ctx.stroke(l, with: .color(eye), style: StrokeStyle(lineWidth: max(1.3, s * 0.055), lineCap: .round))
                } else {
                    let r = bw * 0.075
                    ctx.fill(Path(ellipseIn: CGRect(x: ex - r, y: ey - r * 1.2, width: 2 * r, height: 2.4 * r)), with: .color(eye))
                }
            }
            if state == .cozy {
                let band = CGRect(x: cx - bw * 0.36, y: cy + bh * 0.27, width: bw * 0.72, height: bh * 0.16)
                ctx.fill(Path(roundedRect: band, cornerRadius: band.height / 2), with: .color(KaikuTokens.Colors.mascotScarf))
            }
            if walking {
                // two feet mid-stride
                let fy = cy + bh * 0.48
                for (dx, lift) in [(-0.2, phase), (0.2, 1 - phase)] {
                    let fw = bw * 0.26, fh = bh * 0.22
                    let r = CGRect(x: cx + CGFloat(dx) * bw - fw / 2 + CGFloat(lift - 0.5) * bw * 0.12,
                                   y: fy - CGFloat(lift) * fh * 0.5, width: fw, height: fh)
                    ctx.fill(Path(ellipseIn: r), with: .color(tint))
                }
            }
            if state == .sleepy {
                let z = KaikuTokens.Colors.sky
                ctx.draw(Text("z").font(.system(size: s * 0.30, weight: .heavy, design: .rounded)).foregroundStyle(z),
                         at: CGPoint(x: s * 0.86, y: s * 0.30))
                ctx.draw(Text("z").font(.system(size: s * 0.20, weight: .heavy, design: .rounded)).foregroundStyle(z),
                         at: CGPoint(x: s * 0.96, y: s * 0.10))
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

import SwiftUI

/// The completion moment (design/motion.md: slow, soft, springy; nothing flashes): when a task, game, walk or
/// check-in finishes, a handful of soft sparks rise and fade over ~1.4 s, and never a
/// flash. It never blocks touches and never shows a number. Reduce Motion: no sparks, a single quiet badge that
/// fades in and out. Never on the crisis screen.
struct CelebrationModifier: ViewModifier {
    let trigger: Int
    let enabled: Bool
    @State private var started: Date?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static let duration = KaikuTokens.Duration.slow * 2

    func body(content: Content) -> some View {
        content
            .overlay {
                if let started, enabled {
                    Group {
                        if reduceMotion { CelebrationBadge() } else { CelebrationSparks(started: started) }
                    }
                    .transition(.opacity)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
                }
            }
            .onChange(of: trigger) { _, _ in
                guard enabled else { return }
                let now = Date()
                withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { started = now }
                Task { @MainActor in
                    try? await Task.sleep(nanoseconds: UInt64(Self.duration * 1_000_000_000))
                    guard started == now else { return }
                    withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base)) { started = nil }
                }
            }
    }
}

/// Sparks: deterministic per celebration (seeded by the start time), drawn in one Canvas.
struct CelebrationSparks: View {
    let started: Date
    static let colors: [Color] = [KaikuTokens.Colors.mascotSparkle, KaikuTokens.Colors.honey, KaikuTokens.Colors.clay, KaikuTokens.Colors.sage]

    struct Spark { let x: Double; let delay: Double; let rise: Double; let drift: Double; let size: Double; let color: Int }

    static func sparks(seed: UInt64, count: Int = 18) -> [Spark] {
        var g = SplitMix(seed: seed)
        return (0..<count).map { _ in
            Spark(x: 0.12 + 0.76 * g.unit(), delay: 0.35 * g.unit(), rise: 0.28 + 0.3 * g.unit(),
                  drift: (g.unit() - 0.5) * 0.12, size: 5 + 7 * g.unit(), color: Int(g.unit() * 4) % 4)
        }
    }

    var body: some View {
        let sparks = Self.sparks(seed: UInt64(abs(started.timeIntervalSinceReferenceDate) * 1000))
        TimelineView(.animation) { tl in
            Canvas { ctx, size in
                let t = tl.date.timeIntervalSince(started) / CelebrationModifier.duration
                for s in sparks {
                    let p = min(1, max(0, (t - s.delay) / (1 - s.delay)))
                    guard p > 0, p < 1 else { continue }
                    let eased = 1 - pow(1 - p, 3)                       // gentle-out
                    let x = (s.x + s.drift * eased) * size.width
                    let y = size.height * (0.78 - s.rise * eased)
                    let alpha = sin(p * .pi) * 0.85                     // fades in and out, never a flash
                    let r = s.size * (0.6 + 0.4 * sin(p * .pi))
                    ctx.opacity = alpha
                    ctx.fill(Self.star(center: CGPoint(x: x, y: y), radius: r), with: .color(Self.colors[s.color]))
                }
            }
        }
    }

    /// A soft four-point spark (the mascot's sparkle shape).
    static func star(center c: CGPoint, radius r: Double) -> Path {
        var p = Path()
        let inner = r * 0.38
        for i in 0..<8 {
            let a = Double(i) * .pi / 4 - .pi / 2
            let rr = i % 2 == 0 ? r : inner
            let pt = CGPoint(x: c.x + cos(a) * rr, y: c.y + sin(a) * rr)
            if i == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
        }
        p.closeSubpath()
        return p
    }
}

struct CelebrationBadge: View {
    var body: some View {
        Image(systemName: "checkmark.circle.fill")
            .font(.system(size: KaikuTokens.Space.s7))
            .foregroundStyle(KaikuTokens.Colors.sage)
            .padding(KaikuTokens.Space.s4)
            .background(Circle().fill(KaikuTokens.Colors.surface))
    }
}

/// Tiny deterministic generator, so a celebration looks the same in a test and on screen.
struct SplitMix {
    var state: UInt64
    init(seed: UInt64) { state = seed &+ 0x9E37_79B9_7F4A_7C15 }
    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }
    mutating func unit() -> Double { Double(next() >> 11) / Double(1 << 53) }
}

extension View {
    /// Plays the completion moment each time `trigger` changes.
    func kCelebration(_ trigger: Int, enabled: Bool = true) -> some View {
        modifier(CelebrationModifier(trigger: trigger, enabled: enabled))
    }
}

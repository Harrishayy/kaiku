import SwiftUI

/// Pebble path (Corsi block span). Kaiku hops across 9 pebbles; then you tap the same pebbles in the same order.
/// Starts at 2, adds 1 per success (max 9), ends after 2 misses. Records span_max, accuracy (correct taps / taps),
/// duration. The end draws the longest path as art.
public struct PebbleGame: View {
    @State private var bestPath: [Int] = []
    public init() {}
    public var body: some View {
        GameShell(titleKey: "game.pebbles.t", introText: T("pb.intro"), introState: .idle, endText: T("pb.end"),
                  field: { finish in PebbleField { s, path in bestPath = path; finish(s) } },
                  endArt: { PathArt(path: bestPath).frame(height: 170).padding(.horizontal) })
    }
}

/// Pure game logic (unit-tested).
public struct PebbleEngine: Sendable {
    public static let count = 9
    public static let maxMisses = 2
    public var length = 2
    public var sequence: [Int] = []
    public var entered: [Int] = []
    public var misses = 0
    public var spanMax = 0
    public var bestPath: [Int] = []
    public var taps = 0
    public var correctTaps = 0
    public var over = false

    public init() {}

    public mutating func newRound<R: RandomNumberGenerator>(using rng: inout R) {
        var pool = Array(0..<Self.count)
        pool.shuffle(using: &rng)
        sequence = Array(pool.prefix(length))
        entered = []
    }

    public enum TapResult: Equatable { case good, roundDone, miss, ignored }

    public mutating func tap(_ pebble: Int) -> TapResult {
        guard !over, entered.count < sequence.count else { return .ignored }
        taps += 1
        if sequence[entered.count] == pebble {
            correctTaps += 1
            entered.append(pebble)
            if entered.count == sequence.count {
                if length > spanMax { spanMax = length; bestPath = sequence }
                if length >= Self.count { over = true } else { length += 1 }
                return .roundDone
            }
            return .good
        }
        misses += 1
        if misses >= Self.maxMisses { over = true }
        return .miss
    }

    public var accuracy: Double { taps == 0 ? 0 : Double(correctTaps) / Double(taps) }
}

/// Fixed pebble spots in a pond (0..1 coordinates), loosely scattered like stepping stones.
let pebbleSpots: [CGPoint] = [
    CGPoint(x: 0.16, y: 0.20), CGPoint(x: 0.50, y: 0.13), CGPoint(x: 0.83, y: 0.24),
    CGPoint(x: 0.28, y: 0.47), CGPoint(x: 0.63, y: 0.43), CGPoint(x: 0.88, y: 0.58),
    CGPoint(x: 0.13, y: 0.76), CGPoint(x: 0.45, y: 0.80), CGPoint(x: 0.76, y: 0.86),
]

struct PebbleField: View {
    let finish: (PlaySession?, [Int]) -> Void
    enum Mode { case watching, yourTurn, feedback }
    @State private var engine = PebbleEngine()
    @State private var mode: Mode = .watching
    @State private var lit: Int?
    @State private var kaikuAt: Int?
    @State private var message = T("pb.watch")
    @State private var started = Date()
    @State private var rng = SystemRandomNumberGenerator()
    @Environment(\.accessibilityReduceMotion) private var rm

    var body: some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            Text(message).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentTransition(.opacity)
                .accessibilityAddTraits(.updatesFrequently)
            GeometryReader { geo in
                let s = geo.size
                let d = min(s.width, s.height) * 0.17
                ZStack {
                    RoundedRectangle(cornerRadius: KaikuTokens.Radius.xl, style: .continuous)
                        .fill(KaikuTokens.Colors.skySoft)
                    ForEach(0..<PebbleEngine.count, id: \.self) { i in
                        let p = CGPoint(x: pebbleSpots[i].x * s.width, y: pebbleSpots[i].y * s.height)
                        let on = lit == i || (mode != .watching && engine.entered.contains(i))
                        Button { tap(i) } label: {
                            Ellipse()
                                .fill(on ? KaikuTokens.Colors.honey : KaikuTokens.Colors.mascotShade)
                                .overlay(Ellipse().strokeBorder(KaikuTokens.Colors.mascotOutline, lineWidth: 2))
                                .frame(width: d * 1.25, height: d)
                                .frame(minWidth: 44, minHeight: 44)
                                .contentShape(Ellipse())
                                .scaleEffect(lit == i && !rm ? 1.08 : 1)
                        }
                        .buttonStyle(.plain)
                        .disabled(mode != .yourTurn)
                        .position(p)
                        .accessibilityLabel(T("a11y.pebble", n: i + 1))
                    }
                    if let k = kaikuAt {
                        MascotView(state: .happy, size: d * 1.3, tappable: false)
                            .position(x: pebbleSpots[k].x * s.width, y: pebbleSpots[k].y * s.height - d * 0.55)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                    }
                }
                .animation(rm ? nil : KaikuTokens.Spring.gentle, value: kaikuAt)
                .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast), value: lit)
            }
            .frame(minHeight: 260)
        }
        .task { await playRound() }
    }

    private func playRound() async {
        engine.newRound(using: &rng)
        mode = .watching
        message = T("pb.watch")
        try? await Task.sleep(nanoseconds: 700_000_000)
        for p in engine.sequence {
            kaikuAt = p
            lit = p
            try? await Task.sleep(nanoseconds: 650_000_000)
            lit = nil
            try? await Task.sleep(nanoseconds: 250_000_000)
        }
        kaikuAt = nil
        mode = .yourTurn
        message = T("pb.yourturn")
    }

    private func tap(_ i: Int) {
        let r = engine.tap(i)
        lit = i
        Task {
            try? await Task.sleep(nanoseconds: 250_000_000)
            if lit == i { lit = nil }
        }
        switch r {
        case .good, .ignored: break
        case .roundDone, .miss:
            mode = .feedback
            message = r == .miss ? T("pb.oops") : T("pb.nice")
            if r == .miss { Haptics.dialStep() }
            Task {
                try? await Task.sleep(nanoseconds: 1_100_000_000)
                if engine.over { end() } else { await playRound() }
            }
        }
    }

    private func end() {
        var s = PlaySession(game: .pebbles, device: KaikuPlatform.device, duration_s: Date().timeIntervalSince(started))
        s.span_max = engine.spanMax
        s.accuracy = engine.accuracy
        finish(s, engine.bestPath)
    }
}

/// End art: the longest path drawn as a soft line between pebbles.
struct PathArt: View {
    let path: [Int]
    var body: some View {
        Canvas { ctx, size in
            for (i, spot) in pebbleSpots.enumerated() {
                let p = CGPoint(x: spot.x * size.width, y: spot.y * size.height)
                let on = path.contains(i)
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 14, y: p.y - 10, width: 28, height: 20)),
                         with: .color(on ? KaikuTokens.Colors.honey : KaikuTokens.Colors.mascotShade.opacity(0.6)))
            }
            guard path.count > 1 else { return }
            var line = Path()
            for (k, i) in path.enumerated() {
                let p = CGPoint(x: pebbleSpots[i].x * size.width, y: pebbleSpots[i].y * size.height)
                if k == 0 { line.move(to: p) } else { line.addLine(to: p) }
            }
            ctx.stroke(line, with: .color(KaikuTokens.Colors.clay),
                       style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round, dash: [2, 7]))
        }
        .accessibilityHidden(true)
    }
}

import SwiftUI

/// Pebble path (Corsi block span) on the pond. Kaiku hops across the shown pebbles (each lights in the glow colour
/// with a rising note); then you tap the same pebbles in the same order. A right pebble ripples and sings the next
/// note up and Kaiku hops onto it; a wrong one shakes gently — "Let's try that one again". Starts at 2, adds 1 per
/// success (max 9), ends after 2 misses. Records span_max, accuracy (correct taps / taps), duration. The end draws
/// the longest path as art. Mac: digits 1–9, or arrows + Space.
public struct PebbleGame: View {
    @State private var bestPath: [Int] = []
    public init() {}
    public var body: some View {
        GameShell(titleKey: "game.pebbles.t", scene: .pond, introText: T("pb.intro"), introState: .idle, endText: T("pb.end"),
                  demo: { PebbleDemo() },
                  field: { finish in PebbleField { s, path in bestPath = path; finish(s) } },
                  endArt: { PathArt(path: bestPath).frame(width: 170, height: 130) })
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

/// Fixed pebble spots in a pond (0..1 coordinates), loosely scattered like stepping stones (reading order = 1…9).
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
    @State private var pressed: Int?
    @State private var shaking: Int?
    @State private var shakeAt = Date.distantPast
    @State private var ripples: [(id: UUID, i: Int, at: Date)] = []
    @State private var hop = Hop(from: 4, to: 4, at: .distantPast)
    @State private var message = T("pb.watch")
    @State private var cheer = false
    @State private var started = Date()
    @State private var rng = SystemRandomNumberGenerator()
    @State private var keyFocus: Int?
    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var rm

    struct Hop { var from: Int; var to: Int; var at: Date }

    var body: some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            // Whose turn it is, in a quiet pill (no score). Progress = the path length dots under it.
            HStack(spacing: KaikuTokens.Space.s2) {
                Text(message).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    .contentTransition(.opacity)
                    .accessibilityAddTraits(.updatesFrequently)
                HStack(spacing: 4) {
                    ForEach(0..<max(engine.sequence.count, 1), id: \.self) { k in
                        Circle().fill(k < engine.entered.count ? KaikuTokens.Colors.sage : KaikuTokens.Colors.pebbleEdge.opacity(0.6))
                            .frame(width: 7, height: 7)
                    }
                }
                .opacity(mode == .watching ? 0 : 1)
                .accessibilityHidden(true)
            }
            .padding(.horizontal, KaikuTokens.Space.s4)
            .padding(.vertical, KaikuTokens.Space.s2)
            .background(Capsule().fill(KaikuTokens.Colors.surface.opacity(0.85)))
            .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast), value: message)

            GeometryReader { geo in
                let s = geo.size
                let d = max(46, min(min(s.width, s.height) * 0.16, 86))
                TimelineView(.animation(minimumInterval: 1.0 / 60)) { tl in
                    let now = tl.date
                    ZStack {
                        ForEach(0..<PebbleEngine.count, id: \.self) { i in
                            pebble(i, size: d, now: now)
                                .position(x: pebbleSpots[i].x * s.width, y: pebbleSpots[i].y * s.height)
                        }
                        ForEach(ripples, id: \.id) { r in
                            let k = min(1, now.timeIntervalSince(r.at) / 0.7)
                            Ellipse().strokeBorder(KaikuTokens.Colors.surface.opacity(0.9 * (1 - k)), lineWidth: 2)
                                .frame(width: d * (1.2 + 1.1 * k), height: d * (0.8 + 0.75 * k))
                                .position(x: pebbleSpots[r.i].x * s.width, y: pebbleSpots[r.i].y * s.height + 4)
                                .allowsHitTesting(false)
                        }
                        kaiku(size: d * 1.05, field: s, pebble: d, now: now)
                    }
                }
            }
        }
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(phases: .down) { press in handleKey(press) }
        .task { focused = true; KSound.warmUp([.note(0), .note(1), .note(2), .wobble]); await playRound() }
    }

    // MARK: drawing

    @ViewBuilder private func pebble(_ i: Int, size d: CGFloat, now: Date) -> some View {
        let isLit = lit == i
        let isPressed = pressed == i
        let shakeT = now.timeIntervalSince(shakeAt)
        let dx: CGFloat = (shaking == i && shakeT < 0.45 && !rm) ? CGFloat(sin(shakeT * 42) * 7 * (1 - shakeT / 0.45)) : 0
        let tilt = Double((i * 29) % 17) - 8
        Button { tap(i) } label: {
            ZStack {
                if isLit {
                    Ellipse().fill(KaikuTokens.glowColor.opacity(0.55)).blur(radius: 12)
                        .frame(width: d * 1.7, height: d * 1.2)
                }
                PebbleShape()
                    .fill(isLit ? KaikuTokens.glowColor : (shaking == i && shakeT < 0.6 ? KaikuTokens.Colors.honeySoft : KaikuTokens.Colors.pebble))
                    .overlay(PebbleShape().stroke(isLit ? KaikuTokens.Colors.mascotSparkle : KaikuTokens.Colors.pebbleEdge, lineWidth: 2))
                    .overlay(alignment: .topLeading) {
                        Ellipse().fill(Color.white.opacity(0.35)).frame(width: d * 0.4, height: d * 0.14)
                            .offset(x: d * 0.18, y: d * 0.1)
                    }
                    .frame(width: d * 1.3, height: d * 0.9)
                    .shadow(color: KaikuTokens.Colors.ink.opacity(isPressed ? 0.05 : 0.14), radius: isPressed ? 1 : 4, y: isPressed ? 1 : 3)
                    .rotationEffect(.degrees(tilt))
                if keyFocus == i {
                    PebbleShape().stroke(KaikuTokens.Colors.focus, lineWidth: 3)
                        .frame(width: d * 1.45, height: d * 1.02).rotationEffect(.degrees(tilt))
                }
            }
            .frame(width: max(44, d * 1.4), height: max(44, d * 1.1))
            .scaleEffect(isPressed && !rm ? 0.92 : (isLit && !rm ? 1.06 : 1))
            .offset(x: dx)
            .contentShape(Ellipse())
            .animation(.easeOut(duration: 0.12), value: isPressed)
            .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast), value: isLit)
        }
        .buttonStyle(PebblePress(index: i, pressed: $pressed))
        .disabled(mode != .yourTurn)
        .kPointer(mode == .yourTurn)
        .accessibilityLabel(T("a11y.pebble", n: i + 1))
    }

    /// Kaiku hops along an arc from pebble to pebble (450 ms, soft-in-out), landing with a little squash.
    private func kaiku(size: CGFloat, field s: CGSize, pebble d: CGFloat, now: Date) -> some View {
        let k = rm ? 1 : min(1, max(0, now.timeIntervalSince(hop.at) / 0.45))
        let e = KaikuCurve.ease("soft-in-out", k)
        let a = pebbleSpots[hop.from], b = pebbleSpots[hop.to]
        let x = (a.x + (b.x - a.x) * e) * s.width
        let y = (a.y + (b.y - a.y) * e) * s.height - d * 0.5 - (hop.from == hop.to ? 0 : sin(.pi * e) * d * 0.9)
        let squash = k >= 1 && now.timeIntervalSince(hop.at) < 0.6 && !rm ? 0.92 : 1
        return MascotView(state: cheer ? .happy : (mode == .watching ? .idle : .listening), size: size, tappable: false)
            .scaleEffect(x: 2 - squash, y: squash, anchor: .bottom)
            .position(x: x, y: y)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }

    // MARK: flow

    private func hopTo(_ i: Int) {
        hop = Hop(from: hop.to, to: i, at: Date())
    }

    private func playRound() async {
        engine.newRound(using: &rng)
        mode = .watching
        message = T("pb.watch")
        cheer = false
        try? await Task.sleep(nanoseconds: 700_000_000)
        for (k, p) in engine.sequence.enumerated() {
            hopTo(p)
            try? await Task.sleep(nanoseconds: 300_000_000)
            lit = p
            KSound.play(.note(k))
            try? await Task.sleep(nanoseconds: 450_000_000)
            lit = nil
            try? await Task.sleep(nanoseconds: 150_000_000)
        }
        mode = .yourTurn
        message = T("pb.yourturn")
        focused = true
    }

    private func tap(_ i: Int) {
        guard mode == .yourTurn else { return }
        let r = engine.tap(i)
        switch r {
        case .good, .roundDone:
            hopTo(i)
            lit = i
            ripples.append((UUID(), i, Date()))
            KSound.play(.note(engine.entered.count - 1))
            Haptics.catchFirefly()
            Task {
                try? await Task.sleep(nanoseconds: 320_000_000)
                if lit == i { lit = nil }
                ripples.removeAll { Date().timeIntervalSince($0.at) > 0.8 }
            }
        case .miss:
            shaking = i
            shakeAt = Date()
            KSound.play(.wobble)
            Haptics.softTap()
        case .ignored: return
        }
        guard r == .roundDone || r == .miss else { return }
        mode = .feedback
        cheer = r == .roundDone
        withAnimation { message = r == .miss ? T("pb.oops") : T("pb.nice") }
        Task {
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            shaking = nil
            if engine.over { end() } else { await playRound() }
        }
    }

    private func handleKey(_ press: KeyPress) -> KeyPress.Result {
        if let n = Int(press.characters), (1...9).contains(n) { keyFocus = n - 1; tap(n - 1); return .handled }
        let cur = keyFocus ?? 4
        func nearest(_ dx: CGFloat, _ dy: CGFloat) -> Int {
            let p = pebbleSpots[cur]
            let cands = pebbleSpots.indices.filter { $0 != cur }.filter {
                let v = CGPoint(x: pebbleSpots[$0].x - p.x, y: pebbleSpots[$0].y - p.y)
                return v.x * dx + v.y * dy > 0.05
            }
            return cands.min { a, b in
                let va = hypot(pebbleSpots[a].x - p.x, pebbleSpots[a].y - p.y)
                let vb = hypot(pebbleSpots[b].x - p.x, pebbleSpots[b].y - p.y)
                return va < vb
            } ?? cur
        }
        switch press.key {
        case .leftArrow: keyFocus = nearest(-1, 0)
        case .rightArrow: keyFocus = nearest(1, 0)
        case .upArrow: keyFocus = nearest(0, -1)
        case .downArrow: keyFocus = nearest(0, 1)
        case .space, .return: if let f = keyFocus { tap(f) } else { keyFocus = 4 }
        default: return .ignored
        }
        return .handled
    }

    private func end() {
        var s = PlaySession(game: .pebbles, device: KaikuPlatform.device, duration_s: Date().timeIntervalSince(started))
        s.span_max = engine.spanMax
        s.accuracy = engine.accuracy
        finish(s, engine.bestPath)
    }
}

/// Reports the press state to the field (so the pebble can sink under the finger).
private struct PebblePress: ButtonStyle {
    let index: Int
    @Binding var pressed: Int?
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .onChange(of: configuration.isPressed) { _, p in
                if p { pressed = index } else if pressed == index { pressed = nil }
            }
    }
}

/// A lumpy stepping stone (not a perfect ellipse), like the artifact's `.pebble` radius.
struct PebbleShape: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        let w = r.width, h = r.height
        p.move(to: CGPoint(x: r.minX + w * 0.5, y: r.minY))
        p.addCurve(to: CGPoint(x: r.maxX, y: r.minY + h * 0.48), control1: CGPoint(x: r.minX + w * 0.82, y: r.minY), control2: CGPoint(x: r.maxX, y: r.minY + h * 0.18))
        p.addCurve(to: CGPoint(x: r.minX + w * 0.52, y: r.maxY), control1: CGPoint(x: r.maxX, y: r.minY + h * 0.82), control2: CGPoint(x: r.minX + w * 0.8, y: r.maxY))
        p.addCurve(to: CGPoint(x: r.minX, y: r.minY + h * 0.52), control1: CGPoint(x: r.minX + w * 0.2, y: r.maxY), control2: CGPoint(x: r.minX, y: r.minY + h * 0.84))
        p.addCurve(to: CGPoint(x: r.minX + w * 0.5, y: r.minY), control1: CGPoint(x: r.minX, y: r.minY + h * 0.2), control2: CGPoint(x: r.minX + w * 0.2, y: r.minY))
        p.closeSubpath()
        return p
    }
}

/// End art: the longest path as a dotted line between glowing pebbles.
struct PathArt: View {
    let path: [Int]
    var body: some View {
        Canvas { ctx, size in
            if path.count > 1 {
                var line = Path()
                for (k, i) in path.enumerated() {
                    let p = CGPoint(x: pebbleSpots[i].x * size.width, y: pebbleSpots[i].y * size.height)
                    if k == 0 { line.move(to: p) } else { line.addLine(to: p) }
                }
                ctx.stroke(line, with: .color(KaikuTokens.Colors.muted),
                           style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round, dash: [4, 5]))
            }
            for (i, spot) in pebbleSpots.enumerated() {
                let p = CGPoint(x: spot.x * size.width, y: spot.y * size.height)
                let on = path.contains(i)
                let r = CGRect(x: p.x - 11, y: p.y - 7, width: 22, height: 14)
                ctx.fill(Path(ellipseIn: r), with: .color(on ? KaikuTokens.glowColor : KaikuTokens.Colors.pebble.opacity(0.6)))
                ctx.stroke(Path(ellipseIn: r), with: .color(KaikuTokens.Colors.mascotOutline), lineWidth: 1.5)
            }
        }
        .accessibilityHidden(true)
    }
}

/// Intro demo: three pebbles light in turn as Kaiku hops (watch), then a tap ring follows the same order (you).
struct PebbleDemo: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    let spots = [CGPoint(x: 0.2, y: 0.62), CGPoint(x: 0.5, y: 0.36), CGPoint(x: 0.8, y: 0.6)]
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: rm)) { tl in
            let t = rm ? 0.5 : tl.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 4.8)
            GeometryReader { g in
                let w = g.size.width, h = g.size.height
                let watch = t < 2.4
                let step = min(2, Int((watch ? t : t - 2.4) / 0.8))
                ZStack {
                    LinearGradient(colors: [KaikuTokens.Colors.pondA, KaikuTokens.Colors.pondB], startPoint: .top, endPoint: .bottom)
                        .clipShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.xl, style: .continuous))
                    ForEach(0..<3, id: \.self) { i in
                        PebbleShape().fill(i == step ? KaikuTokens.glowColor : KaikuTokens.Colors.pebble)
                            .overlay(PebbleShape().stroke(KaikuTokens.Colors.pebbleEdge, lineWidth: 2))
                            .frame(width: 54, height: 36)
                            .position(x: spots[i].x * w, y: spots[i].y * h)
                    }
                    let p = spots[step]
                    if watch {
                        MascotView(state: .idle, size: 50, tappable: false)
                            .position(x: p.x * w, y: p.y * h - 30)
                    } else {
                        Image(systemName: KaikuPlatform.isPhone ? "hand.point.up.left.fill" : "cursorarrow")
                            .font(.system(size: 22)).foregroundStyle(KaikuTokens.Colors.ink)
                            .position(x: p.x * w + 12, y: p.y * h + 16)
                    }
                }
            }
        }
        .accessibilityHidden(true)
    }
}

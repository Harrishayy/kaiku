import SwiftUI

/// Firefly (go/no-go, 60 s) in the night scene. Fireflies glow for 1.5 s: tap them (or press Space on Mac) and
/// they burst, chime and fly into the jar. Moths drift: tapping one gives a gentle wobble and a soft puff, never a
/// red error. A missed firefly fades with a tiny trail. Records reaction median + IQR (correct taps), lapses
/// (missed or slower than the contract's 500 ms) and false taps (moths). The end shows the jar, never a number.
public struct FireflyGame: View {
    @State private var caught = 0
    public init() {}

    public var body: some View {
        GameShell(titleKey: "game.firefly.t", scene: .night, introText: T("ff.intro"), introState: .happy,
                  endText: caught > 0 ? T("ff.end") : T("ff.end.none"),
                  demo: { FireflyDemo() },
                  field: { finish in FireflyField { session, n in caught = n; finish(session) } },
                  endArt: { FireflyJar(count: caught, live: false).frame(width: 120, height: 150) })
    }
}

@Observable @MainActor
final class FireflyEngine {
    struct Item: Identifiable {
        let id = UUID()
        let moth: Bool
        let pos: CGPoint        // 0..1
        let born: Date
        var tapped = false
        var drift: CGVector

        /// Position (0..1) at time `t`, drifting from its spawn point.
        func at(_ t: Date, still: Bool = false) -> CGPoint {
            let k = still ? 0 : t.timeIntervalSince(born)
            return CGPoint(x: pos.x + drift.dx * k, y: pos.y + drift.dy * k)
        }
    }

    enum TapOutcome: Equatable { case caught(CGPoint), moth(CGPoint), none }

    static let duration: Double = 60
    static let glow: Double = 1.5
    static let lapseMs: Double = 500

    var items: [Item] = []
    var started = Date()
    var now = Date()
    var reactions: [Double] = []
    var lapses = 0
    var falseTaps = 0
    var caught = 0
    var nextSpawn = Date()
    var done = false
    var reported = false
    /// Fireflies that faded untapped since the view last looked (for the fading trail). Drained by the view.
    var missed: [(pos: CGPoint, at: Date)] = []

    var progress: Double { min(1, now.timeIntervalSince(started) / Self.duration) }

    func start(_ at: Date = Date()) {
        started = at; now = at; nextSpawn = at.addingTimeInterval(0.8)
        items = []; reactions = []; lapses = 0; falseTaps = 0; caught = 0; done = false; reported = false; missed = []
    }

    func tick(_ t: Date) {
        guard !done else { return }
        now = t
        // expire
        for i in items.indices.reversed() {
            let age = t.timeIntervalSince(items[i].born)
            if age > Self.glow {
                if !items[i].moth && !items[i].tapped {
                    lapses += 1
                    missed.append((items[i].at(t), t))
                }
                items.remove(at: i)
            }
        }
        if t.timeIntervalSince(started) >= Self.duration { done = true; items = []; return }
        if t >= nextSpawn, items.count < 3 {
            let moth = Double.random(in: 0...1) < 0.25
            var p = CGPoint(x: .random(in: 0.12...0.88), y: .random(in: 0.12...0.88))
            // keep away from the others
            for _ in 0..<6 where items.contains(where: { hypot($0.pos.x - p.x, $0.pos.y - p.y) < 0.22 }) {
                p = CGPoint(x: .random(in: 0.12...0.88), y: .random(in: 0.12...0.88))
            }
            items.append(Item(moth: moth, pos: p, born: t, drift: CGVector(dx: .random(in: -0.05...0.05), dy: .random(in: -0.04...0.02))))
            nextSpawn = t.addingTimeInterval(.random(in: 0.9...1.6))
        }
    }

    @discardableResult
    func tap(_ id: UUID, at t: Date = Date()) -> TapOutcome {
        guard let i = items.firstIndex(where: { $0.id == id }), !items[i].tapped else { return .none }
        let p = items[i].at(t)
        if items[i].moth {
            falseTaps += 1
            items.remove(at: i)
            return .moth(p)
        }
        let ms = t.timeIntervalSince(items[i].born) * 1000
        reactions.append(ms)
        if ms > Self.lapseMs { lapses += 1 }
        caught += 1
        items[i].tapped = true
        items.remove(at: i)
        return .caught(p)
    }

    /// Keyboard (Space): catch the oldest glowing firefly; with only moths in the air it counts as tapping a moth.
    @discardableResult
    func tapAny(at t: Date = Date()) -> TapOutcome {
        if let f = items.filter({ !$0.moth }).min(by: { $0.born < $1.born }) { return tap(f.id, at: t) }
        if let m = items.first(where: { $0.moth }) { return tap(m.id, at: t) }
        return .none
    }

    func session(device: PlayDevice) -> PlaySession {
        var s = PlaySession(game: .firefly, device: device, duration_s: min(Self.duration, now.timeIntervalSince(started)))
        s.reaction_ms_median = Stats.median(reactions).map { min(5000, $0) }
        s.reaction_ms_iqr = Stats.iqr(reactions).map { min(5000, $0) }
        s.lapses = lapses
        s.false_taps = falseTaps
        return s
    }
}

/// Short-lived visual effects for feedback (catch burst + flight to the jar, moth wobble + puff, missed trail).
private struct FX: Identifiable {
    enum Kind { case caught, moth, missed }
    let id = UUID()
    let kind: Kind
    let pos: CGPoint      // 0..1 in the sky
    let at: Date
    var life: Double {
        switch kind { case .caught: return 0.95; case .moth: return 0.55; case .missed: return 0.7 }
    }
}

struct FireflyField: View {
    let finish: (PlaySession?, Int) -> Void
    @State private var engine = FireflyEngine()
    @State private var fx: [FX] = []
    @State private var kaikuHappyUntil = Date.distantPast
    @Environment(\.accessibilityReduceMotion) private var rm
    @FocusState private var focused: Bool

    /// Fireflies that already reached the jar (the jar fills when they land, not when tapped).
    private func landed(_ now: Date) -> Int {
        engine.caught - fx.filter { $0.kind == .caught && now.timeIntervalSince($0.at) < 0.9 }.count
    }

    var body: some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            ProgressBar(progress: engine.progress, color: KaikuTokens.Colors.firefly.opacity(0.85),
                        track: KaikuTokens.Colors.nightInk.opacity(0.14))
                .padding(.horizontal, KaikuTokens.Space.s2)
            GeometryReader { geo in
                let sky = CGSize(width: geo.size.width, height: max(120, geo.size.height - 118))
                let jarRect = CGRect(x: geo.size.width - 92, y: geo.size.height - 112, width: 84, height: 104)
                let jarMouth = CGPoint(x: jarRect.midX, y: jarRect.minY + 18)
                TimelineView(.animation(minimumInterval: 1.0 / 60)) { tl in
                    let now = tl.date
                    ZStack(alignment: .topLeading) {
                        // the sky: fireflies and moths
                        ForEach(engine.items) { item in
                            let p = item.at(now, still: rm)
                            Button { tap(item.id) } label: {
                                Group {
                                    if item.moth { Moth(age: now.timeIntervalSince(item.born), reduceMotion: rm) }
                                    else { Firefly(age: now.timeIntervalSince(item.born), reduceMotion: rm) }
                                }
                                .frame(width: 64, height: 64)
                                .contentShape(Circle())
                            }
                            .buttonStyle(.plain)
                            .kPointer()
                            .position(x: p.x * sky.width, y: p.y * sky.height)
                            .accessibilityLabel(item.moth ? T("a11y.moth") : T("a11y.firefly"))
                        }
                        // feedback effects
                        ForEach(fx) { e in
                            let t = now.timeIntervalSince(e.at)
                            let p = CGPoint(x: e.pos.x * sky.width, y: e.pos.y * sky.height)
                            switch e.kind {
                            case .caught: CatchFX(t: t, from: p, to: jarMouth, reduceMotion: rm)
                            case .moth: MothFX(t: t, at: p, reduceMotion: rm)
                            case .missed: MissedFX(t: t, at: p, reduceMotion: rm)
                            }
                        }
                        // ground: Kaiku and the jar
                        MascotView(state: now < kaikuHappyUntil ? .happy : .idle, size: 84, tappable: false)
                            .position(x: 50, y: geo.size.height - 50)
                            .accessibilityHidden(true)
                        FireflyJar(count: landed(now), live: true)
                            .frame(width: jarRect.width, height: jarRect.height)
                            .position(x: jarRect.midX, y: jarRect.midY)
                    }
                    .frame(width: geo.size.width, height: geo.size.height)
                    .onChange(of: now) { _, d in
                        engine.tick(d)
                        if !engine.missed.isEmpty {
                            for m in engine.missed {
                                fx.append(FX(kind: .missed, pos: CGPoint(x: m.pos.x, y: m.pos.y), at: m.at))
                            }
                            engine.missed.removeAll()
                        }
                        fx.removeAll { d.timeIntervalSince($0.at) > $0.life }
                        if engine.done && !engine.reported {
                            engine.reported = true
                            finish(engine.session(device: KaikuPlatform.device), engine.caught)
                        }
                    }
                }
            }
        }
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(.space) { handle(engine.tapAny()); return .handled }
        .onAppear {
            engine.start()
            focused = true
            KSound.warmUp([.catchChime, .puff])
        }
    }

    private func tap(_ id: UUID) { handle(engine.tap(id)) }

    private func handle(_ o: FireflyEngine.TapOutcome) {
        switch o {
        case .caught(let p):
            fx.append(FX(kind: .caught, pos: p, at: Date()))
            kaikuHappyUntil = Date().addingTimeInterval(0.9)
            KSound.play(.catchChime)
            Haptics.catchFirefly()
        case .moth(let p):
            fx.append(FX(kind: .moth, pos: p, at: Date()))
            KSound.play(.puff)
            Haptics.softTap()
        case .none: break
        }
    }
}

/// Catch: a ring + eight sparkles burst out (0–0.35 s) while a glowing dot arcs into the jar (0.1–0.9 s).
private struct CatchFX: View {
    let t: Double
    let from: CGPoint
    let to: CGPoint
    let reduceMotion: Bool
    var body: some View {
        ZStack {
            let b = min(1, t / 0.35)
            Circle().strokeBorder(KaikuTokens.Colors.firefly.opacity(0.8 * (1 - b)), lineWidth: 2)
                .frame(width: 20 + 50 * b, height: 20 + 50 * b)
                .position(from)
            if !reduceMotion {
                ForEach(0..<8, id: \.self) { i in
                    let a = Double(i) / 8 * 2 * .pi
                    Circle().fill(KaikuTokens.Colors.firefly)
                        .frame(width: 4, height: 4)
                        .position(x: from.x + cos(a) * 30 * b, y: from.y + sin(a) * 30 * b)
                        .opacity(1 - b)
                }
            }
            // flight to the jar (quadratic arc that lifts first)
            let f = max(0, min(1, (t - 0.1) / 0.8))
            if f < 1 {
                let e = KaikuCurve.ease("soft-in-out", f)
                let c = CGPoint(x: (from.x + to.x) / 2, y: min(from.y, to.y) - 80)
                let x = (1 - e) * (1 - e) * from.x + 2 * (1 - e) * e * c.x + e * e * to.x
                let y = (1 - e) * (1 - e) * from.y + 2 * (1 - e) * e * c.y + e * e * to.y
                GlowDot(size: 14 - 6 * e)
                    .position(reduceMotion ? to : CGPoint(x: x, y: y))
                    .opacity(reduceMotion ? f : 1)
            }
        }
        .allowsHitTesting(false)
    }
}

/// Moth: it wobbles side to side and a soft puff of dust spreads, then it drifts off. No red, no buzz.
private struct MothFX: View {
    let t: Double
    let at: CGPoint
    let reduceMotion: Bool
    var body: some View {
        let k = min(1, t / 0.55)
        ZStack {
            Circle().fill(KaikuTokens.Colors.moth.opacity(0.35 * (1 - k)))
                .frame(width: 24 + 46 * k, height: 24 + 46 * k)
                .blur(radius: 4)
                .position(at)
            Moth(age: 0.5, reduceMotion: true)
                .frame(width: 64, height: 64)
                .rotationEffect(.degrees(reduceMotion ? 0 : sin(t * 34) * 14 * (1 - k)))
                .position(x: at.x + (reduceMotion ? 0 : 26 * k), y: at.y - (reduceMotion ? 0 : 22 * k))
                .opacity(1 - k)
        }
        .allowsHitTesting(false)
    }
}

/// A missed firefly sinks and fades with a tiny trail.
private struct MissedFX: View {
    let t: Double
    let at: CGPoint
    let reduceMotion: Bool
    var body: some View {
        let k = min(1, t / 0.7)
        ZStack {
            ForEach(0..<4, id: \.self) { i in
                let lag = Double(i) * 0.08
                let kk = max(0, min(1, (t - lag) / 0.7))
                Circle().fill(KaikuTokens.Colors.firefly)
                    .frame(width: 7 - CGFloat(i), height: 7 - CGFloat(i))
                    .position(x: at.x - (reduceMotion ? 0 : 6 * kk), y: at.y + (reduceMotion ? 0 : 24 * kk))
                    .opacity((1 - k) * (i == 0 ? 0.7 : 0.35))
            }
        }
        .allowsHitTesting(false)
    }
}

struct GlowDot: View {
    var size: CGFloat = 12
    var body: some View {
        ZStack {
            Circle().fill(RadialGradient(colors: [KaikuTokens.Colors.firefly.opacity(0.7), KaikuTokens.Colors.firefly.opacity(0)],
                                         center: .center, startRadius: 0, endRadius: size * 1.6))
                .frame(width: size * 3.2, height: size * 3.2)
            Circle().fill(KaikuTokens.Colors.firefly).frame(width: size, height: size)
        }
    }
}

struct Firefly: View {
    let age: Double
    let reduceMotion: Bool
    var body: some View {
        // Glow rises over 0.3 s and fades over the last 0.4 s of its 1.5 s (never flashes).
        let a = reduceMotion ? 1 : min(1, age / 0.3) * min(1, max(0, (FireflyEngine.glow - age) / 0.4))
        ZStack {
            Circle().fill(RadialGradient(colors: [KaikuTokens.Colors.firefly.opacity(0.75), KaikuTokens.Colors.firefly.opacity(0)],
                                         center: .center, startRadius: 2, endRadius: 30))
            Circle().fill(KaikuTokens.Colors.firefly).frame(width: 16, height: 16)
            Circle().fill(KaikuTokens.Colors.mascotShine).frame(width: 6, height: 6)
        }
        .scaleEffect(reduceMotion ? 1 : 0.7 + 0.3 * min(1, age / 0.3))
        .opacity(0.2 + 0.8 * a)
    }
}

struct Moth: View {
    var age: Double = 0
    var reduceMotion = false
    var body: some View {
        let flap = reduceMotion ? 1 : 0.8 + 0.2 * abs(sin(age * 9))
        ZStack {
            Ellipse().fill(KaikuTokens.Colors.moth).frame(width: 22, height: 16).scaleEffect(x: flap, y: 1, anchor: .trailing)
                .offset(x: -9).rotationEffect(.degrees(-18))
            Ellipse().fill(KaikuTokens.Colors.moth).frame(width: 22, height: 16).scaleEffect(x: flap, y: 1, anchor: .leading)
                .offset(x: 9).rotationEffect(.degrees(18))
            Capsule().fill(KaikuTokens.Colors.moth.opacity(0.6)).frame(width: 5, height: 18)
        }
        .opacity(reduceMotion ? 0.9 : min(0.9, age / 0.3))
    }
}

/// The jar: glass outline with a lid; one glowing dot per firefly (capped for space), no number. `live` lets the
/// dots twinkle softly while you play.
struct FireflyJar: View {
    let count: Int
    var live: Bool = false
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20, paused: !live || rm)) { tl in
            Canvas { ctx, size in
                let t = tl.date.timeIntervalSinceReferenceDate
                let jar = CGRect(x: size.width * 0.1, y: size.height * 0.14, width: size.width * 0.8, height: size.height * 0.84)
                let glass = Path(roundedRect: jar, cornerRadii: RectangleCornerRadii(topLeading: 12, bottomLeading: 20, bottomTrailing: 20, topTrailing: 12))
                ctx.fill(glass, with: .color(KaikuTokens.Colors.nightInk.opacity(0.08 + min(0.18, Double(count) * 0.012))))
                ctx.stroke(glass, with: .color(KaikuTokens.Colors.nightInk.opacity(0.5)), lineWidth: 2)
                let lid = CGRect(x: size.width * 0.24, y: size.height * 0.06, width: size.width * 0.52, height: size.height * 0.09)
                ctx.fill(Path(roundedRect: lid, cornerRadius: 4), with: .color(KaikuTokens.Colors.nightInk.opacity(0.5)))
                var rng = SeededRandom(seed: 7)
                for i in 0..<min(count, 40) {
                    let p0 = CGPoint(x: jar.minX + 10 + rng.next() * (jar.width - 20), y: jar.maxY - 10 - rng.next() * (jar.height - 24))
                    let ph = Double(i) * 1.7
                    let p = CGPoint(x: p0.x + CGFloat(sin(t * 0.9 + ph)) * 2, y: p0.y + CGFloat(cos(t * 0.7 + ph)) * 3)
                    let tw = live ? 0.75 + 0.25 * sin(t * 2 + ph) : 1
                    ctx.fill(Path(ellipseIn: CGRect(x: p.x - 9, y: p.y - 9, width: 18, height: 18)),
                             with: .radialGradient(Gradient(colors: [KaikuTokens.Colors.firefly.opacity(0.7 * tw), .clear]),
                                                   center: p, startRadius: 0, endRadius: 9))
                    ctx.fill(Path(ellipseIn: CGRect(x: p.x - 3, y: p.y - 3, width: 6, height: 6)), with: .color(KaikuTokens.Colors.firefly))
                }
            }
        }
        .accessibilityHidden(true)
    }
}

/// Intro demo: a firefly glows, a tap ring lands on it and it floats into a little jar; a moth drifts past untouched.
struct FireflyDemo: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: rm)) { tl in
            let t = rm ? 1.0 : tl.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 3.2)
            GeometryReader { g in
                let w = g.size.width, h = g.size.height
                let fly = CGPoint(x: w * 0.36, y: h * 0.38)
                let jar = CGPoint(x: w * 0.82, y: h * 0.72)
                ZStack {
                    // moth drifting across the top
                    Moth(age: t, reduceMotion: rm).frame(width: 50, height: 50)
                        .position(x: w * (0.1 + 0.25 * t / 3.2) + w * 0.4, y: h * 0.2)
                        .opacity(0.8)
                    if t < 1.3 {
                        Firefly(age: min(1, t), reduceMotion: true).frame(width: 64, height: 64).position(fly)
                    }
                    if t > 0.7 && t < 1.3 {
                        let k = (t - 0.7) / 0.6
                        Circle().strokeBorder(KaikuTokens.Colors.nightInk.opacity(0.8 * (1 - k)), lineWidth: 2)
                            .frame(width: 30 + 20 * k, height: 30 + 20 * k).position(fly)
                        Image(systemName: KaikuPlatform.isPhone ? "hand.point.up.left.fill" : "cursorarrow")
                            .font(.system(size: 22)).foregroundStyle(KaikuTokens.Colors.nightInk)
                            .position(x: fly.x + 14, y: fly.y + 20)
                    }
                    if t >= 1.3 && t < 2.2 {
                        let e = KaikuCurve.ease("soft-in-out", (t - 1.3) / 0.9)
                        GlowDot(size: 12 - 4 * e)
                            .position(x: fly.x + (jar.x - fly.x) * e, y: fly.y + (jar.y - 16 - fly.y) * e - 40 * sin(.pi * e))
                    }
                    FireflyJar(count: t >= 2.2 ? 1 : 0).frame(width: 52, height: 64).position(jar)
                }
            }
        }
        .accessibilityHidden(true)
    }
}

struct SeededRandom {
    var state: UInt64
    init(seed: UInt64) { state = seed &* 6364136223846793005 &+ 1 }
    mutating func next() -> CGFloat {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return CGFloat((state >> 33) % 10_000) / 10_000
    }
}

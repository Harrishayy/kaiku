import SwiftUI

/// Lantern (simple reaction time, inspired by the psychomotor vigilance task): Kaiku holds a lantern in the night.
/// After a wait nobody can predict (1.5–4 s) its flame appears; touch anywhere (Space or a click on Mac) and the
/// flame floats up to become a star. Too early → the lantern sways, "wait for the flame". 3 practice lights, then
/// 24 that count. Records median reaction time, variability, response speed, lapses and early taps; the end shows
/// the sky you lit, never a time. What it can say: docs/validation.md → Games.
public struct LanternGame: View {
    @State private var stars = 0
    public init() {}

    public var body: some View {
        GameShell(titleKey: "game.lantern.t", scene: .night, introText: KaikuPlatform.isPhone ? T("ln.intro") : T("ln.intro.mac"), introState: .idle,
                  endText: stars > 0 ? T("ln.end") : T("ln.end.none"),
                  demo: { LanternDemo() },
                  field: { finish in LanternField { session, n in stars = n; finish(session) } },
                  endArt: { StarPatch(count: stars).frame(width: 130, height: 130) })
    }
}

/// Pure trial logic (unit-tested). Time is passed in (seconds, monotonic), so tests drive it without waiting.
public struct LanternEngine: Sendable {
    public static let scored = 24
    public static let practice = 3
    /// Wait before the flame, in seconds: each value four times among the scored trials (balanced), ± `jitter`.
    public static let foreperiods: [Double] = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    public static let jitter = 0.2
    public static let anticipationMs = 100.0   // faster than a person can react: counted as an early tap
    public static let lapseMs = 500.0
    public static let timeout = 2.5            // no answer for this long = missed
    public static let feedback = 0.75
    public static let minValid = 16
    public static let maxFalseStarts = 6

    public enum Phase: Equatable, Sendable { case idle, waiting, lit, feedback, done }
    public enum Outcome: Equatable, Sendable { case hit(lapse: Bool), early, missed, ignored }

    public let plan: [Double]
    public private(set) var index = 0
    public private(set) var phase: Phase = .idle
    public private(set) var trials: [GameTrial] = []
    public private(set) var last: Outcome = .ignored
    public private(set) var lastAt: TimeInterval = 0
    public var interrupted = false
    private var changeAt: TimeInterval = 0
    /// When the flame appeared (the tick that showed it).
    public private(set) var litAt: TimeInterval = 0
    private var startedAt: TimeInterval = 0

    public init<R: RandomNumberGenerator>(using rng: inout R) { plan = Self.makePlan(using: &rng) }

    /// Practice waits first, then the balanced scored waits: shuffled so the same wait never comes three times in a row.
    public static func makePlan<R: RandomNumberGenerator>(using rng: inout R) -> [Double] {
        var base = Array(repeating: foreperiods, count: scored / foreperiods.count).flatMap { $0 }
        for _ in 0..<50 {
            base.shuffle(using: &rng)
            var runs = false
            for i in 2..<base.count where base[i] == base[i - 1] && base[i] == base[i - 2] { runs = true }
            if !runs { break }
        }
        let warm = Array(foreperiods.shuffled(using: &rng).prefix(practice))
        return (warm + base).map { $0 + Double.random(in: -jitter...jitter, using: &rng) }
    }

    public var isPractice: Bool { index < Self.practice }
    public var progress: Double { Double(min(index, plan.count)) / Double(plan.count) }
    /// Lights answered so far among the scored trials (one star each).
    public var stars: Int { trials.filter { !$0.practice && ($0.code == "h" || $0.code == "l") }.count }

    public mutating func begin(at t: TimeInterval) {
        startedAt = t; index = 0; trials = []
        startTrial(t)
    }

    private mutating func startTrial(_ t: TimeInterval) {
        phase = .waiting
        changeAt = t + plan[index]
    }

    /// Advances the clock. Returns true when the phase changed.
    @discardableResult
    public mutating func tick(at t: TimeInterval) -> Bool {
        switch phase {
        case .waiting where t >= changeAt:
            phase = .lit; litAt = t
            return true
        case .lit where t - litAt >= Self.timeout:
            record("m", rt: 0, .missed, at: t)
            return true
        case .feedback where t >= changeAt:
            index += 1
            if index >= plan.count { phase = .done } else { startTrial(t) }
            return true
        default:
            return false
        }
    }

    @discardableResult
    public mutating func respond(at t: TimeInterval) -> Outcome {
        switch phase {
        case .waiting:
            record("a", rt: 0, .early, at: t)
        case .lit:
            let ms = (t - litAt) * 1000
            if ms < Self.anticipationMs { record("a", rt: 0, .early, at: t) }
            else { record(ms >= Self.lapseMs ? "l" : "h", rt: Int(ms.rounded()), .hit(lapse: ms >= Self.lapseMs), at: t) }
        default:
            return .ignored
        }
        return last
    }

    private mutating func record(_ code: String, rt: Int, _ outcome: Outcome, at t: TimeInterval) {
        trials.append(GameTrial(code: code, rt_ms: rt, practice: isPractice, detail: ["foreperiod_s": GameStats.round(plan[index], 3)]))
        last = outcome; lastAt = t
        phase = .feedback
        changeAt = t + Self.feedback
    }

    public var flags: [PlayFlag] {
        let s = trials.filter { !$0.practice }
        var f: [PlayFlag] = []
        if s.filter({ $0.code == "h" || $0.code == "l" }).count < Self.minValid { f.append(.few_trials) }
        if s.filter({ $0.code == "a" }).count > Self.maxFalseStarts { f.append(.false_starts) }
        if interrupted { f.append(.interrupted) }
        return f
    }

    public func session(device: PlayDevice, input: PlayInput?, at t: TimeInterval) -> PlaySession {
        let s = trials.filter { !$0.practice }
        let rts = s.filter { $0.code == "h" || $0.code == "l" }.map { Double($0.rt_ms) }
        var out = PlaySession(game: .lantern, device: device, duration_s: t - startedAt)
        out.reaction_ms_median = Stats.median(rts).map { GameStats.round($0, 1) }
        out.reaction_ms_iqr = Stats.iqr(rts).map { GameStats.round($0, 1) }
        out.reaction_ms_cv = GameStats.cv(rts).map { GameStats.round(min(5, $0), 3) }
        out.response_speed = GameStats.mean(rts.map { 1000 / $0 }).map { GameStats.round(min(10, $0), 3) }
        out.lapses = s.filter { $0.code == "l" || $0.code == "m" }.count
        out.false_starts = s.filter { $0.code == "a" }.count
        out.trials_n = s.count
        out.valid_n = rts.count
        out.input = input
        let f = flags
        out.valid = f.isEmpty
        out.flags = f.isEmpty ? nil : f
        out.rt_ms = s.map(\.rt_ms)
        out.trial_codes = s.map(\.code).joined()
        return out
    }
}

struct LanternField: View {
    let finish: (PlaySession?, Int) -> Void
    @State private var engine: LanternEngine = {
        var rng = SystemRandomNumberGenerator()
        return LanternEngine(using: &rng)
    }()
    @State private var input = InputTracker()
    @State private var down = false
    @State private var reported = false
    @Environment(\.accessibilityReduceMotion) private var rm
    @Environment(\.scenePhase) private var scenePhase
    @FocusState private var focused: Bool

    private var message: String {
        switch engine.phase {
        case .feedback:
            switch engine.last {
            case .early: return T("ln.early")
            case .missed: return T("ln.missed")
            default: return engine.isPractice ? T("ln.practice.good") : " "
            }
        default:
            return engine.isPractice ? T("ln.practice") : " "
        }
    }

    var body: some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            ProgressBar(progress: engine.progress, color: KaikuTokens.Colors.firefly.opacity(0.85),
                        track: KaikuTokens.Colors.nightInk.opacity(0.14))
                .padding(.horizontal, KaikuTokens.Space.s2)
            Text(message).kText(.callout).foregroundStyle(KaikuTokens.Colors.nightInk).wraps()
                .multilineTextAlignment(.center).frame(minHeight: 24)
                .accessibilityAddTraits(.updatesFrequently)
            GeometryReader { geo in
                TimelineView(.animation(minimumInterval: 1.0 / 120)) { tl in
                    let now = GameClock.now
                    let lit = engine.phase == .lit
                    let hit: Bool = { if case .hit = engine.last { return engine.phase == .feedback }; return false }()
                    let early = engine.phase == .feedback && engine.last == .early
                    let since = now - engine.lastAt
                    let side = min(geo.size.width, geo.size.height)
                    let centre = CGPoint(x: geo.size.width / 2, y: geo.size.height * 0.56)
                    ZStack {
                        StarPatch(count: engine.stars, rising: hit ? min(1, since / 0.6) : 1)
                            .frame(width: geo.size.width, height: geo.size.height * 0.42)
                            .position(x: geo.size.width / 2, y: geo.size.height * 0.21)
                        if hit && !rm {
                            // the flame floats up to join the stars
                            let k = KaikuCurve.ease("soft-in-out", min(1, since / 0.6))
                            GlowDot(size: 14 - 6 * k)
                                .position(x: centre.x, y: centre.y - 20 - (centre.y - geo.size.height * 0.2) * k)
                                .opacity(1 - k * 0.6)
                        }
                        Lantern(lit: lit, glow: lit ? min(1, (now - engine.litAt) / 0.7) : 0)
                            .frame(width: side * 0.34, height: side * 0.46)
                            .rotationEffect(.degrees(early && !rm ? sin(since * 22) * 7 * max(0, 1 - since / 0.6) : 0), anchor: .top)
                            .position(centre)
                        MascotView(state: hit ? .happy : .idle, size: min(96, side * 0.26), tappable: false)
                            .position(x: centre.x - side * 0.3, y: geo.size.height - min(96, side * 0.26) * 0.55)
                            .accessibilityHidden(true)
                    }
                    .frame(width: geo.size.width, height: geo.size.height)
                    .onChange(of: tl.date) { _, _ in step() }
                }
                .contentShape(Rectangle())
                // touch-down (not touch-up) answers: the time of the finger landing is the reaction
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { _ in if !down { down = true; respond(InputTracker.pointing) } }
                    .onEnded { _ in down = false })
            }
            .accessibilityElement()
            .accessibilityLabel(T("a11y.lantern"))
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { respond(InputTracker.pointing) }
        }
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(.space, phases: .down) { _ in respond(.keyboard); return .handled }
        .onChange(of: scenePhase) { _, p in if p != .active { engine.interrupted = true } }
        .onAppear {
            engine.begin(at: GameClock.now)
            focused = true
            KSound.warmUp([.catchChime, .puff])
        }
    }

    private func step() {
        engine.tick(at: GameClock.now)
        if engine.phase == .done && !reported {
            reported = true
            let s = engine.session(device: KaikuPlatform.device, input: input.value, at: GameClock.now)
            let trials = engine.trials
            Task { await GameTrialLog.shared.append(game: .lantern, input: input.value, trials: trials) }
            finish(s, engine.stars)
        }
    }

    private func respond(_ how: PlayInput) {
        input.note(how)
        switch engine.respond(at: GameClock.now) {
        case .hit:
            KSound.play(.catchChime)
            Haptics.catchFirefly()
        case .early:
            KSound.play(.puff)
            Haptics.softTap()
        case .missed, .ignored:
            break
        }
    }
}

/// The lantern: a frame with a handle. Lit: the flame is there at once (it is what you react to); only its halo
/// swells in afterwards (`glow` 0…1), so nothing flashes.
struct Lantern: View {
    let lit: Bool
    var glow: Double = 0
    var body: some View {
        GeometryReader { g in
            let w = g.size.width, h = g.size.height
            ZStack {
                if lit {
                    Circle()
                        .fill(RadialGradient(colors: [KaikuTokens.Colors.firefly.opacity(0.55 * glow), KaikuTokens.Colors.firefly.opacity(0)],
                                             center: .center, startRadius: 0, endRadius: w * 0.9))
                        .frame(width: w * 1.8, height: w * 1.8)
                        .position(x: w / 2, y: h * 0.6)
                }
                // handle + cap
                Circle().trim(from: 0.5, to: 1).stroke(KaikuTokens.Colors.nightInk.opacity(0.6), lineWidth: 3)
                    .frame(width: w * 0.5, height: w * 0.5).position(x: w / 2, y: h * 0.2)
                RoundedRectangle(cornerRadius: 4).fill(KaikuTokens.Colors.nightInk.opacity(0.6))
                    .frame(width: w * 0.6, height: h * 0.07).position(x: w / 2, y: h * 0.24)
                // glass
                RoundedRectangle(cornerRadius: w * 0.16, style: .continuous)
                    .fill(lit ? KaikuTokens.Colors.firefly.opacity(0.22) : KaikuTokens.Colors.nightInk.opacity(0.07))
                    .overlay(RoundedRectangle(cornerRadius: w * 0.16, style: .continuous)
                        .strokeBorder(KaikuTokens.Colors.nightInk.opacity(0.6), lineWidth: 3))
                    .frame(width: w * 0.74, height: h * 0.6).position(x: w / 2, y: h * 0.58)
                if lit {
                    FlameShape().fill(KaikuTokens.Colors.firefly)
                        .frame(width: w * 0.3, height: h * 0.34).position(x: w / 2, y: h * 0.6)
                    FlameShape().fill(KaikuTokens.Colors.mascotShine)
                        .frame(width: w * 0.12, height: h * 0.15).position(x: w / 2, y: h * 0.67)
                }
                RoundedRectangle(cornerRadius: 4).fill(KaikuTokens.Colors.nightInk.opacity(0.6))
                    .frame(width: w * 0.66, height: h * 0.07).position(x: w / 2, y: h * 0.91)
            }
        }
        .accessibilityHidden(true)
    }
}

struct FlameShape: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.midX, y: r.minY))
        p.addQuadCurve(to: CGPoint(x: r.midX, y: r.maxY), control: CGPoint(x: r.maxX + r.width * 0.25, y: r.maxY * 0.75 + r.minY * 0.25))
        p.addQuadCurve(to: CGPoint(x: r.midX, y: r.minY), control: CGPoint(x: r.minX - r.width * 0.25, y: r.maxY * 0.75 + r.minY * 0.25))
        return p
    }
}

/// The sky you lit: one star per answered light (fixed scattered spots, no number). `rising` fades the newest in.
struct StarPatch: View {
    let count: Int
    var rising: Double = 1
    var body: some View {
        Canvas { ctx, size in
            var rng = SeededRandom(seed: 23)
            for i in 0..<min(count, 40) {
                let p = CGPoint(x: (0.06 + rng.next() * 0.88) * size.width, y: (0.08 + rng.next() * 0.84) * size.height)
                let r = 2.2 + rng.next() * 2.2
                let a = i == count - 1 ? rising : 1
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - r * 3, y: p.y - r * 3, width: r * 6, height: r * 6)),
                         with: .radialGradient(Gradient(colors: [KaikuTokens.Colors.firefly.opacity(0.55 * a), .clear]),
                                               center: p, startRadius: 0, endRadius: r * 3))
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - r / 2, y: p.y - r / 2, width: r, height: r)),
                         with: .color(KaikuTokens.Colors.firefly.opacity(a)))
            }
        }
        .accessibilityHidden(true)
    }
}

/// Intro demo: the lantern waits, lights, a touch ring lands, the flame floats up into a star.
struct LanternDemo: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: rm)) { tl in
            let t = rm ? 1.6 : tl.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 3.6)
            GeometryReader { g in
                let c = CGPoint(x: g.size.width / 2, y: g.size.height * 0.6)
                ZStack {
                    StarPatch(count: t > 2.4 ? 4 : 3, rising: min(1, max(0, (t - 2.4) / 0.6)))
                        .frame(width: g.size.width, height: g.size.height * 0.4)
                        .position(x: g.size.width / 2, y: g.size.height * 0.2)
                    Lantern(lit: t > 1.2 && t < 1.9, glow: min(1, max(0, (t - 1.2) / 0.7)))
                        .frame(width: 70, height: 96).position(c)
                    if t > 1.5 && t < 2.0 {
                        let k = (t - 1.5) / 0.5
                        Circle().strokeBorder(KaikuTokens.Colors.nightInk.opacity(0.8 * (1 - k)), lineWidth: 2)
                            .frame(width: 30 + 24 * k, height: 30 + 24 * k).position(x: c.x + 50, y: c.y + 30)
                        Image(systemName: KaikuPlatform.isPhone ? "hand.point.up.left.fill" : "cursorarrow")
                            .font(.system(size: 22)).foregroundStyle(KaikuTokens.Colors.nightInk)
                            .position(x: c.x + 62, y: c.y + 46)
                    }
                    if t >= 1.9 && t < 2.5 {
                        let e = KaikuCurve.ease("soft-in-out", (t - 1.9) / 0.6)
                        GlowDot(size: 12 - 4 * e).position(x: c.x, y: c.y - 10 - (c.y - g.size.height * 0.2) * e)
                    }
                }
            }
        }
        .accessibilityHidden(true)
    }
}

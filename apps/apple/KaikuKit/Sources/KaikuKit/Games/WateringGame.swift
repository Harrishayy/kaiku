import SwiftUI

/// Watering (effort-for-reward choice, inspired by effort-based decision tasks): each round offers two plants.
/// The daisy needs a few taps of the watering can and gives one flower; the other needs a long watering and
/// gives two to five. Pick one (← / → on Mac), then tap the can (Space) until it has had enough. First you fill
/// the can with eight taps: that sets "a long watering" to your own tapping pace. Eight rounds: every size of
/// reward with a shorter and a longer watering, sides balanced. Nothing is lost: an unfinished watering still
/// gives one flower. Records how often the bigger, harder plant was chosen and the tapping pace; the end shows
/// the flower bed. What it can say: docs/validation.md → Games.
public struct WateringGame: View {
    @State private var flowers = 0
    public init() {}

    public var body: some View {
        // Read here, in this view's own body: the end picture must be rebuilt when the result arrives.
        let grown = flowers
        return GameShell(titleKey: "game.watering.t", scene: .calm, introText: T("wt.intro"), introState: .idle, endText: T("wt.end"),
                  demo: { WateringDemo() },
                  field: { finish in WateringField { session, n in flowers = n; finish(session) } },
                  endArt: { FlowerBed(count: grown).frame(width: 150, height: 120) })
    }
}

/// Pure trial logic (unit-tested); time is passed in.
public struct WateringEngine: Sendable {
    public static let rewards = [2, 3, 4, 5]
    public static let rounds = 8
    public static let calibrationTaps = 8
    public static let easyTaps = 4
    public static let bloom = 0.9
    public static let minChosen = 6
    public static let tooFastMs = 250.0

    public enum Phase: Equatable, Sendable { case idle, calibrate, choose, water, bloom, done }

    public struct Offer: Equatable, Sendable {
        public let reward: Int        // flowers for the hard plant (the easy one always gives 1)
        public let hardTaps: Int
        public let long: Bool         // the longer of the two hard waterings
        public let hardOnLeft: Bool
    }

    public private(set) var phase: Phase = .idle
    public private(set) var offers: [Offer] = []
    public private(set) var round = 0
    public private(set) var taps = 0
    public private(set) var need = 0
    public private(set) var choseHard = false
    public private(set) var flowers = 0
    public private(set) var lastBloom = 0
    public private(set) var trials: [GameTrial] = []
    public private(set) var rate = 4.0           // the person's own tapping pace, taps per second
    public var interrupted = false
    private var rates: [Double] = []
    private var firstTap: TimeInterval = 0
    private var lastTap: TimeInterval = 0
    private var shownAt: TimeInterval = 0
    private var decisionMs = 0
    private var deadline: TimeInterval = 0
    private var bloomUntil: TimeInterval = 0
    private var startedAt: TimeInterval = 0
    private var endedAt: TimeInterval = 0
    private var order: [(Int, Bool, Bool)]      // reward, long, hardOnLeft — fixed at init, taps filled after calibration

    public init<R: RandomNumberGenerator>(using rng: inout R) {
        var cells = Self.rewards.flatMap { r in [(r, false), (r, true)] }
        cells.shuffle(using: &rng)
        var sides = Array(repeating: true, count: Self.rounds / 2) + Array(repeating: false, count: Self.rounds / 2)
        sides.shuffle(using: &rng)
        order = zip(cells, sides).map { ($0.0, $0.1, $1) }
    }

    /// How many taps a hard watering takes for someone tapping at `rate`: about 2.5 s (shorter) or 5 s (longer).
    public static func hardTaps(rate: Double, long: Bool) -> Int {
        long ? min(40, max(16, Int((rate * 5).rounded()))) : min(20, max(8, Int((rate * 2.5).rounded())))
    }

    public var offer: Offer? { round < offers.count ? offers[round] : nil }
    public var progress: Double {
        phase == .calibrate ? 0 : Double(min(round, Self.rounds)) / Double(Self.rounds)
    }
    public var waterProgress: Double { need == 0 ? 0 : min(1, Double(taps) / Double(need)) }

    public mutating func begin(at t: TimeInterval) {
        startedAt = t; phase = .calibrate; taps = 0; need = Self.calibrationTaps
    }

    /// A tap on the can (calibration or watering). Returns true when that filled it.
    @discardableResult
    public mutating func tap(at t: TimeInterval) -> Bool {
        guard phase == .calibrate || phase == .water else { return false }
        if taps == 0 { firstTap = t }
        taps += 1; lastTap = t
        guard taps >= need else { return false }
        let r = pace()
        if phase == .calibrate {
            rate = min(9, max(2, r ?? 4))
            offers = order.map { Offer(reward: $0.0, hardTaps: Self.hardTaps(rate: rate, long: $0.1), long: $0.1, hardOnLeft: $0.2) }
            if let r { rates.append(r) }
            phase = .choose; shownAt = t; taps = 0
        } else {
            if let r { rates.append(r) }
            finishRound(completed: true, at: t)
        }
        return true
    }

    private func pace() -> Double? {
        guard taps >= 3, lastTap > firstTap else { return nil }
        return Double(taps - 1) / (lastTap - firstTap)
    }

    public mutating func choose(hard: Bool, at t: TimeInterval) {
        guard phase == .choose, let o = offer else { return }
        choseHard = hard
        decisionMs = min(10_000, max(0, Int(((t - shownAt) * 1000).rounded())))
        need = hard ? o.hardTaps : Self.easyTaps
        taps = 0
        // generous: twice the time the person's own pace needs, plus a breath
        deadline = t + Double(need) / rate * 2 + 2.5
        phase = .water
    }

    /// Advances the clock. Returns true when the phase changed.
    @discardableResult
    public mutating func tick(at t: TimeInterval) -> Bool {
        switch phase {
        case .water where t >= deadline:
            finishRound(completed: false, at: t)
            return true
        case .bloom where t >= bloomUntil:
            round += 1
            if round >= Self.rounds { phase = .done; endedAt = t } else { phase = .choose; shownAt = t; taps = 0 }
            return true
        default:
            return false
        }
    }

    private mutating func finishRound(completed: Bool, at t: TimeInterval) {
        guard let o = offer else { return }
        lastBloom = completed && choseHard ? o.reward : 1
        flowers += lastBloom
        let code = choseHard ? (completed ? "H" : "h") : (completed ? "E" : "e")
        trials.append(GameTrial(code: code, rt_ms: decisionMs, detail: [
            "reward": Double(o.reward), "hard_taps": Double(o.hardTaps), "hard_left": o.hardOnLeft ? 1 : 0,
            "taps_done": Double(taps), "tap_rate_hz": GameStats.round(pace() ?? 0, 2)]))
        phase = .bloom
        bloomUntil = t + Self.bloom
    }

    public var flags: [PlayFlag] {
        var f: [PlayFlag] = []
        if trials.count < Self.minChosen { f.append(.few_trials) }
        if let m = Stats.median(trials.map { Double($0.rt_ms) }), m < Self.tooFastMs { f.append(.too_fast) }
        if interrupted { f.append(.interrupted) }
        return f
    }

    public func session(device: PlayDevice, input: PlayInput?, at t: TimeInterval) -> PlaySession {
        var out = PlaySession(game: .watering, device: device, duration_s: (phase == .done ? endedAt : t) - startedAt)
        let hard = trials.filter { $0.code.uppercased() == "H" }.count
        out.hard_choice_ratio = trials.isEmpty ? nil : GameStats.round(Double(hard) / Double(trials.count), 3)
        out.tap_rate_hz = Stats.median(rates).map { GameStats.round(min(20, $0), 2) }
        out.trials_n = Self.rounds
        out.valid_n = trials.filter { $0.code == "H" || $0.code == "E" }.count
        out.input = input
        let f = flags
        out.valid = f.isEmpty
        out.flags = f.isEmpty ? nil : f
        out.rt_ms = trials.map(\.rt_ms)
        out.trial_codes = trials.map(\.code).joined()
        return out
    }
}

struct WateringField: View {
    let finish: (PlaySession?, Int) -> Void
    @State private var engine: WateringEngine = {
        var rng = SystemRandomNumberGenerator()
        return WateringEngine(using: &rng)
    }()
    @State private var input = InputTracker()
    @State private var reported = false
    @State private var pressAt = -10.0
    @Environment(\.accessibilityReduceMotion) private var rm
    @Environment(\.scenePhase) private var scenePhase
    @FocusState private var focused: Bool

    private var message: String {
        switch engine.phase {
        case .calibrate: return T("wt.fill")
        case .choose: return T("wt.choose")
        case .water: return T("wt.water")
        case .bloom: return engine.lastBloom > 1 ? T("wt.bloom.many") : T("wt.bloom.one")
        default: return " "
        }
    }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { tl in
            let now = GameClock.now
            VStack(spacing: KaikuTokens.Space.s3) {
                ProgressBar(progress: engine.progress, color: KaikuTokens.Colors.sage)
                    .padding(.horizontal, KaikuTokens.Space.s2)
                Text(message).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    .multilineTextAlignment(.center).frame(minHeight: 24)
                    .accessibilityAddTraits(.updatesFrequently)
                Group {
                    if engine.phase == .choose, let o = engine.offer {
                        HStack(spacing: KaikuTokens.Space.s3) {
                            if o.hardOnLeft { plantCard(hard: true, o) }
                            plantCard(hard: false, o)
                            if !o.hardOnLeft { plantCard(hard: true, o) }
                        }
                    } else {
                        can(now: now)
                    }
                }
                .frame(maxHeight: .infinity)
                FlowerBed(count: engine.flowers).frame(height: 54)
            }
            .onChange(of: tl.date) { _, _ in step() }
        }
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(phases: .down) { press in
            switch press.key {
            case .space: tapCan(.keyboard)
            case .leftArrow: if let o = engine.offer { choose(hard: o.hardOnLeft, .keyboard) }
            case .rightArrow: if let o = engine.offer { choose(hard: !o.hardOnLeft, .keyboard) }
            default: return .ignored
            }
            return .handled
        }
        .onChange(of: scenePhase) { _, p in if p != .active { engine.interrupted = true } }
        .onAppear {
            engine.begin(at: GameClock.now)
            focused = true
            KSound.warmUp([.tick, .catchChime])
        }
    }

    /// One plant on offer: its flowers, and how long a watering it wants (a row of drops, sized to the taps).
    private func plantCard(hard: Bool, _ o: WateringEngine.Offer) -> some View {
        let n = hard ? o.reward : 1
        let taps = hard ? o.hardTaps : WateringEngine.easyTaps
        return Button { choose(hard: hard, InputTracker.pointing) } label: {
            VStack(spacing: KaikuTokens.Space.s2) {
                FlowerBed(count: n, perRow: 5, soil: false).frame(height: 44)
                Text(hard ? T("wt.big") : T("wt.small")).kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                EffortDrops(taps: taps).frame(height: 30)
                Text(hard ? (o.long ? T("wt.effort.long") : T("wt.effort.mid")) : T("wt.effort.short"))
                    .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps().multilineTextAlignment(.center)
            }
            .padding(KaikuTokens.Space.s3)
            .frame(maxWidth: 240, maxHeight: 230)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface))
            .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous))
        }
        .buttonStyle(.kPress)
        .kPointer()
        .accessibilityLabel(T(hard ? "a11y.plant.big" : "a11y.plant.small", n: n))
    }

    private func can(now: TimeInterval) -> some View {
        let pressed = now - pressAt < 0.1 && !rm
        let blooming = engine.phase == .bloom
        return HStack(spacing: KaikuTokens.Space.s4) {
            MascotView(state: blooming ? .cheering : .idle, size: 92, tappable: false).accessibilityHidden(true)
            Button { tapCan(InputTracker.pointing) } label: {
                ZStack {
                    ProgressRing(progress: blooming ? 1 : engine.waterProgress, color: KaikuTokens.Colors.sky, width: 8,
                                 track: KaikuTokens.Colors.sky.opacity(0.18))
                    Circle().fill(KaikuTokens.Colors.skySoft).padding(12)
                    Image(systemName: blooming ? "camera.macro" : "drop.fill")
                        .font(.system(size: 44, weight: .semibold))
                        .foregroundStyle(blooming ? KaikuTokens.Colors.clay : KaikuTokens.Colors.sky)
                }
                .frame(width: 150, height: 150)
                .scaleEffect(pressed ? 0.96 : 1)
                .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .kPointer(!blooming)
            .disabled(blooming)
            .accessibilityLabel(T("a11y.can"))
        }
    }

    private func step() {
        engine.tick(at: GameClock.now)
        if engine.phase == .done && !reported {
            reported = true
            let s = engine.session(device: KaikuPlatform.device, input: input.value, at: GameClock.now)
            let trials = engine.trials
            Task { await GameTrialLog.shared.append(game: .watering, input: input.value, trials: trials) }
            finish(s, engine.flowers)
        }
    }

    private func choose(hard: Bool, _ how: PlayInput) {
        guard engine.phase == .choose else { return }
        input.note(how)
        engine.choose(hard: hard, at: GameClock.now)
        KSound.play(.tick)
        Haptics.softTap()
    }

    private func tapCan(_ how: PlayInput) {
        guard engine.phase == .calibrate || engine.phase == .water else { return }
        input.note(how)
        pressAt = GameClock.now
        if engine.tap(at: GameClock.now) {
            KSound.play(.catchChime)
            Haptics.catchFirefly()
        } else {
            KSound.play(.tick)
            Haptics.dialStep()
        }
    }
}

/// How long a watering: one small drop per two taps, wrapping into rows (a picture of the effort, not a number).
struct EffortDrops: View {
    let taps: Int
    var body: some View {
        Canvas { ctx, size in
            let n = max(1, (taps + 1) / 2)
            let perRow = 10
            let d: CGFloat = min(9, size.width / CGFloat(perRow) - 3)
            let rows = (n + perRow - 1) / perRow
            for i in 0..<n {
                let r = i / perRow
                let inRow = r == rows - 1 ? n - r * perRow : perRow
                let x0 = (size.width - CGFloat(inRow) * (d + 3) + 3) / 2
                let rect = CGRect(x: x0 + CGFloat(i % perRow) * (d + 3), y: CGFloat(r) * (d + 4), width: d, height: d * 1.15)
                ctx.fill(Path(ellipseIn: rect), with: .color(KaikuTokens.Colors.sky))
            }
        }
        .accessibilityHidden(true)
    }
}

/// The flower bed: one flower per flower grown (capped for space, no number).
struct FlowerBed: View {
    let count: Int
    var perRow = 12
    var soil = true
    var body: some View {
        Canvas { ctx, size in
            let shown = min(count, perRow * 3)
            let rows = max(1, (shown + perRow - 1) / perRow)
            let rowH = size.height / CGFloat(rows)
            let tones = [KaikuTokens.Colors.clay, KaikuTokens.Colors.honey, KaikuTokens.Colors.sky]
            for i in 0..<shown {
                let r = i / perRow
                let inRow = r == rows - 1 ? shown - r * perRow : perRow
                let slot = min(size.width / CGFloat(perRow), 30)
                let x0 = (size.width - CGFloat(inRow) * slot) / 2 + slot / 2
                let x = x0 + CGFloat(i % perRow) * slot
                let base = rowH * CGFloat(r + 1) - 3
                let h = min(rowH - 12, 22 + CGFloat((i * 5) % 7))
                var stem = Path()
                stem.move(to: CGPoint(x: x, y: base)); stem.addLine(to: CGPoint(x: x, y: base - h))
                ctx.stroke(stem, with: .color(KaikuTokens.Colors.sage), style: StrokeStyle(lineWidth: 2, lineCap: .round))
                let c = CGPoint(x: x, y: base - h)
                let pr: CGFloat = min(5, slot * 0.2)
                for k in 0..<5 {
                    let a = Double(k) / 5 * 2 * .pi - .pi / 2
                    let p = CGPoint(x: c.x + CGFloat(cos(a)) * pr, y: c.y + CGFloat(sin(a)) * pr)
                    ctx.fill(Path(ellipseIn: CGRect(x: p.x - pr * 0.7, y: p.y - pr * 0.7, width: pr * 1.4, height: pr * 1.4)),
                             with: .color(tones[i % tones.count]))
                }
                ctx.fill(Path(ellipseIn: CGRect(x: c.x - pr * 0.5, y: c.y - pr * 0.5, width: pr, height: pr)),
                         with: .color(KaikuTokens.Colors.mascotShine))
            }
            if soil {
                var line = Path()
                line.move(to: CGPoint(x: 0, y: size.height - 2)); line.addLine(to: CGPoint(x: size.width, y: size.height - 2))
                ctx.stroke(line, with: .color(KaikuTokens.Colors.pebbleEdge.opacity(0.7)), style: StrokeStyle(lineWidth: 2, lineCap: .round))
            }
        }
        .accessibilityHidden(true)
    }
}

/// Intro demo: two plants side by side, one is picked, the can fills, flowers bloom.
struct WateringDemo: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20, paused: rm)) { tl in
            let t = rm ? 2.6 : tl.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 3.6)
            VStack(spacing: KaikuTokens.Space.s3) {
                HStack(spacing: KaikuTokens.Space.s4) {
                    demoCard(flowers: 1, taps: 4, on: false)
                    demoCard(flowers: 4, taps: 20, on: t > 0.8)
                }
                HStack(spacing: KaikuTokens.Space.s3) {
                    ProgressRing(progress: min(1, max(0, (t - 1.0) / 1.4)), color: KaikuTokens.Colors.sky, width: 5,
                                 track: KaikuTokens.Colors.sky.opacity(0.18))
                        .frame(width: 40, height: 40)
                        .overlay(Image(systemName: "drop.fill").foregroundStyle(KaikuTokens.Colors.sky))
                    FlowerBed(count: t > 2.4 ? 4 : 0, perRow: 6).frame(width: 150, height: 40)
                }
            }
            .padding(KaikuTokens.Space.s3)
        }
        .accessibilityHidden(true)
    }

    private func demoCard(flowers: Int, taps: Int, on: Bool) -> some View {
        VStack(spacing: 6) {
            FlowerBed(count: flowers, perRow: 5, soil: false).frame(width: 90, height: 34)
            EffortDrops(taps: taps).frame(width: 90, height: 22)
        }
        .padding(KaikuTokens.Space.s2)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(on ? KaikuTokens.Colors.sageSoft : KaikuTokens.Colors.surface))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(on ? KaikuTokens.Colors.sage : KaikuTokens.Colors.line, lineWidth: on ? 2 : 1))
    }
}

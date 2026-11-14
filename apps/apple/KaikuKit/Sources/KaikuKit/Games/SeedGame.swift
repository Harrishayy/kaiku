import SwiftUI

/// Seed shelf (symbol–digit substitution, the classic processing-speed task): the shelf on top pairs nine seed
/// marks with the pots 1–9 — a new pairing every session. Kaiku holds up a seed packet; tap the pot its mark
/// belongs to (keys 1–9 on Mac). A right pot grows a sprout; a wrong one just wobbles and the next packet comes.
/// 4 practice packets with the answer shown, then 90 seconds. Records right answers per minute, accuracy and the
/// time per packet; the end shows the sprouts, never a count. What it can say: docs/validation.md → Games.
public struct SeedGame: View {
    @State private var sprouts = 0
    public init() {}

    public var body: some View {
        GameShell(titleKey: "game.seeds.t", scene: .warm, introText: T("sd.intro"), introState: .idle, endText: T("sd.end"),
                  demo: { SeedDemo() },
                  field: { finish in SeedField { session, n in sprouts = n; finish(session) } },
                  endArt: { SproutRow(count: sprouts, rows: 3).frame(width: 150, height: 110) })
    }
}

/// Pure trial logic (unit-tested); time is passed in.
public struct SeedEngine: Sendable {
    public static let symbols = 9
    public static let duration = 90.0
    public static let practice = 4
    public static let minAnswers = 15
    public static let minAccuracy = 0.7
    public static let tooFastMs = 300.0
    public static let maxSent = 120

    public enum Phase: Equatable, Sendable { case idle, practice, scored, done }

    /// `key[symbol]` = the pot (1…9) that seed mark belongs to. A fresh pairing each session (an alternate form:
    /// the pairing itself cannot be learned by heart from day to day).
    public let key: [Int]
    /// Seed marks in the order shown: shuffled blocks of nine (each mark equally often), never the same twice in a row.
    public let queue: [Int]
    public private(set) var index = 0
    public private(set) var phase: Phase = .idle
    public private(set) var trials: [GameTrial] = []
    public var interrupted = false
    private var shownAt: TimeInterval = 0
    private var scoredStart: TimeInterval = 0
    private var startedAt: TimeInterval = 0
    private var endedAt: TimeInterval = 0

    public init<R: RandomNumberGenerator>(using rng: inout R) {
        key = Array(1...Self.symbols).shuffled(using: &rng)
        var q: [Int] = []
        for _ in 0..<24 {
            var block = Array(0..<Self.symbols).shuffled(using: &rng)
            if let last = q.last, block[0] == last { block.swapAt(0, Self.symbols - 1) }
            q += block
        }
        queue = q
    }

    public var current: Int { queue[min(index, queue.count - 1)] }
    public var answer: Int { key[current] }
    public var correct: Int { trials.filter { !$0.practice && $0.code == "c" }.count }

    public func progress(at t: TimeInterval) -> Double {
        switch phase {
        case .scored: return min(1, (t - scoredStart) / Self.duration)
        case .done: return 1
        default: return 0
        }
    }

    public mutating func begin(at t: TimeInterval) {
        startedAt = t; shownAt = t; index = 0; trials = []
        phase = .practice
    }

    /// Returns true when the timed part just ended.
    @discardableResult
    public mutating func tick(at t: TimeInterval) -> Bool {
        guard phase == .scored, t - scoredStart >= Self.duration else { return false }
        phase = .done; endedAt = t
        return true
    }

    /// The person picked a pot. nil = ignored. Practice: a wrong pot does not move on (the answer is shown).
    @discardableResult
    public mutating func pick(_ digit: Int, at t: TimeInterval) -> Bool? {
        guard phase == .practice || phase == .scored, (1...Self.symbols).contains(digit), index < queue.count else { return nil }
        tick(at: t)
        guard phase != .done else { return nil }
        let right = digit == answer
        let rt = Int(((t - shownAt) * 1000).rounded())
        let practising = phase == .practice
        trials.append(GameTrial(code: right ? "c" : "x", rt_ms: min(10_000, max(0, rt)), practice: practising,
                                detail: ["symbol": Double(current), "digit": Double(digit)]))
        if practising && !right { return false }
        index += 1
        shownAt = t
        if practising && index >= Self.practice { phase = .scored; scoredStart = t }
        if index >= queue.count { phase = .done; endedAt = t }
        return right
    }

    public var flags: [PlayFlag] {
        let s = trials.filter { !$0.practice }
        let right = s.filter { $0.code == "c" }
        var f: [PlayFlag] = []
        if s.count < Self.minAnswers { f.append(.few_trials) }
        if !s.isEmpty && Double(right.count) / Double(s.count) < Self.minAccuracy { f.append(.low_accuracy) }
        if let m = Stats.median(s.map { Double($0.rt_ms) }), m < Self.tooFastMs { f.append(.too_fast) }
        if interrupted { f.append(.interrupted) }
        return f
    }

    public func session(device: PlayDevice, input: PlayInput?) -> PlaySession {
        let s = trials.filter { !$0.practice }
        let right = s.filter { $0.code == "c" }
        var out = PlaySession(game: .seeds, device: device, duration_s: max(0, (phase == .done ? endedAt : shownAt) - startedAt))
        out.throughput_per_min = GameStats.round(Double(right.count) / (Self.duration / 60), 2)
        out.accuracy = s.isEmpty ? nil : GameStats.round(Double(right.count) / Double(s.count), 3)
        out.reaction_ms_median = Stats.median(right.map { Double($0.rt_ms) }).map { min(5000, GameStats.round($0, 1)) }
        out.reaction_ms_iqr = Stats.iqr(right.map { Double($0.rt_ms) }).map { min(5000, GameStats.round($0, 1)) }
        out.trials_n = s.count
        out.valid_n = right.count
        out.input = input
        let f = flags
        out.valid = f.isEmpty
        out.flags = f.isEmpty ? nil : f
        out.rt_ms = s.prefix(Self.maxSent).map(\.rt_ms)
        out.trial_codes = s.prefix(Self.maxSent).map(\.code).joined()
        return out
    }
}

/// The nine seed marks (drawn glyphs in token colours; the pairing with pots changes, the marks do not).
enum SeedMark {
    static let glyphs = ["leaf.fill", "drop.fill", "sun.max.fill", "moon.fill", "star.fill", "cloud.fill", "snowflake",
                         "flame.fill", "mountain.2.fill"]
    static func color(_ i: Int) -> Color {
        [KaikuTokens.Colors.sage, KaikuTokens.Colors.sky, KaikuTokens.Colors.honey, KaikuTokens.Colors.clay][i % 4]
    }
    static func image(_ i: Int, size: CGFloat) -> some View {
        Image(systemName: glyphs[i]).font(.system(size: size, weight: .semibold)).foregroundStyle(color(i))
    }
}

struct SeedField: View {
    let finish: (PlaySession?, Int) -> Void
    @State private var engine: SeedEngine = {
        var rng = SystemRandomNumberGenerator()
        return SeedEngine(using: &rng)
    }()
    @State private var input = InputTracker()
    @State private var wobbleAt = -10.0
    @State private var popAt = -10.0
    @State private var reported = false
    @Environment(\.accessibilityReduceMotion) private var rm
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var dts
    @FocusState private var focused: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { tl in
            let now = GameClock.now
            VStack(spacing: KaikuTokens.Space.s3) {
                ProgressBar(progress: engine.progress(at: now), color: KaikuTokens.Colors.sage)
                    .padding(.horizontal, KaikuTokens.Space.s2)
                shelf
                Text(engine.phase == .practice ? T("sd.practice") : T("sd.go"))
                    .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps().multilineTextAlignment(.center)
                packet(now: now)
                SproutRow(count: engine.correct, rows: 1).frame(height: 30)
                keypad
            }
            .onChange(of: tl.date) { _, _ in step() }
        }
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(phases: .down) { press in
            guard let n = Int(press.characters), (1...9).contains(n) else { return .ignored }
            pick(n, .keyboard)
            return .handled
        }
        .onChange(of: scenePhase) { _, p in if p != .active { engine.interrupted = true } }
        .onAppear {
            engine.begin(at: GameClock.now)
            focused = true
            KSound.warmUp([.note(0), .note(2), .wobble])
        }
    }

    /// The shelf: nine seed marks, each over its pot number. Practice lights the pair for the packet in hand.
    private var shelf: some View {
        HStack(spacing: 3) {
            ForEach(0..<SeedEngine.symbols, id: \.self) { i in
                let hint = engine.phase == .practice && engine.current == i
                VStack(spacing: 2) {
                    SeedMark.image(i, size: 17).frame(height: 22)
                    Text("\(engine.key[i])").kText(.callout, weight: .semibold, mono: true).foregroundStyle(KaikuTokens.Colors.ink)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(hint ? KaikuTokens.Colors.honeySoft : KaikuTokens.Colors.surface))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(hint ? KaikuTokens.Colors.honey : KaikuTokens.Colors.line, lineWidth: hint ? 2 : 1))
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(T("a11y.seedshelf"))
    }

    private func packet(now: TimeInterval) -> some View {
        let w = now - wobbleAt
        let dx: CGFloat = (w < 0.4 && !rm) ? CGFloat(sin(w * 40) * 7 * (1 - w / 0.4)) : 0
        let pop = now - popAt
        return HStack(spacing: KaikuTokens.Space.s4) {
            MascotView(state: pop < 0.6 ? .happy : .idle, size: 84, tappable: false).accessibilityHidden(true)
            SeedMark.image(engine.current, size: 46)
                .frame(width: 96, height: 108)
                .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(KaikuTokens.Colors.surface)
                    .shadow(color: KaikuTokens.Colors.ink.opacity(0.08), radius: 8, y: 3))
                .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
                .offset(x: dx)
                .id(engine.index)
                .transition(rm ? .opacity : .opacity.combined(with: .scale(scale: 0.9)))
                .accessibilityLabel(T("a11y.seedpacket", n: engine.current + 1))
        }
        .frame(maxHeight: .infinity)
        .animation(KaikuTokens.Easing.gentleOut(0.12), value: engine.index)
    }

    private var keypad: some View {
        let side: CGFloat = dts.isAccessibilitySize ? 60 : (KaikuPlatform.isPhone ? 54 : 50)
        return VStack(spacing: 8) {
            ForEach(0..<3, id: \.self) { r in
                HStack(spacing: 8) {
                    ForEach(1...3, id: \.self) { c in
                        let n = r * 3 + c
                        Button { pick(n, InputTracker.pointing) } label: {
                            Text("\(n)").kText(.title3, weight: .semibold, mono: true).foregroundStyle(KaikuTokens.Colors.ink)
                                .frame(maxWidth: 110).frame(height: side)
                                .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(KaikuTokens.Colors.surface))
                                .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(KaikuTokens.Colors.pebbleEdge, lineWidth: 1.5))
                                .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                        }
                        .buttonStyle(.kPress)
                        .kPointer()
                        .accessibilityLabel(T("a11y.pot", n: n))
                    }
                }
            }
        }
    }

    private func step() {
        if engine.tick(at: GameClock.now) || (engine.phase == .done && !reported) { report() }
    }

    private func report() {
        guard !reported else { return }
        reported = true
        let s = engine.session(device: KaikuPlatform.device, input: input.value)
        let trials = engine.trials
        Task { await GameTrialLog.shared.append(game: .seeds, input: input.value, trials: trials) }
        finish(s, engine.correct)
    }

    private func pick(_ n: Int, _ how: PlayInput) {
        input.note(how)
        guard let right = engine.pick(n, at: GameClock.now) else { return }
        if right {
            popAt = GameClock.now
            KSound.play(.note(engine.correct % 5))
            Haptics.catchFirefly()
        } else {
            wobbleAt = GameClock.now
            KSound.play(.wobble)
            Haptics.softTap()
        }
        if engine.phase == .done { report() }
    }
}

/// Sprouts along a line of soil: one per right pot (capped for space, no number).
struct SproutRow: View {
    let count: Int
    var rows = 1
    var body: some View {
        Canvas { ctx, size in
            let perRow = rows == 1 ? 24 : 12
            let shown = min(count, perRow * rows)
            let rowH = size.height / CGFloat(rows)
            for r in 0..<rows {
                let y = rowH * CGFloat(r + 1) - 3
                var soil = Path()
                soil.move(to: CGPoint(x: 0, y: y)); soil.addLine(to: CGPoint(x: size.width, y: y))
                ctx.stroke(soil, with: .color(KaikuTokens.Colors.pebbleEdge.opacity(0.7)), style: StrokeStyle(lineWidth: 2, lineCap: .round))
            }
            for i in 0..<shown {
                let r = i / perRow
                let x = (CGFloat(i % perRow) + 0.5) / CGFloat(perRow) * size.width
                let y = rowH * CGFloat(r + 1) - 3
                let h = min(rowH - 8, 16 + CGFloat((i * 7) % 5))
                var stem = Path()
                stem.move(to: CGPoint(x: x, y: y)); stem.addLine(to: CGPoint(x: x, y: y - h))
                ctx.stroke(stem, with: .color(KaikuTokens.Colors.sage), style: StrokeStyle(lineWidth: 2, lineCap: .round))
                for side in [-1.0, 1.0] {
                    let leaf = Path(ellipseIn: CGRect(x: x + (side < 0 ? -6 : 0), y: y - h - 2, width: 6, height: 4))
                    ctx.fill(leaf, with: .color(KaikuTokens.Colors.sage))
                }
            }
        }
        .accessibilityHidden(true)
    }
}

/// Intro demo: a little shelf, a packet, the matching pot lights and a sprout grows.
struct SeedDemo: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20, paused: rm)) { tl in
            let t = rm ? 2.0 : tl.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 3.2)
            VStack(spacing: KaikuTokens.Space.s3) {
                HStack(spacing: 6) {
                    ForEach(0..<4, id: \.self) { i in
                        let on = i == 2 && t > 0.8
                        VStack(spacing: 2) {
                            SeedMark.image(i, size: 18).frame(height: 24)
                            Text("\([3, 1, 4, 2][i])").kText(.callout, weight: .semibold, mono: true).foregroundStyle(KaikuTokens.Colors.ink)
                        }
                        .frame(width: 44).padding(.vertical, 6)
                        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(on ? KaikuTokens.Colors.honeySoft : KaikuTokens.Colors.surface))
                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(on ? KaikuTokens.Colors.honey : KaikuTokens.Colors.line, lineWidth: on ? 2 : 1))
                    }
                }
                HStack(spacing: KaikuTokens.Space.s4) {
                    SeedMark.image(2, size: 34).frame(width: 64, height: 72)
                        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(KaikuTokens.Colors.surface))
                        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
                    Image(systemName: "arrow.right").foregroundStyle(KaikuTokens.Colors.muted)
                    Text("4").kText(.title3, weight: .semibold, mono: true).foregroundStyle(KaikuTokens.Colors.ink)
                        .frame(width: 56, height: 50)
                        .background(RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .fill(t > 1.6 ? KaikuTokens.Colors.sageSoft : KaikuTokens.Colors.surface))
                        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(KaikuTokens.Colors.pebbleEdge, lineWidth: 1.5))
                }
                SproutRow(count: t > 2.0 ? 4 : 3).frame(width: 200, height: 28)
            }
            .padding(KaikuTokens.Space.s3)
        }
        .accessibilityHidden(true)
    }
}

import SwiftUI

/// Firefly (go/no-go, 60 s). Fireflies glow for 1.5 s: tap them. Moths drift: let them go. Records reaction
/// median + IQR (correct taps), lapses (missed fireflies or responses slower than the contract's 500 ms) and
/// false taps (moths). The end shows the jar, never a number.
public struct FireflyGame: View {
    @State private var caught = 0
    public init() {}

    public var body: some View {
        GameShell(titleKey: "game.firefly.t", introText: T("ff.intro"), introState: .happy,
                  endText: caught > 0 ? T("ff.end") : T("ff.end.none"),
                  field: { finish in FireflyField { session, n in caught = n; finish(session) } },
                  endArt: { FireflyJar(count: caught).frame(width: 150, height: 170) })
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
    }

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

    var progress: Double { min(1, now.timeIntervalSince(started) / Self.duration) }

    func start(_ at: Date = Date()) {
        started = at; now = at; nextSpawn = at.addingTimeInterval(0.8)
        items = []; reactions = []; lapses = 0; falseTaps = 0; caught = 0; done = false; reported = false
    }

    func tick(_ t: Date) {
        guard !done else { return }
        now = t
        // expire
        for i in items.indices.reversed() {
            let age = t.timeIntervalSince(items[i].born)
            if age > Self.glow {
                if !items[i].moth && !items[i].tapped { lapses += 1 }
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

    func tap(_ id: UUID, at t: Date = Date()) {
        guard let i = items.firstIndex(where: { $0.id == id }), !items[i].tapped else { return }
        if items[i].moth {
            falseTaps += 1
            items.remove(at: i)
            return
        }
        let ms = t.timeIntervalSince(items[i].born) * 1000
        reactions.append(ms)
        if ms > Self.lapseMs { lapses += 1 }
        caught += 1
        items[i].tapped = true
        items.remove(at: i)
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

struct FireflyField: View {
    let finish: (PlaySession?, Int) -> Void
    @State private var engine = FireflyEngine()
    @Environment(\.accessibilityReduceMotion) private var rm

    var body: some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            HStack(spacing: KaikuTokens.Space.s3) {
                ProgressRing(progress: engine.progress, color: KaikuTokens.Colors.honey).frame(width: 28, height: 28)
                Text(T("ff.intro")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            GeometryReader { geo in
                TimelineView(.animation(minimumInterval: 1.0 / 30)) { tl in
                    ZStack {
                        RoundedRectangle(cornerRadius: KaikuTokens.Radius.xl, style: .continuous)
                            .fill(LinearGradient(colors: [KaikuTokens.Colors.skySoft, KaikuTokens.Colors.surface2],
                                                 startPoint: .top, endPoint: .bottom))
                        // grass
                        VStack { Spacer(); GardenPatch(plants: 12, resting: false, height: 40).padding(.horizontal) }
                        ForEach(engine.items) { item in
                            let age = tl.date.timeIntervalSince(item.born)
                            let k = rm ? 0 : age
                            let p = CGPoint(x: (item.pos.x + item.drift.dx * k) * geo.size.width,
                                            y: (item.pos.y + item.drift.dy * k) * geo.size.height)
                            Button { engine.tap(item.id) } label: {
                                Group {
                                    if item.moth { Moth() } else { Firefly(age: age, reduceMotion: rm) }
                                }
                                .frame(width: 64, height: 64)
                                .contentShape(Circle())
                            }
                            .buttonStyle(.plain)
                            .position(p)
                            .accessibilityLabel(item.moth ? T("a11y.moth") : T("a11y.firefly"))
                            .transition(.opacity)
                        }
                    }
                    .onChange(of: tl.date) { _, d in
                        engine.tick(d)
                        if engine.done && !engine.reported { engine.reported = true; finish(engine.session(device: KaikuPlatform.device), engine.caught) }
                    }
                }
            }
            .frame(minHeight: 240)
        }
        .onAppear { engine.start() }
    }
}

struct Firefly: View {
    let age: Double
    let reduceMotion: Bool
    var body: some View {
        // Glow rises over 0.3 s and fades over the last 0.4 s of its 1.5 s (never flashes).
        let a = reduceMotion ? 1 : min(1, age / 0.3) * min(1, max(0, (FireflyEngine.glow - age) / 0.4))
        ZStack {
            Circle().fill(RadialGradient(colors: [KaikuTokens.Colors.mascotSparkle.opacity(0.9), KaikuTokens.Colors.mascotSparkle.opacity(0)],
                                         center: .center, startRadius: 2, endRadius: 30))
            Circle().fill(KaikuTokens.Colors.mascotSparkle).frame(width: 14, height: 14)
            Circle().fill(KaikuTokens.Colors.mascotShine).frame(width: 5, height: 5)
        }
        .opacity(0.25 + 0.75 * a)
    }
}

struct Moth: View {
    var body: some View {
        ZStack {
            Ellipse().fill(KaikuTokens.Colors.muted.opacity(0.55)).frame(width: 22, height: 16).offset(x: -9).rotationEffect(.degrees(-18))
            Ellipse().fill(KaikuTokens.Colors.muted.opacity(0.55)).frame(width: 22, height: 16).offset(x: 9).rotationEffect(.degrees(18))
            Capsule().fill(KaikuTokens.Colors.ink2).frame(width: 5, height: 18)
        }
    }
}

/// The end art: a jar with one glowing dot per firefly caught (capped for space), no number.
struct FireflyJar: View {
    let count: Int
    var body: some View {
        Canvas { ctx, size in
            let jar = CGRect(x: size.width * 0.15, y: size.height * 0.18, width: size.width * 0.7, height: size.height * 0.78)
            ctx.fill(Path(roundedRect: jar, cornerRadius: 22), with: .color(KaikuTokens.Colors.skySoft.opacity(0.8)))
            ctx.stroke(Path(roundedRect: jar, cornerRadius: 22), with: .color(KaikuTokens.Colors.line), lineWidth: 3)
            let lid = CGRect(x: size.width * 0.25, y: size.height * 0.08, width: size.width * 0.5, height: size.height * 0.1)
            ctx.fill(Path(roundedRect: lid, cornerRadius: 6), with: .color(KaikuTokens.Colors.mascotShade))
            var rng = SeededRandom(seed: 7)
            for _ in 0..<min(count, 40) {
                let p = CGPoint(x: jar.minX + 14 + rng.next() * (jar.width - 28), y: jar.minY + 14 + rng.next() * (jar.height - 28))
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 10, y: p.y - 10, width: 20, height: 20)),
                         with: .radialGradient(Gradient(colors: [KaikuTokens.Colors.mascotSparkle.opacity(0.8), .clear]),
                                               center: p, startRadius: 0, endRadius: 10))
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 3, y: p.y - 3, width: 6, height: 6)), with: .color(KaikuTokens.Colors.mascotSparkle))
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

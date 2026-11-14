import SwiftUI

/// Breathe with Kaiku: 6 breaths a minute (10 s cycle: 5 s in, 5 s out). Kaiku `breathing` in a glow pool that
/// swells on the in-breath; a countdown ring empties over each phase; the cue word + seconds left; six breath
/// dots as the quiet progress. Haptic tick on each turn (if on), a very soft tone. Records obs.play_session
/// {game: breathe}. Reduce Motion: Kaiku still, the glow cross-fades, the words carry the rhythm.
public struct BreatheView: View {
    public init() {}
    public var body: some View {
        GameShell(titleKey: "game.breathe.t", scene: .calm, introText: T("game.breathe.d"), introState: .breathing, endText: T("br.end"),
                  demo: { BreatheDemo() },
                  field: { finish in BreatheField(finish: finish) },
                  endArt: { EmptyView() })
    }
}

struct BreatheField: View {
    let finish: (PlaySession?) -> Void
    static let breaths = 6
    @State private var start = Date()
    @State private var lastHalf = -1
    @State private var finished = false
    @Environment(\.accessibilityReduceMotion) private var rm
    @Environment(AppModel.self) private var app

    var cycle: Double { 60 / KaikuTokens.GuideBreath.breathsPerMinute }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { tl in
            let t = tl.date.timeIntervalSince(start)
            let n = min(Self.breaths, Int(t / cycle) + 1)
            let ph = t.truncatingRemainder(dividingBy: cycle) / cycle
            let inhale = ph < KaikuTokens.GuideBreath.inhaleRatio
            let phaseK = inhale ? ph * 2 : (ph - 0.5) * 2               // 0..1 within the phase
            let k = KaikuCurve.ease("soft-in-out", inhale ? phaseK : 1 - phaseK)  // breath "fullness"
            let left = max(1, Int(ceil(cycle / 2 * (1 - phaseK))))
            let (glow, _) = GlowClock.current(tl.date)
            VStack(spacing: KaikuTokens.Space.s4) {
                Spacer(minLength: 0)
                RingStage(maxSide: 300, minSide: 150) { side in
                    ZStack {
                        Circle()
                            .fill(RadialGradient(colors: [glow.opacity(rm ? (inhale ? 0.55 : 0.3) : 0.25 + 0.4 * k), glow.opacity(0)],
                                                 center: .center, startRadius: 0, endRadius: side * 0.5))
                            .scaleEffect(rm ? 1 : 0.8 + 0.25 * k)
                            .animation(rm ? .easeInOut(duration: KaikuTokens.Duration.slow) : nil, value: inhale)
                        Circle()
                            .strokeBorder(KaikuTokens.Colors.sage.opacity(0.45), style: StrokeStyle(lineWidth: 2, dash: [5, 7]))
                            .scaleEffect(rm ? 1 : 0.84 + 0.16 * k)
                        ProgressRing(progress: 1 - phaseK, color: inhale ? KaikuTokens.Colors.sage : KaikuTokens.Colors.sky,
                                     width: 5, track: KaikuTokens.Colors.sage.opacity(0.12))
                            .padding(side * 0.02)
                        MascotView(state: .breathing, size: side * 0.6, tappable: false, cycleStart: start)
                    }
                }
                VStack(spacing: 2) {
                    Text(inhale ? T("br.in") : T("br.out"))
                        .kText(.title1)
                        .foregroundStyle(KaikuTokens.Colors.ink)
                        .wraps()
                        .contentTransition(.opacity)
                        .animation(KaikuTokens.Easing.softInOut(KaikuTokens.Duration.slow), value: inhale)
                        .accessibilityAddTraits(.updatesFrequently)
                    Text(verbatim: String(left))
                        .kText(.title3, weight: .medium)
                        .monospacedDigit()
                        .foregroundStyle(KaikuTokens.Colors.muted)
                        .contentTransition(.numericText(countsDown: true))
                        .animation(.easeOut(duration: 0.2), value: left)
                        .accessibilityHidden(true)
                }
                HStack(spacing: 8) {
                    ForEach(1...Self.breaths, id: \.self) { i in
                        Circle()
                            .fill(i < n ? KaikuTokens.Colors.sage : (i == n ? KaikuTokens.Colors.sage.opacity(0.35 + 0.65 * ph) : KaikuTokens.Colors.sage.opacity(0.15)))
                            .frame(width: 9, height: 9)
                    }
                }
                .accessibilityElement()
                .accessibilityLabel(T("br.count", n: n))
                Spacer(minLength: 0)
                Button(T("br.stop")) { finish(nil) }
                    .buttonStyle(.kSecondary)
                    .frame(maxWidth: 420)
            }
            .frame(maxWidth: .infinity)
            .onChange(of: Int(t / (cycle / 2))) { _, half in
                if half != lastHalf {
                    lastHalf = half
                    #if os(iOS)
                    if half % 2 == 0 { KaikuLiveActivities.updateBreathe(breath: min(Self.breaths, half / 2 + 1), total: Self.breaths) }
                    #endif
                    if app.breathHaptics { Haptics.breathTurn() }
                    if Double(half) * cycle / 2 < cycle * Double(Self.breaths) {
                        KSound.play(half % 2 == 0 ? .breathIn : .breathOut)
                    }
                }
                if t >= cycle * Double(Self.breaths), !finished {
                    finished = true
                    finish(PlaySession(game: .breathe, device: KaikuPlatform.device, duration_s: t))
                }
            }
        }
        .onAppear {
            start = Date()
            KSound.play(.breathIn)
            #if os(iOS)
            KaikuLiveActivities.startBreathe(lang: app.language.rawValue, total: Self.breaths)
            #endif
        }
        .onDisappear {
            #if os(iOS)
            KaikuLiveActivities.endBreathe()
            #endif
        }
    }
}

/// Intro demo: a ring swells for "in" and settles for "out", with the cue word.
struct BreatheDemo: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: rm)) { tl in
            let t = rm ? 1.0 : tl.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 6)
            let inhale = t < 3
            let k = KaikuCurve.ease("soft-in-out", inhale ? t / 3 : 1 - (t - 3) / 3)
            VStack(spacing: KaikuTokens.Space.s2) {
                ZStack {
                    Circle().fill(KaikuTokens.Colors.sage.opacity(0.18 + 0.2 * k)).frame(width: 64 + 50 * k, height: 64 + 50 * k)
                    MascotView(state: .breathing, size: 70, tappable: false)
                }
                .frame(height: 120)
                Text(inhale ? T("br.in") : T("br.out")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink2)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .accessibilityHidden(true)
    }
}

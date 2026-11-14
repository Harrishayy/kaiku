import SwiftUI

/// Breathe with Kaiku: 6 breaths a minute (10 s cycle: 5 s in, 5 s out), Kaiku `breathing`, a dashed ring that
/// grows with the breath, cue words, "Breath n of 6", Stop. Records obs.play_session {game: breathe}.
public struct BreatheView: View {
    public init() {}
    public var body: some View {
        GameShell(titleKey: "game.breathe.t", introText: T("game.breathe.d"), introState: .breathing, endText: T("br.end"),
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
            let k = KaikuCurve.ease("soft-in-out", inhale ? ph * 2 : (1 - ph) * 2)
            VStack(spacing: KaikuTokens.Space.s4) {
                Spacer(minLength: 0)
                RingStage(maxSide: 250, minSide: 72) { side in
                    ZStack {
                        Circle()
                            .strokeBorder(KaikuTokens.Colors.sage, style: StrokeStyle(lineWidth: 3, dash: [6, 8]))
                            .scaleEffect(rm ? 1 : 0.82 + 0.18 * k)
                            .opacity(rm ? (inhale ? 1 : 0.5) : 1)
                        MascotView(state: .breathing, size: side * 0.68, tappable: false, cycleStart: start)
                    }
                }
                Text(inhale ? T("br.in") : T("br.out"))
                    .kText(.title2)
                    .foregroundStyle(KaikuTokens.Colors.ink)
                    .wraps()
                    .contentTransition(.opacity)
                    .animation(KaikuTokens.Easing.softInOut(KaikuTokens.Duration.slow), value: inhale)
                    .accessibilityAddTraits(.updatesFrequently)
                Text(T("br.count", n: n)).kText(.body).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                Spacer(minLength: 0)
                Button(T("br.stop")) { finish(nil) }.buttonStyle(.kSecondary)
            }
            .frame(maxWidth: .infinity)
            .onChange(of: Int(t / (cycle / 2))) { _, half in
                if half != lastHalf {
                    lastHalf = half
                    if app.breathHaptics { Haptics.breathTurn() }
                }
                if t >= cycle * Double(Self.breaths), !finished {
                    finished = true
                    finish(PlaySession(game: .breathe, device: KaikuPlatform.device, duration_s: t))
                }
            }
        }
        .onAppear { start = Date() }
    }
}

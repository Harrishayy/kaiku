import SwiftUI

/// Play: game cards (icon, title, one line, minutes under the title), today's suggested game first.
public struct PlayView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dynamicTypeSize) private var dts
    public init() {}

    struct Card: Identifiable {
        let route: KaikuRoute
        let key: String
        let symbol: String
        let tint: Color
        let minutes: Int
        var id: String { key }
    }

    var cards: [Card] {
        var c = [
            Card(route: .firefly, key: "firefly", symbol: "sparkle", tint: KaikuTokens.Colors.honey, minutes: 1),
            Card(route: .pebbles, key: "pebbles", symbol: "circle.grid.3x3", tint: KaikuTokens.Colors.sky, minutes: 2),
            Card(route: .tell, key: "tell", symbol: "ear", tint: KaikuTokens.Colors.clay, minutes: 1),
            Card(route: .breathe, key: "breathe", symbol: "wind", tint: KaikuTokens.Colors.sage, minutes: 1),
        ]
        if KaikuPlatform.isPhone {
            c.append(Card(route: .walk, key: "lighthunt", symbol: "figure.walk", tint: KaikuTokens.Colors.sage, minutes: 15))
        }
        let first: String? = switch app.nudge?.arm {
        case .breathe?: "breathe"
        case .icbt_exercise?: "tell"
        case .daylight_walk?: KaikuPlatform.isPhone ? "lighthunt" : nil
        default: nil
        }
        if let f = first, let i = c.firstIndex(where: { $0.key == f }) { c.insert(c.remove(at: i), at: 0) }
        return c
    }

    public var body: some View {
        KScreen(T("play.title")) {
            Text(T("play.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            ForEach(cards) { card in
                NavigationLink(value: card.route) {
                    KCard {
                        HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
                            if !dts.isAccessibilitySize { RowIcon(symbol: card.symbol, tint: card.tint) }
                            VStack(alignment: .leading, spacing: 4) {
                                Text(T("game.\(card.key).t")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                                Text(T("game.\(card.key).d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                                Text(T("game.time", n: card.minutes)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold))
                                .foregroundStyle(KaikuTokens.Colors.muted).padding(.top, 8)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }
}

/// Every game: intro → play → gentle end (Kaiku cheering then happy; "Play again" / "That's enough for today").
/// `play` gets a `finish` callback with the session to record (nil = ended early, nothing recorded).
struct GameShell<Field: View, EndArt: View>: View {
    enum Phase { case intro, play, end }
    let titleKey: String
    let introText: String
    let introState: MascotState
    let endText: String
    @ViewBuilder let field: (_ finish: @escaping (PlaySession?) -> Void) -> Field
    @ViewBuilder let endArt: () -> EndArt
    var onStart: () -> Void = {}

    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var phase: Phase = .intro
    @State private var round = 0

    var body: some View {
        switch phase {
        case .intro:
            KScreen(T(titleKey), back: { dismiss() }) {
                // Dev hook for screenshots (`-kaikuAutostart YES`): skip the intro once.
                let _ = autostartOnce()
                MascotView(state: introState, size: 170).frame(maxWidth: .infinity)
                Text(introText).kText(.title3, weight: .regular).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                VStack(spacing: KaikuTokens.Space.s2) {
                    Button(T("game.start")) { start() }.buttonStyle(.kPrimary)
                    Button(T("common.nottoday")) { dismiss() }.buttonStyle(.kGhost)
                }
            }
        case .play:
            KScreen(T(titleKey), back: { phase = .intro }, scrolls: false) {
                field { session in
                    if let s = session {
                        Haptics.finished()
                        Task { await app.recordPlay(s) }
                        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base)) { phase = .end }
                    } else {
                        phase = .intro
                    }
                }
                .id(round)
            }
        case .end:
            KScreen(T(titleKey), back: { dismiss() }) {
                MascotView(state: .cheering, size: 150).frame(maxWidth: .infinity)
                endArt().frame(maxWidth: .infinity)
                Text(endText).kText(.title3, weight: .regular).foregroundStyle(KaikuTokens.Colors.ink)
                    .multilineTextAlignment(.center).wraps().frame(maxWidth: .infinity)
                VStack(spacing: KaikuTokens.Space.s2) {
                    Button(T("game.again")) { start() }.buttonStyle(.kSecondary)
                    Button(T("game.enough")) { dismiss() }.buttonStyle(.kGhost)
                }
            }
        }
    }

    private func autostartOnce() -> Bool {
        if round == 0, UserDefaults.standard.bool(forKey: "kaikuAutostart") {
            DispatchQueue.main.async { if round == 0 { start() } }
        }
        return true
    }

    private func start() {
        round += 1
        onStart()
        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { phase = .play }
    }
}

/// A thin progress ring (time left in a game, the hold ring in Tell Kaiku). Never shows a number.
struct ProgressRing: View {
    let progress: Double
    var color: Color = KaikuTokens.Colors.clay
    var width: CGFloat = 6
    var body: some View {
        ZStack {
            Circle().stroke(KaikuTokens.Colors.line, lineWidth: width)
            Circle().trim(from: 0, to: max(0, min(1, progress)))
                .stroke(color, style: StrokeStyle(lineWidth: width, lineCap: .round))
                .rotationEffect(.degrees(-90))
        }
        .accessibilityHidden(true)
    }
}

enum Stats {
    static func median(_ xs: [Double]) -> Double? {
        guard !xs.isEmpty else { return nil }
        let s = xs.sorted()
        return s.count % 2 == 1 ? s[s.count / 2] : (s[s.count / 2 - 1] + s[s.count / 2]) / 2
    }

    /// Interquartile range (linear interpolation, like numpy's default).
    static func iqr(_ xs: [Double]) -> Double? {
        guard xs.count >= 2 else { return xs.isEmpty ? nil : 0 }
        let s = xs.sorted()
        func q(_ p: Double) -> Double {
            let pos = p * Double(s.count - 1)
            let lo = Int(pos.rounded(.down)), hi = Int(pos.rounded(.up))
            return s[lo] + (s[hi] - s[lo]) * (pos - Double(lo))
        }
        return q(0.75) - q(0.25)
    }
}

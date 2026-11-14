import SwiftUI

/// Play: one card per game with a little scene tile (night jar, pond, ear, breath rings), title, one line and
/// minutes; today's suggested game first. iPhone: a compact list that fits one screen. Mac: a 2 × 2 grid.
public struct PlayView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dynamicTypeSize) private var dts
    public init() {}

    struct Card: Identifiable {
        let route: KaikuRoute
        let key: String
        let tone: KTone
        let minutes: Int
        var id: String { key }
    }

    var cards: [Card] {
        var c = [
            Card(route: .lantern, key: "lantern", tone: .honey, minutes: 2),
            Card(route: .seeds, key: "seeds", tone: .sage, minutes: 2),
            Card(route: .pebbles, key: "pebbles", tone: .sky, minutes: 2),
            Card(route: .watering, key: "watering", tone: .clay, minutes: 2),
            Card(route: .firefly, key: "firefly", tone: .honey, minutes: 1),
            Card(route: .tell, key: "tell", tone: .clay, minutes: 1),
            Card(route: .breathe, key: "breathe", tone: .sage, minutes: 1),
        ]
        if KaikuPlatform.isPhone {
            c.append(Card(route: .walk, key: "lighthunt", tone: .sage, minutes: 15))
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
        KScreen(T("play.title"), subtitle: T("play.body"), maxWidth: 1000, spacing: KaikuTokens.Space.s4) {
            TodayPathCard()
            SectionHeader(T("play.all"), subtitle: T("play.all.d"), icon: "square.grid.2x2.fill", tone: .honey)
            WideAware { wide in
                if wide {
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: KaikuTokens.Space.s4), GridItem(.flexible())],
                              spacing: KaikuTokens.Space.s4) {
                        ForEach(cards) { card in link(card, tall: true) }
                    }
                } else {
                    VStack(spacing: KaikuTokens.Space.s3) {
                        ForEach(cards) { card in link(card, tall: false) }
                    }
                }
            }
        }
    }

    private func link(_ card: Card, tall: Bool) -> some View {
        NavigationLink(value: card.route) { GameCard(card: card, tall: tall) }
            .buttonStyle(.kPress)
    }
}

struct GameCard: View {
    let card: PlayView.Card
    let tall: Bool
    @Environment(\.dynamicTypeSize) private var dts

    var body: some View {
        Group {
            if tall {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
                    GameTile(key: card.key, tone: card.tone).frame(height: 104)
                    text
                }
            } else {
                HStack(alignment: .center, spacing: KaikuTokens.Space.s4) {
                    if !dts.isAccessibilitySize { GameTile(key: card.key, tone: card.tone).frame(width: 64, height: 64) }
                    text.frame(maxWidth: .infinity, alignment: .leading)
                    Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)).foregroundStyle(KaikuTokens.Colors.muted)
                }
            }
        }
        .padding(tall ? KaikuTokens.Space.s3 : KaikuTokens.Space.s3)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
                .shadow(color: KaikuTokens.Colors.ink.opacity(0.05), radius: 10, y: 4)
        )
        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
        .contentShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous))
        .accessibilityElement(children: .combine)
    }

    private var text: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(T("game.\(card.key).t")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("game.\(card.key).d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            Text(T("game.time", n: card.minutes))
                .kText(.caption).foregroundStyle(card.tone.ink)
                .padding(.horizontal, 8).padding(.vertical, 3)
                .background(Capsule().fill(card.tone.soft))
                .padding(.top, 4)
        }
        .padding(.horizontal, tall ? KaikuTokens.Space.s1 : 0)
    }
}

/// A small illustrated scene per game, in its tone (no stock icons): a jar of light at night, stones on a pond,
/// Kaiku's ear on clay, breath rings on sage.
struct GameTile: View {
    let key: String
    let tone: KTone
    var body: some View {
        ZStack {
            switch key {
            case "firefly":
                LinearGradient(colors: [KaikuTokens.Colors.nightA, KaikuTokens.Colors.nightB], startPoint: .top, endPoint: .bottom)
                Canvas { ctx, s in
                    for (x, y, r) in [(0.25, 0.32, 5.0), (0.62, 0.22, 4.0), (0.45, 0.62, 6.0), (0.8, 0.55, 3.5)] {
                        let p = CGPoint(x: s.width * x, y: s.height * y)
                        ctx.fill(Path(ellipseIn: CGRect(x: p.x - r * 3, y: p.y - r * 3, width: r * 6, height: r * 6)),
                                 with: .radialGradient(Gradient(colors: [KaikuTokens.Colors.firefly.opacity(0.6), .clear]),
                                                       center: p, startRadius: 0, endRadius: r * 3))
                        ctx.fill(Path(ellipseIn: CGRect(x: p.x - r / 2, y: p.y - r / 2, width: r, height: r)), with: .color(KaikuTokens.Colors.firefly))
                    }
                }
            case "pebbles":
                LinearGradient(colors: [KaikuTokens.Colors.pondA, KaikuTokens.Colors.pondB], startPoint: .top, endPoint: .bottom)
                Canvas { ctx, s in
                    let pts = [(0.22, 0.66), (0.48, 0.38), (0.76, 0.62)]
                    var line = Path()
                    for (i, (x, y)) in pts.enumerated() {
                        let p = CGPoint(x: s.width * x, y: s.height * y)
                        if i == 0 { line.move(to: p) } else { line.addLine(to: p) }
                    }
                    ctx.stroke(line, with: .color(KaikuTokens.Colors.sky.opacity(0.5)), style: StrokeStyle(lineWidth: 1.5, dash: [3, 4]))
                    for (i, (x, y)) in pts.enumerated() {
                        let r = CGRect(x: s.width * x - 11, y: s.height * y - 7, width: 22, height: 14)
                        ctx.fill(Path(ellipseIn: r), with: .color(i == 1 ? KaikuTokens.glowColor : KaikuTokens.Colors.pebble))
                        ctx.stroke(Path(ellipseIn: r), with: .color(KaikuTokens.Colors.pebbleEdge), lineWidth: 1.5)
                    }
                }
            case "lantern":
                LinearGradient(colors: [KaikuTokens.Colors.nightA, KaikuTokens.Colors.nightB], startPoint: .top, endPoint: .bottom)
                StarPatch(count: 7).padding(.bottom, 26)
                Lantern(lit: true, glow: 1).frame(width: 30, height: 42).offset(y: 12)
            case "seeds":
                tone.soft
                HStack(spacing: 8) { ForEach(0..<3, id: \.self) { SeedMark.image($0, size: 20) } }
            case "watering":
                tone.soft
                FlowerBed(count: 4, perRow: 6).padding(.horizontal, 6).padding(.vertical, 12)
            case "breathe":
                tone.soft
                ForEach(0..<3, id: \.self) { i in
                    Circle().strokeBorder(tone.ink.opacity(0.55 - Double(i) * 0.15), style: StrokeStyle(lineWidth: 2, dash: i == 2 ? [3, 4] : []))
                        .padding(CGFloat(10 + i * -6) + 6)
                }
                Circle().fill(tone.ink.opacity(0.25)).padding(22)
            default:
                tone.soft
                Image(systemName: key == "lighthunt" ? "figure.walk" : "ear.fill").font(.system(size: 26, weight: .semibold)).foregroundStyle(tone.ink)
                    .rotationEffect(.degrees(-12))
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .accessibilityHidden(true)
    }
}

extension KaikuTokens {
    /// The current time-of-day glow colour (a lit pebble, Kaiku's chest).
    static var glowColor: Color { GlowClock.current().0 }
}

/// The scene a game is played in (design artifact: night for Firefly, pond for Pebble path; calm washes for the
/// others). Night is dark in both themes, so its text uses `night-ink`.
enum GameScene {
    case night, pond, calm, warm

    var isDark: Bool { self == .night }
    var ink: Color { isDark ? KaikuTokens.Colors.nightInk : KaikuTokens.Colors.ink }
    var ink2: Color { isDark ? KaikuTokens.Colors.nightInk.opacity(0.78) : KaikuTokens.Colors.ink2 }
}

struct SceneBackground: View {
    let scene: GameScene
    var body: some View {
        ZStack {
            switch scene {
            case .night:
                LinearGradient(colors: [KaikuTokens.Colors.nightA, KaikuTokens.Colors.nightB], startPoint: .top, endPoint: .bottom)
                Canvas { ctx, s in
                    var rng = SeededRandom(seed: 11)
                    for _ in 0..<28 {
                        let p = CGPoint(x: rng.next() * s.width, y: rng.next() * s.height * 0.6)
                        let r = 0.6 + rng.next() * 1.1
                        ctx.fill(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)),
                                 with: .color(KaikuTokens.Colors.nightInk.opacity(0.18 + Double(rng.next()) * 0.3)))
                    }
                    // a low hill
                    var hill = Path()
                    hill.move(to: CGPoint(x: 0, y: s.height - 70))
                    hill.addQuadCurve(to: CGPoint(x: s.width, y: s.height - 50), control: CGPoint(x: s.width * 0.45, y: s.height - 120))
                    hill.addLine(to: CGPoint(x: s.width, y: s.height)); hill.addLine(to: CGPoint(x: 0, y: s.height)); hill.closeSubpath()
                    ctx.fill(hill, with: .color(Color.black.opacity(0.22)))
                }
            case .pond:
                LinearGradient(stops: [.init(color: KaikuTokens.Colors.bg, location: 0), .init(color: KaikuTokens.Colors.pondA, location: 0.22),
                                       .init(color: KaikuTokens.Colors.pondB, location: 1)], startPoint: .top, endPoint: .bottom)
            case .calm:
                LinearGradient(colors: [KaikuTokens.Colors.sageSoft, KaikuTokens.Colors.bg], startPoint: .top, endPoint: .bottom)
            case .warm:
                LinearGradient(colors: [KaikuTokens.Colors.honeySoft, KaikuTokens.Colors.bg], startPoint: .top, endPoint: .center)
                KaikuTokens.Colors.bg.opacity(0.001)
            }
        }
        // iPhone: full bleed. Mac: under the toolbar only — never under the sidebar (its glass would take the tint).
        .ignoresSafeArea(.container, edges: KaikuPlatform.isPhone ? .all : .top)
        .accessibilityHidden(true)
    }
}

/// Every game: intro (a tiny animated demo of what to do) → play (the field gets the room; a quiet progress
/// line, no score) → a warm end (Kaiku cheering, the game's art, "Play again" / "That's enough for today").
/// `field` gets a `finish` callback with the session to record (nil = ended early, nothing recorded). The tab bar
/// hides while a game is open; Esc / the back button leaves; Return starts.
struct GameShell<Demo: View, Field: View, EndArt: View>: View {
    enum Phase { case intro, play, end }
    let titleKey: String
    var scene: GameScene = .warm
    let introText: String
    let introState: MascotState
    let endText: String
    @ViewBuilder let demo: () -> Demo
    @ViewBuilder let field: (_ finish: @escaping (PlaySession?) -> Void) -> Field
    @ViewBuilder let endArt: () -> EndArt
    var onStart: () -> Void = {}

    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var rm
    @Environment(\.dynamicTypeSize) private var dts
    @State private var phase: Phase = .intro
    @State private var round = 0
    @State private var camera = TaskCamera()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        // The scene is a background, never a layout sibling: on macOS a safe-area-ignoring sibling fed its grown
        // size back into the pane (it grew past the window and clipped the sidebar + Start button).
        VStack(spacing: 0) {
            VStack(spacing: KaikuTokens.Space.s3) {
                topBar
                if phase == .play, camera.state != .off {
                    HStack(spacing: KaikuTokens.Space.s2) {
                        Image(systemName: "camera.fill")
                        Text(T(camera.state == .capturing ? "task.camera.active" : camera.state == .requesting ? "task.camera.request" : "task.camera.unavailable"))
                            .wraps()
                        Spacer(minLength: 0)
                        Button(T("task.camera.stop")) { camera.cancel(); app.consents[.camera] = false }
                    }
                    .kText(.footnote).foregroundStyle(scene.ink)
                    .accessibilityElement(children: .contain)
                }
                Group {
                    switch phase {
                    case .intro: intro
                    case .play: play
                    case .end: end
                    }
                }
                .frame(maxWidth: 720, maxHeight: .infinity)
                .frame(maxWidth: .infinity)
                .transition(rm ? .opacity : .opacity.combined(with: .scale(scale: 0.98)))
            }
            .padding(.horizontal, KaikuPlatform.sidePadding)
            .padding(.top, KaikuPlatform.isPhone ? KaikuTokens.Space.s2 : KaikuTokens.Space.s4)
            .padding(.bottom, KaikuTokens.Space.s4)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .fillsProposal()
        .background { SceneBackground(scene: scene) }
        .environment(\.colorScheme, scene.isDark ? .dark : colorSchemeFallback)
        .task(id: phase) {
            if phase == .play { await camera.begin(allowed: app.allowed(.camera) && app.allowed(.checkins)) }
        }
        .onDisappear { camera.cancel() }
        .onChange(of: app.allowed(.camera)) { _, allowed in if !allowed { camera.cancel() } }
        .onChange(of: app.allowed(.checkins)) { _, allowed in if !allowed { camera.cancel() } }
        .onChange(of: scenePhase) { _, state in
            if state != .active, phase == .play { camera.cancel(); phase = .intro }
        }
        #if os(iOS)
        .toolbar(.hidden, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
        #else
        .navigationTitle(T(titleKey))
        #endif
    }

    @Environment(\.colorScheme) private var colorSchemeFallback

    private func back() { camera.cancel(); if phase == .play { withAnimation(fade) { phase = .intro } } else { dismiss() } }

    @ViewBuilder private var topBar: some View {
        #if os(macOS)
        EscapeKey(action: back)   // Mac: system toolbar back + the game's name as the window title
        #else
        HStack(spacing: KaikuTokens.Space.s3) {
            BackButton(onDark: scene.isDark, action: back)
            if !dts.isAccessibilitySize || phase != .play {
                Text(T(titleKey)).kText(.title3, weight: .semibold).foregroundStyle(scene.ink)
                    .lineLimit(2).layoutPriority(1).accessibilityAddTraits(.isHeader)
            }
            Spacer(minLength: 0)
            NotOKPill(onDark: scene.isDark)
        }
        #endif
    }

    private var fade: Animation { KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast) }

    private var intro: some View {
        VStack(spacing: KaikuTokens.Space.s5) {
            Spacer(minLength: 0)
            // Dev hook for screenshots (`-kaikuAutostart YES`): skip the intro once.
            let _ = autostartOnce()
            demo()
                .frame(maxWidth: KaikuPlatform.isPhone ? 360 : 540, maxHeight: KaikuPlatform.isPhone ? 230 : 340)
                .frame(minHeight: 150)
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.xl, style: .continuous)
                    .fill(scene.isDark ? KaikuTokens.Colors.nightInk.opacity(0.06) : KaikuTokens.Colors.surface.opacity(0.7)))
                .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.xl, style: .continuous)
                    .strokeBorder(scene.isDark ? KaikuTokens.Colors.nightInk.opacity(0.14) : KaikuTokens.Colors.line, lineWidth: 1))
            Text(introText).kText(.title3, weight: .medium).foregroundStyle(scene.ink)
                .multilineTextAlignment(.center).wraps().frame(maxWidth: 440)
            Spacer(minLength: 0)
            VStack(spacing: KaikuTokens.Space.s1) {
                Toggle(isOn: Binding(get: { app.consents[.camera] == true }, set: { app.consents[.camera] = $0 })) {
                    Text(T("task.camera.optin")).kText(.footnote).wraps()
                }
                .tint(KaikuTokens.Colors.sage)
                .disabled(app.isPaused)
                Button(T("game.start")) { start() }
                    .buttonStyle(KButtonStyle(.primary))
                    .keyboardShortcut(.defaultAction)
                Button(T("common.nottoday")) { dismiss() }.buttonStyle(KButtonStyle(scene.isDark ? .nightGhost : .ghost))
            }
            .frame(maxWidth: 420)
        }
    }

    private var play: some View {
        field { session in
            guard phase == .play else { return }
            let summary = camera.finish()
            if var s = session {
                if app.allowed(.camera), let summary {
                    s.expressivity_index = summary.expressivity; s.face_movement = summary.movement
                    s.camera_face_coverage = summary.coverage; s.camera_samples = summary.samples
                    s.camera_method = "vision_landmarks"
                }
                Haptics.finished()
                KSound.play(.done)
                Task { await app.recordPlay(s) }
                withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base)) { phase = .end }
            } else {
                withAnimation(fade) { phase = .intro }
            }
        }
        .id(round)
    }

    private var end: some View {
        VStack(spacing: KaikuTokens.Space.s4) {
            Spacer(minLength: 0)
            ZStack {
                MascotHalo(size: 150)
                HStack(alignment: .bottom, spacing: KaikuTokens.Space.s2) {
                    MascotView(state: .cheering, size: 130)
                    endArt()
                }
            }
            .frame(maxWidth: .infinity)
            Text(endText).kText(.title3, weight: .medium).foregroundStyle(scene.ink)
                .multilineTextAlignment(.center).wraps().frame(maxWidth: 440)
            Spacer(minLength: 0)
            VStack(spacing: KaikuTokens.Space.s1) {
                if let next = app.nextPathStep {
                    // Duolingo-style: the end of one step hands you the next, no menu needed.
                    Button(T("path.upnext", ["name": T(next.titleKey)])) { app.go(next) }
                        .buttonStyle(KButtonStyle(.primary))
                        .keyboardShortcut(.defaultAction)
                    Button(T("game.again")) { start() }.buttonStyle(KButtonStyle(scene.isDark ? .nightGhost : .ghost))
                } else {
                    Button(T("game.again")) { start() }
                        .buttonStyle(KButtonStyle(.primary))
                        .keyboardShortcut(.defaultAction)
                }
                Button(T("game.enough")) { dismiss() }.buttonStyle(KButtonStyle(scene.isDark ? .nightGhost : .ghost))
            }
            .frame(maxWidth: 420)
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
        KSound.play(.start)
        withAnimation(fade) { phase = .play }
    }
}

/// A thin progress ring (the hold ring in Tell Kaiku, the breath phase). Never shows a number.
struct ProgressRing: View {
    let progress: Double
    var color: Color = KaikuTokens.Colors.clay
    var width: CGFloat = 6
    var track: Color = KaikuTokens.Colors.line
    var body: some View {
        ZStack {
            Circle().stroke(track, lineWidth: width)
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

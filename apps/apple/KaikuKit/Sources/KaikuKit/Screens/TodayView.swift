import SwiftUI

/// Today: greeting + not-OK, Kaiku in its time-of-day glow with the one suggestion, primary + "not today", Weather
/// check (sky) + Breathe (sage) rows, garden. One viewport: two columns on the Mac window, a compact stack on
/// iPhone. Mascot mood from /v1/me; loading → thinking; offline → sky banner. When the cloud has an invitation
/// (`InvitationModel`), its card stands where Kaiku's line is until it is answered. What the person said yes to
/// in a conversation today, on any device, stands above it (`AgreedStack`): it arrives through the home stream
/// while this screen is open, with no reload.
public struct TodayView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.kaikuPaneWidth) private var width
    @Environment(\.scenePhase) private var scenePhase
    @State private var declined = false
    /// The one list the app keeps (the home stream refreshes it, the notification rules follow it).
    private var invite: InvitationModel { .shared }

    public init() {}

    /// Today's suggestion. Robot activities (drum, a light to a friend) are only offered when the robot has been
    /// heard from today: a phone- or Mac-only person is never sent to hardware they do not have.
    var arm: NudgeArm? {
        guard let a = app.nudge?.arm else { return nil }
        if a == .drum || a == .friend_ping {
            let robotHere = app.todayEvents.contains { ["head", "sensors", "hub"].contains($0.source) }
            return robotHere ? a : nil
        }
        return a
    }

    var bubble: String {
        if declined { return T("today.nottoday.reply") }
        if app.me == nil && app.loading { return T("common.loading") }
        if let arm { return T("today.suggest.\(arm.rawValue)") }
        return T("today.suggest.none")
    }

    public var body: some View {
        KScreen(app.greeting, maxWidth: KaikuTokens.Size.paneMax) {
            KAdaptiveColumns(minWidth: 600, leadingFraction: 0.48) {
                WideAware { wide in
                    // Agreed items first, then the invitation; Kaiku's own line only when neither has a card.
                    let board = board(wide: wide)
                    if wide {
                        VStack(spacing: KaikuTokens.Space.s4) {
                            GlowingMascot(state: app.ambientState, size: KaikuTokens.Size.mascotL)
                            if !board.isEmpty { agreedStack(board, mascot: false) }
                            if let inv = invite.invitation {
                                invitationCard(inv, mascot: false)
                            } else if board.card == nil {
                                Bubble(bubble, big: true, centered: true)
                            }
                        }
                        .frame(maxWidth: .infinity)
                    } else {
                        // One card with buttons at a time: the service holds the invitation back while an
                        // agreed item is open or started, so the invitation only ever stands under done lines.
                        VStack(spacing: KaikuTokens.Space.s3) {
                            if !board.isEmpty { agreedStack(board, mascot: true) }
                            if let inv = invite.invitation {
                                invitationCard(inv, mascot: board.card == nil)
                            } else if board.card == nil {
                                MascotWithBubble(state: app.ambientState, text: bubble, size: KaikuTokens.Size.mascotM, big: true)
                            }
                        }
                    }
                }
                .animation(gently, value: invite.invitation?.id)   // the card arrives and leaves softly
                .animation(gently, value: board(wide: false).key)
                if invite.invitation == nil, board(wide: false).card == nil { actions }
            } trailing: {
                TodayPathCard()
                GardenCard(garden: app.me?.garden ?? Garden()) { app.deepLink = .days }
            }
        }
        .refreshable { await app.refresh(); await loadInvitation() }
        .task(id: app.pairingRevision) { await loadInvitation() }
        .onChange(of: scenePhase) { _, p in if p == .active { Task { await loadInvitation() } } }
    }

    // MARK: agreed in a conversation today (D50)

    /// One card and at most a few single lines (two on a phone): the day's path keeps its first stop on screen
    /// on the smallest phone.
    private func board(wide: Bool) -> AgreedBoard {
        AgreedBoard.make(invite.agreed, today: AppModel.dayKey(Date()), maxRows: wide ? AgreedBoard.maxRows : 2)
    }

    private func agreedStack(_ board: AgreedBoard, mascot: Bool) -> some View {
        AgreedStack(board: board, showsMascot: mascot, waiting: invite.settling,
                    hear: { VoiceLines.shared.say($0.text, lang: app.language) },
                    start: { start($0) }, notNow: { putAside($0) })
    }

    /// Start: the activity's screen opens at once and the service hears it was opened (the item then reads
    /// "Started" on every screen).
    private func start(_ item: AgreedActivity) {
        VoiceLines.shared.stop()
        guard let route = item.route() else { return }
        Task { await invite.settle(item.id, .opened, app: app) }
        app.deepLink = route
        app.selectedTab = route.tab
    }

    /// Not now: the item leaves here and everywhere, and Kaiku says it will be here.
    private func putAside(_ item: AgreedActivity) {
        VoiceLines.shared.stop()
        declined = true
        Task { await invite.settle(item.id, .put_aside, app: app) }
    }

    // MARK: invitation (one thing Kaiku would like to bring up or offer now)

    private var gently: Animation { KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast) }

    private func loadInvitation() async { await invite.load(app: app) }

    private func invitationCard(_ inv: Invitation, mascot: Bool) -> some View {
        InvitationCard(invitation: inv, showsMascot: mascot, waiting: invite.sending,
                       hear: { VoiceLines.shared.say(inv.text, lang: app.language) },
                       yes: { answer(.yes) }, notNow: { answer(.not_now) })
            .transition(.opacity.combined(with: .scale(scale: 0.97, anchor: .top)))
    }

    /// Yes: the answer goes to the service, then the screen it leads to opens. Not now: the card leaves and Kaiku
    /// says it will be here.
    private func answer(_ a: InvitationAnswer.Answer) {
        VoiceLines.shared.stop()
        if a == .not_now { declined = true }
        Task {
            switch await invite.answer(a, app: app) {
            case .talk?: app.selectedTab = .talk
            case .route(let r)?: app.deepLink = r; app.selectedTab = r.tab
            case nil: break
            }
        }
    }

    @ViewBuilder private var actions: some View {
        if let arm, !declined, arm == .drum || arm == .friend_ping {
            VStack(spacing: KaikuTokens.Space.s1) {
                suggestionButton(arm)
                Button(T("common.nottoday")) {
                    withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { declined = true }
                }
                .buttonStyle(.kGhost)
            }
            .transition(.opacity.combined(with: .scale(scale: 0.97, anchor: .top)))
        }
    }

    @ViewBuilder private func suggestionButton(_ arm: NudgeArm) -> some View {
        switch arm {
        case .breathe:
            NavigationLink(value: KaikuRoute.breathe) { Text(T("today.cta.breathe")) }.buttonStyle(.kPrimary)
        case .icbt_exercise:
            NavigationLink(value: KaikuRoute.tell) { Text(T("today.cta.icbt_exercise")) }.buttonStyle(.kPrimary)
        case .daylight_walk:
            if KaikuPlatform.isPhone {
                NavigationLink(value: KaikuRoute.walk) { Text(T("today.cta.walk")) }.buttonStyle(.kPrimary)
            } else {
                Button(T("today.cta.walk")) { app.showToast(T("today.walk.toast")); declined = true }.buttonStyle(.kPrimary)
            }
        case .drum, .friend_ping:
            Button(T("today.cta.\(arm.rawValue)")) { app.showToast(T("today.robot.toast")); declined = true }.buttonStyle(.kPrimary)
        }
    }
}

/// Gives its content whether the pane is in the two-column (wide) layout.
struct WideAware<Content: View>: View {
    @ViewBuilder let content: (Bool) -> Content
    @Environment(\.kaikuPaneWidth) private var width
    @Environment(\.dynamicTypeSize) private var dts
    var body: some View { content(KAdaptiveColumns<EmptyView, EmptyView>.isWide(width, dts)) }
}

/// The garden (artifact `.garden`): a sky-to-paper wash, sprouts on a soft mound (one per interaction in the last
/// 14 days, max 14); rests after 3 quiet days, never wilts. Opens Your days.
struct GardenStrip: View {
    let garden: Garden
    var height: CGFloat = 64
    let open: () -> Void
    var body: some View {
        Button(action: open) {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                HStack(alignment: .bottom, spacing: KaikuTokens.Space.s3) {
                    GardenPatch(plants: garden.plants, resting: garden.resting, height: height)
                        .frame(maxWidth: .infinity)
                    KChevron(tint: KaikuTokens.Colors.sage).padding(.bottom, KaikuTokens.Space.s3)
                }
                Text(garden.resting ? T("days.resting") : T("days.garden"))
                    .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            }
            .padding(.horizontal, KaikuTokens.Space.s4)
            .padding(.top, KaikuTokens.Space.s3)
            .padding(.bottom, KaikuTokens.Space.s4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(GardenWash())
        }
        .buttonStyle(.kPress)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(T("tab.days"))
    }
}

/// Today's garden card: "Your garden", this week's seven day plots (big enough to read), a line on what grows it.
struct GardenCard: View {
    let garden: Garden
    let open: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            Button(action: open) {
                HStack {
                    Text(T("garden.title")).kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                        .accessibilityAddTraits(.isHeader)
                    Spacer()
                    KChevron(tint: KaikuTokens.Colors.sage)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.kPress)
            GardenBeds(garden: garden, weeks: 1, plantHeight: 84)
            Text(garden.resting ? T("days.resting") : T("garden.legend"))
                .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
        }
        .padding(KaikuTokens.Space.s4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(GardenWash())
    }
}

struct GardenWash: View {
    var body: some View {
        RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
            .fill(LinearGradient(colors: [KaikuTokens.Colors.skySoft, KaikuTokens.Colors.sageSoft.opacity(0.7)],
                                 startPoint: .top, endPoint: .bottom))
    }
}

/// Garden drawing: sprouts that grow by index on a soft mound; some carry a bud or a bloom. Resting = sprouts lean
/// a little with a moon (never wilts).
struct GardenPatch: View {
    let plants: Int
    let resting: Bool
    var height: CGFloat = 80
    var body: some View {
        Canvas { ctx, size in
            let n = max(0, min(14, plants))
            var mound = Path()
            mound.move(to: CGPoint(x: 0, y: size.height - 4))
            mound.addQuadCurve(to: CGPoint(x: size.width, y: size.height - 4), control: CGPoint(x: size.width / 2, y: size.height - 16))
            mound.addLine(to: CGPoint(x: size.width, y: size.height))
            mound.addLine(to: CGPoint(x: 0, y: size.height))
            mound.closeSubpath()
            ctx.fill(mound, with: .color(KaikuTokens.Colors.mascotShade.opacity(0.7)))
            guard n > 0 else {
                ctx.fill(Path(ellipseIn: CGRect(x: size.width / 2 - 6, y: size.height - 16, width: 12, height: 6)),
                         with: .color(KaikuTokens.Colors.mascotOutline))
                return
            }
            let gap = size.width / CGFloat(n + 1)
            for i in 0..<n {
                let x = gap * CGFloat(i + 1)
                let base = size.height - 6 - 10 * sin(.pi * x / size.width)
                let hgt = (base - 8) * (0.42 + 0.5 * CGFloat((i * 37) % 10) / 10)
                let lean: CGFloat = resting ? 5 : 0
                var stem = Path()
                stem.move(to: CGPoint(x: x, y: base))
                stem.addCurve(to: CGPoint(x: x + lean, y: base - hgt), control1: CGPoint(x: x - 2, y: base - hgt / 2),
                              control2: CGPoint(x: x + 2, y: base - hgt / 2))
                ctx.stroke(stem, with: .color(KaikuTokens.Colors.sage), style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                // two leaves (artifact plant shape)
                var l1 = Path()
                let a = CGPoint(x: x, y: base - hgt * 0.45)
                l1.move(to: a); l1.addQuadCurve(to: CGPoint(x: a.x - 12, y: a.y - 9), control: CGPoint(x: a.x - 12, y: a.y - 1))
                l1.addQuadCurve(to: a, control: CGPoint(x: a.x - 3, y: a.y - 10))
                ctx.fill(l1, with: .color(KaikuTokens.Colors.sage))
                if (i * 7) % 3 != 0 {
                    var l2 = Path()
                    let b = CGPoint(x: x + lean * 0.6, y: base - hgt * 0.72)
                    l2.move(to: b); l2.addQuadCurve(to: CGPoint(x: b.x + 12, y: b.y - 9), control: CGPoint(x: b.x + 12, y: b.y - 1))
                    l2.addQuadCurve(to: b, control: CGPoint(x: b.x + 3, y: b.y - 10))
                    ctx.fill(l2, with: .color(KaikuTokens.Colors.sage.opacity(0.85)))
                }
                let top = CGPoint(x: x + lean, y: base - hgt)
                if !resting, i % 3 == 1 {
                    let r: CGFloat = i % 2 == 0 ? 5 : 3.5
                    ctx.fill(Path(ellipseIn: CGRect(x: top.x - r, y: top.y - r - 2, width: r * 2, height: r * 2)),
                             with: .color(i % 2 == 0 ? KaikuTokens.Colors.mascotSparkle : KaikuTokens.Colors.mascotBlush))
                }
            }
            if resting {
                let m = CGRect(x: size.width - 22, y: 2, width: 14, height: 14)
                ctx.fill(Path(ellipseIn: m), with: .color(KaikuTokens.Colors.sky.opacity(0.6)))
            }
        }
        .frame(height: height)
        .accessibilityHidden(true)
    }
}

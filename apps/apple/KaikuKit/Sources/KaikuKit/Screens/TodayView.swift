import SwiftUI

/// Today: greeting + not-OK, Kaiku in its time-of-day glow with the one suggestion, primary + "not today", Weather
/// check (sky) + Breathe (sage) rows, garden. One viewport: two columns on the Mac window, a compact stack on
/// iPhone. Mascot mood from /v1/me; loading → thinking; offline → sky banner.
public struct TodayView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.kaikuPaneWidth) private var width
    @State private var declined = false

    public init() {}

    var arm: NudgeArm? { app.nudge?.arm }

    var bubble: String {
        if declined { return T("today.nottoday.reply") }
        if app.me == nil && app.loading { return T("common.loading") }
        if let arm { return T("today.suggest.\(arm.rawValue)") }
        return T("today.suggest.none")
    }

    public var body: some View {
        KScreen(app.greeting, maxWidth: 1000) {
            if app.offline { OfflineBanner() }
            KAdaptiveColumns(minWidth: 600, leadingFraction: 0.48) {
                WideAware { wide in
                    if wide {
                        VStack(spacing: KaikuTokens.Space.s4) {
                            GlowingMascot(state: app.ambientState, size: 176)
                            Bubble(bubble, big: true, centered: true)
                        }
                        .frame(maxWidth: .infinity)
                    } else {
                        MascotWithBubble(state: app.ambientState, text: bubble, size: 144, big: true)
                    }
                }
                actions
            } trailing: {
                KSection {
                    NavigationLink(value: KaikuRoute.weather) {
                        KRow(icon: "sun.max.fill", tint: KaikuTokens.Colors.sky, title: T("today.card.weather.t"),
                             detail: app.weatherDoneToday ? T("today.card.weather.done") : T("today.card.weather.d"),
                             accessory: app.weatherDoneToday ? .check : .chevron)
                    }
                    .buttonStyle(.kPressRow())
                    KDivider()
                    NavigationLink(value: KaikuRoute.breathe) {
                        KRow(icon: "wind", tint: KaikuTokens.Colors.sage, title: T("today.card.breathe.t"), detail: T("today.card.breathe.d"))
                    }
                    .buttonStyle(.kPressRow())
                }
                GardenStrip(garden: app.me?.garden ?? Garden()) { app.selectedTab = .days }
            }
        }
        .refreshable { await app.refresh() }
    }

    @ViewBuilder private var actions: some View {
        if let arm, !declined {
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
                    Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold))
                        .foregroundStyle(KaikuTokens.Colors.sage).padding(.bottom, 14)
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

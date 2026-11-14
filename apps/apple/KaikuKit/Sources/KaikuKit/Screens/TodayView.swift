import SwiftUI

/// Today: greeting + not-OK, Kaiku with the one suggestion, primary + "not today", Weather check + Breathe rows,
/// garden strip. Mascot mood from /v1/me; loading → thinking; offline → sky banner.
public struct TodayView: View {
    @Environment(AppModel.self) private var app
    @State private var declined = false

    public init() {}

    var greeting: String { app.greeting }

    var arm: NudgeArm? { app.nudge?.arm }

    var bubble: String {
        if declined { return T("today.nottoday.reply") }
        if app.me == nil && app.loading { return T("common.loading") }
        if let arm { return T("today.suggest.\(arm.rawValue)") }
        return T("today.suggest.none")
    }

    public var body: some View {
        KScreen(greeting) {
            if app.offline { OfflineBanner() }
            MascotWithBubble(state: app.ambientState, text: bubble)
            if let arm, !declined {
                VStack(spacing: KaikuTokens.Space.s2) {
                    suggestionButton(arm)
                    Button(T("common.nottoday")) {
                        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base)) { declined = true }
                    }
                    .buttonStyle(.kGhost)
                }
            }
            KSection {
                NavigationLink(value: KaikuRoute.weather) {
                    KRow(icon: "cloud.sun.fill", tint: KaikuTokens.Colors.honey, title: T("today.card.weather.t"),
                         detail: app.weatherDoneToday ? T("today.card.weather.done") : T("today.card.weather.d"),
                         accessory: app.weatherDoneToday ? .check : .chevron)
                }
                .buttonStyle(.plain)
                KDivider()
                NavigationLink(value: KaikuRoute.breathe) {
                    KRow(icon: "wind", tint: KaikuTokens.Colors.sky, title: T("today.card.breathe.t"), detail: T("today.card.breathe.d"))
                }
                .buttonStyle(.plain)
            }
            GardenStrip(garden: app.me?.garden ?? Garden()) { app.selectedTab = .days }
        }
        .refreshable { await app.refresh() }
    }

    @ViewBuilder private func suggestionButton(_ arm: NudgeArm) -> some View {
        switch arm {
        case .breathe:
            NavigationLink(value: KaikuRoute.breathe) { Text(T("today.cta.breathe")) }.buttonStyle(.kPrimary)
        case .icbt_exercise:
            NavigationLink(value: KaikuRoute.tell) { Text(T("today.cta.icbt_exercise")) }.buttonStyle(.kPrimary)
        case .daylight_walk:
            Button(T("today.cta.walk")) { app.showToast(T("today.walk.toast")); declined = true }.buttonStyle(.kPrimary)
        case .drum, .friend_ping:
            Button(T("today.cta.\(arm.rawValue)")) { app.showToast(T("today.robot.toast")); declined = true }.buttonStyle(.kPrimary)
        }
    }
}

/// A row of sprouts (one per interaction in the last 14 days, max 14); rests (sleeps) after 3 quiet days.
struct GardenStrip: View {
    let garden: Garden
    let open: () -> Void
    var body: some View {
        Button(action: open) {
            KCard(tint: KaikuTokens.Colors.sageSoft) {
                HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                    GardenPatch(plants: garden.plants, resting: garden.resting, height: 46)
                        .frame(maxWidth: .infinity)
                    Image(systemName: "chevron.right").foregroundStyle(KaikuTokens.Colors.sage)
                }
                Text(garden.resting ? T("days.resting") : T("days.garden"))
                    .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            }
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(T("tab.days"))
    }
}

/// Garden drawing: sprouts that grow by index; resting = sprouts droop slightly with a moon (never wilts).
struct GardenPatch: View {
    let plants: Int
    let resting: Bool
    var height: CGFloat = 80
    var body: some View {
        Canvas { ctx, size in
            let n = max(0, min(14, plants))
            let ground = Path(roundedRect: CGRect(x: 0, y: size.height - 8, width: size.width, height: 8), cornerRadius: 4)
            ctx.fill(ground, with: .color(KaikuTokens.Colors.sage.opacity(0.25)))
            guard n > 0 else {
                // a single seed mound
                ctx.fill(Path(ellipseIn: CGRect(x: size.width / 2 - 6, y: size.height - 12, width: 12, height: 6)),
                         with: .color(KaikuTokens.Colors.mascotShade))
                return
            }
            let gap = size.width / CGFloat(n + 1)
            for i in 0..<n {
                let x = gap * CGFloat(i + 1)
                let hgt = (size.height - 12) * (0.45 + 0.55 * CGFloat((i * 37) % 10) / 10)
                var stem = Path()
                stem.move(to: CGPoint(x: x, y: size.height - 8))
                let lean: CGFloat = resting ? 4 : 0
                stem.addQuadCurve(to: CGPoint(x: x + lean, y: size.height - 8 - hgt), control: CGPoint(x: x - 3, y: size.height - 8 - hgt / 2))
                ctx.stroke(stem, with: .color(KaikuTokens.Colors.sage), style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                let top = CGPoint(x: x + lean, y: size.height - 8 - hgt)
                let leafL = Path(ellipseIn: CGRect(x: top.x - 10, y: top.y - 3, width: 10, height: 6))
                let leafR = Path(ellipseIn: CGRect(x: top.x, y: top.y - 6, width: 10, height: 6))
                ctx.fill(leafL, with: .color(KaikuTokens.Colors.sage))
                ctx.fill(leafR, with: .color(KaikuTokens.Colors.sage.opacity(0.8)))
                if i % 4 == 2 && !resting {
                    ctx.fill(Path(ellipseIn: CGRect(x: top.x - 3, y: top.y - 10, width: 6, height: 6)), with: .color(KaikuTokens.Colors.honey))
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

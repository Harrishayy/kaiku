import SwiftUI

// MARK: Today's path — the guided order ("first this, then this"), so nobody has to pick from a menu.

/// One step of today's path. The path is always three steps: the weather check, Kaiku's suggestion for today
/// (the nudge arm), and a small game. Done-ness is local (this device) — the garden carries the cross-device view.
public struct PathStep: Identifiable, Equatable {
    public let route: KaikuRoute
    public let titleKey: String
    public let whyKey: String
    public let icon: String
    public let tone: KTone
    public let minutes: Int
    public let done: Bool
    public var id: KaikuRoute { route }
}

extension AppModel {
    /// Weather check → today's suggestion → a game (Firefly / Pebble path alternate by day, so both get played).
    var todayPath: [PathStep] {
        let weather = PathStep(route: .weather, titleKey: "today.card.weather.t", whyKey: "path.why.weather",
                               icon: "sun.max.fill", tone: .sky, minutes: 1, done: weatherDoneToday)
        let suggested: PathStep
        switch nudge?.arm {
        case .icbt_exercise?:
            suggested = PathStep(route: .tell, titleKey: "game.tell.t", whyKey: "path.why.suggest", icon: "ear.fill",
                                 tone: .clay, minutes: 1, done: playedToday("tell"))
        case .daylight_walk? where KaikuPlatform.isPhone:
            suggested = PathStep(route: .walk, titleKey: "game.lighthunt.t", whyKey: "path.why.suggest",
                                 icon: "figure.walk", tone: .sage, minutes: 15, done: walkedToday)
        default:
            suggested = PathStep(route: .breathe, titleKey: "game.breathe.t", whyKey: "path.why.suggest", icon: "wind",
                                 tone: .sage, minutes: 1, done: playedToday("breathe"))
        }
        let odd = (Calendar.current.ordinality(of: .day, in: .year, for: Date()) ?? 0) % 2 == 1
        let game = odd
            ? PathStep(route: .pebbles, titleKey: "game.pebbles.t", whyKey: "path.why.game", icon: "circle.grid.2x1.fill",
                       tone: .sky, minutes: 2, done: playedToday("pebbles"))
            : PathStep(route: .firefly, titleKey: "game.firefly.t", whyKey: "path.why.game", icon: "sparkles",
                       tone: .honey, minutes: 1, done: playedToday("firefly"))
        return [weather, suggested, game]
    }

    var nextPathStep: PathStep? { todayPath.first { !$0.done } }

    /// A walk counts once the garden shows an outing today (walks are posted by the walk flow, not a game).
    var walkedToday: Bool {
        me?.garden?.days.last.map { $0.date == Self.dayKey(Date()) && $0.kinds.contains("outing") } ?? false
    }

    /// Go to a step from anywhere (Today, a game's end screen): switches tab + pushes the route.
    func go(_ step: PathStep) {
        deepLink = step.route
        selectedTab = step.route.tab
    }
}

/// "Today's path": three numbered stops on a dotted trail. The current stop is lit and carries the one big button;
/// done stops get a tick; later stops stay tappable (never locked). All done → Kaiku cheers.
struct TodayPathCard: View {
    @Environment(AppModel.self) private var app
    var showsHeader = true

    var body: some View {
        let steps = app.todayPath
        let doneN = steps.filter(\.done).count
        let current = steps.first { !$0.done }
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            if showsHeader {
                HStack(alignment: .firstTextBaseline) {
                    Text(T("path.title")).kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                        .accessibilityAddTraits(.isHeader)
                    Spacer(minLength: KaikuTokens.Space.s2)
                    Text(T("path.progress", n: doneN)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted)
                }
                ProgressDots(total: steps.count, done: doneN)
            }
            VStack(spacing: 0) {
                ForEach(Array(steps.enumerated()), id: \.element.id) { i, step in
                    PathStopRow(index: i + 1, step: step, current: step == current,
                                last: i == steps.count - 1) { app.go(step) }
                }
            }
            if current == nil {
                HStack(spacing: KaikuTokens.Space.s3) {
                    MascotView(state: .cheering, size: 56, tappable: false)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(T("path.done.t")).kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                        Text(T("path.done.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    }
                }
                .padding(KaikuTokens.Space.s3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.honeySoft))
            }
        }
        .padding(KaikuTokens.Space.s4)
        .background(
            RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
                .shadow(color: KaikuTokens.Colors.ink.opacity(0.05), radius: 10, y: 4)
        )
        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
    }
}

struct ProgressDots: View {
    let total: Int
    let done: Int
    var body: some View {
        HStack(spacing: 6) {
            ForEach(0..<total, id: \.self) { i in
                Capsule().fill(i < done ? KaikuTokens.Colors.sage : KaikuTokens.Colors.line)
                    .frame(height: 6)
            }
        }
        .accessibilityHidden(true)
    }
}

struct PathStopRow: View {
    let index: Int
    let step: PathStep
    let current: Bool
    let last: Bool
    let open: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
            // the trail: a stop disc + a dotted line down to the next stop
            VStack(spacing: 0) {
                ZStack {
                    Circle().fill(step.done ? KaikuTokens.Colors.sage : current ? step.tone.ink : KaikuTokens.Colors.surface)
                    Circle().strokeBorder(step.done || current ? .clear : KaikuTokens.Colors.line, lineWidth: 2)
                    if step.done {
                        Image(systemName: "checkmark").font(.system(size: 15, weight: .bold)).foregroundStyle(.white)
                    } else {
                        Text("\(index)").kText(.callout, weight: .bold)
                            .foregroundStyle(current ? .white : KaikuTokens.Colors.muted)
                    }
                }
                .frame(width: 36, height: 36)
                .shadow(color: current ? step.tone.ink.opacity(0.35) : .clear, radius: 8, y: 2)
                if !last {
                    Rectangle().fill(.clear).frame(width: 2).frame(minHeight: 18, maxHeight: .infinity)
                        .overlay(Line().stroke(step.done ? KaikuTokens.Colors.sage : KaikuTokens.Colors.line,
                                               style: StrokeStyle(lineWidth: 2.5, lineCap: .round, dash: [2, 5])))
                }
            }
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                Button(action: open) {
                    HStack(spacing: KaikuTokens.Space.s3) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(T(step.whyKey)).kText(.caption).foregroundStyle(current ? step.tone.ink : KaikuTokens.Colors.muted).wraps()
                            Text(T(step.titleKey)).kText(.callout, weight: .semibold)
                                .foregroundStyle(step.done ? KaikuTokens.Colors.ink2 : KaikuTokens.Colors.ink).wraps()
                        }
                        Spacer(minLength: KaikuTokens.Space.s2)
                        Text(T("game.time", n: step.minutes)).kText(.caption).foregroundStyle(step.tone.ink)
                            .padding(.horizontal, 8).padding(.vertical, 3)
                            .background(Capsule().fill(step.tone.soft))
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.kPress)
                if current {
                    Button(action: open) {
                        Label(T(index == 1 ? "path.start" : "path.next.go"), systemImage: "arrow.right")
                            .labelStyle(TrailingIconLabel())
                    }
                    .buttonStyle(.kPrimary)
                }
            }
            .padding(.top, 6)
            .padding(.bottom, last ? 0 : KaikuTokens.Space.s3)
        }
        .accessibilityElement(children: .combine)
        .accessibilityValue(step.done ? T("path.a11y.done") : current ? T("path.a11y.next") : "")
    }
}

private struct Line: Shape {
    func path(in r: CGRect) -> Path { var p = Path(); p.move(to: CGPoint(x: r.midX, y: r.minY + 4)); p.addLine(to: CGPoint(x: r.midX, y: r.maxY - 4)); return p }
}

struct TrailingIconLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 8) { configuration.title; configuration.icon }
    }
}

// MARK: Garden — one plot per day, so you can see what each day held.

@MainActor extension GardenDay {
    static let kindStyle: [String: (String, Color)] = [
        "outing": ("figure.walk", KaikuTokens.Colors.sage),
        "weather_check": ("sun.max.fill", KaikuTokens.Colors.sky),
        "play_session": ("sparkles", KaikuTokens.Colors.honey),
        "ritual": ("sunrise.fill", KaikuTokens.Colors.clay),
        "drum_session": ("music.note", KaikuTokens.Colors.clay),
        "friend_link": ("heart.fill", KaikuTokens.Colors.mascotBlush),
    ]

    var dateValue: Date? { KaikuTime.parse(date) }
    var isToday: Bool { date == AppModel.dayKey(Date()) }

    var summary: String {
        guard count > 0 else { return T("garden.empty") }
        return kinds.map { T("garden.kind.\($0)") }.joined(separator: ", ")
    }
}

/// The garden as a row of day plots (7 on Today, 14 in two weeks on Your days). Each plot's plant grows with what
/// was done together that day; small icons say what; today is outlined. Tap a plot to read the day.
struct GardenBeds: View {
    let garden: Garden
    var weeks: Int = 1
    var plantHeight: CGFloat = 96
    var selectable = true
    @State private var selected: String?

    var days: [GardenDay] {
        if !garden.days.isEmpty { return Array(garden.days.suffix(7 * weeks)) }
        // older cloud / offline: still draw the plots (empty), never an empty box
        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        return (0..<(7 * weeks)).reversed().compactMap { cal.date(byAdding: .day, value: -$0, to: today) }
            .map { GardenDay(date: AppModel.dayKey($0)) }
    }

    var body: some View {
        let all = days
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            ForEach(0..<max(1, all.count / 7), id: \.self) { w in
                let row = Array(all[(w * 7)..<min(all.count, w * 7 + 7)])
                if weeks > 1 {
                    Text(T(w == weeks - 1 ? "garden.recent" : "garden.lastweek")).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted)
                }
                HStack(alignment: .bottom, spacing: 6) {
                    ForEach(row, id: \.date) { d in plot(d) }
                }
            }
            if selectable, let s = selected, let d = all.first(where: { $0.date == s }) {
                HStack(alignment: .firstTextBaseline, spacing: KaikuTokens.Space.s2) {
                    Text(DayName.long(d.date)).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                    Text(d.summary).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                }
                .transition(.opacity)
            }
        }
    }

    private func plot(_ d: GardenDay) -> some View {
        let on = selected == d.date
        return Button {
            guard selectable else { return }
            withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { selected = on ? nil : d.date }
        } label: {
            VStack(spacing: 6) {
                DayPlant(count: d.count, seed: d.date.hashValue, tint: d.kinds.contains("play_session") ? KaikuTokens.Colors.honey : KaikuTokens.Colors.mascotBlush)
                    .frame(height: plantHeight)
                HStack(spacing: 2) {
                    ForEach(d.kinds.prefix(3), id: \.self) { k in
                        if let (sym, c) = GardenDay.kindStyle[k] {
                            Image(systemName: sym).font(.system(size: 9, weight: .bold)).foregroundStyle(c)
                        }
                    }
                }
                .frame(height: 11)
                VStack(spacing: 0) {
                    Text(d.dateValue.map { DayName.short($0) } ?? "").kText(.caption, weight: d.isToday ? .bold : .regular)
                        .foregroundStyle(d.isToday ? KaikuTokens.Colors.clay : KaikuTokens.Colors.muted)
                    Text(d.dateValue.map { "\(Calendar.current.component(.day, from: $0))" } ?? "")
                        .kText(.caption).foregroundStyle(d.isToday ? KaikuTokens.Colors.clay : KaikuTokens.Colors.ink2)
                }
                .lineLimit(1).minimumScaleFactor(0.7)
            }
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous)
                .fill(on ? KaikuTokens.Colors.surface : KaikuTokens.Colors.surface.opacity(d.isToday ? 0.55 : 0)))
            .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous)
                .strokeBorder(d.isToday ? KaikuTokens.Colors.clay.opacity(0.6) : .clear, style: StrokeStyle(lineWidth: 1.5, dash: [4, 3])))
            .contentShape(Rectangle())
        }
        .buttonStyle(.kPress)
        .accessibilityLabel(DayName.long(d.date))
        .accessibilityValue(d.summary)
    }
}

/// One day's plant: a seed in soil (quiet day, never wilted) → sprout → leaves → bud → flower as the day fills up.
struct DayPlant: View {
    let count: Int
    let seed: Int
    let tint: Color
    var body: some View {
        Canvas { ctx, s in
            let soilY = s.height - 8
            let mid = s.width / 2
            ctx.fill(Path(ellipseIn: CGRect(x: mid - s.width * 0.42, y: soilY - 5, width: s.width * 0.84, height: 12)),
                     with: .color(KaikuTokens.Colors.mascotShade.opacity(0.75)))
            guard count > 0 else {
                ctx.fill(Path(ellipseIn: CGRect(x: mid - 4, y: soilY - 6, width: 8, height: 6)), with: .color(KaikuTokens.Colors.mascotOutline.opacity(0.6)))
                return
            }
            let level = min(count, 5)
            let h = (soilY - 14) * (0.32 + 0.17 * CGFloat(level - 1))
            let sway = CGFloat((abs(seed) % 7) - 3)
            let top = CGPoint(x: mid + sway, y: soilY - h)
            var stem = Path()
            stem.move(to: CGPoint(x: mid, y: soilY - 2))
            stem.addQuadCurve(to: top, control: CGPoint(x: mid - sway, y: soilY - h / 2))
            ctx.stroke(stem, with: .color(KaikuTokens.Colors.sage), style: StrokeStyle(lineWidth: 3, lineCap: .round))
            // leaves: one per level up to 4, alternating sides
            for i in 0..<min(level + 1, 4) {
                let t = 0.3 + 0.17 * CGFloat(i)
                let a = CGPoint(x: mid + sway * t, y: soilY - h * t)
                let dir: CGFloat = i % 2 == 0 ? -1 : 1
                let len: CGFloat = 13 + CGFloat(level) * 1.5
                var leaf = Path()
                leaf.move(to: a)
                leaf.addQuadCurve(to: CGPoint(x: a.x + dir * len, y: a.y - len * 0.7), control: CGPoint(x: a.x + dir * len, y: a.y))
                leaf.addQuadCurve(to: a, control: CGPoint(x: a.x + dir * len * 0.2, y: a.y - len * 0.8))
                ctx.fill(leaf, with: .color(KaikuTokens.Colors.sage.opacity(i % 2 == 0 ? 1 : 0.82)))
            }
            if level >= 3 {
                // flower: petals around a centre
                let r: CGFloat = level >= 4 ? 7 : 5
                for k in 0..<5 {
                    let ang = Double(k) / 5 * 2 * .pi
                    let c = CGPoint(x: top.x + cos(ang) * r, y: top.y + sin(ang) * r)
                    ctx.fill(Path(ellipseIn: CGRect(x: c.x - r * 0.75, y: c.y - r * 0.75, width: r * 1.5, height: r * 1.5)), with: .color(tint))
                }
                ctx.fill(Path(ellipseIn: CGRect(x: top.x - r * 0.6, y: top.y - r * 0.6, width: r * 1.2, height: r * 1.2)),
                         with: .color(KaikuTokens.Colors.mascotSparkle))
            } else if level == 2 {
                ctx.fill(Path(ellipseIn: CGRect(x: top.x - 4, y: top.y - 7, width: 8, height: 10)), with: .color(tint.opacity(0.85)))
            }
        }
        .accessibilityHidden(true)
    }
}

extension DayName {
    /// "Mon" / "ma" — the short weekday in the UI language.
    static func short(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.shared.language.rawValue)
        f.dateFormat = "EEE"
        return f.string(from: d).replacingOccurrences(of: ".", with: "")
    }
}

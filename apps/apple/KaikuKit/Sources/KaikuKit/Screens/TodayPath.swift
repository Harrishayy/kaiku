import SwiftUI

// MARK: Today's path — the guided order ("first this, then this"), so nobody has to pick from a menu.

/// One step of today's path. The path is always four steps: the weather check, Kaiku's suggestion for today
/// (the nudge arm), the lantern (every day) and one more small game that rotates (`GameRotation`): about three
/// minutes of games a day. Done-ness is local (this device) — the garden carries the cross-device view.
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
    /// Weather check → today's suggestion → the lantern → today's rotating game (seed shelf / pebble path / watering).
    var todayPath: [PathStep] {
        let weather = PathStep(route: .weather, titleKey: "today.card.weather.t", whyKey: "path.why.weather",
                               icon: "sun.max.fill", tone: .sky, minutes: 1, done: weatherDoneToday)
        let tell = PathStep(route: .tell, titleKey: "game.tell.t", whyKey: "path.why.suggest", icon: "ear.fill",
                            tone: .clay, minutes: 1, done: playedToday("tell"))
        let walk = PathStep(route: .walk, titleKey: "game.lighthunt.t", whyKey: "path.why.suggest",
                            icon: "figure.walk", tone: .sage, minutes: 15, done: walkedToday || playedToday("walk"))
        let breathe = PathStep(route: .breathe, titleKey: "game.breathe.t", whyKey: "path.why.suggest", icon: "wind",
                               tone: .sage, minutes: 1, done: playedToday("breathe"))
        let current: PathStep
        switch nudge?.arm {
        case .icbt_exercise?: current = tell
        case .daylight_walk? where KaikuPlatform.isPhone: current = walk
        default: current = breathe
        }
        let suggested = Self.suggestedStep(current: current, candidates: KaikuPlatform.isPhone ? [breathe, tell, walk] : [breathe, tell])
        return [weather, suggested] + GameRotation.today().enumerated().map { i, g in
            gameStep(g, whyKey: i == 0 ? "path.why.game" : "path.why.game2")
        }
    }

    /// The suggestion stop for today. A stop that was completed stays completed: when the suggestion changes
    /// later in the day (a new nudge arrives), the one already done keeps its place instead of being replaced by
    /// a new, undone one (the path used to drop from 4 of 4 to 3 of 4).
    nonisolated static func suggestedStep(current: PathStep, candidates: [PathStep]) -> PathStep {
        if current.done { return current }
        return candidates.first(where: \.done) ?? current
    }

    private func gameStep(_ g: PlayGame, whyKey: String) -> PathStep {
        let (route, icon, tone): (KaikuRoute, String, KTone) = switch g {
        case .lantern: (.lantern, "lightbulb.fill", .honey)
        case .seeds: (.seeds, "leaf.fill", .sage)
        case .watering: (.watering, "drop.fill", .clay)
        default: (.pebbles, "circle.grid.2x1.fill", .sky)
        }
        return PathStep(route: route, titleKey: "game.\(g.rawValue).t", whyKey: whyKey, icon: icon, tone: tone,
                        minutes: Int((Double(GameRotation.seconds(g)) / 60).rounded()), done: playedToday(g.rawValue))
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
                    MascotView(state: .cheering, size: KaikuTokens.Size.mascotS, tappable: false)
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
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
                .kaikuShadow(KaikuTokens.Elevation.card)
        )
        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
    }
}

struct ProgressDots: View {
    let total: Int
    let done: Int
    var body: some View {
        HStack(spacing: KaikuTokens.Space.s2) {
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
                        Image(systemName: "checkmark").kText(.footnote, weight: .bold).foregroundStyle(KaikuTokens.Colors.bg)
                    } else {
                        Text("\(index)").kText(.callout, weight: .bold)
                            .foregroundStyle(current ? KaikuTokens.Colors.bg : KaikuTokens.Colors.muted)
                    }
                }
                .frame(width: KaikuTokens.Size.iconTile, height: KaikuTokens.Size.iconTile)
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
                        VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                            Text(T(step.whyKey)).kText(.caption).foregroundStyle(current ? step.tone.ink : KaikuTokens.Colors.muted).wraps()
                            Text(T(step.titleKey)).kText(.callout, weight: .semibold)
                                .foregroundStyle(step.done ? KaikuTokens.Colors.ink2 : KaikuTokens.Colors.ink).wraps()
                        }
                        Spacer(minLength: KaikuTokens.Space.s2)
                        KChip(T("game.time", n: step.minutes), tone: step.tone)
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
            .padding(.top, KaikuTokens.Space.s2)
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
        HStack(spacing: KaikuTokens.Space.s2) { configuration.title; configuration.icon }
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
                GardenPlots(spacing: KaikuTokens.Space.s2) {
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
            VStack(spacing: KaikuTokens.Space.s2) {
                DayPlant(count: d.count, seed: d.date.hashValue, tint: d.kinds.contains("play_session") ? KaikuTokens.Colors.honey : KaikuTokens.Colors.mascotBlush)
                    .frame(height: plantHeight)
                PlotMarks(kinds: d.kinds)
                    .frame(height: 11)
                VStack(spacing: 0) {
                    Text(d.dateValue.map { DayName.short($0) } ?? "").kText(.caption, weight: d.isToday ? .bold : .regular)
                        .foregroundStyle(d.isToday ? KaikuTokens.Colors.clay : KaikuTokens.Colors.muted)
                    Text(d.dateValue.map { "\(Calendar.current.component(.day, from: $0))" } ?? "")
                        .kText(.caption).foregroundStyle(d.isToday ? KaikuTokens.Colors.clay : KaikuTokens.Colors.ink2)
                }
                .lineLimit(1).minimumScaleFactor(0.7)
            }
            .padding(.vertical, KaikuTokens.Space.s2)
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

/// How a row of the garden is shared out (pure): every plot gets the same width, whatever it holds.
enum GardenRow {
    /// The width a plot is drawn for when nobody says how wide the row may be.
    static let idealPlot: CGFloat = 48

    /// One plot's width in a row this wide: the plots and the gaps between them fill the row exactly. A row too
    /// narrow even for its gaps gives zero, never less.
    static func plotWidth(row: CGFloat, plots: Int, gap: CGFloat) -> CGFloat {
        guard plots > 0, row.isFinite else { return 0 }
        return max(0, (row - gap * CGFloat(plots - 1)) / CGFloat(plots))
    }

    static func idealWidth(plots: Int, gap: CGFloat) -> CGFloat {
        CGFloat(max(0, plots)) * idealPlot + gap * CGFloat(max(0, plots - 1))
    }
}

/// A row of day plots, all the same width. The row is exactly as wide as it is offered: what a plot holds can
/// never make the row, its card or the page wider. (As an `HStack` the row could not be narrower than its
/// plots' icons: six days of three icons each needed 334 pt, more than a small phone's card has, which pushed
/// Today past the screen and left an empty day with no width at all.)
struct GardenPlots: Layout {
    var spacing: CGFloat = KaikuTokens.Space.s2

    private func plot(in row: CGFloat, _ subviews: Subviews) -> CGFloat {
        GardenRow.plotWidth(row: row, plots: subviews.count, gap: spacing)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        var row = GardenRow.idealWidth(plots: subviews.count, gap: spacing)
        if let offered = proposal.width, offered.isFinite { row = max(0, offered) }
        let each = ProposedViewSize(width: plot(in: row, subviews), height: nil)
        return CGSize(width: row, height: subviews.map { $0.sizeThatFits(each).height }.max() ?? 0)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let width = plot(in: bounds.width, subviews)
        var x = bounds.minX
        for subview in subviews {
            subview.place(at: CGPoint(x: x + width / 2, y: bounds.maxY), anchor: .bottom,
                          proposal: ProposedViewSize(width: width, height: nil))
            x += width + spacing
        }
    }
}

/// What a day held, under its plant: up to three icons at the largest of a few sizes the plot has room for
/// (their own size where there is room; a phone's plot takes them a little smaller). In a plot too narrow even
/// for the smallest, how many kinds of thing there were.
struct PlotMarks: View {
    let kinds: [String]
    /// Smaller sizes to try after the icons' own (`micro`, 12 pt, 4 pt apart): the size and the gap at that size.
    static let smaller: [(size: CGFloat, gap: CGFloat)] = [(10.5, 3), (9.5, 2), (8.5, 1.5), (7.5, 1)]
    @ScaledMetric(relativeTo: .caption2) private var unit: CGFloat = 1

    var body: some View {
        let marks = kinds.prefix(3).compactMap { GardenDay.kindStyle[$0] }
        ZStack {   // always a view, so a quiet day's plot keeps the same height as its neighbours
            if !marks.isEmpty {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: KaikuTokens.Space.s1) {
                        ForEach(marks.indices, id: \.self) { i in
                            Image(systemName: marks[i].0).kText(.micro, weight: .bold).foregroundStyle(marks[i].1)
                        }
                    }
                    ForEach(Self.smaller.indices, id: \.self) { step in
                        HStack(spacing: Self.smaller[step].gap) {
                            ForEach(marks.indices, id: \.self) { i in
                                Image(systemName: marks[i].0)
                                    .font(.system(size: Self.smaller[step].size * unit, weight: .bold, design: .rounded))
                                    .foregroundStyle(marks[i].1)
                            }
                        }
                    }
                    Text("\(marks.count)").kText(.micro, weight: .bold).foregroundStyle(KaikuTokens.Colors.muted)
                }
            }
        }
    }
}

/// One day's plant: a seed in soil (quiet day, never wilted) → sprout → leaves → bud → flower as the day fills up.
struct DayPlant: View {
    let count: Int
    let seed: Int
    let tint: Color

    /// How long a leaf is drawn (pure): as designed where the plot has room, and in a narrow plot (a phone's
    /// week) no further than the plot's edge, where the drawing would be cut off straight.
    static func leafLength(level: Int, plot: CGFloat, sway: CGFloat) -> CGFloat {
        min(13 + CGFloat(level) * 1.5, max(6, plot / 2 - abs(sway) - 1))
    }
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
                let len = Self.leafLength(level: level, plot: s.width, sway: sway)
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

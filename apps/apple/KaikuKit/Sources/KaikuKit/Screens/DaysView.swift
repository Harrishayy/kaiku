import SwiftUI

/// Your days: the garden (a sprout per interaction; rests after 3 quiet days, never wilts), this week's strip
/// (tap a day to mark it good or hard — hard days count too), little moments from /v1/me highlights, postcards.
public struct DaysView: View {
    @Environment(AppModel.self) private var app
    @State private var marking: Date?
    public init() {}

    var week: [Date] {
        var cal = Calendar(identifier: .gregorian)
        cal.firstWeekday = 2
        let today = cal.startOfDay(for: Date())
        let start = cal.dateInterval(of: .weekOfYear, for: today)?.start ?? today
        return (0..<7).compactMap { cal.date(byAdding: .day, value: $0, to: start) }
    }

    func kind(_ d: Date) -> HighlightKind? {
        let key = AppModel.dayKey(d)
        if let m = app.marks[key] { return m }
        return app.me?.highlights?.first(where: { $0.date == key })?.kind
    }

    public var body: some View {
        KScreen(T("tab.days"), subtitle: T("days.sub"), maxWidth: 1000, spacing: KaikuTokens.Space.s4) {
            KAdaptiveColumns(minWidth: 600, leadingFraction: 0.5) {
                WideAware { wide in
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
                        SectionHeader(T("garden.title"), subtitle: T("garden.recent"), icon: "leaf.fill", tone: .sage)
                        GardenBeds(garden: app.me?.garden ?? Garden(), weeks: 1, plantHeight: wide ? 130 : 110)
                        GardenLegend()
                        Text((app.me?.garden?.resting ?? false) ? T("days.resting") : T("garden.legend"))
                            .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    }
                    .padding(KaikuTokens.Space.s4)
                    .background(GardenWash())
                }
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
                    SectionHeader(T("days.week"), subtitle: T("days.mark"), icon: "calendar", tone: .honey)
                    WeekStrip(days: week, kind: kind) { marking = $0 }
                }
            } trailing: {
                if let hs = app.me?.highlights, !hs.isEmpty {
                    MomentsTimeline(highlights: Array(hs.prefix(6)))
                }
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
                    SectionHeader(T("days.postcards"), icon: "photo.on.rectangle.angled", tone: .sky)
                    HStack(spacing: KaikuTokens.Space.s3) {
                        MascotView(state: .cozy, size: 52, tappable: false)
                        Text(T("empty.postcards")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(KaikuTokens.Space.s3)
                    .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                        .strokeBorder(KaikuTokens.Colors.line, style: StrokeStyle(lineWidth: 1.5, dash: [5, 5])))
                }
            }
        }
        .sheet(item: Binding(get: { marking.map(IdentDate.init) }, set: { marking = $0?.date })) { d in
            MarkDaySheet(date: d.date, current: app.marks[AppModel.dayKey(d.date)]) { k in
                let key = AppModel.dayKey(d.date)
                if let k { app.marks[key] = k } else { app.marks.removeValue(forKey: key) }
                marking = nil
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .refreshable { await app.refresh() }
    }
}

/// "Little moments this week" as a timeline: grouped by day, a soft tone tile per moment, and where it came from
/// (robot, glasses, phone, Mac, watch) as a small chip — so the week reads like a diary, not a list.
struct MomentsTimeline: View {
    let highlights: [Highlight]

    var groups: [(String, [Highlight])] {
        var order: [String] = []
        var by: [String: [Highlight]] = [:]
        for h in highlights {
            if by[h.date] == nil { order.append(h.date) }
            by[h.date, default: []].append(h)
        }
        return order.map { ($0, by[$0] ?? []) }
    }

    static let sources: [String: (String, String)] = [
        "robot": ("circle.hexagongrid.fill", "source.robot"), "glasses": ("eyeglasses", "source.glasses"),
        "phone": ("iphone", "source.phone"), "laptop": ("laptopcomputer", "source.laptop"),
        "wearable": ("applewatch", "source.wearable"),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            SectionHeader(T("days.highlights"), subtitle: T("days.highlights.d"), icon: "sparkles", tone: .clay)
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s4) {
                ForEach(groups, id: \.0) { day, items in
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                        Text(DayName.long(day)).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.muted)
                        ForEach(Array(items.enumerated()), id: \.offset) { i, h in
                            moment(h, last: i == items.count - 1)
                        }
                    }
                }
            }
            .padding(KaikuPlatform.isPhone ? KaikuTokens.Space.s5 - 4 : KaikuTokens.Space.s4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
                    .shadow(color: KaikuTokens.Colors.ink.opacity(0.05), radius: 10, y: 4)
            )
            .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
        }
    }

    private func moment(_ h: Highlight, last: Bool) -> some View {
        let good = h.kind == .good
        let tone: KTone = good ? .honey : .sky
        return HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
            VStack(spacing: 0) {
                RowIcon(symbol: good ? "sun.max.fill" : "cloud.drizzle.fill", tint: tone.ink, side: 34)
                if !last { Rectangle().fill(KaikuTokens.Colors.line).frame(width: 2).frame(maxHeight: .infinity).padding(.top, 4) }
            }
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                Text(h.text).kText(.body).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                if let (sym, key) = Self.sources[h.source] {
                    Label(T(key), systemImage: sym)
                        .kText(.caption, weight: .medium)
                        .foregroundStyle(KaikuTokens.Colors.ink2)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(Capsule().fill(KaikuTokens.Colors.bg))
                        .overlay(Capsule().strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
                }
            }
            .padding(.bottom, last ? 0 : KaikuTokens.Space.s3)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .combine)
    }
}

/// What the little icons under each plot mean.
struct GardenLegend: View {
    let kinds = ["outing", "weather_check", "play_session", "ritual", "drum_session", "friend_link"]
    var body: some View {
        FlowRow(spacing: KaikuTokens.Space.s3) {
            ForEach(kinds, id: \.self) { k in
                if let (sym, c) = GardenDay.kindStyle[k] {
                    HStack(spacing: 4) {
                        Image(systemName: sym).font(.system(size: 11, weight: .bold)).foregroundStyle(c)
                        Text(T("garden.kind.\(k)")).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink2)
                    }
                }
            }
        }
    }
}

/// Wraps children onto new lines (legend chips).
struct FlowRow: Layout {
    var spacing: CGFloat = 8
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let w = proposal.width ?? 320
        var x: CGFloat = 0, y: CGFloat = 0, line: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > 0 && x + s.width > w { x = 0; y += line + 4; line = 0 }
            x += s.width + spacing; line = max(line, s.height)
        }
        return CGSize(width: w, height: y + line)
    }
    func placeSubviews(in b: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = b.minX, y = b.minY, line: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > b.minX && x + s.width > b.maxX { x = b.minX; y += line + 4; line = 0 }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + spacing; line = max(line, s.height)
        }
    }
}

struct IdentDate: Identifiable { let date: Date; var id: Double { date.timeIntervalSince1970 } }

struct WeekStrip: View {
    let days: [Date]
    let kind: (Date) -> HighlightKind?
    let tap: (Date) -> Void

    var body: some View {
        let letters = T("days.weekdays").split(separator: " ").map(String.init)
        HStack(spacing: 4) {
            ForEach(Array(days.enumerated()), id: \.offset) { i, d in
                let isToday = Calendar.current.isDateInToday(d)
                let future = d > Date()
                let k = kind(d)
                Button { tap(d) } label: {
                    VStack(spacing: 6) {
                        Text(i < letters.count ? letters[i] : "").kText(.caption).foregroundStyle(KaikuTokens.Colors.muted)
                            .lineLimit(1).minimumScaleFactor(0.8)
                        ZStack {
                            Circle().fill(k == .good ? KaikuTokens.Colors.honeySoft : k == .hard ? KaikuTokens.Colors.skySoft : KaikuTokens.Colors.surface)
                            Circle().strokeBorder(isToday ? KaikuTokens.Colors.clay : KaikuTokens.Colors.line, style: StrokeStyle(lineWidth: isToday ? 2 : 1.5, dash: isToday ? [4, 3] : []))
                            if let k {
                                Image(systemName: k == .good ? "sun.max.fill" : "cloud.fill")
                                    .font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(k == .good ? KaikuTokens.Colors.honey : KaikuTokens.Colors.sky)
                            }
                        }
                        .frame(width: 42, height: 42)
                    }
                    .frame(maxWidth: .infinity, minHeight: 64)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.kPress)
                .disabled(future)
                .opacity(future ? 0.45 : 1)
                .accessibilityLabel(DayName.long(AppModel.dayKey(d)))
                .accessibilityValue(k == .good ? T("days.good") : k == .hard ? T("days.hard") : "")
            }
        }
    }
}

struct MarkDaySheet: View {
    let date: Date
    let current: HighlightKind?
    let done: (HighlightKind?) -> Void
    @State private var choice: Int = 0

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s4) {
                Text(T("days.sheet.title.day", ["day": DayName.weekday(date)]))
                    .kText(.title2).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                ForEach([(1, "days.good", "sun.max.fill"), (2, "days.hard", "cloud.fill"), (0, "days.clear", "circle.dashed")], id: \.0) { v, key, sym in
                    Button { choice = v } label: {
                        HStack(spacing: KaikuTokens.Space.s3) {
                            Image(systemName: sym).foregroundStyle(KaikuTokens.Colors.clay).frame(width: 28)
                            Text(T(key)).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Image(systemName: choice == v ? "largecircle.fill.circle" : "circle")
                                .foregroundStyle(choice == v ? KaikuTokens.Colors.clay : KaikuTokens.Colors.muted)
                        }
                        .padding(KaikuTokens.Space.s4)
                        .frame(minHeight: 56)
                        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous)
                            .fill(choice == v ? KaikuTokens.Colors.claySoft : KaikuTokens.Colors.surface))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.kPress)
                    .accessibilityAddTraits(choice == v ? .isSelected : [])
                }
                Button(T("common.done")) { done(choice == 1 ? .good : choice == 2 ? .hard : nil) }.buttonStyle(.kPrimary)
            }
            .padding(KaikuPlatform.sidePadding)
            .padding(.top, KaikuTokens.Space.s4)
        }
        .background(KaikuTokens.Colors.bg.ignoresSafeArea())
        .onAppear { choice = current == .good ? 1 : current == .hard ? 2 : 0 }
    }
}

/// Weekday names in the UI language (Finnish weekdays are lowercase nominative: "torstai").
enum DayName {
    static func weekday(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.shared.language.rawValue)
        f.dateFormat = "EEEE"
        let s = f.string(from: d)
        return L10n.shared.language == .en ? s : s.lowercased()
    }

    static func long(_ key: String) -> String {
        guard let d = KaikuTime.parse(key) else { return key }
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.shared.language.rawValue)
        f.setLocalizedDateFormatFromTemplate("EEEEdMMMM")
        return f.string(from: d)
    }
}

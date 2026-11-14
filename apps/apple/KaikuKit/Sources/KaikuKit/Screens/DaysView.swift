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
        KScreen(T("tab.days"), maxWidth: 1000, spacing: KaikuTokens.Space.s4) {
            KAdaptiveColumns(minWidth: 600, leadingFraction: 0.5) {
                WideAware { wide in
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                        GardenPatch(plants: app.me?.garden?.plants ?? 0, resting: app.me?.garden?.resting ?? false, height: wide ? 150 : 76)
                        Text((app.me?.garden?.resting ?? false) ? T("days.resting") : T("days.garden"))
                            .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    }
                    .padding(.horizontal, KaikuTokens.Space.s4)
                    .padding(.top, KaikuTokens.Space.s4)
                    .padding(.bottom, KaikuTokens.Space.s4)
                    .background(GardenWash())
                }
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                    Text(T("days.week")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps().accessibilityAddTraits(.isHeader)
                    WeekStrip(days: week, kind: kind) { marking = $0 }
                    Text(T("days.mark")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
            } trailing: {
                WideAware { wide in
                    if let hs = app.me?.highlights, !hs.isEmpty {
                        KSection(T("days.highlights")) {
                            ForEach(Array(hs.prefix(wide ? 5 : 2).enumerated()), id: \.offset) { i, h in
                                if i > 0 { KDivider() }
                                KRow(icon: h.kind == .good ? "sun.max.fill" : "cloud.drizzle.fill",
                                     tint: h.kind == .good ? KaikuTokens.Colors.honey : KaikuTokens.Colors.sky,
                                     title: h.text, detail: DayName.long(h.date), accessory: .none)
                            }
                        }
                    }
                }
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                    Text(T("days.postcards")).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                        .padding(.horizontal, KaikuTokens.Space.s1).accessibilityAddTraits(.isHeader)
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

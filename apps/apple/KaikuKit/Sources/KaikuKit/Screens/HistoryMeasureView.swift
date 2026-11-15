import Charts
import SwiftUI

// One measure's page: a range switch (day, week, month), a chart, what the period adds up to, the person's own
// usual range as a soft band when the service gives one, a month week by week, and the sessions underneath, each
// with its own numbers. The band is the only comparison on the page; nothing here says better or worse.

struct HistoryMeasureView: View {
    let ref: HistoryRef
    let model: HistoryModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        if let history = model.history, let found = model.measure(ref) {
            KScreen(found.measure.title, back: { dismiss() }, maxWidth: KaikuTokens.Size.paneMax) {
                HistoryMeasureBody(history: history, group: found.group, measure: found.measure, range: Self.firstRange)
            }
            .accessibilityIdentifier("history.measure.\(found.measure.key)")
        } else {
            KScreen(T("tab.history"), back: { dismiss() }) { HistoryEmpty(text: T("history.gone")) }
        }
    }

    private static var firstRange: HistoryRange {
        #if DEBUG
        if let r = HistoryDebug.launchRange { return r }
        #endif
        return .week
    }
}

/// The page under its title: the range switch, the period, what it adds up to, the chart, and the lists.
struct HistoryMeasureBody: View {
    let history: PersonHistory
    let group: HistoryGroup
    let measure: HistoryMeasure
    @State private var range: HistoryRange
    @State private var back = 0
    @State private var selected: String?
    @State private var showsAll = false

    init(history: PersonHistory, group: HistoryGroup, measure: HistoryMeasure, range: HistoryRange = .week) {
        self.history = history; self.group = group; self.measure = measure
        _range = State(initialValue: range)
    }

    var body: some View {
        let m = measure
        let zone = history.zone
        let today = HistoryDayKey.local(Date(), zone: zone)
        // Day view steps through the days that have a record; week and month step by whole periods from today.
        let recorded = range == .day ? HistoryMath.recordedDays(m, zone: zone) : []
        let period = range == .day
            ? HistoryPeriod.ending(recorded.isEmpty ? today : recorded[max(0, recorded.count - 1 - back)], .day)
            : HistoryPeriod.ending(today, range, back: back)
        let hasEarlier = range == .day ? back < recorded.count - 1 : period.first > history.first_day
        let points = HistoryMath.points(m.days, in: period)
        let stats = HistoryMath.stats(points)
        let listed = HistoryMath.sessions(m.sessions, from: period.first, to: period.last, zone: zone)
        let marks = range == .day ? HistoryMath.marks(m, on: period.last, zone: zone) : []
        var notes: [String] = []
        if range == .day {
            if HistorySessionChart.fades(marks, measure: m) { notes.append(T("history.legend.warmup")) }
        } else {
            if points.contains(where: { $0.day == today && $0.value != nil }) { notes.append(T("history.legend.today")) }
        }
        return KAdaptiveColumns(minWidth: 600, leadingFraction: 0.56) {
            HistoryAbout(measure: m)
            KSegmented(HistoryRange.allCases.map { ($0, T("history.range.\($0.rawValue)")) }, selection: $range)
            HistoryPeriodBar(label: HistoryFormat.days(period.first, period.last, today: today),
                             earlier: hasEarlier ? { back += 1; selected = nil } : nil,
                             later: back > 0 ? { back -= 1; selected = nil } : nil)
            HistoryHeadline(measure: m, range: range, stats: stats)
            // A chart only where there is something to draw: an empty frame says nothing the line above has not.
            if range == .day ? !marks.isEmpty && !m.isClock : stats.days > 0 {
                KCard {
                    if range == .day {
                        HistorySessionChart(measure: m, marks: marks, tone: group.tone)
                    } else {
                        HistoryDayChart(measure: m, points: points, range: range, tone: group.tone,
                                        fades: false, selected: $selected)
                        if let s = selected, let p = points.first(where: { $0.day == s }) {
                            HistoryPicked(measure: m, point: p, today: today)
                        }
                    }
                    HistoryLegend(measure: m, tone: group.tone, showsUsual: range != .day, notes: notes)
                }
            }
        } trailing: {
            if range == .month { HistoryWeeks(measure: m, weeks: HistoryMath.weeks(points), today: today, tone: group.tone) }
            HistorySessions(sessions: showsAll ? listed : Array(listed.prefix(HistorySessions.short)), total: listed.count,
                            range: range, zone: zone, today: today, tone: group.tone) { showsAll = true }
        }
        .onChange(of: range) { _, _ in back = 0; selected = nil; showsAll = false }
    }
}

/// Where the readings came from, how one day's value is made, and the scale when the unit is one.
struct HistoryAbout: View {
    let measure: HistoryMeasure
    private var lines: [String] {
        var out: [String] = []
        let devices = HistoryDevice.names(measure.devices)
        if !devices.isEmpty { out.append(T("evidence.from", ["name": devices])) }
        if let rule = measure.rule { out.append(T("history.perday.\(rule.rawValue)")) }
        if HistoryFormat.isScale(measure.unit) { out.append(T("history.scale", ["scale": measure.unit])) }
        if measure.isClock { out.append(T("history.clock")) }
        return out
    }
    var body: some View {
        Text(lines.joined(separator: " · ")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The period's days with a step to earlier and to later ones.
struct HistoryPeriodBar: View {
    let label: String
    let earlier: (() -> Void)?
    let later: (() -> Void)?
    var body: some View {
        HStack(spacing: KaikuTokens.Space.s2) {
            IconButton("chevron.left", label: T("history.earlier")) { earlier?() }
                .disabled(earlier == nil).opacity(earlier == nil ? 0.35 : 1)
            Text(label).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                .multilineTextAlignment(.center).wraps()
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("history.period")
            IconButton("chevron.right", label: T("history.later")) { later?() }
                .disabled(later == nil).opacity(later == nil ? 0.35 : 1)
        }
    }
}

/// What the period adds up to: the total or the average in large type, then the range and the days it is made of.
struct HistoryHeadline: View {
    let measure: HistoryMeasure
    let range: HistoryRange
    let stats: HistoryStats

    private var label: String {
        if range == .day { return T("history.perday.\(measure.rule?.rawValue ?? "average")") }
        return T(measure.rule?.addsUp == true ? "history.total" : "history.average")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            if let v = HistoryMath.headline(stats, rule: measure.rule) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(label).kText(.caption, weight: .semibold).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                    Text(written(v)).kText(.title1, weight: .bold).monospacedDigit()
                        .foregroundStyle(KaikuTokens.Colors.ink).wraps()
                        .accessibilityIdentifier("history.headline")
                }
                .accessibilityElement(children: .combine)
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: KaikuTokens.Space.s5) { facts }
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) { facts }
                }
            } else {
                Text(T(HistoryFormat.emptyKey(measure, card: false))).kText(.body)
                    .foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder private var facts: some View {
        if range == .day {
            fact(T("history.sessions"), String(stats.sessions))
        } else {
            if measure.rule?.addsUp == true, let a = stats.average { fact(T("history.average.day"), HistoryFormat.average(a, of: measure)) }
            if let lo = stats.low, let hi = stats.high { fact(T("history.spread"), HistoryFormat.span(lo, hi, of: measure)) }
            fact(T("history.days"), String(stats.days))
        }
    }

    /// A total and a single day are written as they are; an average of days may need a decimal more.
    private func written(_ v: Double) -> String {
        range == .day || measure.rule?.addsUp == true ? HistoryFormat.value(v, of: measure) : HistoryFormat.average(v, of: measure)
    }

    private func fact(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title).kText(.caption, weight: .semibold).foregroundStyle(KaikuTokens.Colors.muted)
            Text(value).kText(.footnote, weight: .semibold).monospacedDigit().foregroundStyle(KaikuTokens.Colors.ink)
        }
        .fixedSize()
        .accessibilityElement(children: .combine)
    }
}

/// The bars' colour: the group's tone, lighter for what the legend calls lighter. Never a judgement.
private func historyFill(_ tone: KTone, light: Bool) -> Color { tone.ink.opacity(light ? 0.45 : 1) }

/// Week and month, one mark a day, with the usual range as a soft band behind. A measure that adds up over a day
/// (minutes, steps, taps) is a bar standing on zero; a level (an average, a latest value, a time of day) is a dot
/// at its height on an axis that fits the person's own values, because a bar would say "this much" of something
/// that is not an amount.
struct HistoryDayChart: View {
    let measure: HistoryMeasure
    let points: [HistoryPoint]
    let range: HistoryRange
    let tone: KTone
    /// Unused since 2026-11-15: History no longer marks simulated days (always false).
    let fades: Bool
    @Binding var selected: String?

    private var values: [Double] { points.compactMap(\.value) + [measure.usual?.low, measure.usual?.high].compactMap { $0 } }
    private var domain: ClosedRange<Double> { HistoryMath.domain(values, measure: measure) }
    private var labelled: [String] {
        // A month names one day a week, three days in from each week's end, so no label sits on the chart's edge.
        range == .week ? points.map(\.day) : points.enumerated().filter { (points.count - 1 - $0.offset) % 7 == 3 }.map(\.element.day)
    }

    var body: some View {
        Chart {
            if let u = measure.usual {
                RectangleMark(yStart: .value("low", u.low), yEnd: .value("high", u.high))
                    .foregroundStyle(tone.soft)
                    .accessibilityHidden(true)
            }
            ForEach(points) { p in
                if let v = p.value {
                    if !HistoryMath.standsOnZero(measure) {
                        PointMark(x: .value("day", p.day), y: .value(measure.title, v))
                            .symbolSize(range == .week ? 110 : 44)
                            .foregroundStyle(historyFill(tone, light: fades && p.simulated))
                    } else {
                        BarMark(x: .value("day", p.day), y: .value(measure.title, v), width: .ratio(range == .week ? 0.56 : 0.7))
                            .cornerRadius(range == .week ? 4 : 2)
                            .foregroundStyle(historyFill(tone, light: fades && p.simulated))
                    }
                }
            }
            if let s = selected, points.contains(where: { $0.day == s }) {
                RuleMark(x: .value("day", s)).foregroundStyle(KaikuTokens.Colors.ink2.opacity(0.35))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    .accessibilityHidden(true)
            }
        }
        .chartXScale(domain: points.map(\.day))
        .chartYScale(domain: domain)
        .chartXAxis {
            AxisMarks(values: labelled) { v in
                AxisValueLabel { if let k = v.as(String.self) { Text(HistoryFormat.axisDay(k, range: range)).kText(.micro) } }
            }
        }
        .chartYAxis { HistoryAxis.marks(domain, measure: measure) }
        .chartOverlay { proxy in
            GeometryReader { g in
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onTapGesture { at in
                        guard let frame = proxy.plotFrame else { return }
                        let day: String? = proxy.value(atX: at.x - g[frame].origin.x)
                        selected = day == selected ? nil : day
                    }
            }
        }
        .frame(height: 200)
        .accessibilityIdentifier("history.chart")
    }
}

/// Day: that day's sessions on the day's clock. A count measure is drawn as how many in each hour. Shown only
/// when the day has marks (a time-of-day measure, and one whose own reading cannot be told, have none).
struct HistorySessionChart: View {
    let measure: HistoryMeasure
    let marks: [HistoryMark]
    let tone: KTone

    private struct Bar: Identifiable { let id: String; let minute: Double; let value: Double; let light: Bool }
    private var bars: [Bar] {
        if measure.rule == .count {
            let hours = Dictionary(grouping: marks) { Int($0.minute / 60) }
            return hours.keys.sorted().map { Bar(id: "h\($0)", minute: Double($0) * 60 + 30, value: Double(hours[$0]?.count ?? 0), light: false) }
        }
        let mixed = Self.fades(marks, measure: measure)
        return marks.map { Bar(id: $0.id, minute: $0.minute, value: $0.value, light: mixed && $0.warmup) }
    }

    /// A day's sessions always stand on zero: each bar is one session's own reading (or how many in that hour).
    private var domain: ClosedRange<Double> { 0...Swift.max(1, (bars.map(\.value).max() ?? 1) * 1.08) }

    /// Warm-up sessions are drawn lighter only when the day also has other sessions to tell them from.
    static func fades(_ marks: [HistoryMark], measure: HistoryMeasure) -> Bool {
        measure.rule != .count && !measure.isClock
            && marks.contains { $0.warmup } && marks.contains { !$0.warmup }
    }

    var body: some View {
        Chart(bars) { b in
            BarMark(x: .value("time", b.minute), y: .value(measure.title, b.value), width: .fixed(measure.rule == .count ? 9 : 7))
                .cornerRadius(3)
                .foregroundStyle(historyFill(tone, light: b.light))
        }
        .chartXScale(domain: 0...1440)
        .chartYScale(domain: domain)
        .chartXAxis {
            AxisMarks(values: [0, 360, 720, 1080, 1440]) { v in
                AxisGridLine().foregroundStyle(KaikuTokens.Colors.line)
                AxisValueLabel { if let m = v.as(Double.self), m < 1440 { Text(HistoryFormat.hour(m)).kText(.micro) } }
            }
        }
        .chartYAxis { HistoryAxis.marks(domain, measure: measure) }
        .frame(height: 200)
        .accessibilityIdentifier("history.chart")
    }
}

/// The value axis of both charts: plain numbers, a time of day as a time, a share as a percentage, and minutes
/// from two hours up in hours.
enum HistoryAxis {
    /// One tick's label. `hours`: the axis counts in hours (minutes from two hours up).
    static func label(_ d: Double, measure: HistoryMeasure, hours: Bool) -> String {
        switch measure.kind {
        case .clock: return HistoryFormat.clock(d)
        case .percent: return HistoryFormat.percent(d, decimals: abs(d * 100 - (d * 100).rounded()) > 0.05 ? 1 : 0)
        case .duration, .number: return hours ? "\(HistoryFormat.number(d / 60)) \(T("history.unit.h"))" : HistoryFormat.number(d)
        }
    }

    /// Minutes are counted in hours on the axis once it reaches two hours.
    static func countsHours(_ domain: ClosedRange<Double>, measure: HistoryMeasure) -> Bool {
        (measure.kind == .duration || (measure.kind == .number && measure.unit == "min")) && domain.upperBound >= 120
    }

    /// Minutes between ticks: the first step that leaves at most about four ticks across the axis.
    static func step(_ domain: ClosedRange<Double>, from steps: [Double]) -> Double {
        let span = domain.upperBound - domain.lowerBound
        return steps.first { span / $0 <= 4 } ?? (steps.last ?? 60) * 2
    }

    static func marks(_ domain: ClosedRange<Double>, measure: HistoryMeasure) -> some AxisContent {
        let hours: Double? = countsHours(domain, measure: measure)
            ? step(domain, from: [30, 60, 120, 180, 240, 360, 480, 720]) : nil
        let clock: Double? = measure.isClock ? step(domain, from: [15, 30, 60, 120, 180, 240, 360]) : nil
        let ticks: AxisMarkValues = (hours ?? clock).map { .stride(by: $0) } ?? .automatic(desiredCount: 4)
        return AxisMarks(position: .trailing, values: ticks) { v in
            AxisGridLine().foregroundStyle(KaikuTokens.Colors.line)
            AxisValueLabel {
                if let d = v.as(Double.self) {
                    Text(label(d, measure: measure, hours: hours != nil)).kText(.micro)
                }
            }
        }
    }
}

/// The day picked on the chart, in words.
struct HistoryPicked: View {
    let measure: HistoryMeasure
    let point: HistoryPoint
    let today: String
    var body: some View {
        let day = HistoryFormat.day(point.day, today: today, soFar: true)
        let words: String = {
            guard let v = point.value else { return "\(day) · \(T("history.none.day"))" }
            let parts = [day, HistoryFormat.value(v, of: measure), T("history.sessions.n", n: point.sessions)]
            return parts.joined(separator: " · ")
        }()
        Text(words).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityIdentifier("history.picked")
    }
}

/// What the chart's marks mean: the unit, the soft band, lighter bars.
struct HistoryLegend: View {
    let measure: HistoryMeasure
    let tone: KTone
    let showsUsual: Bool
    /// What lighter marks mean when the chart has any, and that today's mark is the day so far.
    let notes: [String]
    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
            if showsUsual, let u = measure.usual {
                HStack(alignment: .firstTextBaseline, spacing: KaikuTokens.Space.s2) {
                    RoundedRectangle(cornerRadius: 3, style: .continuous).fill(tone.soft)
                        .overlay(RoundedRectangle(cornerRadius: 3, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
                        .frame(width: 18, height: 10)
                        .accessibilityHidden(true)
                    Text(T("history.usual", ["range": HistoryFormat.span(u.low, u.high, of: measure)]))
                        .kText(.caption).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                }
                .accessibilityIdentifier("history.usual")
            }
            ForEach(notes, id: \.self) { Text($0).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A month, week by week: each week's days and what they add up to.
struct HistoryWeeks: View {
    let measure: HistoryMeasure
    let weeks: [HistoryWeek]
    let today: String
    let tone: KTone
    var body: some View {
        KSection(T("history.byweek"), icon: "calendar", tone: tone) {
            ForEach(Array(weeks.enumerated()), id: \.element.id) { i, w in
                if i > 0 { HistoryRule() }
                HStack(alignment: .firstTextBaseline, spacing: KaikuTokens.Space.s3) {
                    Text(HistoryFormat.days(w.first, w.last, today: today)).kText(.body).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                        .frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .trailing, spacing: 0) {
                        if let v = HistoryMath.headline(w.stats, rule: measure.rule) {
                            Text(measure.rule?.addsUp == true ? HistoryFormat.value(v, of: measure) : HistoryFormat.average(v, of: measure))
                                .kText(.body, weight: .semibold).monospacedDigit()
                                .foregroundStyle(KaikuTokens.Colors.ink)
                            if let lo = w.stats.low, let hi = w.stats.high, w.stats.days > 1 {
                                Text(HistoryFormat.span(lo, hi, of: measure)).kText(.caption).monospacedDigit()
                                    .foregroundStyle(KaikuTokens.Colors.muted)
                            }
                        } else {
                            Text(T("history.none.week")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted)
                        }
                    }
                }
                .padding(.horizontal, KaikuTokens.Space.s4)
                .padding(.vertical, KaikuTokens.Space.s3)
                .accessibilityElement(children: .combine)
            }
        }
    }
}

/// A hairline between rows that have no icon tile.
struct HistoryRule: View {
    var body: some View { Rectangle().fill(KaikuTokens.Colors.line).frame(height: 1).padding(.leading, KaikuTokens.Space.s4) }
}

/// The sessions of the period, newest first, each with its own numbers.
struct HistorySessions: View {
    static let short = 6
    let sessions: [HistorySession]
    let total: Int
    let range: HistoryRange
    let zone: TimeZone
    let today: String
    let tone: KTone
    let more: () -> Void

    var body: some View {
        KSection(T("history.sessions"), subtitle: T("history.sessions.d"), icon: "list.bullet", tone: tone) {
            if sessions.isEmpty {
                Text(T("history.sessions.none")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(KaikuTokens.Space.s4)
            }
            ForEach(Array(sessions.enumerated()), id: \.element.id) { i, s in
                if i > 0 { HistoryRule() }
                HistorySessionRow(session: s, zone: zone, today: today)
            }
            if total > sessions.count {
                HistoryRule()
                Button(action: more) {
                    Text(T("history.sessions.more", n: total - sessions.count)).kText(.body, weight: .semibold)
                        .foregroundStyle(KaikuTokens.Colors.clay)
                        .frame(maxWidth: .infinity, minHeight: KaikuTokens.Size.tapMin, alignment: .leading)
                        .padding(.horizontal, KaikuTokens.Space.s4)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.kPressRow())
            }
        }
    }
}

/// One session: when, on which device, and its numbers in a line that wraps.
struct HistorySessionRow: View {
    let session: HistorySession
    let zone: TimeZone
    let today: String
    @Environment(\.dynamicTypeSize) private var dts

    private var when: String {
        guard let d = KaikuTime.parse(session.ts) else { return session.ts }
        return "\(HistoryFormat.day(HistoryDayKey.local(d, zone: zone), today: today)) \(HistoryFormat.time(d, zone: zone))"
    }

    /// The row's title: which kind of session where the service says so (a ritual step), else when it happened.
    private var label: String? { session.label.flatMap { $0.isEmpty ? nil : $0 } }

    private var notes: String {
        var parts: [String] = []
        if label != nil { parts.append(when) }
        if let name = HistoryDevice.name(session.device) { parts.append(name) }
        if session.warmup == true { parts.append(T("history.warmup")) }
        return parts.joined(separator: " · ")
    }

    /// "Tempo 96 bpm": the title quietly, the number in ink. A pair stays together when the row wraps.
    private func pair(_ v: HistoryValue) -> some View {
        (Text(v.title + " ").foregroundStyle(KaikuTokens.Colors.ink2)
            + Text(HistoryFormat.value(v)).fontWeight(.semibold).foregroundStyle(KaikuTokens.Colors.ink))
            .kText(.footnote).monospacedDigit()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
            Text(label ?? when).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            if !session.values.isEmpty {
                if dts.isAccessibilitySize {
                    ForEach(session.values) { pair($0).wraps() }
                } else {
                    // One pair a line piece; a pair longer than the row itself (a long title from the service) wraps.
                    FlowRow(spacing: KaikuTokens.Space.s3) { ForEach(session.values) { pair($0).fixedSize(horizontal: false, vertical: true) } }
                }
            }
            if !notes.isEmpty { Text(notes).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .accessibilityElement(children: .combine)
    }
}

import Foundation

// History's arithmetic, pure and tested: which days a period covers, what a period adds up to from the daily
// values, a month as weeks, the sessions of one day, and how a number is written. No views, no network.
// The daily values come from the service (`PersonHistory`); nothing here judges them or compares them.

/// The measure page's range switch.
public enum HistoryRange: String, CaseIterable, Identifiable, Sendable {
    case day, week, month
    public var id: String { rawValue }
    /// Days in one period. A month is four whole weeks, so it reads week by week without a ragged end.
    public var length: Int {
        switch self {
        case .day: return 1
        case .week: return 7
        case .month: return 28
        }
    }
}

/// Local day keys ("2026-11-14") as plain calendar days: adding days never touches a time zone or daylight saving.
public enum HistoryDayKey {
    private static let calendar: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }()
    private static let format: DateFormatter = {
        let f = DateFormatter()
        f.calendar = calendar
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = calendar.timeZone
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// Noon UTC of that calendar day (a stable point to format or chart; nil for a malformed key).
    public static func date(_ key: String) -> Date? {
        guard key.count == 10, let d = format.date(from: key) else { return nil }
        return d.addingTimeInterval(12 * 3600)
    }

    public static func adding(_ days: Int, to key: String) -> String? {
        guard key.count == 10, let d = format.date(from: key), let next = calendar.date(byAdding: .day, value: days, to: d) else { return nil }
        return format.string(from: next)
    }

    /// Whole days from `a` to `b` (positive when `b` is later).
    public static func days(from a: String, to b: String) -> Int? {
        guard let x = format.date(from: a), let y = format.date(from: b) else { return nil }
        return calendar.dateComponents([.day], from: x, to: y).day
    }

    /// The local day of a moment in `zone` (the home's: a session at 23:40 belongs to that evening).
    public static func local(_ date: Date, zone: TimeZone = .current) -> String {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = zone
        let p = c.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", p.year ?? 0, p.month ?? 0, p.day ?? 0)
    }

    /// Minutes after local midnight of a moment in `zone`.
    public static func minutes(_ date: Date, zone: TimeZone) -> Double {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = zone
        let p = c.dateComponents([.hour, .minute, .second], from: date)
        return Double((p.hour ?? 0) * 60 + (p.minute ?? 0)) + Double(p.second ?? 0) / 60
    }
}

/// One period on the measure page: consecutive local days, oldest first.
public struct HistoryPeriod: Equatable, Sendable {
    public let range: HistoryRange
    public let days: [String]
    public var first: String { days.first ?? "" }
    public var last: String { days.last ?? "" }

    /// The period of `range` that ends on `day`, or `back` whole periods before it.
    public static func ending(_ day: String, _ range: HistoryRange, back: Int = 0) -> HistoryPeriod {
        let end = HistoryDayKey.adding(-max(0, back) * range.length, to: day) ?? day
        let keys = (0..<range.length).reversed().compactMap { HistoryDayKey.adding(-$0, to: end) }
        return HistoryPeriod(range: range, days: keys.isEmpty ? [day] : keys)
    }
}

/// One day of a period: the day's value, or nothing recorded.
public struct HistoryPoint: Equatable, Sendable, Identifiable {
    public let day: String
    public var value: Double?
    public var sessions: Int
    public var simulated: Bool
    public var id: String { day }
    public init(day: String, value: Double? = nil, sessions: Int = 0, simulated: Bool = false) {
        self.day = day; self.value = value; self.sessions = sessions; self.simulated = simulated
    }
}

/// What a period adds up to. Only days with a value count: a day without a record is not a zero.
public struct HistoryStats: Equatable, Sendable {
    /// The average of the days that have a value.
    public var average: Double?
    /// Their sum (shown only for a measure whose day is a total or a count).
    public var total: Double?
    public var low: Double?
    public var high: Double?
    /// Days that have a value.
    public var days: Int
    public var sessions: Int
    /// How many of those days hold simulated records.
    public var simulatedDays: Int
    /// Every counted day holds simulated records (the label "Simulated", as in "Today, so far").
    public var simulated: Bool { days > 0 && simulatedDays == days }
    /// Some days are simulated and some are not.
    public var partlySimulated: Bool { simulatedDays > 0 && simulatedDays < days }
}

/// Seven days of a month view, with what they add up to.
public struct HistoryWeek: Equatable, Sendable, Identifiable {
    public let first: String
    public let last: String
    public let stats: HistoryStats
    public var id: String { first }
}

/// One session placed on its day: when it happened and, where the wire lets us tell, this measure's own reading.
public struct HistoryMark: Equatable, Sendable, Identifiable {
    public let id: String
    /// Minutes after local midnight in the home's time zone.
    public let minute: Double
    public let value: Double
    public let warmup: Bool
    public let simulated: Bool
}

public extension HistoryPerDay {
    /// A total stays a total over a week or a month; every other rule rolls up as an average of the days.
    var addsUp: Bool { self == .total || self == .count }
}

public enum HistoryMath {
    /// The period day by day; a day the service has no value for stays empty.
    public static func points(_ days: [HistoryDay], in period: HistoryPeriod) -> [HistoryPoint] {
        var by: [String: HistoryDay] = [:]
        for d in days where d.value.isFinite { by[d.date] = d }   // a repeated day: the later entry wins
        return period.days.map { key in
            guard let d = by[key] else { return HistoryPoint(day: key) }
            return HistoryPoint(day: key, value: d.value, sessions: max(0, d.sessions), simulated: d.sim)
        }
    }

    public static func stats(_ points: [HistoryPoint]) -> HistoryStats {
        let with = points.filter { $0.value != nil }
        let values = with.compactMap(\.value)
        let sum = values.reduce(0, +)
        return HistoryStats(average: values.isEmpty ? nil : sum / Double(values.count), total: values.isEmpty ? nil : sum,
                            low: values.min(), high: values.max(), days: values.count,
                            sessions: with.reduce(0) { $0 + $1.sessions },
                            simulatedDays: with.filter(\.simulated).count)
    }

    /// The one number a period is summed up by: the total for a measure that adds up, else the average of its days.
    public static func headline(_ stats: HistoryStats, rule: HistoryPerDay?) -> Double? {
        rule?.addsUp == true ? stats.total : stats.average
    }

    /// A period as whole weeks, newest first; the oldest block keeps what is left when the days do not divide by 7.
    public static func weeks(_ points: [HistoryPoint]) -> [HistoryWeek] {
        var out: [HistoryWeek] = []
        var end = points.count
        while end > 0 {
            let start = max(0, end - 7)
            let block = Array(points[start..<end])
            if let f = block.first, let l = block.last { out.append(HistoryWeek(first: f.day, last: l.day, stats: stats(block))) }
            end = start
        }
        return out
    }

    /// The newest day that has a value (what a summary card shows).
    public static func latest(_ days: [HistoryDay]) -> HistoryDay? {
        days.filter { $0.value.isFinite }.max { $0.date < $1.date }
    }

    /// The sessions that happened on one local day (the home's time zone), earliest first.
    public static func sessions(_ all: [HistorySession], on day: String, zone: TimeZone) -> [HistorySession] {
        Array(sessions(all, from: day, to: day, zone: zone).reversed())
    }

    /// The sessions inside a span of local days, newest first.
    public static func sessions(_ all: [HistorySession], from first: String, to last: String, zone: TimeZone) -> [HistorySession] {
        all.compactMap { s -> (Date, HistorySession)? in
            guard let d = KaikuTime.parse(s.ts) else { return nil }
            let key = HistoryDayKey.local(d, zone: zone)
            return key >= first && key <= last ? (d, s) : nil
        }
        .sorted { $0.0 > $1.0 }
        .map(\.1)
    }

    /// The days day view steps through, oldest first: every day with a value or a listed session. Stepping
    /// lands on the next recorded day, not on each empty one in between.
    public static func recordedDays(_ measure: HistoryMeasure, zone: TimeZone) -> [String] {
        var days = Set(measure.days.filter { $0.value.isFinite }.map(\.date))
        for s in measure.sessions { if let d = KaikuTime.parse(s.ts) { days.insert(HistoryDayKey.local(d, zone: zone)) } }
        return days.sorted()
    }

    /// The newest day that has anything to show in day view: a listed session, else a daily value.
    public static func latestDay(_ measure: HistoryMeasure, zone: TimeZone) -> String? {
        recordedDays(measure, zone: zone).last
    }

    // MARK: how a measure is drawn

    /// A measure whose day is a total or a count is drawn as bars standing on zero: the bar's length is the amount.
    /// Every other measure is a level (an average, a latest value, a time of day): drawn as a mark at its height.
    public static func standsOnZero(_ m: HistoryMeasure) -> Bool { m.rule?.addsUp == true && !m.isClock }

    /// The lowest and the highest value of a scale unit ("1 to 5" gives 1...5); nil for any other unit.
    public static func scale(_ unit: String) -> ClosedRange<Double>? {
        let parts = unit.split(separator: " ")
        guard parts.count == 3, parts[1] == "to", let a = Double(parts[0]), let b = Double(parts[2]), a < b else { return nil }
        return a...b
    }

    /// The chart's value axis. Bars stand on zero. A scale shows the whole scale. A time of day and any other
    /// level get the room their own values (and the usual range) need, with a margin, never below zero for a
    /// measure that has no negative values; when that room reaches most of the way to zero it starts at zero.
    public static func domain(_ values: [Double], measure m: HistoryMeasure) -> ClosedRange<Double> {
        let finite = values.filter(\.isFinite)
        guard let low = finite.min(), let high = finite.max() else { return 0...1 }
        if standsOnZero(m) { return Swift.min(0, low)...(high > 0 ? high * 1.08 : 1) }
        if m.kind == .percent {
            // A share: the room its own values need, never below 0% and never above 100% (unless a value is).
            let pad = Swift.max((high - low) * 0.35, 0.02)
            var floor = Swift.max(Swift.min(0, low), low - pad)
            if floor <= high * 0.4 { floor = Swift.min(0, low) }
            return floor...Swift.max(high, Swift.min(1, high + pad))
        }
        if let s = scale(m.unit), !m.isClock { return Swift.min(s.lowerBound, low)...Swift.max(s.upperBound, high) }
        if m.isClock {
            let pad = Swift.max(30, (high - low) * 0.25)
            return (low - pad)...(high + pad)
        }
        let pad = Swift.max((high - low) * 0.35, abs(high) * 0.04, 1e-6)
        var floor = low - pad
        if low >= 0, floor <= high * 0.4 { floor = 0 }
        return floor...(high + pad)
    }

    // MARK: which of a session's numbers is this measure's own

    /// The key of the session number that is this measure's own reading, or nil when the wire does not let us tell.
    /// The wire names a session's numbers by payload field and a measure by its own key, with no link between
    /// them, so the link is proved from the data: a number qualifies only if it has the measure's unit and format
    /// and, on every day whose sessions are all listed, rolling it up by the measure's own per-day rule gives that
    /// day's value. Nothing is guessed from a title: a measure whose reading is not among the session numbers gets
    /// no per-session chart rather than a neighbour's numbers.
    public static func sessionKey(_ m: HistoryMeasure, zone: TimeZone) -> String? {
        guard let rule = m.rule, rule != .count else { return nil }
        var keys: [String] = []
        for s in m.sessions { for v in s.values where v.unit == m.unit && v.format == m.format && !keys.contains(v.key) { keys.append(v.key) } }
        guard !keys.isEmpty else { return nil }
        var byDay: [String: [(Date, HistorySession)]] = [:]
        for s in m.sessions where s.warmup != true {
            guard let d = KaikuTime.parse(s.ts) else { continue }
            byDay[HistoryDayKey.local(d, zone: zone), default: []].append((d, s))
        }
        var best: (key: String, error: Double)?
        for key in keys {
            let digits = fractionDigits(m.sessions.flatMap(\.values).filter { $0.key == key }.map(\.value))
            let slack = 0.5 * pow(10, -Double(digits)) + 1e-6
            var checked = 0, error = 0.0, wrong = false
            for day in m.days {
                let values = (byDay[day.date] ?? []).sorted { $0.0 < $1.0 }.compactMap { $0.1.values.first { $0.key == key }?.value }
                guard !values.isEmpty, values.count == day.sessions else { continue }   // not every session of the day is listed
                let candidates = rolled(values, rule)
                let off = candidates.map { abs($0 - day.value) }.min() ?? .infinity
                if off > slack * (rule == .total ? Double(values.count) : 1) { wrong = true; break }
                checked += 1; error += off
            }
            if !wrong, checked > 0, best == nil || error < best!.error { best = (key, error) }
        }
        return best?.key
    }

    /// A day's sessions rolled up by the per-day rule. "average" covers the service's mean and its median.
    static func rolled(_ values: [Double], _ rule: HistoryPerDay) -> [Double] {
        guard let first = values.first, let last = values.last else { return [] }
        switch rule {
        case .average:
            let sorted = values.sorted(), n = sorted.count
            let median = n % 2 == 1 ? sorted[n / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2
            return [values.reduce(0, +) / Double(n), median]
        case .total: return [values.reduce(0, +)]
        case .highest: return [values.max() ?? first]
        case .lowest: return [values.min() ?? first]
        case .latest: return [last]
        case .first: return [first]
        case .count: return [Double(values.count)]
        }
    }

    static func fractionDigits(_ values: [Double]) -> Int {
        for d in 0...2 where values.allSatisfy({ abs(($0 * pow(10, Double(d))).rounded() - $0 * pow(10, Double(d))) < 1e-6 }) { return d }
        return 3
    }

    /// One day's sessions as marks on the day's clock. A count measure gives one mark per session (each counts 1);
    /// otherwise the marks carry this measure's own reading, and there are none when it cannot be told (`sessionKey`).
    public static func marks(_ m: HistoryMeasure, on day: String, zone: TimeZone) -> [HistoryMark] {
        let key = sessionKey(m, zone: zone)
        guard m.rule == .count || key != nil else { return [] }
        return sessions(m.sessions, on: day, zone: zone).compactMap { s in
            guard let d = KaikuTime.parse(s.ts) else { return nil }
            let value: Double
            if m.rule == .count { value = 1 } else {
                guard let v = s.values.first(where: { $0.key == key })?.value else { return nil }
                value = v
            }
            return HistoryMark(id: s.id, minute: HistoryDayKey.minutes(d, zone: zone), value: value,
                               warmup: s.warmup == true, simulated: s.sim)
        }
    }
}

/// How History writes numbers and days: plainly, in the device's language, never with a judgement.
public enum HistoryFormat {
    static var locale: Locale { Locale(identifier: L10n.shared.language.rawValue) }

    /// "72", "1,240", "3.1", "0.83". Without `decimals`, whole numbers stay whole and small ones keep up to two.
    public static func number(_ v: Double, decimals: Int? = nil) -> String {
        guard v.isFinite else { return "–" }
        let f = NumberFormatter()
        f.locale = locale
        f.numberStyle = .decimal
        let a = abs(v)
        let digits = decimals ?? (abs(v - v.rounded()) < 1e-9 || a >= 100 ? 0 : a >= 10 ? 1 : 2)
        f.minimumFractionDigits = decimals ?? 0
        f.maximumFractionDigits = max(0, digits)
        f.roundingMode = .halfUp
        return f.string(from: NSNumber(value: v)) ?? String(v)
    }

    /// "23:30" for minutes after local midnight (negative = the evening before, past 1440 = after the next midnight).
    public static func clock(_ minutes: Double) -> String {
        guard minutes.isFinite else { return "–" }
        let m = ((Int(minutes.rounded()) % 1440) + 1440) % 1440
        let f = DateFormatter()
        f.locale = locale
        f.timeZone = TimeZone(identifier: "UTC")
        f.timeStyle = .short
        f.dateStyle = .none
        return f.string(from: Date(timeIntervalSince1970: TimeInterval(m * 60)))
    }

    /// The line for a measure without a value in view. No day at all: its sessions were practice rounds (a game's
    /// first sessions), or sessions that are listed and do not count toward a day (too short, or another kind).
    /// It says "practice" only where a practice round is listed.
    public static func emptyKey(_ m: HistoryMeasure, card: Bool) -> String {
        if !m.days.isEmpty { return card ? "history.card.uncounted" : "history.none" }
        let practice = m.sessions.isEmpty || m.sessions.contains { $0.warmup == true }
        return practice ? (card ? "history.card.practice" : "history.practice") : (card ? "history.card.uncounted" : "history.uncounted")
    }

    /// A unit that is really a scale ("0 to 1", "1 to 5"): written once beside the measure, not after every number.
    public static func isScale(_ unit: String) -> Bool {
        let parts = unit.split(separator: " ")
        return parts.count == 3 && parts[1] == "to" && Double(parts[0]) != nil && Double(parts[2]) != nil
    }

    /// "72 bpm", "0.83", "07:40", "7 h 12 min", "3 min 5 s", "14%", "14% of the time". A scale or an empty unit
    /// leaves just the number. The format is the service's word for how the value is to be read:
    /// `clock` (minutes after midnight), `percent` (a share from 0 to 1; `decimals` are the percentage's),
    /// `duration` (minutes, whatever the unit says), else a plain number with its unit.
    public static func value(_ v: Double, unit: String, format: HistoryValueFormat = .number, decimals: Int? = nil) -> String {
        switch format {
        case .clock: return clock(v)
        case .percent:
            let n = percent(v, decimals: decimals ?? 0)
            return unit.isEmpty ? n : "\(n) \(unit)"
        case .duration:
            if let long = duration(v, unit: "min") { return long }
            return "\(number(v, decimals: decimals ?? 0)) \(T("history.unit.min"))"
        case .number:
            if let long = duration(v, unit: unit) { return long }
            let n = number(v, decimals: decimals)
            return unit.isEmpty || isScale(unit) ? n : "\(n) \(unit)"
        }
    }

    public static func value(_ v: Double, unit: String, clock isClock: Bool, decimals: Int? = nil) -> String {
        value(v, unit: unit, format: isClock ? .clock : .number, decimals: decimals)
    }

    public static func value(_ v: Double, of m: HistoryMeasure) -> String {
        value(v, unit: m.unit, format: m.kind, decimals: m.decimals)
    }

    /// "14%", "4.5%": a share from 0 to 1 as a percentage, in the language's own way of writing one.
    public static func percent(_ share: Double, decimals: Int = 0) -> String {
        guard share.isFinite else { return "–" }
        let f = NumberFormatter()
        f.locale = locale
        f.numberStyle = .percent
        f.minimumFractionDigits = max(0, decimals)
        f.maximumFractionDigits = max(0, decimals)
        f.roundingMode = .halfUp
        return f.string(from: NSNumber(value: share)) ?? "\(number(share * 100, decimals: decimals))%"
    }

    /// An average of days. A measure counted in whole numbers keeps one decimal while its average is small
    /// ("4.5 pebbles", not "5 pebbles" beside a range of 4 – 5); from ten up it is written like any day's value.
    /// A percentage is judged by the number it is written as (4.5%, 14%).
    public static func average(_ v: Double, of m: HistoryMeasure) -> String {
        let shown = m.kind == .percent ? v * 100 : v
        let fine = m.decimals == 0 && m.kind != .clock && abs(shown) < 10 && abs(shown - shown.rounded()) > 0.05
        return value(v, unit: m.unit, format: m.kind, decimals: fine ? 1 : m.decimals)
    }

    /// A session's number beside its own title: "Tempo" + "96 bpm", but "Taps" + "82" and "Early taps" + "0"
    /// (a unit that only repeats the title's last word is left out).
    public static func value(_ v: HistoryValue) -> String {
        let title = v.title.lowercased(), unit = v.unit.lowercased()
        let repeats = !unit.isEmpty && (title == unit || title.hasSuffix(" " + unit))
        // A session's number carries no decimals of its own: a plain number keeps what it has, a percentage and
        // minutes are whole.
        return value(v.value, unit: repeats ? "" : v.unit, format: v.kind)
    }

    /// "6 AM" / "06": the hour under a day's chart.
    public static func hour(_ minutes: Double) -> String {
        let m = ((Int(minutes.rounded()) % 1440) + 1440) % 1440
        let f = DateFormatter()
        f.locale = locale
        f.timeZone = TimeZone(identifier: "UTC")
        f.setLocalizedDateFormatFromTemplate("j")
        return f.string(from: Date(timeIntervalSince1970: TimeInterval(m * 60)))
    }

    /// Minutes from an hour up and seconds from a minute up are written in the larger unit too.
    static func duration(_ v: Double, unit: String) -> String? {
        guard v.isFinite, v.rounded() >= 60, unit == "min" || unit == "s" else { return nil }   // 59.6 is written "1 h", not "60 min"
        let whole = Int(v.rounded())
        let big = whole / 60, small = whole % 60
        let (a, b) = unit == "min" ? (T("history.unit.h"), T("history.unit.min")) : (T("history.unit.min"), T("history.unit.s"))
        return small == 0 ? "\(big) \(a)" : "\(big) \(a) \(small) \(b)"
    }

    /// "64 – 81 bpm", "23:10 – 00:40"; one value when the lowest and the highest are written the same.
    public static func span(_ low: Double, _ high: Double, of m: HistoryMeasure) -> String {
        let a = value(low, of: m), b = value(high, of: m)
        if a == b { return a }
        switch m.kind {
        case .clock: return "\(a) – \(b)"
        case .percent: return "\(percent(low, decimals: m.decimals)) – \(b)"                     // "10% – 18% of the time"
        case .duration:
            return duration(high, unit: "min") != nil ? "\(a) – \(b)" : "\(number(low, decimals: m.decimals)) – \(b)"
        case .number:
            if duration(high, unit: m.unit) != nil || m.unit.isEmpty || isScale(m.unit) { return "\(a) – \(b)" }
            return "\(number(low, decimals: m.decimals)) – \(b)"
        }
    }

    /// "Today", "Yesterday", else "Tue 11 Nov". `soFar`: today is still running, so its value is "Today so far".
    public static func day(_ key: String, today: String, soFar: Bool = false) -> String {
        if key == today { return T(soFar ? "history.today.sofar" : "history.today") }
        if HistoryDayKey.days(from: key, to: today) == 1 { return T("history.yesterday") }
        guard let d = HistoryDayKey.date(key) else { return key }
        return utc("EEEdMMM").string(from: d)
    }

    /// "Nov 8 – 14", "Oct 28 – Nov 3" as the language writes a span of days; one day is written as a day (today
    /// as "Today so far").
    public static func days(_ first: String, _ last: String, today: String) -> String {
        guard first != last else { return day(first, today: today, soFar: true) }
        guard let a = HistoryDayKey.date(first), let b = HistoryDayKey.date(last) else { return "\(first) – \(last)" }
        let f = DateIntervalFormatter()
        f.locale = locale
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateTemplate = "dMMM"
        return f.string(from: a, to: b)
    }

    /// "14:02" for a moment, in the home's time zone, as a clock on the wall shows it (14:02:40 is still 14:02).
    public static func time(_ date: Date, zone: TimeZone) -> String {
        clock(HistoryDayKey.minutes(date, zone: zone).rounded(.down))
    }

    public static func time(_ ts: String, zone: TimeZone) -> String? {
        KaikuTime.parse(ts).map { time($0, zone: zone) }
    }

    /// "Today 14:02", "Tue 11 Nov 09:15": when a session happened, or when History was last fetched.
    public static func moment(_ date: Date, zone: TimeZone, now: Date = Date()) -> String {
        "\(day(HistoryDayKey.local(date, zone: zone), today: HistoryDayKey.local(now, zone: zone))) \(time(date, zone: zone))"
    }

    /// The weekday letter or the day of the month under a chart bar.
    public static func axisDay(_ key: String, range: HistoryRange) -> String {
        guard let d = HistoryDayKey.date(key) else { return "" }
        return utc(range == .week ? "EEEEE" : "d").string(from: d)
    }

    private static func utc(_ template: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = locale
        f.timeZone = TimeZone(identifier: "UTC")
        f.setLocalizedDateFormatFromTemplate(template)
        return f
    }
}

public extension PersonHistory {
    /// The home's time zone; the device's when the name is unknown here.
    var zone: TimeZone { TimeZone(identifier: timezone) ?? .current }

    /// Groups and measures that have something to show, in the service's order. A game with only practice rounds
    /// so far has sessions and no days yet: it is shown, and says so.
    var shown: [HistoryGroup] {
        groups.compactMap { g in
            let measures = g.measures.filter { !$0.days.isEmpty || !$0.sessions.isEmpty }
            return measures.isEmpty ? nil : HistoryGroup(key: g.key, title: g.title, measures: measures)
        }
    }
}

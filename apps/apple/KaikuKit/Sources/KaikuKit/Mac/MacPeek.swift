import Foundation

// Notch island peeks (plan 03 §5.4, plan 02 §8 — the 01:10 peek). Deterministic reflex rules, scripted lines, no
// model: late night (01:00–05:00 and the person is active) → sleepy Kaiku; a long stretch without a break
// (> 90 active min) → "stretch with me?". At most 3 peeks a day, one late peek a night, snoozable (1 h / today),
// never while sharing the screen or with a full-screen app in front, never while sensing is paused.

public enum MacPeekKind: String, Codable, Sendable, CaseIterable {
    case lateNight, stretch

    /// Copy keys (design/copy.json; stretch lines in copy.apple.json). `late_night.peek` in voice_lines.toml.
    public var lineKey: String { self == .lateNight ? "mac.late" : "mac.stretch" }
    public var yesKey: String { self == .lateNight ? "mac.goodnight" : "mac.stretch.yes" }
    public var laterKey: String { self == .lateNight ? "mac.five" : "mac.later" }
    public var voiceKey: String? { self == .lateNight ? "late_night.peek" : nil }
    public var mascot: MascotState { self == .lateNight ? .sleepy : .idle }
}

public enum MacSnooze: Sendable { case hour, today }

/// What the rules see right now. `blocked` = screen sharing / full-screen video or presentation (best effort).
public struct MacPeekContext: Sendable {
    public var now: Date
    public var active: Bool
    public var stretchMin: Double
    public var paused: Bool
    public var blocked: Bool
    public var quietHours: Bool
    public init(now: Date, active: Bool, stretchMin: Double, paused: Bool = false, blocked: Bool = false, quietHours: Bool = false) {
        self.now = now; self.active = active; self.stretchMin = stretchMin; self.paused = paused
        self.blocked = blocked; self.quietHours = quietHours
    }
}

/// What was shown and when (UserDefaults JSON). Wall-clock dates, so a snooze holds across sleep/wake and restarts.
public struct MacPeekLedger: Codable, Sendable, Equatable {
    public var day: String?
    public var count = 0
    public var lateNight: String?
    public var lastStretchAt: Date?
    public var snoozedUntil: Date?
    public init() {}

    public func shownToday(_ now: Date) -> Int { day == macDayKey(now) ? count : 0 }

    public mutating func record(_ kind: MacPeekKind, at now: Date) {
        let key = macDayKey(now)
        if day != key { day = key; count = 0 }
        count += 1
        switch kind {
        case .lateNight: lateNight = key
        case .stretch: lastStretchAt = now
        }
    }

    public mutating func snooze(_ s: MacSnooze, at now: Date, calendar cal: Calendar = .current) {
        switch s {
        case .hour: snoozedUntil = now.addingTimeInterval(3600)
        case .today: snoozedUntil = cal.date(byAdding: .day, value: 1, to: cal.startOfDay(for: now))
        }
    }
}

public enum MacPeekRules {
    public static let maxPerDay = 3
    public static let lateFromHour = 1
    public static let lateToHour = 5
    public static let stretchMin = 90.0

    /// The peek to show now, or nil. Pure: same inputs → same answer.
    public static func decide(_ c: MacPeekContext, _ l: MacPeekLedger, calendar cal: Calendar = .current) -> MacPeekKind? {
        if c.paused || c.blocked || !c.active { return nil }
        if let u = l.snoozedUntil, c.now < u { return nil }
        if l.shownToday(c.now) >= maxPerDay { return nil }
        let hour = cal.component(.hour, from: c.now)
        if hour >= lateFromHour && hour < lateToHour {
            // The late peek is the bedtime nudge itself, so it is the one peek quiet hours don't silence.
            return l.lateNight == macDayKey(c.now) ? nil : .lateNight
        }
        if c.quietHours { return nil }
        if c.stretchMin > stretchMin {
            if let last = l.lastStretchAt, c.now.timeIntervalSince(last) < stretchMin * 60 { return nil }
            return .stretch
        }
        return nil
    }
}

/// When the one daily invitation (Mac notification) goes out: the preferred time today, else tomorrow, moved to
/// the end of quiet hours when it falls inside them. Quiet hours wrap midnight (22:00 → 08:00).
public enum MacInvitationTime {
    public static func inQuiet(_ d: Date, from: Date, to: Date, calendar cal: Calendar = .current) -> Bool {
        let m = minutes(d, cal), f = minutes(from, cal), t = minutes(to, cal)
        if f == t { return false }
        return f < t ? (m >= f && m < t) : (m >= f || m < t)
    }

    public static func next(after now: Date, hour: Int = 17, minute: Int = 0, quietFrom: Date, quietTo: Date,
                            calendar cal: Calendar = .current) -> Date {
        var d = cal.date(bySettingHour: hour, minute: minute, second: 0, of: now)!
        if d <= now { d = cal.date(byAdding: .day, value: 1, to: d)! }
        if inQuiet(d, from: quietFrom, to: quietTo, calendar: cal) {
            let t = cal.dateComponents([.hour, .minute], from: quietTo)
            var e = cal.date(bySettingHour: t.hour ?? 8, minute: t.minute ?? 0, second: 0, of: d)!
            if e <= d { e = cal.date(byAdding: .day, value: 1, to: e)! }
            d = e
        }
        return d
    }

    static func minutes(_ d: Date, _ cal: Calendar) -> Int {
        let c = cal.dateComponents([.hour, .minute], from: d)
        return (c.hour ?? 0) * 60 + (c.minute ?? 0)
    }
}

/// Local calendar day "yyyy-MM-dd" (same format as `AppModel.dayKey`, callable off the main actor).
func macDayKey(_ d: Date, _ cal: Calendar = .current) -> String {
    let c = cal.dateComponents([.year, .month, .day], from: d)
    return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
}

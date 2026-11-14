import Foundation

public enum HealthState: String, Sendable { case off, connected, denied, unavailable }

/// The pure part of the Apple Health summary (plan 05 §5), so it is unit-tested without HealthKit.
/// `date` = the local morning; sleep = the night that ended that morning (18:00 the day before → 12:00);
/// steps / exercise / resting HR / HRV = the previous day (00:00 → 00:00), so a re-sync gives the same numbers.
public enum WearableDailyBuilder {
    public struct Inputs: Sendable {
        public var asleep: [DateInterval] = []
        public var steps: Double?
        public var exerciseMin: Double?
        public var restingHR: Double?
        public var hrvSDNN: Double?
        public var device: WearableDevice = .phone_only
        public init() {}
    }

    /// The window the sleep of `morning` is read from.
    public static func sleepWindow(_ morning: Date, _ cal: Calendar) -> DateInterval {
        let day = cal.startOfDay(for: morning)
        return DateInterval(start: day.addingTimeInterval(-6 * 3600), end: day.addingTimeInterval(12 * 3600))
    }

    public static func dayWindow(_ morning: Date, _ cal: Calendar) -> DateInterval {
        let day = cal.startOfDay(for: morning)
        return DateInterval(start: cal.date(byAdding: .day, value: -1, to: day)!, end: day)
    }

    /// Merges overlapping sleep stages (watch + phone both writing) before summing.
    public static func merge(_ xs: [DateInterval]) -> [DateInterval] {
        var out: [DateInterval] = []
        for x in xs.sorted(by: { $0.start < $1.start }) {
            if let last = out.last, x.start <= last.end {
                out[out.count - 1] = DateInterval(start: last.start, end: max(last.end, x.end))
            } else { out.append(x) }
        }
        return out
    }

    public static func build(morning: Date, _ i: Inputs, calendar cal: Calendar = .current) -> WearableDaily? {
        var w = WearableDaily(date: NudgeScheduler.dayKey(morning, cal), device: i.device)
        let window = sleepWindow(morning, cal)
        let asleep = merge(i.asleep.compactMap { $0.intersection(with: window) })
        if !asleep.isEmpty {
            let total = asleep.reduce(0) { $0 + $1.duration } / 60
            w.sleep_min = min(1440, total.rounded())
            let mid = asleep.first!.start.addingTimeInterval(asleep.last!.end.timeIntervalSince(asleep.first!.start) / 2)
            let midnight = cal.startOfDay(for: morning)
            w.sleep_midpoint_min = max(-720, min(720, (mid.timeIntervalSince(midnight) / 60).rounded()))
        }
        w.steps = i.steps.map { min(200_000, Int($0.rounded())) }
        w.exercise_min = i.exerciseMin.map { min(1440, $0.rounded()) }
        w.resting_hr_bpm = i.restingHR.flatMap { $0 > 20 && $0 < 250 ? ($0 * 10).rounded() / 10 : nil }
        w.hrv_sdnn_ms = i.hrvSDNN.map { min(500, ($0 * 10).rounded() / 10) }
        // Nothing at all → no obs (no watch / no data that day).
        if w.sleep_min == nil, w.steps == nil, w.exercise_min == nil, w.resting_hr_bpm == nil, w.hrv_sdnn_ms == nil { return nil }
        return w
    }

    /// Equal snapshots retry idempotently; new HealthKit samples on the same day get a distinct event.
    public static func envelopeID(home: String, summary: WearableDaily) -> String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let snapshot = (try? encoder.encode(summary)).map { String(decoding: $0, as: UTF8.self) } ?? summary.date
        return StableID.make("wearable_daily|\(home)|\(snapshot)")
    }

    /// Legacy day identifier retained for stored-event compatibility.
    public static func envelopeID(home: String, date: String) -> String { StableID.make("wearable_daily|\(home)|\(date)") }
}

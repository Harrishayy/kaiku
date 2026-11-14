import Foundation

public enum HealthState: String, Sendable { case off, connected, denied, unavailable }

/// The pure part of the Apple Health summary (plan 05 §5), so it is unit-tested without HealthKit.
/// `date` = the local morning; sleep (with its stages and time awake) = the night that ended that morning
/// (18:00 the day before → 12:00); steps / distance / exercise / daylight / resting and walking HR / HRV = the
/// previous day (00:00 → 00:00), so a re-sync gives the same numbers. Only what Apple Health holds is summed up:
/// there is no sleep score here, because Health has none to read, and none is made up.
public enum WearableDailyBuilder {
    public struct Inputs: Sendable {
        /// Every sample that says "asleep", whatever its stage (unspecified, core, deep, REM).
        public var asleep: [DateInterval] = []
        /// The staged samples by stage. All three are empty when the source wrote no stages.
        public var deep: [DateInterval] = []
        public var rem: [DateInterval] = []
        public var core: [DateInterval] = []
        /// The samples that say "awake" (a watch writes them inside its sleep session).
        public var awake: [DateInterval] = []
        public var steps: Double?
        /// Walking and running distance, km.
        public var distanceKm: Double?
        public var exerciseMin: Double?
        /// Time in daylight, minutes.
        public var daylightMin: Double?
        public var restingHR: Double?
        /// Average heart rate while walking, beats a minute.
        public var walkingHR: Double?
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

    /// The parts of `xs` inside `span`, merged. A sample that only touches the span's edge has no length and is left out.
    static func inside(_ xs: [DateInterval], _ span: DateInterval) -> [DateInterval] {
        merge(xs.compactMap { $0.intersection(with: span) }.filter { $0.duration > 0 })
    }

    /// Whole minutes, never more than a day.
    static func minutes(_ xs: [DateInterval]) -> Double {
        min(1440, (xs.reduce(0) { $0 + $1.duration } / 60).rounded())
    }

    /// A heart rate to one place; nil outside what the contract takes (above 20, below 250).
    static func bpm(_ v: Double?) -> Double? {
        guard let v, v.isFinite else { return nil }
        let r = (v * 10).rounded() / 10
        return r > 20 && r < 250 ? r : nil
    }

    /// An amount that cannot be negative: nil for a broken number, else `round`ed and held to `most`.
    static func amount(_ v: Double?, most: Double, round: (Double) -> Double) -> Double? {
        guard let v, v.isFinite, v >= 0 else { return nil }
        return min(most, round(v))
    }

    public static func build(morning: Date, _ i: Inputs, calendar cal: Calendar = .current) -> WearableDaily? {
        var w = WearableDaily(date: NudgeScheduler.dayKey(morning, cal), device: i.device)
        let window = sleepWindow(morning, cal)
        let asleep = inside(i.asleep, window)
        if let first = asleep.first, let last = asleep.last {
            w.sleep_min = minutes(asleep)
            let mid = first.start.addingTimeInterval(last.end.timeIntervalSince(first.start) / 2)
            let midnight = cal.startOfDay(for: morning)
            w.sleep_midpoint_min = max(-720, min(720, (mid.timeIntervalSince(midnight) / 60).rounded()))
            // Stages: each stage's own samples merged (a watch and a phone can both write), then summed. A night
            // with any staged sample sends all three, a stage it never reached as 0; a night without stages
            // (a source that only says "asleep") sends none of them.
            let deep = inside(i.deep, window), rem = inside(i.rem, window), core = inside(i.core, window)
            let staged = !(deep.isEmpty && rem.isEmpty && core.isEmpty)
            if staged {
                w.sleep_deep_min = minutes(deep); w.sleep_rem_min = minutes(rem); w.sleep_core_min = minutes(core)
            }
            // Awake: only what the source wrote as "awake", and only between first falling asleep and last waking
            // (lying awake before sleep came, or after getting up, is not part of the night). A source that
            // writes stages and no awake sample had none to write: 0. One that writes neither says nothing.
            if staged || !inside(i.awake, window).isEmpty {
                w.sleep_awake_min = minutes(inside(i.awake, DateInterval(start: first.start, end: last.end)))
            }
        }
        w.steps = i.steps.flatMap { $0.isFinite && $0 >= 0 ? min(200_000, Int($0.rounded())) : nil }
        w.distance_km = amount(i.distanceKm, most: 300) { ($0 * 100).rounded() / 100 }
        w.exercise_min = i.exerciseMin.map { min(1440, $0.rounded()) }
        w.daylight_min = amount(i.daylightMin, most: 1440) { $0.rounded() }
        w.resting_hr_bpm = bpm(i.restingHR)
        w.walking_hr_bpm = bpm(i.walkingHR)
        w.hrv_sdnn_ms = i.hrvSDNN.map { min(500, ($0 * 10).rounded() / 10) }
        // Nothing at all → no obs (no watch / no data that day).
        if isEmpty(w) { return nil }
        return w
    }

    /// No number in it: nothing to send.
    static func isEmpty(_ w: WearableDaily) -> Bool {
        let numbers: [Double?] = [w.sleep_min, w.sleep_midpoint_min, w.sleep_regularity, w.resting_hr_bpm, w.hrv_sdnn_ms,
                                  w.steps.map(Double.init), w.exercise_min, w.distance_km, w.daylight_min, w.walking_hr_bpm,
                                  w.sleep_deep_min, w.sleep_rem_min, w.sleep_core_min, w.sleep_awake_min]
        return numbers.allSatisfy { $0 == nil }
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

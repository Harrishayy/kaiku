import XCTest
import SwiftUI
@testable import KaikuKit

// History: the arithmetic (periods, roll-ups, a month as weeks, the sessions of a day, how a number is written),
// the contract mirror, the copy kept for offline and what a pairing change does to it, and the routing.

private let helsinki = TimeZone(identifier: "Europe/Helsinki")!

private func day(_ d: Int, _ value: Double, sessions: Int = 1, sim: Bool = false) -> HistoryDay {
    HistoryDay(date: String(format: "2026-11-%02d", d), value: value, sessions: sessions, sim: sim)
}

/// A drum session at a Helsinki wall-clock time (UTC+2 in November).
private func drum(_ id: String, day: Int, hour: Int, minute: Int = 0, tempo: Double, start: Double, taps: Double,
                  warmup: Bool? = nil, sim: Bool = false) -> HistorySession {
    let ts = String(format: "2026-11-%02dT%02d:%02d:00Z", hour >= 2 ? day : day - 1, (hour + 22) % 24, minute)
    return HistorySession(id: id, ts: ts, device: "robot", sim: sim, warmup: warmup, values: [
        HistoryValue(key: "tempo_bpm", title: "Tempo", value: tempo, unit: "bpm"),
        HistoryValue(key: "taps", title: "Taps", value: taps, unit: "taps"),
        HistoryValue(key: "tempo_start_bpm", title: "Tempo at the start", value: start, unit: "bpm"),
    ])
}

final class HistoryPeriodTests: XCTestCase {
    func testAWeekIsSevenDaysEndingOnTheDayAndAMonthIsFourWeeks() {
        let week = HistoryPeriod.ending("2026-11-14", .week)
        XCTAssertEqual(week.days, ["2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14"])
        let month = HistoryPeriod.ending("2026-11-14", .month)
        XCTAssertEqual(month.days.count, 28)
        XCTAssertEqual(month.first, "2026-10-18")
        XCTAssertEqual(month.last, "2026-11-14")
        XCTAssertEqual(HistoryPeriod.ending("2026-11-14", .day).days, ["2026-11-14"])
    }

    func testSteppingBackMovesByWholePeriodsAndCrossesMonthsYearsAndClockChanges() {
        XCTAssertEqual(HistoryPeriod.ending("2026-11-14", .week, back: 1).days.last, "2026-11-07")
        XCTAssertEqual(HistoryPeriod.ending("2026-11-14", .week, back: 2).first, "2026-10-25")
        XCTAssertEqual(HistoryPeriod.ending("2026-11-14", .day, back: 14).days, ["2026-10-31"])
        XCTAssertEqual(HistoryPeriod.ending("2027-01-03", .week).first, "2026-12-28")
        // The week the clocks go back in Helsinki (25 October 2026) still has seven different days.
        let dst = HistoryPeriod.ending("2026-10-28", .week)
        XCTAssertEqual(Set(dst.days).count, 7)
        XCTAssertEqual(dst.first, "2026-10-22")
        XCTAssertEqual(HistoryDayKey.days(from: "2026-10-24", to: "2026-10-26"), 2)
        XCTAssertNil(HistoryDayKey.adding(1, to: "not a day"))
    }

    func testAMomentBelongsToItsDayInTheHomesTimeZone() throws {
        // 21:40 UTC on the 13th is 23:40 in Helsinki that evening; 22:10 UTC is already ten past midnight there.
        let late = try XCTUnwrap(KaikuTime.parse("2026-11-13T21:40:00Z"))
        let past = try XCTUnwrap(KaikuTime.parse("2026-11-13T22:10:00Z"))
        XCTAssertEqual(HistoryDayKey.local(late, zone: helsinki), "2026-11-13")
        XCTAssertEqual(HistoryDayKey.local(past, zone: helsinki), "2026-11-14")
        XCTAssertEqual(HistoryDayKey.minutes(late, zone: helsinki), 23 * 60 + 40)
        XCTAssertEqual(HistoryDayKey.minutes(past, zone: helsinki), 10)
    }
}

final class HistoryRollUpTests: XCTestCase {
    private let week = HistoryPeriod.ending("2026-11-14", .week)

    func testADayWithoutARecordStaysEmptyAndIsNotAZero() {
        let points = HistoryMath.points([day(9, 40), day(11, 20, sessions: 2), day(13, 60), day(1, 999)], in: week)
        XCTAssertEqual(points.map(\.day), week.days)
        XCTAssertEqual(points.map(\.value), [nil, 40, nil, 20, nil, 60, nil])
        let stats = HistoryMath.stats(points)
        XCTAssertEqual(stats.days, 3)
        XCTAssertEqual(stats.average, 40)          // of the three days that have a value, not of seven
        XCTAssertEqual(stats.total, 120)
        XCTAssertEqual(stats.low, 20)
        XCTAssertEqual(stats.high, 60)
        XCTAssertEqual(stats.sessions, 4)
    }

    func testAnEmptyPeriodHasNoNumbersAtAll() {
        let stats = HistoryMath.stats(HistoryMath.points([], in: week))
        XCTAssertNil(stats.average); XCTAssertNil(stats.total); XCTAssertNil(stats.low); XCTAssertNil(stats.high)
        XCTAssertEqual(stats.days, 0)
        XCTAssertFalse(stats.simulated)
        XCTAssertNil(HistoryMath.headline(stats, rule: .total))
    }

    func testATotalStaysATotalAndEverythingElseIsAnAverageOfDays() {
        let stats = HistoryMath.stats(HistoryMath.points([day(12, 30), day(13, 50), day(14, 10)], in: week))
        XCTAssertEqual(HistoryMath.headline(stats, rule: .total), 90)
        XCTAssertEqual(HistoryMath.headline(stats, rule: .count), 90)
        for rule in [HistoryPerDay.average, .highest, .lowest, .latest, .first] {
            XCTAssertEqual(HistoryMath.headline(stats, rule: rule), 30, rule.rawValue)
        }
        XCTAssertEqual(HistoryMath.headline(stats, rule: nil), 30, "a rule this build does not know is not summed")
        XCTAssertEqual(Set(HistoryPerDay.allCases.filter(\.addsUp)), [.total, .count])
    }

    func testAClockRollsUpAsAnAverageClockAcrossMidnight() {
        // The middle of the night's sleep: 23:30 (-30), 00:30 (30), 01:00 (60) average to 00:20.
        let points = HistoryMath.points([day(12, -30), day(13, 30), day(14, 60)], in: week)
        let stats = HistoryMath.stats(points)
        XCTAssertEqual(HistoryMath.headline(stats, rule: .latest), 20)
        XCTAssertEqual(HistoryFormat.clock(20), HistoryFormat.clock(1460))
        XCTAssertEqual(HistoryFormat.clock(-30), HistoryFormat.clock(1410))
    }

    func testSimulatedDaysAreCountedSoTheLabelIsOnlyForAllOfThem() {
        let all = HistoryMath.stats(HistoryMath.points([day(12, 1, sim: true), day(13, 2, sim: true)], in: week))
        XCTAssertTrue(all.simulated); XCTAssertFalse(all.partlySimulated)
        let some = HistoryMath.stats(HistoryMath.points([day(12, 1, sim: true), day(13, 2)], in: week))
        XCTAssertFalse(some.simulated); XCTAssertTrue(some.partlySimulated)
        let none = HistoryMath.stats(HistoryMath.points([day(12, 1), day(13, 2)], in: week))
        XCTAssertFalse(none.simulated); XCTAssertFalse(none.partlySimulated)
    }

    func testAMonthReadsAsFourWeeksNewestFirst() {
        let month = HistoryPeriod.ending("2026-11-14", .month)
        let days = [day(14, 10), day(13, 30), day(8, 20), day(7, 100), day(1, 50)]
            + [HistoryDay(date: "2026-10-20", value: 7)]
        let weeks = HistoryMath.weeks(HistoryMath.points(days, in: month))
        XCTAssertEqual(weeks.count, 4)
        XCTAssertEqual(weeks.map(\.first), ["2026-11-08", "2026-11-01", "2026-10-25", "2026-10-18"])
        XCTAssertEqual(weeks.map(\.last), ["2026-11-14", "2026-11-07", "2026-10-31", "2026-10-24"])
        XCTAssertEqual(weeks[0].stats.average, 20)
        XCTAssertEqual(weeks[0].stats.total, 60)
        XCTAssertEqual(weeks[1].stats.total, 150)
        XCTAssertEqual(weeks[2].stats.days, 0)
        XCTAssertNil(weeks[2].stats.average)
        XCTAssertEqual(weeks[3].stats.average, 7)
        // Days that do not divide by seven: the oldest block keeps what is left.
        let ragged = HistoryMath.weeks(HistoryMath.points(days, in: HistoryPeriod(range: .month, days: Array(month.days.suffix(10)))))
        XCTAssertEqual(ragged.map { HistoryDayKey.days(from: $0.first, to: $0.last) }, [6, 2])
    }

    func testTheLatestDayIsTheNewestWithAValueWhateverTheOrder() {
        XCTAssertEqual(HistoryMath.latest([day(12, 1), day(14, 3), day(13, 2)])?.date, "2026-11-14")
        XCTAssertNil(HistoryMath.latest([]))
        XCTAssertNil(HistoryMath.latest([HistoryDay(date: "2026-11-14", value: .nan)]))
    }
}

final class HistorySessionTests: XCTestCase {
    private func tempo(days: [HistoryDay], sessions: [HistorySession], perDay: String = "average", unit: String = "bpm") -> HistoryMeasure {
        HistoryMeasure(key: "drum_tempo", title: "Drum tempo", unit: unit, per_day: perDay, devices: ["robot"], days: days, sessions: sessions)
    }

    func testTheSessionsOfADayAreThatLocalDaysEarliestFirst() {
        let sessions = [drum("c", day: 13, hour: 23, minute: 40, tempo: 100, start: 90, taps: 40),
                        drum("b", day: 13, hour: 9, tempo: 96, start: 92, taps: 30),
                        drum("d", day: 14, hour: 0, minute: 10, tempo: 104, start: 99, taps: 50),
                        drum("a", day: 12, hour: 18, tempo: 90, start: 88, taps: 20)]
        XCTAssertEqual(HistoryMath.sessions(sessions, on: "2026-11-13", zone: helsinki).map(\.id), ["b", "c"])
        XCTAssertEqual(HistoryMath.sessions(sessions, on: "2026-11-14", zone: helsinki).map(\.id), ["d"])
        XCTAssertEqual(HistoryMath.sessions(sessions, from: "2026-11-12", to: "2026-11-13", zone: helsinki).map(\.id), ["c", "b", "a"])
        XCTAssertEqual(HistoryMath.sessions(sessions, on: "2026-11-10", zone: helsinki), [])
        // In UTC the same late session falls on the same date but the one after midnight does not move back.
        XCTAssertEqual(HistoryMath.sessions(sessions, on: "2026-11-13", zone: TimeZone(identifier: "UTC")!).map(\.id), ["b", "c", "d"])
    }

    func testTheMeasuresOwnNumberIsFoundByRollingTheSessionsUpNotByItsName() {
        // Two numbers share the unit (tempo and tempo at the start); only the tempo averages to the days' values.
        let sessions = [drum("a", day: 12, hour: 8, tempo: 96, start: 80, taps: 30), drum("b", day: 12, hour: 19, tempo: 104, start: 81, taps: 44),
                        drum("c", day: 13, hour: 8, tempo: 101, start: 99, taps: 36)]
        let m = tempo(days: [day(12, 100.2, sessions: 2), day(13, 100.6)], sessions: sessions)
        XCTAssertEqual(HistoryMath.sessionKey(m, zone: helsinki), "tempo_bpm")
        let marks = HistoryMath.marks(m, on: "2026-11-12", zone: helsinki)
        XCTAssertEqual(marks.map(\.value), [96, 104])
        XCTAssertEqual(marks.map(\.minute), [480, 1140])
        // The same sessions under a measure that is the day's total of taps: the taps are its number.
        let taps = HistoryMeasure(key: "drum_taps", title: "Drum taps", unit: "taps", per_day: "total", days: [day(12, 74, sessions: 2), day(13, 36)], sessions: sessions)
        XCTAssertEqual(HistoryMath.sessionKey(taps, zone: helsinki), "taps")
        XCTAssertEqual(HistoryMath.marks(taps, on: "2026-11-13", zone: helsinki).map(\.value), [36])
    }

    func testANumberThatDoesNotRollUpToTheDaysIsNotBorrowed() {
        // "Time in messages and calls" (min): the sessions list other minutes, none of which is this measure's.
        let hour = { (id: String, h: Int, active: Double, late: Double) in
            HistorySession(id: id, ts: String(format: "2026-11-13T%02d:00:00Z", h), device: "mac", values: [
                HistoryValue(key: "active_min", title: "Active time", value: active, unit: "min"),
                HistoryValue(key: "late_night_min", title: "Late-night minutes", value: late, unit: "min"),
            ])
        }
        let m = HistoryMeasure(key: "communication_min", title: "Time in messages and calls", unit: "min", per_day: "total",
                               days: [day(13, 59, sessions: 3)], sessions: [hour("a", 8, 40, 0), hour("b", 9, 50, 0), hour("c", 10, 30, 0)])
        XCTAssertNil(HistoryMath.sessionKey(m, zone: helsinki))
        XCTAssertEqual(HistoryMath.marks(m, on: "2026-11-13", zone: helsinki), [], "no chart rather than a neighbour's numbers")
        // A day whose sessions are not all listed proves nothing either way.
        let cut = tempo(days: [day(13, 100, sessions: 5)], sessions: [drum("a", day: 13, hour: 8, tempo: 100, start: 100, taps: 1)])
        XCTAssertNil(HistoryMath.sessionKey(cut, zone: helsinki))
        // No number in the measure's unit: nothing to consider.
        XCTAssertNil(HistoryMath.sessionKey(tempo(days: [day(13, 100)], sessions: [drum("a", day: 13, hour: 8, tempo: 100, start: 100, taps: 1)], unit: "lux"), zone: helsinki))
    }

    func testPracticeRoundsAreLeftOutOfTheProofAndStillDrawnAsSessions() {
        let sessions = [drum("w", day: 13, hour: 8, tempo: 60, start: 60, taps: 5, warmup: true),
                        drum("a", day: 13, hour: 9, tempo: 100, start: 91, taps: 30, warmup: false)]
        let m = tempo(days: [day(13, 100)], sessions: sessions, perDay: "highest")
        XCTAssertEqual(HistoryMath.sessionKey(m, zone: helsinki), "tempo_bpm")
        let marks = HistoryMath.marks(m, on: "2026-11-13", zone: helsinki)
        XCTAssertEqual(marks.map(\.warmup), [true, false])
        XCTAssertEqual(marks.map(\.value), [60, 100])
    }

    func testEveryPerDayRuleRollsADayUpTheWayItsNameSays() {
        let v: [Double] = [4, 9, 2, 7]
        XCTAssertEqual(HistoryMath.rolled(v, .average), [5.5, 5.5])
        XCTAssertEqual(HistoryMath.rolled([1, 2, 9], .average), [4, 2], "the mean and the median: the service uses either")
        XCTAssertEqual(HistoryMath.rolled(v, .total), [22])
        XCTAssertEqual(HistoryMath.rolled(v, .highest), [9])
        XCTAssertEqual(HistoryMath.rolled(v, .lowest), [2])
        XCTAssertEqual(HistoryMath.rolled(v, .latest), [7])
        XCTAssertEqual(HistoryMath.rolled(v, .first), [4])
        XCTAssertEqual(HistoryMath.rolled(v, .count), [4])
        XCTAssertEqual(HistoryMath.rolled([], .total), [])
        XCTAssertEqual(HistoryMath.fractionDigits([1, 2]), 0)
        XCTAssertEqual(HistoryMath.fractionDigits([0.8, 0.83]), 2)
    }

    func testACountMeasureMarksEverySessionOnceAndNeedsNoNumber() {
        let step = { (id: String, h: Int, label: String) in
            HistorySession(id: id, ts: String(format: "2026-11-13T%02d:10:00Z", h), device: "robot", label: label)
        }
        let m = HistoryMeasure(key: "ritual_steps", title: "Ritual steps completed", unit: "steps", per_day: "count",
                               days: [day(13, 3, sessions: 3)], sessions: [step("a", 5, "Breathing"), step("b", 5, "Drumming"), step("c", 6, "Goodbye")])
        XCTAssertNil(HistoryMath.sessionKey(m, zone: helsinki))
        let marks = HistoryMath.marks(m, on: "2026-11-13", zone: helsinki)
        XCTAssertEqual(marks.map(\.value), [1, 1, 1])
        XCTAssertEqual(marks.map { Int($0.minute / 60) }, [7, 7, 8])
    }

    func testTheNewestDayWithSomethingToShow() {
        let m = tempo(days: [day(12, 100)], sessions: [drum("a", day: 13, hour: 9, tempo: 60, start: 60, taps: 3, warmup: true)])
        XCTAssertEqual(HistoryMath.latestDay(m, zone: helsinki), "2026-11-13", "a practice round is a session of its day")
        XCTAssertEqual(HistoryMath.latestDay(tempo(days: [day(12, 100)], sessions: []), zone: helsinki), "2026-11-12")
        XCTAssertNil(HistoryMath.latestDay(tempo(days: [], sessions: []), zone: helsinki))
        // Day view steps through recorded days only: a value, a listed session, or both, each day once.
        let stepped = tempo(days: [day(12, 100), day(9, 98)], sessions: [drum("a", day: 13, hour: 9, tempo: 60, start: 60, taps: 3, warmup: true),
                                                                        drum("b", day: 12, hour: 9, tempo: 100, start: 99, taps: 30)])
        XCTAssertEqual(HistoryMath.recordedDays(stepped, zone: helsinki), ["2026-11-09", "2026-11-12", "2026-11-13"])
    }
}

final class HistoryDrawingTests: XCTestCase {
    private func measure(_ perDay: String, unit: String = "bpm", format: String = "number") -> HistoryMeasure {
        HistoryMeasure(key: "m", title: "M", unit: unit, format: format, per_day: perDay)
    }

    func testAnAmountStandsOnZeroAndALevelDoesNot() {
        XCTAssertTrue(HistoryMath.standsOnZero(measure("total", unit: "min")))
        XCTAssertTrue(HistoryMath.standsOnZero(measure("count", unit: "times")))
        for rule in ["average", "highest", "lowest", "latest", "first", "something new"] {
            XCTAssertFalse(HistoryMath.standsOnZero(measure(rule)), rule)
        }
        XCTAssertFalse(HistoryMath.standsOnZero(measure("total", format: "clock")))
    }

    func testTheValueAxis() {
        // Bars: from zero to a little above the highest.
        let bars = HistoryMath.domain([20, 48], measure: measure("total", unit: "min"))
        XCTAssertEqual(bars.lowerBound, 0)
        XCTAssertGreaterThan(bars.upperBound, 48)
        // A level far from zero: room around the person's own values, not a strip at the top of an empty chart.
        let level = HistoryMath.domain([99, 103, 100, 108], measure: measure("average"))
        XCTAssertGreaterThan(level.lowerBound, 90); XCTAssertLessThan(level.lowerBound, 99)
        XCTAssertGreaterThan(level.upperBound, 108); XCTAssertLessThan(level.upperBound, 115)
        // A level near zero starts at zero.
        XCTAssertEqual(HistoryMath.domain([2, 9], measure: measure("average")).lowerBound, 0)
        XCTAssertEqual(HistoryMath.domain([0, 10], measure: measure("latest", unit: "min")).lowerBound, 0)
        // A scale shows the whole scale.
        XCTAssertEqual(HistoryMath.domain([3.5, 4], measure: measure("average", unit: "1 to 5")), 1...5)
        XCTAssertEqual(HistoryMath.domain([0.77, 0.87], measure: measure("average", unit: "0 to 1")), 0...1)
        // A time of day: at least half an hour of room on both sides, and it may go below midnight.
        let clock = HistoryMath.domain([-30, 60], measure: measure("latest", unit: "", format: "clock"))
        XCTAssertLessThanOrEqual(clock.lowerBound, -60); XCTAssertGreaterThanOrEqual(clock.upperBound, 90)
        // One value, or none.
        let one = HistoryMath.domain([72], measure: measure("average"))
        XCTAssertLessThan(one.lowerBound, 72); XCTAssertGreaterThan(one.upperBound, 72)
        XCTAssertEqual(HistoryMath.domain([], measure: measure("average")), 0...1)
        XCTAssertEqual(HistoryMath.scale("1 to 5"), 1...5)
        XCTAssertNil(HistoryMath.scale("steps/min")); XCTAssertNil(HistoryMath.scale("5 to 1")); XCTAssertNil(HistoryMath.scale(""))
    }
}

final class HistoryFormatTests: XCTestCase {
    override func setUp() { L10n.shared.language = .en }

    func testNumbersAreWrittenPlainly() {
        XCTAssertEqual(HistoryFormat.number(72), "72")
        XCTAssertEqual(HistoryFormat.number(0.83), "0.83")
        XCTAssertEqual(HistoryFormat.number(3.14159), "3.14")
        XCTAssertEqual(HistoryFormat.number(72.44), "72.4")
        XCTAssertEqual(HistoryFormat.number(312.4), "312")
        XCTAssertEqual(HistoryFormat.number(4896), "4,896")
        XCTAssertEqual(HistoryFormat.number(100.6, decimals: 0), "101")
        XCTAssertEqual(HistoryFormat.number(4, decimals: 1), "4.0")
        XCTAssertEqual(HistoryFormat.number(.nan), "–")
    }

    func testAValueCarriesItsUnitUnlessTheUnitIsAScale() {
        let tempo = HistoryMeasure(key: "t", title: "T", unit: "bpm", decimals: 0)
        XCTAssertEqual(HistoryFormat.value(100.6, of: tempo), "101 bpm")
        XCTAssertEqual(HistoryFormat.span(99, 103, of: tempo), "99 – 103 bpm")
        XCTAssertEqual(HistoryFormat.span(100.2, 100.4, of: tempo), "100 bpm", "the same when written: one value")
        let steady = HistoryMeasure(key: "s", title: "S", unit: "0 to 1", decimals: 2)
        XCTAssertTrue(HistoryFormat.isScale("0 to 1")); XCTAssertTrue(HistoryFormat.isScale("1 to 5"))
        XCTAssertFalse(HistoryFormat.isScale("right per minute")); XCTAssertFalse(HistoryFormat.isScale(""))
        XCTAssertEqual(HistoryFormat.value(0.8, of: steady), "0.80")
        XCTAssertEqual(HistoryFormat.span(0.77, 0.87, of: steady), "0.77 – 0.87")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "k", title: "Steadiness", value: 0.83, unit: "0 to 1")), "0.83")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "k", title: "Pace", value: 14.5, unit: "right per minute")), "14.5 right per minute")
        XCTAssertEqual(HistoryFormat.value(7, unit: ""), "7")
        // A unit that only repeats the title is left out beside it.
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "k", title: "Steps", value: 4896, unit: "steps")), "4,896")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "k", title: "Taps", value: 82, unit: "taps")), "82")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "k", title: "Early taps", value: 0, unit: "taps")), "0")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "k", title: "Taps on a moth", value: 2, unit: "taps")), "2 taps")
    }

    func testAnAverageOfWholeNumberDaysKeepsADecimalWhileItIsSmall() {
        let pebbles = HistoryMeasure(key: "p", title: "P", unit: "pebbles", decimals: 0)
        XCTAssertEqual(HistoryFormat.average(4.5, of: pebbles), "4.5 pebbles")
        XCTAssertEqual(HistoryFormat.average(4, of: pebbles), "4 pebbles")
        XCTAssertEqual(HistoryFormat.value(4.5, of: pebbles), "5 pebbles", "half rounds up, never to the even neighbour")
        XCTAssertEqual(HistoryFormat.average(101.3, of: HistoryMeasure(key: "t", title: "T", unit: "bpm")), "101 bpm")
        XCTAssertEqual(HistoryFormat.average(3.75, of: HistoryMeasure(key: "m", title: "M", unit: "1 to 5", decimals: 1)), "3.8")
        XCTAssertEqual(HistoryFormat.hour(0), HistoryFormat.hour(1440))
        XCTAssertTrue(HistoryFormat.hour(1080).contains("6"), HistoryFormat.hour(1080))
    }

    func testMinutesAndSecondsAreWrittenInTheLargerUnitFromSixtyUp() {
        let sleep = HistoryMeasure(key: "s", title: "S", unit: "min")
        XCTAssertEqual(HistoryFormat.value(419, of: sleep), "6 h 59 min")
        XCTAssertEqual(HistoryFormat.value(420, of: sleep), "7 h")
        XCTAssertEqual(HistoryFormat.value(48, of: sleep), "48 min")
        XCTAssertEqual(HistoryFormat.value(185, unit: "s"), "3 min 5 s")
        XCTAssertEqual(HistoryFormat.value(48, unit: "s"), "48 s")
        XCTAssertEqual(HistoryFormat.span(403, 453, of: sleep), "6 h 43 min – 7 h 33 min")
        XCTAssertEqual(HistoryFormat.span(29, 45, of: sleep), "29 – 45 min")
    }

    func testAClockValueIsATimeOfDay() {
        let hello = HistoryMeasure(key: "g", title: "G", unit: "", format: "clock", per_day: "first")
        XCTAssertTrue(hello.isClock)
        let written = HistoryFormat.value(454, of: hello)
        XCTAssertTrue(written.contains("7:34"), written)
        XCTAssertTrue(HistoryFormat.clock(-30).contains("11:30"), HistoryFormat.clock(-30))
        XCTAssertTrue(HistoryFormat.value(HistoryValue(key: "@local_minutes", title: "First hello", value: 454, format: "clock")).contains("7:34"))
        XCTAssertTrue(HistoryFormat.span(422, 454, of: hello).contains(" – "))
        XCTAssertEqual(HistoryFormat.time("2026-11-13T05:34:00Z", zone: helsinki), HistoryFormat.clock(454))
        XCTAssertEqual(HistoryFormat.time("2026-11-13T05:34:40Z", zone: helsinki), HistoryFormat.clock(454), "a clock does not round up")
        XCTAssertEqual(HistoryFormat.clock(454.6), HistoryFormat.clock(455), "an average of times does")
    }

    func testDaysAreNamedFromToday() {
        XCTAssertEqual(HistoryFormat.day("2026-11-14", today: "2026-11-14"), "Today")
        XCTAssertEqual(HistoryFormat.day("2026-11-14", today: "2026-11-14", soFar: true), "Today so far")
        XCTAssertEqual(HistoryFormat.day("2026-11-13", today: "2026-11-14", soFar: true), "Yesterday")
        let older = HistoryFormat.day("2026-11-10", today: "2026-11-14")
        XCTAssertTrue(older.contains("Tue") && older.contains("10") && older.contains("Nov"), older)
        let span = HistoryFormat.days("2026-11-08", "2026-11-14", today: "2026-11-14")
        XCTAssertTrue(span.contains("8") && span.contains("14") && span.contains("Nov"), span)
        XCTAssertEqual(span.components(separatedBy: "Nov").count, 2, "the month once inside one month: \(span)")
        let across = HistoryFormat.days("2026-10-28", "2026-11-03", today: "2026-11-14")
        XCTAssertTrue(across.contains("Oct") && across.contains("Nov"), across)
        XCTAssertEqual(HistoryFormat.days("2026-11-14", "2026-11-14", today: "2026-11-14"), "Today so far")
        XCTAssertEqual(HistoryFormat.axisDay("2026-11-14", range: .week), "S")
        XCTAssertEqual(HistoryFormat.axisDay("2026-11-14", range: .month), "14")
    }

    func testEveryWordHistoryPutsTogetherExistsInBothLanguages() {
        var keys = HistoryRange.allCases.map { "history.range.\($0.rawValue)" } + HistoryPerDay.allCases.map { "history.perday.\($0.rawValue)" }
        keys += ["history.today", "history.today.sofar", "history.yesterday", "history.unit.h", "history.unit.min", "history.unit.s",
                 "history.fetched", "history.fetched.stale", "history.empty", "history.empty.unpaired", "tab.history"]
        for k in keys { XCTAssertTrue(L10n.shared.has(k, .en) && L10n.shared.has(k, .fi), k) }
        for d in HistoryMeasure.devices { XCTAssertNotNil(HistoryDevice.name(d), d) }
        XCTAssertNil(HistoryDevice.name("toaster"), "a device this build does not know is left out, not shown raw")
        XCTAssertEqual(HistoryDevice.names(["robot", "toaster", "phone"]), "Robot, iPhone")
    }
}

final class HistoryContractTests: XCTestCase {
    private func schema(_ name: String) throws -> (props: [String: Any], required: Set<String>) {
        let s = try json("contracts/schemas/api/\(name).schema.json") as! [String: Any]
        return (s["properties"] as! [String: Any], Set(s["required"] as? [String] ?? []))
    }
    private func keys<T: Encodable>(_ v: T) throws -> Set<String> {
        Set((try JSONSerialization.jsonObject(with: JSONEncoder().encode(v)) as! [String: Any]).keys)
    }
    private func words(_ props: [String: Any], _ key: String) -> Set<String> {
        let p = props[key] as! [String: Any]
        return Set((p["enum"] ?? (p["items"] as? [String: Any])?["enum"]) as! [String])
    }

    func testTheModelsMirrorTheSchemas() throws {
        let value = HistoryValue(key: "tempo_bpm", title: "Tempo", value: 96, unit: "bpm")
        let session = HistorySession(id: "s", ts: "2026-11-13T07:20:00Z", device: "robot", warmup: false, label: "Drumming", values: [value])
        let measure = HistoryMeasure(key: "drum_tempo", title: "Drum tempo", unit: "bpm", per_day: "average", devices: ["robot"],
                                     days: [day(13, 96)], usual: HistoryUsual(low: 90, high: 104), sessions: [session])
        let group = HistoryGroup(key: "robot", title: "Robot", measures: [measure])
        let history = PersonHistory(home_id: "h", days: 30, first_day: "2026-10-16", last_day: "2026-11-14", timezone: "Europe/Helsinki",
                                    groups: [group], generated_at: "2026-11-14T10:00:00Z")
        let pairs: [(String, Set<String>)] = [
            ("HistoryValue", try keys(value)), ("HistorySession", try keys(session)), ("HistoryMeasure", try keys(measure)),
            ("HistoryGroup", try keys(group)), ("PersonHistory", try keys(history)), ("HistoryDay", try keys(day(13, 96))),
            ("HistoryUsual", try keys(HistoryUsual(low: 1, high: 2))),
        ]
        for (name, sent) in pairs {
            let s = try schema(name)
            XCTAssertEqual(sent, Set(s.props.keys), "\(name): the Swift model and the schema name the same fields")
            XCTAssertTrue(s.required.isSubset(of: sent), name)
        }
    }

    func testTheWordsMatchTheSchemas() throws {
        XCTAssertEqual(try words(schema("HistoryGroup").props, "key"), Set(HistoryGroup.keys))
        let m = try schema("HistoryMeasure").props
        XCTAssertEqual(words(m, "devices"), Set(HistoryMeasure.devices))
        XCTAssertEqual(words(m, "per_day"), Set(HistoryPerDay.allCases.map(\.rawValue)))
        XCTAssertEqual(words(m, "format"), Set(HistoryValueFormat.allCases.map(\.rawValue)))
        XCTAssertEqual(try words(schema("HistorySession").props, "device"), Set(HistoryMeasure.devices))
        XCTAssertEqual(try words(schema("HistoryValue").props, "format"), Set(HistoryValueFormat.allCases.map(\.rawValue)))
    }

    func testAResponseDecodesWithItsDefaultsAndWordsThisBuildHasNeverSeen() throws {
        let wire = """
        {"home_id":"h","days":30,"first_day":"2026-10-16","last_day":"2026-11-14","timezone":"Europe/Helsinki","generated_at":"2026-11-14T10:00:00Z",
         "groups":[{"key":"garden","title":"Garden","measures":[
           {"key":"soil","title":"Soil warmth","per_day":"warmest","devices":["trowel"],"unit":"°C",
            "days":[{"date":"2026-11-13","value":7.5,"sessions":2}],
            "sessions":[{"id":"a","ts":"2026-11-13T07:20:00Z","device":"trowel","values":[{"key":"t","title":"Warmth","value":7.5}]}]},
           {"key":"lantern_speed","title":"Lantern: response speed","per_day":"average","devices":[],"days":[],"usual":null,
            "sessions":[{"id":"w","ts":"2026-11-13T08:00:00Z","device":"phone","warmup":true,"label":null}]}]}]}
        """
        let h = try JSONDecoder().decode(PersonHistory.self, from: Data(wire.utf8))
        XCTAssertFalse(h.sim)
        XCTAssertEqual(h.zone.identifier, "Europe/Helsinki")
        let soil = h.groups[0].measures[0]
        XCTAssertNil(soil.rule, "a per-day rule this build does not know is not acted on")
        XCTAssertEqual(soil.format, "number"); XCTAssertEqual(soil.decimals, 0); XCTAssertFalse(soil.sim)
        XCTAssertEqual(soil.days[0].sim, false)
        XCTAssertEqual(soil.sessions[0].values[0].unit, "")
        XCTAssertEqual(HistoryFormat.value(7.5, of: soil), "8 °C")
        XCTAssertFalse(HistoryMath.standsOnZero(soil))
        XCTAssertEqual(HistoryMath.headline(HistoryMath.stats(HistoryMath.points(soil.days, in: .ending("2026-11-14", .week))), rule: soil.rule), 7.5)
        // A game with only practice rounds: sessions and no days. It is shown, and nothing assumes a last day.
        XCTAssertEqual(h.shown.first?.measures.map(\.key), ["soil", "lantern_speed"])
        XCTAssertNil(HistoryMath.latest(h.groups[0].measures[1].days))
        XCTAssertEqual(HistoryMath.latestDay(h.groups[0].measures[1], zone: h.zone), "2026-11-13")
        // A measure with neither is left out, and a group left with nothing is too.
        let empty = PersonHistory(home_id: "h", days: 30, first_day: "a", last_day: "b",
                                  groups: [HistoryGroup(key: "mac", title: "Mac", measures: [HistoryMeasure(key: "x", title: "X")])])
        XCTAssertEqual(empty.shown, [])
        XCTAssertEqual(PersonHistory(home_id: "h", days: 1, first_day: "a", last_day: "b", timezone: "Mars/Olympus", groups: []).zone, .current)
        // What is kept for offline reads back the same.
        XCTAssertEqual(try JSONDecoder().decode(PersonHistory.self, from: JSONEncoder().encode(h)), h)
    }
}

@MainActor final class HistoryModelTests: XCTestCase {
    private var dir: URL!

    override func setUp() {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("history-" + UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }
    override func tearDown() { try? FileManager.default.removeItem(at: dir) }

    private func pairing(_ home: String = "home-a", server: String = "http://127.0.0.1:9") -> Pairing {
        Pairing(baseURL: URL(string: server)!, homeID: home, token: nil)
    }

    private func app(_ p: Pairing?) -> AppModel {
        AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: p, api: APIClient(pairing: p, timeout: 1),
                 queue: OfflineQueue(url: dir.appendingPathComponent(UUID().uuidString + "-q.json")),
                 episodes: EpisodeOutbox(url: dir.appendingPathComponent(UUID().uuidString + "-e.json")),
                 saveService: { _ in true })
    }

    private func history(_ home: String = "home-a", tempo: Double = 100) -> PersonHistory {
        PersonHistory(home_id: home, days: 56, first_day: "2026-09-20", last_day: "2026-11-14", timezone: "Europe/Helsinki", groups: [
            HistoryGroup(key: "robot", title: "Robot", measures: [
                HistoryMeasure(key: "drum_tempo", title: "Drum tempo", unit: "bpm", devices: ["robot"], days: [day(13, tempo)])]),
        ])
    }

    private var cache: HistoryCache { HistoryCache(url: dir.appendingPathComponent("history.json")) }

    func testAFetchIsShownAndKeptForNextTime() async {
        let model = HistoryModel(cache: cache)
        var asked: [Pairing] = []
        model.fetch = { p in asked.append(p); return self.history() }
        let a = app(pairing())
        await model.load(app: a)
        XCTAssertEqual(asked, [pairing()])
        XCTAssertEqual(model.groups.first?.measures.first?.days.first?.value, 100)
        XCTAssertNotNil(model.fetched); XCTAssertFalse(model.stale); XCTAssertFalse(model.failed); XCTAssertFalse(model.loading)
        XCTAssertEqual(cache.load(for: pairing())?.history, history())
        XCTAssertEqual(model.measure(HistoryRef(group: "robot", measure: "drum_tempo"))?.measure.title, "Drum tempo")
        XCTAssertNil(model.measure(HistoryRef(group: "games", measure: "drum_tempo")))
        XCTAssertEqual(model.measure(key: "drum_tempo")?.group.key, "robot")
    }

    func testOfflineItOpensWithWhatItLastHadAndSaysWhenThatWasFetched() async throws {
        let then = Date(timeIntervalSinceNow: -3 * 3600)
        cache.save(history(tempo: 96), for: pairing(), at: then)
        let model = HistoryModel(cache: cache)
        model.fetch = { _ in throw APIError.offline }
        await model.load(app: app(pairing()))
        XCTAssertEqual(model.groups.first?.measures.first?.days.first?.value, 96)
        XCTAssertTrue(model.stale); XCTAssertFalse(model.failed)
        XCTAssertEqual(try XCTUnwrap(model.fetched).timeIntervalSince1970, then.timeIntervalSince1970, accuracy: 1)
        // Back online: the fresh answer replaces the copy and the mark goes.
        model.fetch = { _ in self.history(tempo: 104) }
        await model.load(app: app(pairing()))
        XCTAssertEqual(model.groups.first?.measures.first?.days.first?.value, 104)
        XCTAssertFalse(model.stale)
        XCTAssertGreaterThan(try XCTUnwrap(model.fetched), then.addingTimeInterval(3600))
    }

    func testWithNothingKeptAFailedRequestShowsNothingAndSaysSo() async {
        let model = HistoryModel(cache: cache)
        model.fetch = { _ in throw APIError.http(404) }   // a service that does not have the route yet
        await model.load(app: app(pairing()))
        XCTAssertNil(model.history); XCTAssertTrue(model.failed); XCTAssertFalse(model.stale); XCTAssertEqual(model.groups, [])
        XCTAssertNil(cache.load(for: pairing()))
    }

    func testTheCopyBelongsToOneServiceAndOneHome() {
        cache.save(history(), for: pairing())
        XCTAssertNotNil(cache.load(for: pairing()))
        XCTAssertNil(cache.load(for: pairing("home-b")), "another home")
        XCTAssertNil(cache.load(for: pairing(server: "http://127.0.0.1:10")), "the same home name on another service")
        // An answer for a different home than was asked for is neither shown nor kept.
        cache.clear()
        cache.save(history("home-b"), for: pairing())
        XCTAssertNil(cache.load(for: pairing()))
        // The file carries no credentials.
        let secret = Pairing(baseURL: URL(string: "http://127.0.0.1:9")!, homeID: "home-a", token: "tok-SECRET")
        cache.save(history(), for: secret)
        let text = String(decoding: try! Data(contentsOf: dir.appendingPathComponent("history.json")), as: UTF8.self)
        XCTAssertFalse(text.contains("tok-SECRET"))
    }

    func testAnAnswerForAnotherHomeIsNotShown() async {
        let model = HistoryModel(cache: cache)
        model.fetch = { _ in self.history("home-b") }
        await model.load(app: app(pairing()))
        XCTAssertNil(model.history); XCTAssertTrue(model.failed)
    }

    func testAPairingChangeEmptiesTheScreenAndRemovesTheCopy() async {
        let shared = HistoryModel.shared
        let before = (shared.cache, shared.fetch)
        defer { shared.clearForPairingChange(); shared.cache = before.0; shared.fetch = before.1 }
        shared.cache = cache
        shared.fetch = { p in self.history(p.homeID) }
        let a = app(pairing())
        await shared.load(app: a)
        XCTAssertNotNil(shared.history); XCTAssertNotNil(cache.load(for: pairing()))
        // The same home, a new token: nothing about the person changed.
        await a.updatePairing(Pairing(baseURL: pairing().baseURL, homeID: "home-a", token: "t2"))
        XCTAssertNotNil(shared.history)
        // Another home: the numbers on screen and the kept copy both go, before anything is fetched again.
        await a.updatePairing(pairing("home-b"))
        XCTAssertNil(shared.history); XCTAssertNil(shared.fetched)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("history.json").path))
        await shared.load(app: a)
        XCTAssertEqual(shared.history?.home_id, "home-b")
        // Unpairing: nothing is shown.
        await a.updatePairing(nil)
        XCTAssertNil(shared.history)
        await shared.load(app: a)
        XCTAssertNil(shared.history)
    }

    func testALateAnswerForThePreviousHomeIsDropped() async {
        let model = HistoryModel(cache: cache)
        let a = app(pairing())
        let gate = AsyncStream<Void>.makeStream()
        model.fetch = { p in
            for await _ in gate.stream { break }
            return self.history(p.homeID)
        }
        let first = Task { await model.load(app: a) }
        await Task.yield()
        await a.updatePairing(pairing("home-b"))      // the person re-pairs while the request is out
        model.clearForPairingChange()
        gate.continuation.yield(); gate.continuation.finish()
        await first.value
        XCTAssertNil(model.history, "home-a's numbers must not appear after the pairing changed")
        XCTAssertNil(cache.load(for: pairing()))
    }

    func testTheRequestAsksForTheHomesDays() async throws {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [HistoryStub.self]
        let p = pairing(server: "http://history.test")
        let api = APIClient(pairing: p, session: URLSession(configuration: cfg))
        let h = try await api.history(days: HistoryModel.days)
        XCTAssertEqual(h.home_id, "home-a")
        let url = try XCTUnwrap(HistoryStub.seen)
        XCTAssertEqual(url.path, "/v1/me/history")
        let query = Dictionary(uniqueKeysWithValues: (URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []).map { ($0.name, $0.value ?? "") })
        XCTAssertEqual(query, ["home_id": "home-a", "days": "56"])
        XCTAssertLessThanOrEqual(HistoryModel.days, 90, "the service's most")
        XCTAssertGreaterThanOrEqual(HistoryModel.days, 2 * HistoryRange.month.length)
    }
}

/// Answers `history.test` with an empty History and remembers what was asked.
private final class HistoryStub: URLProtocol {
    nonisolated(unsafe) static var seen: URL?
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "history.test" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        HistoryStub.seen = request.url
        let body = #"{"home_id":"home-a","days":56,"first_day":"2026-09-20","last_day":"2026-11-14","timezone":"Europe/Helsinki","groups":[],"generated_at":"2026-11-14T10:00:00Z"}"#
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

final class HistoryRoutingTests: XCTestCase {
    func testTabsWithHistoryWhereYourDaysWasAndKaikuBot() {
        XCTAssertEqual(KaikuTab.allCases.map(\.rawValue), ["today", "play", "talk", "history", "bot", "you"])
        XCTAssertEqual(KaikuTab.bot.title, "Kaiku bot")
        XCTAssertEqual(KaikuTab.phoneBar.map(\.rawValue), ["today", "play", "talk", "history", "you"], "an iPhone bar shows five")
        XCTAssertEqual(KaikuRoute.bot.tab, .you)
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://bot")!), .tab(.bot))
        XCTAssertEqual(KaikuRoute.days.tab, .history)
        XCTAssertTrue(KaikuScreen.allCases.contains(.history) && KaikuScreen.allCases.contains(.historyMeasure))
        XCTAssertTrue(KaikuScreen.allCases.contains(.days) && KaikuScreen.allCases.contains(.markDay), "Your days is still a screen")
        XCTAssertEqual(KaikuScreen.history.platform, .both)
    }

    func testLinks() {
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://history")!), .tab(.history))
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://history/days")!), .route(.days))
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://days")!), .route(.days), "links made before the fold still land on Your days")
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://history/anything-else")!), .tab(.history))
    }
}

#if os(macOS)
/// Opt-in: PNGs of History as it is drawn, from a real response saved to a file.
///   KAIKU_HISTORY_JSON=<a saved GET /v1/me/history answer> KAIKU_HISTORY_RENDER_DIR=<dir> swift test --filter HistoryRenderTests
@MainActor final class HistoryRenderTests: XCTestCase {
    private func write<V: View>(_ view: V, width: CGFloat, _ name: String, to dir: String, type: DynamicTypeSize = .large) throws {
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: nil, api: APIClient(pairing: nil, timeout: 1),
                           queue: OfflineQueue(url: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
                           episodes: EpisodeOutbox(url: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
                           saveService: { _ in true })
        let framed = VStack(alignment: .leading, spacing: KaikuTokens.Space.s5) { view }
            .frame(width: width, alignment: .leading)
            .padding(KaikuPlatform.sidePadding)
            .background(KaikuTokens.Colors.bg)
            .environment(\.kaikuPaneWidth, width)
            .environment(\.kaikuStaticLayout, true)
            .environment(\.dynamicTypeSize, type)
            .environment(app)
            .environment(\.colorScheme, .light)
        let r = ImageRenderer(content: framed)
        r.scale = 2
        let cg = try XCTUnwrap(r.cgImage)
        let data = try XCTUnwrap(NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]))
        try data.write(to: URL(fileURLWithPath: dir).appendingPathComponent(name))
    }

    private func pane<V: View>(_ view: V, _ name: String, to dir: String) throws {
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: nil, api: APIClient(pairing: nil, timeout: 1),
                           queue: OfflineQueue(url: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
                           episodes: EpisodeOutbox(url: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
                           saveService: { _ in true })
        let framed = NavigationStack { view }
            .frame(width: 760, height: 692, alignment: .top).clipped()
            .background(KaikuTokens.Colors.bg)
            .environment(\.kaikuStaticLayout, true)
            .environment(app)
            .environment(\.colorScheme, .light)
        let r = ImageRenderer(content: framed)
        r.scale = 2
        let cg = try XCTUnwrap(r.cgImage)
        let data = try XCTUnwrap(NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]))
        try data.write(to: URL(fileURLWithPath: dir).appendingPathComponent(name))
    }

    func testRenderHistory() throws {
        let env = ProcessInfo.processInfo.environment
        guard let dir = env["KAIKU_HISTORY_RENDER_DIR"], let file = env["KAIKU_HISTORY_JSON"] else {
            throw XCTSkip("set KAIKU_HISTORY_RENDER_DIR and KAIKU_HISTORY_JSON")
        }
        L10n.shared.language = .en
        let history = try JSONDecoder().decode(PersonHistory.self, from: Data(contentsOf: URL(fileURLWithPath: file)))
        let cache = HistoryCache(url: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json"))
        let pairing = Pairing(baseURL: URL(string: "http://127.0.0.1:9")!, homeID: history.home_id, token: nil)
        cache.save(history, for: pairing)
        let model = HistoryModel(cache: cache)
        model.show(cached: pairing)
        let widths: [(CGFloat, String)] = [(288, "320"), (343, "phone"), (708, "mac")]
        for (width, tag) in widths {
            try write(Group { HistoryDaysCard(); HistorySummary(model: model) { _ in } }, width: width, "summary-\(tag).png", to: dir)
        }
        // The Mac pane as the window opens it (980 × 720 window: 760 × 692 beside the sidebar and under the title bar).
        let shared = HistoryModel.shared
        let kept = (shared.cache, shared.fetch)
        defer { shared.clearForPairingChange(); shared.cache = kept.0; shared.fetch = kept.1 }
        shared.cache = cache
        shared.show(cached: pairing)
        try pane(KaikuPanePreview(tab: .history), "mac-pane-history.png", to: dir)
        for key in ["drum_tempo", "outing_min"] {
            guard let found = shared.measure(key: key) else { continue }
            try pane(HistoryMeasureView(ref: HistoryRef(group: found.group.key, measure: key), model: shared),
                     "mac-pane-measure-\(key).png", to: dir)
        }
        // Which session number each measure's day view draws (none = no chart for a single day).
        let links = history.shown.flatMap { g in g.measures.map { "\(g.key)/\($0.key): \(HistoryMath.sessionKey($0, zone: history.zone) ?? ($0.rule == .count ? "(count)" : "none"))" } }
        try links.joined(separator: "\n").write(to: URL(fileURLWithPath: dir).appendingPathComponent("session-links.txt"), atomically: true, encoding: .utf8)
        // Large text on the smallest phone, and nothing recorded yet.
        try write(HistorySummary(model: model) { _ in }, width: 288, "summary-320-large-text.png", to: dir, type: .accessibility2)
        try write(HistoryEmpty(text: T("history.empty")), width: 288, "empty-320.png", to: dir)
        for key in (env["KAIKU_HISTORY_MEASURES"] ?? "drum_tempo,pebble_span,outing_min").split(separator: ",").map(String.init) {
            guard let found = model.measure(key: key) else { continue }
            for range in HistoryRange.allCases {
                for (width, tag) in widths {
                    try write(HistoryMeasureBody(history: history, group: found.group, measure: found.measure, range: range),
                              width: width, "measure-\(key)-\(range.rawValue)-\(tag).png", to: dir)
                }
            }
            try write(HistoryMeasureBody(history: history, group: found.group, measure: found.measure, range: .week),
                      width: 288, "measure-\(key)-week-320-large-text.png", to: dir, type: .accessibility2)
        }
    }
}
#endif

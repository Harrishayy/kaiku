import Foundation
import XCTest
@testable import KaikuKit

/// Mac extras (A3): usage-rhythm aggregation + payload privacy, notch peek rules, invitation timing.
/// Dates are built in `Calendar.current` (the same zone `AppModel.dayKey` uses).
private let cal = Calendar.current
private func at(_ h: Int, _ m: Int = 0, day: Int = 14) -> Date {
    cal.date(from: DateComponents(year: 2026, month: 11, day: day, hour: h, minute: m))!
}

final class MacUsageTests: XCTestCase {
    func testCategoryTable() {
        XCTAssertEqual(MacAppCategory.of(bundleID: "com.apple.mail"), .communication)
        XCTAssertEqual(MacAppCategory.of(bundleID: "com.apple.dt.Xcode"), .work)
        XCTAssertEqual(MacAppCategory.of(bundleID: "com.jetbrains.goland"), .work)
        XCTAssertEqual(MacAppCategory.of(bundleID: "com.valvesoftware.dota2"), .games)
        XCTAssertEqual(MacAppCategory.of(bundleID: "com.apple.Safari"), .other)   // browsers: content, so not read
        XCTAssertEqual(MacAppCategory.of(bundleID: "org.example.unknown"), .other)
        XCTAssertEqual(MacAppCategory.of(bundleID: nil), .other)
        let schema = try! json("contracts/schemas/obs/screen_activity.schema.json") as! [String: Any]
        let defs = schema["$defs"] as! [String: Any]
        let cats = Set(((defs["ScreenCategoryMinutes"] as! [String: Any])["properties"] as! [String: Any]).keys)
        XCTAssertEqual(Set(MacAppCategory.allCases.map(\.rawValue)), cats)
    }

    /// Feeds `minutes` of 30 s samples from `start`.
    func feed(_ a: inout MacUsageAggregator, from start: Date, minutes: Double, cat: MacAppCategory = .work,
              idle: (Double) -> Double = { _ in 2 }, switches: Int = 0, paused: Bool = false) -> [ScreenActivity] {
        var out: [ScreenActivity] = []
        var t = 0.0
        while t < minutes * 60 {
            let s = MacUsageSample(at: start.addingTimeInterval(t), category: cat, idleSeconds: idle(t), switches: switches, paused: paused)
            out += a.ingest(s, calendar: cal).map(\.payload)
            t += 30
        }
        return out
    }

    func testHourlyPeriodClosesWithMinutesByCategory() {
        var a = MacUsageAggregator()
        XCTAssertTrue(feed(&a, from: at(10), minutes: 40, cat: .work, switches: 1).isEmpty)
        XCTAssertTrue(feed(&a, from: at(10, 40), minutes: 20, cat: .communication).isEmpty)
        let closed = a.ingest(MacUsageSample(at: at(11), category: .work, idleSeconds: 1), calendar: cal)
        XCTAssertEqual(closed.count, 1)
        let p = closed[0].payload
        XCTAssertEqual(p.period_min, 60)
        XCTAssertEqual(p.active_min, 60, accuracy: 0.6)
        XCTAssertEqual(p.category_min["work"]!, 40, accuracy: 0.6)
        XCTAssertEqual(p.category_min["communication"]!, 20, accuracy: 0.6)
        XCTAssertEqual(p.late_night_min, 0)
        XCTAssertEqual(p.breaks, 0)
        XCTAssertEqual(p.longest_stretch_min, 60, accuracy: 0.6)
        XCTAssertEqual(p.switches_per_hour, 80, accuracy: 1)        // 80 switches in one active hour
        XCTAssertLessThanOrEqual(p.category_min.values.reduce(0, +), p.period_min + 0.5)
        XCTAssertEqual(a.currentStretchMin, 60.5, accuracy: 0.6)
    }

    func testLateNightBreaksAndSleepGap() {
        var a = MacUsageAggregator()
        _ = feed(&a, from: at(1), minutes: 20)
        // Idle for 6 minutes (the system idle counter climbs) → one break, stretch ends.
        _ = feed(&a, from: at(1, 20), minutes: 6, idle: { t in 62 + t })
        XCTAssertEqual(a.currentStretchMin, 0)
        _ = feed(&a, from: at(1, 26), minutes: 10)
        // Lid closed for two hours: the gap is idle time (another break), not activity.
        let closed = a.ingest(MacUsageSample(at: at(3, 40), category: .video, idleSeconds: 1), calendar: cal).map(\.payload)
        XCTAssertEqual(closed.count, 1)
        XCTAssertEqual(closed[0].late_night_min, 30, accuracy: 0.6)
        XCTAssertEqual(closed[0].active_min, 30, accuracy: 0.6)
        XCTAssertEqual(closed[0].breaks, 1)
        XCTAssertEqual(closed[0].longest_stretch_min, 20, accuracy: 0.6)
        XCTAssertEqual(a.today?.breaks, 2)
        XCTAssertLessThan(a.currentStretchMin, 1)
    }

    func testPausedSamplesCountNothing() {
        var a = MacUsageAggregator()
        _ = feed(&a, from: at(14), minutes: 30, paused: true)
        let p = a.closeCurrent()!.payload
        XCTAssertTrue(p.paused)
        XCTAssertEqual(p.active_min, 0)
        XCTAssertEqual(p.category_min.values.reduce(0, +), 0)
    }

    /// D26: the payload is numbers + category keys only (no titles, URLs, ids, text of any kind), and every key is
    /// a schema property.
    func testPayloadIsNumbersAndCategoryKeysOnly() throws {
        var a = MacUsageAggregator()
        _ = feed(&a, from: at(9), minutes: 50, cat: .social, switches: 2)
        let p = a.closeCurrent()!.payload
        let obj = try JSONSerialization.jsonObject(with: JSONEncoder().encode(p)) as! [String: Any]
        let schema = try json("contracts/schemas/obs/screen_activity.schema.json") as! [String: Any]
        let defs = schema["$defs"] as! [String: Any]
        let props = Set(((defs["ScreenActivity"] as! [String: Any])["properties"] as! [String: Any]).keys)
        let catProps = Set(((defs["ScreenCategoryMinutes"] as! [String: Any])["properties"] as! [String: Any]).keys)
        XCTAssertTrue(Set(obj.keys).isSubset(of: props), "\(obj.keys)")
        for (k, v) in obj {
            if k == "category_min" {
                let c = v as! [String: Any]
                XCTAssertEqual(Set(c.keys), catProps)
                for (_, n) in c { XCTAssertTrue(n is NSNumber && !(n is String)) }
            } else {
                XCTAssertTrue(v is NSNumber, "\(k) is not a number/bool")
            }
        }
        let text = String(data: try JSONEncoder().encode(p), encoding: .utf8)!
        XCTAssertFalse(text.contains("com."))
        // The persisted aggregate holds no app ids either (the sampler reduces ids to categories first).
        let saved = String(data: try JSONEncoder().encode(a), encoding: .utf8)!
        XCTAssertFalse(saved.contains("com."))
    }

    @MainActor func testReceiptReadsTheLocalAggregate() {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("mac_usage_\(UUID()).json")
        do {
            let store = MacUsageStore(url: url)
            XCTAssertEqual(store.receiptLines(), [L10n.shared.string("saw.mac.none")])
            let now = Date()
            var a = MacUsageAggregator()
            _ = feed(&a, from: now.addingTimeInterval(-600), minutes: 10, cat: .work)
            store.aggregator = a
            store.save()
            let reloaded = MacUsageStore(url: url)
            XCTAssertEqual(reloaded.aggregator, a)
            let lines = reloaded.receiptLines(now: now)
            XCTAssertTrue(lines[0].contains("10"), lines.joined())
        }
    }
}

final class MacPeekTests: XCTestCase {
    func ctx(_ d: Date, active: Bool = true, stretch: Double = 0, paused: Bool = false, blocked: Bool = false,
             quiet: Bool = false) -> MacPeekContext {
        MacPeekContext(now: d, active: active, stretchMin: stretch, paused: paused, blocked: blocked, quietHours: quiet)
    }

    func testLateNightStartsAtOne() {
        let l = MacPeekLedger()
        XCTAssertNil(MacPeekRules.decide(ctx(at(0, 59)), l, calendar: cal))
        XCTAssertEqual(MacPeekRules.decide(ctx(at(1, 0)), l, calendar: cal), .lateNight)
        XCTAssertEqual(MacPeekRules.decide(ctx(at(1, 10), quiet: true), l, calendar: cal), .lateNight)
        XCTAssertNil(MacPeekRules.decide(ctx(at(1, 10), active: false), l, calendar: cal))   // asleep at the desk
        XCTAssertNil(MacPeekRules.decide(ctx(at(5, 0)), l, calendar: cal))
    }

    func testOneLatePeekPerNight() {
        var l = MacPeekLedger()
        l.record(.lateNight, at: at(1, 10))
        XCTAssertNil(MacPeekRules.decide(ctx(at(2, 30)), l, calendar: cal))
        XCTAssertEqual(MacPeekRules.decide(ctx(at(1, 10, day: 15)), l, calendar: cal), .lateNight)
    }

    func testStretchThreshold() {
        let l = MacPeekLedger()
        XCTAssertNil(MacPeekRules.decide(ctx(at(14), stretch: 89), l, calendar: cal))
        XCTAssertNil(MacPeekRules.decide(ctx(at(14), stretch: 90), l, calendar: cal))
        XCTAssertEqual(MacPeekRules.decide(ctx(at(14), stretch: 91), l, calendar: cal), .stretch)
        XCTAssertNil(MacPeekRules.decide(ctx(at(22, 30), stretch: 120, quiet: true), l, calendar: cal))
    }

    func testFourthPeekSuppressed() {
        var l = MacPeekLedger()
        for h in [9, 11, 13] { l.record(.stretch, at: at(h)) }
        XCTAssertEqual(l.shownToday(at(16)), 3)
        XCTAssertNil(MacPeekRules.decide(ctx(at(16), stretch: 200), l, calendar: cal))
        XCTAssertEqual(MacPeekRules.decide(ctx(at(1, 10, day: 15)), l, calendar: cal), .lateNight)  // new day
    }

    func testStretchRepeatsOnlyAfterAnother90Min() {
        var l = MacPeekLedger()
        l.record(.stretch, at: at(10))
        XCTAssertNil(MacPeekRules.decide(ctx(at(11), stretch: 150), l, calendar: cal))
        XCTAssertEqual(MacPeekRules.decide(ctx(at(11, 31), stretch: 181), l, calendar: cal), .stretch)
    }

    /// Snooze is a wall-clock date in the persisted ledger: a sleep/wake (or relaunch) in between doesn't reset it.
    func testSnoozeHonouredAcrossSleepWake() throws {
        var l = MacPeekLedger()
        l.snooze(.hour, at: at(14), calendar: cal)
        let woke = try JSONDecoder().decode(MacPeekLedger.self, from: JSONEncoder().encode(l))
        XCTAssertNil(MacPeekRules.decide(ctx(at(14, 59), stretch: 120), woke, calendar: cal))
        XCTAssertEqual(MacPeekRules.decide(ctx(at(15, 1), stretch: 120), woke, calendar: cal), .stretch)

        var t = MacPeekLedger()
        t.snooze(.today, at: at(15), calendar: cal)
        XCTAssertNil(MacPeekRules.decide(ctx(at(20), stretch: 200), t, calendar: cal))
        XCTAssertEqual(MacPeekRules.decide(ctx(at(1, 10, day: 15)), t, calendar: cal), .lateNight)
    }

    func testQuietWhenPausedOrBlocked() {
        let l = MacPeekLedger()
        XCTAssertNil(MacPeekRules.decide(ctx(at(1, 10), paused: true), l, calendar: cal))
        XCTAssertNil(MacPeekRules.decide(ctx(at(1, 10), blocked: true), l, calendar: cal))
        XCTAssertNil(MacPeekRules.decide(ctx(at(14), stretch: 120, paused: true), l, calendar: cal))
    }

    func testLinesExist() {
        for k in MacPeekKind.allCases {
            for key in [k.lineKey, k.yesKey, k.laterKey] {
                XCTAssertTrue(L10n.shared.has(key, .en), key); XCTAssertTrue(L10n.shared.has(key, .fi), key)
            }
        }
        for c in MacAppCategory.allCases { XCTAssertTrue(L10n.shared.has("mac.cat.\(c.rawValue)", .fi)) }
    }

    func testInvitationRespectsQuietHours() {
        let from = at(22), to = at(8)
        XCTAssertEqual(MacInvitationTime.next(after: at(10), quietFrom: from, quietTo: to, calendar: cal), at(17))
        XCTAssertEqual(MacInvitationTime.next(after: at(18), quietFrom: from, quietTo: to, calendar: cal), at(17, day: 15))
        XCTAssertEqual(MacInvitationTime.next(after: at(10), hour: 23, quietFrom: from, quietTo: to, calendar: cal), at(8, day: 15))
        XCTAssertTrue(MacInvitationTime.inQuiet(at(1), from: from, to: to, calendar: cal))
        XCTAssertFalse(MacInvitationTime.inQuiet(at(12), from: from, to: to, calendar: cal))
    }
}

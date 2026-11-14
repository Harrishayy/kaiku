import Foundation
import XCTest
@testable import KaikuKit

/// Plan 05 §7: the pure parts of the iPhone extras.
final class NudgeSchedulerTests: XCTestCase {
    var cal: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Europe/Helsinki")!
        return c
    }()

    /// A weekday (Thu 2026-11-12) at hh:mm local.
    func at(_ h: Int, _ m: Int, day: Int = 12) -> Date {
        cal.date(from: DateComponents(year: 2026, month: 11, day: day, hour: h, minute: m))!
    }

    func input(_ now: Date, arm: NudgeArm? = .daylight_walk, done: Set<NudgeScheduler.Activity> = []) -> NudgeScheduler.Input {
        NudgeScheduler.Input(now: now, calendar: cal, windows: [.init(9 * 60, 23 * 60)], quiet: .init(from: 22 * 60, to: 8 * 60),
                             done: done, arm: arm)
    }

    func testQuietHoursBoundary() {
        let i = input(at(20, 0))
        // 21:59 is inside the window and before quiet → kept as is
        XCTAssertEqual(NudgeScheduler.place(at(21, 59), i), at(21, 59))
        // 22:00 is quiet → next window start not in quiet: tomorrow 09:00
        XCTAssertEqual(NudgeScheduler.place(at(22, 0), i), at(9, 0, day: 13))
    }

    func testOneInvitationADayAndNeverQuiet() {
        let plan = NudgeScheduler.plan(input(at(7, 30)))
        let inv = plan.filter { $0.kind == .invitation }
        XCTAssertEqual(inv.count, 2)  // today + tomorrow
        XCTAssertEqual(Set(inv.map { NudgeScheduler.dayKey($0.fireDate, cal) }).count, 2)
        for p in plan {
            let m = cal.component(.hour, from: p.fireDate) * 60 + cal.component(.minute, from: p.fireDate)
            XCTAssertFalse(NudgeScheduler.Quiet().contains(minute: m, weekend: false), p.id)
        }
        XCTAssertFalse(inv[0].passive)
        XCTAssertTrue(plan.filter { $0.kind == .checkin }.allSatisfy(\.passive))
    }

    func testAlreadyWalkedOnGlasses() {
        let events = [env("obs.outing", ["minutes": .number(20), "method": .string("dat_imu")], source: "glasses")]
        let done = NudgeScheduler.doneToday(events: events)
        XCTAssertTrue(done.contains(.walk))
        let plan = NudgeScheduler.plan(input(at(9, 0), arm: .daylight_walk, done: done))
        XCTAssertFalse(plan.contains { $0.kind == .invitation && cal.isDate($0.fireDate, inSameDayAs: at(9, 0)) })
    }

    func testCheckinOnRobotMeansNoReminder() {
        let events = [env("obs.self_report", ["item": .string("mood"), "value": .number(3), "channel": .string("robot")], source: "hub")]
        let plan = NudgeScheduler.plan(input(at(8, 5), done: NudgeScheduler.doneToday(events: events)))
        XCTAssertFalse(plan.contains { $0.kind == .checkin && cal.isDate($0.fireDate, inSameDayAs: at(8, 5)) })
        // without it, the reminder is at the usual 10:00
        let plain = NudgeScheduler.plan(input(at(8, 5)))
        XCTAssertEqual(plain.first { $0.kind == .checkin }?.fireDate, at(10, 0))
    }

    func testLaterOnlyOnce() {
        var i = input(at(11, 0))
        i.laterUntil = at(13, 0)
        let plan = NudgeScheduler.plan(i)
        let today = plan.first { $0.kind == .invitation && cal.isDate($0.fireDate, inSameDayAs: at(11, 0)) }!
        XCTAssertEqual(today.fireDate, at(13, 0))
        XCTAssertEqual(today.category, NudgeScheduler.Category.invitationNoLater)   // no second "Later"
        XCTAssertTrue(today.id.hasSuffix(".later"))
    }

    func testNotTodayAndDeliveredAreFinal() {
        var i = input(at(11, 0))
        i.declinedToday = true
        XCTAssertFalse(NudgeScheduler.plan(i).contains { $0.kind == .invitation && cal.isDate($0.fireDate, inSameDayAs: at(11, 0)) })
        var j = input(at(15, 0))
        j.delivered = [NudgeScheduler.id(.invitation, day: "2026-11-12")]
        XCTAssertFalse(NudgeScheduler.plan(j).contains { $0.kind == .invitation && cal.isDate($0.fireDate, inSameDayAs: at(15, 0)) })
    }

    func testTimezoneChangeKeepsIdsNoDuplicates() {
        let a = NudgeScheduler.plan(input(at(7, 0)))
        cal.timeZone = TimeZone(identifier: "Europe/Stockholm")!
        let b = NudgeScheduler.plan(input(at(6, 0)))   // same instant, an hour earlier on the wall clock
        XCTAssertEqual(Set(a.map(\.id)), Set(b.map(\.id)))
        XCTAssertEqual(b.count, Set(b.map(\.id)).count)
        // the reminder stays at 10:00 local in the new zone
        XCTAssertEqual(cal.component(.hour, from: b.first { $0.kind == .checkin }!.fireDate), 10)
    }

    func testDSTDayStillLocalTime() {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Europe/Helsinki")!
        cal = c
        let dst = cal.date(from: DateComponents(year: 2026, month: 3, day: 29, hour: 7, minute: 0))!  // clocks went forward
        let plan = NudgeScheduler.plan(input(dst))
        XCTAssertEqual(cal.component(.hour, from: plan.first { $0.kind == .checkin }!.fireDate), 10)
    }

    func testPausedAndPHQ9Once() {
        var i = input(at(11, 0))
        i.paused = true
        XCTAssertTrue(NudgeScheduler.plan(i).isEmpty)
        var j = input(at(11, 0))
        j.phq9Due = true
        XCTAssertEqual(NudgeScheduler.plan(j).filter { $0.kind == .phq9 }.count, 1)
        j.delivered = ["kaiku.phq9"]
        XCTAssertEqual(NudgeScheduler.plan(j).filter { $0.kind == .phq9 }.count, 0)
    }

    func testWeekendSleepIn() {
        let q = NudgeScheduler.Quiet(from: 22 * 60, to: 8 * 60, sleepInWeekends: true)
        XCTAssertTrue(q.contains(minute: 9 * 60, weekend: true))
        XCTAssertFalse(q.contains(minute: 9 * 60, weekend: false))
    }

    func env(_ type: String, _ payload: [String: JSONValue], source: String) -> AnyEnvelope {
        let data = try! JSONSerialization.data(withJSONObject: [
            "v": 1, "id": UUID7.make(), "ts": KaikuTime.iso(Date()), "home_id": "demo-aino", "source": source, "type": type,
            "payload": try! JSONSerialization.jsonObject(with: JSONEncoder().encode(payload)),
        ])
        return try! JSONDecoder().decode(AnyEnvelope.self, from: data)
    }
}

final class DeepLinkTests: XCTestCase {
    func testLinks() {
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://today")!), .tab(.today))
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://play/firefly")!), .route(.firefly))
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://checkin")!), .route(.weather))
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://walk")!), .route(.walk))
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://phq9")!), .phq9)
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://you/memories")!), .route(.memories))
        XCTAssertEqual(DeepLink.parse(URL(string: "kaiku://you/firefly")!), .tab(.you))   // only You's own screens
        XCTAssertNil(DeepLink.parse(URL(string: "kaiku://pair?home=demo-aino")!))   // pairing is not a deep link
        XCTAssertNil(DeepLink.parse(URL(string: "https://example.com/?home=demo-aino")!))
    }
}

final class SpokenDialTests: XCTestCase {
    func testEnFiSv() {
        XCTAssertEqual(SpokenDial.parse("pretty tired, maybe a two"), 2)
        XCTAssertEqual(SpokenDial.parse("kakkonen"), 2)
        XCTAssertEqual(SpokenDial.parse("en tvåa"), 2)
        XCTAssertEqual(SpokenDial.parse("ehkä kolme"), 3)
        XCTAssertEqual(SpokenDial.parse("Fyra, tror jag"), 4)
        XCTAssertEqual(SpokenDial.parse("three, no, a two"), 2)
        XCTAssertEqual(SpokenDial.parse("three out of five"), 3)
        XCTAssertEqual(SpokenDial.parse("tre av fem"), 3)
        XCTAssertEqual(SpokenDial.parse("4"), 4)
        XCTAssertNil(SpokenDial.parse("I don't know"))
        XCTAssertNil(SpokenDial.parse("en bra dag"))
        XCTAssertNil(SpokenDial.parse("seven"))
    }

    func testOnDeviceGateEnFiSv() {
        // the on-device listener uses the same gate as typed text and the hub (fixture parity is in SafetyGateTests)
        let toml = try! String(contentsOf: repoRoot.appendingPathComponent("config/safety_phrases.toml"), encoding: .utf8)
        let parsed = MiniTOML.parse(toml)
        var langs = 0
        for (lang, table) in parsed where ["en", "fi", "sv"].contains(lang) {
            guard let v = table.first?.1, case .array(let items) = v, let first = items.first else { continue }
            langs += 1
            XCTAssertNotNil(OnDeviceListener.evaluate("well \(first) honestly").crisis, lang)
        }
        XCTAssertEqual(langs, 3)
        XCTAssertEqual(OnDeviceListener.evaluate("maybe a two").dial, 2)
        XCTAssertNil(OnDeviceListener.evaluate("maybe a two").crisis)
    }
}

final class GaitTests: XCTestCase {
    func testMockWalkGivesCadenceRegularityHeadUp() {
        var gen = MockGait(cadence: 108)
        var g = GaitAnalyzer()
        g.add(gen.next(seconds: 120))
        XCTAssertEqual(g.cadence ?? 0, 108, accuracy: 6)
        XCTAssertGreaterThan(g.regularity ?? 0, 0.85)
        // looks down 4 s of every 30 s → ~0.87 head-up (minus filter lag)
        XCTAssertEqual(g.headUpRatio ?? 0, 0.86, accuracy: 0.08)
        XCTAssertEqual(Double(g.steps), 216, accuracy: 12)
    }

    func testStandingStillIsNoSteps() {
        var g = GaitAnalyzer()
        g.add((0..<600).map { IMUSample(t: Double($0) / 30, accel: SIMD3(0, 9.81, 0)) })
        XCTAssertEqual(g.steps, 0)
        XCTAssertNil(g.cadence)
        XCTAssertEqual(g.headUpRatio ?? 0, 1, accuracy: 0.01)
    }

    func testDaylight() {
        var d = DaylightCounter()
        let t0 = Date()
        d.add(0.7, at: t0)
        d.add(0.2, at: t0.addingTimeInterval(30))
        d.add(0.6, at: t0.addingTimeInterval(60))
        d.close(at: t0.addingTimeInterval(90))
        XCTAssertEqual(d.minutes ?? 0, 1.0, accuracy: 0.01)
    }

    @MainActor func testOutingFromGlassesWalk() throws {
        let w = WalkModel()
        let o = w.makeOuting(minutes: 12.34)
        XCTAssertEqual(o.method, .steps)    // no glasses data → phone method
        XCTAssertEqual(o.minutes, 12.3)
    }
}

final class WearableTests: XCTestCase {
    var cal: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Europe/Helsinki")!
        return c
    }()

    func testSleepAndMidpoint() throws {
        let morning = cal.date(from: DateComponents(year: 2026, month: 11, day: 14, hour: 8))!
        let midnight = cal.startOfDay(for: morning)
        var i = WearableDailyBuilder.Inputs()
        i.asleep = [
            DateInterval(start: midnight.addingTimeInterval(-50 * 60), end: midnight.addingTimeInterval(3 * 3600)),
            DateInterval(start: midnight.addingTimeInterval(2 * 3600), end: midnight.addingTimeInterval(7 * 3600 + 5 * 60)),  // overlaps
        ]
        i.steps = 6400.4; i.restingHR = 62; i.hrvSDNN = 48.04; i.exerciseMin = 24; i.device = .apple_watch
        let w = try XCTUnwrap(WearableDailyBuilder.build(morning: morning, i, calendar: cal))
        XCTAssertEqual(w.date, "2026-11-14")
        XCTAssertEqual(w.sleep_min, 475)                // 23:10 → 07:05
        XCTAssertEqual(w.sleep_midpoint_min, 188)       // ≈ 03:07
        XCTAssertEqual(w.steps, 6400)
        XCTAssertEqual(w.hrv_sdnn_ms, 48)
    }

    func testNoWatchNoObs() {
        XCTAssertNil(WearableDailyBuilder.build(morning: Date(), WearableDailyBuilder.Inputs(), calendar: cal))
    }

    func testLateHealthSamplesGetNewIDAndEqualSnapshotsRetry() {
        var morning = WearableDaily(date: "2026-11-14", device: .apple_watch)
        morning.sleep_min = 390
        let first = WearableDailyBuilder.envelopeID(home: "demo-aino", summary: morning)
        XCTAssertEqual(first, WearableDailyBuilder.envelopeID(home: "demo-aino", summary: morning))
        morning.sleep_min = 420
        XCTAssertNotEqual(first, WearableDailyBuilder.envelopeID(home: "demo-aino", summary: morning))
    }

    func testIdempotentID() {
        let a = WearableDailyBuilder.envelopeID(home: "demo-aino", date: "2026-11-14")
        XCTAssertEqual(a, WearableDailyBuilder.envelopeID(home: "demo-aino", date: "2026-11-14"))
        XCTAssertNotEqual(a, WearableDailyBuilder.envelopeID(home: "demo-aino", date: "2026-11-15"))
        XCTAssertNotNil(UUID(uuidString: a))
    }
}

final class ExtrasContractTests: XCTestCase {
    func props(_ obs: String) throws -> (Set<String>, Set<String>) {
        let s = try json("contracts/schemas/obs/\(obs).schema.json") as! [String: Any]
        let defs = s["$defs"] as! [String: Any]
        let name = defs.keys.first { !["NextDay"].contains($0) }!
        let d = defs[name] as! [String: Any]
        return (Set((d["properties"] as! [String: Any]).keys), Set(d["required"] as? [String] ?? []))
    }

    func testPayloads() throws {
        var o = Outing(minutes: 20, method: .dat_imu)
        o.steps = 2100; o.cadence_spm = 105; o.gait_regularity = 0.9; o.head_up_ratio = 0.8; o.daylight_min = 12
        var w = WearableDaily(date: "2026-11-14", device: .apple_watch)
        w.sleep_min = 470; w.sleep_midpoint_min = 190; w.resting_hr_bpm = 62; w.hrv_sdnn_ms = 48; w.steps = 6400; w.exercise_min = 24
        let samples: [(String, Data)] = [
            ("outing", try JSONEncoder().encode(o)),
            ("wearable_daily", try JSONEncoder().encode(w)),
            ("nudge_outcome", try JSONEncoder().encode(NudgeOutcome(arm: .daylight_walk, accepted: true))),
        ]
        for (obs, data) in samples {
            let body = try JSONSerialization.jsonObject(with: data) as! [String: Any]
            let (p, req) = try props(obs)
            XCTAssertTrue(Set(body.keys).isSubset(of: p), "\(obs): extra \(Set(body.keys).subtracting(p))")
            XCTAssertTrue(req.isSubset(of: Set(body.keys)), "\(obs): missing \(req.subtracting(body.keys))")
        }
        let s = try json("contracts/schemas/obs/outing.schema.json") as! [String: Any]
        let m = (((s["$defs"] as! [String: Any])["Outing"] as! [String: Any])["properties"] as! [String: Any])["method"] as! [String: Any]
        XCTAssertTrue((m["enum"] as! [String]).contains("dat_imu"))
    }
}

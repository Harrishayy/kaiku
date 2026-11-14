import XCTest
@testable import KaikuKit

// The daily Apple Health summary with its newer numbers: walking and running distance, time in daylight, walking
// heart rate, sleep stages and time awake. Everything here is the pure builder, the delivery, the receipts and
// History's writing of numbers, on made-up intervals and values. No test opens Apple Health: what HealthKit hands
// over on a phone with a watch is not shown by any of this.

final class HealthSummaryBuilderTests: XCTestCase {
    private var cal: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Europe/Helsinki")!
        return c
    }()
    private var morning: Date { cal.date(from: DateComponents(year: 2026, month: 11, day: 14, hour: 8))! }
    private var midnight: Date { cal.startOfDay(for: morning) }

    /// Hours after last midnight (negative: the evening before).
    private func span(_ from: Double, _ to: Double) -> DateInterval {
        DateInterval(start: midnight.addingTimeInterval(from * 3600), end: midnight.addingTimeInterval(to * 3600))
    }

    private func build(_ fill: (inout WearableDailyBuilder.Inputs) -> Void) -> WearableDaily? {
        var i = WearableDailyBuilder.Inputs()
        fill(&i)
        return WearableDailyBuilder.build(morning: morning, i, calendar: cal)
    }

    /// A night as a watch writes it: every asleep sample also counts as "asleep".
    private func night(_ i: inout WearableDailyBuilder.Inputs, core: [DateInterval] = [], deep: [DateInterval] = [], rem: [DateInterval] = [],
                       unspecified: [DateInterval] = [], awake: [DateInterval] = []) {
        i.core = core; i.deep = deep; i.rem = rem; i.awake = awake
        i.asleep = core + deep + rem + unspecified
    }

    // MARK: stages

    func testStagesAreMergedByStageBeforeSumming() throws {
        // A watch and a phone both wrote the deep hour (overlapping), and the watch wrote core in two pieces.
        let w = try XCTUnwrap(build { i in
            night(&i, core: [span(-1, 1), span(4.5, 7)],
                  deep: [span(1, 2), span(1.5, 2.25)],          // 01:00 to 02:15 once, not 1 h + 45 min
                  rem: [span(2.25, 4.5)])
        })
        XCTAssertEqual(w.sleep_core_min, 270)   // 2 h + 2 h 30 min
        XCTAssertEqual(w.sleep_deep_min, 75)
        XCTAssertEqual(w.sleep_rem_min, 135)
        XCTAssertEqual(w.sleep_min, 480)        // 23:00 to 07:00, as before
        XCTAssertEqual(w.sleep_awake_min, 0, "a staged night with no awake sample had none to write")
    }

    func testANightWithoutStagesSendsNoStageAndNoAwake() throws {
        let w = try XCTUnwrap(build { i in night(&i, unspecified: [span(-0.5, 6.5)]) })
        XCTAssertEqual(w.sleep_min, 420)
        XCTAssertNil(w.sleep_deep_min); XCTAssertNil(w.sleep_rem_min); XCTAssertNil(w.sleep_core_min)
        XCTAssertNil(w.sleep_awake_min, "a source that writes neither stages nor awake time says nothing about being awake")
    }

    func testAStageNeverReachedIsZeroOnceTheNightIsStaged() throws {
        let w = try XCTUnwrap(build { i in night(&i, core: [span(0, 3)], deep: [span(3, 4)]) })
        XCTAssertEqual(w.sleep_core_min, 180); XCTAssertEqual(w.sleep_deep_min, 60)
        XCTAssertEqual(w.sleep_rem_min, 0, "all three are sent together; a zero is a real zero here")
    }

    func testAStageSampleOutsideTheSleepWindowIsNotCounted() throws {
        // A deep sample the afternoon before (15:00, outside 18:00 to 12:00) and one that straddles noon.
        let w = try XCTUnwrap(build { i in night(&i, core: [span(0, 6)], deep: [span(-9, -8.5), span(11.5, 12.5)]) })
        XCTAssertEqual(w.sleep_deep_min, 30, "only the half hour before noon lies in the window")
        XCTAssertEqual(w.sleep_core_min, 360)
    }

    // MARK: awake

    func testAwakeCountsOnlyBetweenFirstFallingAsleepAndLastWaking() throws {
        let w = try XCTUnwrap(build { i in
            night(&i, core: [span(-0.5, 2.5), span(2.75, 7)],
                  awake: [span(-1, -0.5),            // in bed, not yet asleep: before the night
                          span(2.5, 2.75),           // a quarter of an hour in the night
                          span(2.6, 2.75),           // the phone wrote the same waking: merged, not doubled
                          span(7, 7.2)])             // after the last waking
        })
        XCTAssertEqual(w.sleep_awake_min, 15)
    }

    func testAnAwakeSampleThatCrossesTheNightsEdgeIsCutThere() throws {
        // Awake from 06:40 to 07:20 by one source while another has her asleep until 07:00.
        let w = try XCTUnwrap(build { i in night(&i, core: [span(0, 7)], awake: [span(6 + 40.0 / 60, 7 + 20.0 / 60)]) })
        XCTAssertEqual(w.sleep_awake_min, 20)
    }

    func testAwakeSamplesCountWithoutStagesToo() throws {
        let w = try XCTUnwrap(build { i in night(&i, unspecified: [span(0, 3), span(3.2, 7)], awake: [span(3, 3.2)]) })
        XCTAssertEqual(w.sleep_awake_min, 12)
        XCTAssertNil(w.sleep_deep_min, "awake samples do not make a night staged")
    }

    func testAwakeOnlyOutsideTheNightIsZeroNotAbsent() throws {
        // The source does write awake time; none of it fell inside the night.
        let w = try XCTUnwrap(build { i in night(&i, unspecified: [span(0, 7)], awake: [span(-0.4, 0)]) })
        XCTAssertEqual(w.sleep_awake_min, 0)
    }

    func testAwakeWithoutAnySleepIsNothing() {
        XCTAssertNil(build { i in i.awake = [span(1, 2)] }, "no night: nothing to send")
    }

    // MARK: a nap inside the window

    func testAnEveningNapInsideTheWindow() throws {
        // 19:00 to 19:40 asleep on the sofa (the window opens at 18:00), then the night from 23:30 to 07:00.
        // The watch closed the nap with five minutes awake and wrote ten minutes awake at 03:00.
        let w = try XCTUnwrap(build { i in
            night(&i, core: [span(-5, -4 - 20.0 / 60), span(-0.5, 3), span(3 + 10.0 / 60, 7)],
                  awake: [span(-4 - 20.0 / 60, -4 - 15.0 / 60), span(3, 3 + 10.0 / 60)])
        })
        XCTAssertEqual(w.sleep_min, 480, "the nap counts toward sleep, as it did before: 40 min + 7 h 20 min")
        XCTAssertEqual(w.sleep_core_min, 480)
        // "Between the first falling asleep and the last waking" starts at the nap: both awake samples count.
        // The evening between the nap and the night is not awake time here: nobody wrote it as an awake sample.
        XCTAssertEqual(w.sleep_awake_min, 15)
    }

    func testANapBeforeTheWindowIsNotPartOfTheNight() throws {
        // 16:00 to 16:45: before 18:00. One from 17:30 to 18:20 is cut at the window's start.
        let w = try XCTUnwrap(build { i in night(&i, core: [span(-8, -7.25), span(-6.5, -5 - 40.0 / 60), span(0, 6)]) })
        XCTAssertEqual(w.sleep_min, 380)   // 20 min + 6 h
    }

    func testASampleThatOnlyTouchesTheWindowHasNoLength() {
        // Asleep until exactly 18:00 the day before: it meets the window at one instant.
        XCTAssertNil(build { i in night(&i, unspecified: [span(-7, -6)]) })
    }

    // MARK: distance, daylight, walking heart rate

    func testRoundingOfTheDaysNumbers() throws {
        let w = try XCTUnwrap(build { i in i.distanceKm = 4.6649; i.daylightMin = 47.5; i.walkingHR = 98.44; i.steps = 6400.4 })
        XCTAssertEqual(w.distance_km, 4.66)          // two places
        XCTAssertEqual(w.daylight_min, 48)           // whole minutes
        XCTAssertEqual(w.walking_hr_bpm, 98.4)       // one place
        XCTAssertEqual(w.steps, 6400)
        XCTAssertEqual(build { $0.distanceKm = 4.666 }?.distance_km, 4.67)
        XCTAssertEqual(build { $0.distanceKm = 0 }?.distance_km, 0, "a day Health holds as zero is a zero")
    }

    func testRanges() {
        XCTAssertEqual(build { $0.distanceKm = 412.3 }?.distance_km, 300)
        XCTAssertEqual(build { $0.daylightMin = 2000 }?.daylight_min, 1440)
        XCTAssertNil(build { $0.distanceKm = -0.2 }, "a negative distance is a broken number, not a walk")
        XCTAssertNil(build { $0.distanceKm = .nan })
        XCTAssertNil(build { $0.daylightMin = .infinity })
        // A heart rate the contract would refuse is left out, never clamped into a made-up one.
        XCTAssertNil(build { $0.walkingHR = 20 })
        XCTAssertNil(build { $0.walkingHR = 250 })
        XCTAssertNil(build { $0.walkingHR = 249.96 }, "it rounds to 250.0, which the contract refuses")
        XCTAssertNil(build { $0.walkingHR = .nan })
        XCTAssertEqual(build { $0.walkingHR = 249.94 }?.walking_hr_bpm, 249.9)
        XCTAssertEqual(build { $0.walkingHR = 20.06 }?.walking_hr_bpm, 20.1)
        XCTAssertEqual(build { $0.restingHR = 61.96 }?.resting_hr_bpm, 62, "the resting rate is written as before")
    }

    func testANewNumberAloneIsAnObservation() {
        XCTAssertNotNil(build { $0.distanceKm = 1.2 })
        XCTAssertNotNil(build { $0.daylightMin = 12 })
        XCTAssertNotNil(build { $0.walkingHR = 101 })
        XCTAssertNil(build { _ in }, "nothing at all is still no observation")
    }

    // MARK: the wire

    func testTheNewNumbersGoOutUnderTheContractsNames() throws {
        var w = WearableDaily(date: "2026-11-14", device: .apple_watch)
        w.sleep_min = 455; w.steps = 6400
        w.distance_km = 4.66; w.daylight_min = 53; w.walking_hr_bpm = 98.4
        w.sleep_deep_min = 60; w.sleep_rem_min = 90; w.sleep_core_min = 305; w.sleep_awake_min = 15
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(w)) as? [String: Any])
        for (name, value) in ["distance_km": 4.66, "daylight_min": 53, "walking_hr_bpm": 98.4, "sleep_deep_min": 60,
                              "sleep_rem_min": 90, "sleep_core_min": 305, "sleep_awake_min": 15] {
            XCTAssertEqual(body[name] as? Double, value, name)
        }
        XCTAssertEqual(try JSONDecoder().decode(WearableDaily.self, from: JSONEncoder().encode(w)), w)
    }

    func testASummaryWithoutTheNewNumbersIsWrittenAsBefore() throws {
        var w = WearableDaily(date: "2026-11-14", device: .apple_watch)
        w.sleep_min = 470; w.sleep_midpoint_min = 190; w.resting_hr_bpm = 62; w.hrv_sdnn_ms = 48; w.steps = 6400; w.exercise_min = 24
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(w)) as? [String: Any])
        XCTAssertEqual(Set(body.keys), ["date", "device", "sleep_min", "sleep_midpoint_min", "resting_hr_bpm", "hrv_sdnn_ms", "steps", "exercise_min"],
                       "an absent number is left out, never sent as null or zero: the envelope id of an older summary stays what it was")
        let before = WearableDailyBuilder.envelopeID(home: "demo-aino", summary: w)
        w.distance_km = 4.66
        XCTAssertNotEqual(before, WearableDailyBuilder.envelopeID(home: "demo-aino", summary: w), "more numbers for the same morning are a new observation")
    }

    /// Once the contract has the fields, the app's payload must fit its schema. Until then this says so and skips.
    func testThePayloadFitsTheContractSchemaOnceItHasTheFields() throws {
        let schema = try json("contracts/schemas/obs/wearable_daily.schema.json") as! [String: Any]
        let defs = schema["$defs"] as! [String: Any]
        let model = try XCTUnwrap(defs["WearableDaily"] as? [String: Any])
        let known = Set((model["properties"] as! [String: Any]).keys)
        let new: Set<String> = ["distance_km", "daylight_min", "walking_hr_bpm", "sleep_deep_min", "sleep_rem_min", "sleep_core_min", "sleep_awake_min"]
        guard new.isSubset(of: known) else {
            throw XCTSkip("contracts/schemas/obs/wearable_daily.schema.json does not have the new fields yet: \(new.subtracting(known).sorted())")
        }
        var w = WearableDaily(date: "2026-11-14", device: .apple_watch)
        w.distance_km = 4.66; w.daylight_min = 53; w.walking_hr_bpm = 98.4
        w.sleep_deep_min = 60; w.sleep_rem_min = 90; w.sleep_core_min = 305; w.sleep_awake_min = 15
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(w)) as? [String: Any])
        XCTAssertTrue(Set(body.keys).isSubset(of: known))
    }
}

// MARK: - delivery

@MainActor final class HealthDeliveryMarkTests: XCTestCase {
    private var dir: URL!
    private let pairing = Pairing(baseURL: URL(string: "https://health.test")!, homeID: "health-home", token: nil)

    override func setUp() async throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        FaceSignsHTTP.reset()
    }
    override func tearDown() async throws { try? FileManager.default.removeItem(at: dir) }

    private func makeApp() -> AppModel {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [FaceSignsHTTP.self]
        let api = APIClient(pairing: pairing, maxAttempts: 1, session: URLSession(configuration: config))
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        defaults.set(["watch": true], forKey: "kaiku.consents")
        return AppModel(defaults: defaults, pairing: pairing, api: api, queue: OfflineQueue(url: dir.appendingPathComponent("events.json")),
                        episodes: EpisodeOutbox(url: dir.appendingPathComponent("episodes.json")))
    }

    private func summary(_ morning: Date) -> WearableDaily {
        var w = WearableDaily(date: AppModel.dayKey(morning), device: .apple_watch)
        w.sleep_min = 455; w.sleep_deep_min = 60; w.sleep_rem_min = 90; w.sleep_core_min = 305; w.sleep_awake_min = 15
        w.steps = 6400; w.distance_km = 4.66; w.daylight_min = 53
        return w
    }

    func testASummaryMadeOfSampleDataGoesOutAsSimulated() async throws {
        let app = makeApp()
        await HealthDelivery.sync(app: app, summary: { self.summary($0) }, simulated: { _ in true })
        let sent = FaceSignsHTTP.accepted.filter { $0["type"] as? String == "obs.wearable_daily" }
        XCTAssertEqual(sent.count, 2)
        for e in sent {
            XCTAssertEqual(e["sim"] as? Bool, true, "stand-in numbers are never sent as the person's")
            let p = try XCTUnwrap(e["payload"] as? [String: Any])
            XCTAssertEqual(p["distance_km"] as? Double, 4.66); XCTAssertEqual(p["sleep_awake_min"] as? Double, 15)
        }
    }

    func testAPersonsOwnSummaryIsNotMarkedSimulated() async {
        let app = makeApp()
        await HealthDelivery.sync(app: app, summary: { self.summary($0) })
        let sent = FaceSignsHTTP.accepted.filter { $0["type"] as? String == "obs.wearable_daily" }
        XCTAssertEqual(sent.count, 2)
        XCTAssertTrue(sent.allSatisfy { ($0["sim"] as? Bool ?? false) == false })
    }

    func testTheChoiceSwitchedOffWhileTheSourceIsCheckedSendsNothing() async {
        let app = makeApp()
        await HealthDelivery.sync(app: app, summary: { self.summary($0) }, simulated: { _ in app.consents[.watch] = false; return false })
        XCTAssertTrue(FaceSignsHTTP.accepted.isEmpty)
    }
}

// MARK: - receipts and consent text

final class HealthReceiptTests: XCTestCase {
    override func setUp() { L10n.shared.language = .en }

    private func health(_ payload: [String: JSONValue], sim: Bool? = nil) -> AnyEnvelope {
        let p = try! JSONEncoder().encode(JSONValue.object(payload))
        let simText = sim.map { ",\"sim\":\($0)" } ?? ""
        let json = "{\"v\":1,\"id\":\"\(UUID().uuidString)\",\"ts\":\"2026-11-14T06:00:00.000Z\",\"home_id\":\"h\",\"source\":\"phone\",\"type\":\"obs.wearable_daily\",\"payload\":\(String(data: p, encoding: .utf8)!)\(simText)}"
        return try! JSONDecoder().decode(AnyEnvelope.self, from: Data(json.utf8))
    }

    private let whole: [String: JSONValue] = [
        "date": .string("2026-11-14"), "device": .string("apple_watch"),
        "sleep_min": .number(455), "sleep_midpoint_min": .number(188), "sleep_deep_min": .number(60), "sleep_rem_min": .number(90),
        "sleep_core_min": .number(305), "sleep_awake_min": .number(15), "resting_hr_bpm": .number(62), "walking_hr_bpm": .number(98.4),
        "hrv_sdnn_ms": .number(48), "steps": .number(6400), "distance_km": .number(4.66), "exercise_min": .number(24), "daylight_min": .number(53),
    ]

    func testTheReceiptNamesEveryKindOfNumberTheSummaryHolds() {
        let e = DayEvidence.build(events: [health(whole)], talks: 0, transcriptsKept: false)
        XCTAssertEqual(e.items.map(\.kind), [.health])
        XCTAssertEqual(e.items[0].facts, ["Last night and yesterday: sleep, sleep stages, time awake at night, resting heart rate, walking heart rate, heart rate variability, steps, distance, exercise minutes, time in daylight"])
        XCTAssertEqual(e.items[0].sources, ["evidence.src.phone"])
        XCTAssertEqual(e.items[0].sharing, .numbers)
    }

    func testTheReceiptNamesOnlyWhatIsThere() {
        // A phone without a watch: steps and distance, nothing else.
        let phone = DayEvidence.build(events: [health(["date": .string("2026-11-14"), "device": .string("phone_only"),
                                                       "steps": .number(4100), "distance_km": .number(2.9)])], talks: 0, transcriptsKept: false)
        XCTAssertEqual(phone.items[0].facts, ["Last night and yesterday: steps, distance"])
        // A tracker that writes sleep without stages.
        let plain = DayEvidence.healthNames([health(["sleep_min": .number(420), "sleep_midpoint_min": .number(200)])])
        XCTAssertEqual(plain, ["sleep"])
        // Two summaries today (yesterday's morning sent late, and today's): each kind is named once.
        let two = DayEvidence.healthNames([health(["steps": .number(100)]), health(["steps": .number(200), "daylight_min": .number(20)])])
        XCTAssertEqual(two, ["steps", "time in daylight"])
        // A summary of an older build's shape that this build cannot read a number from: the plain line.
        let none = DayEvidence.build(events: [health(["date": .string("2026-11-14")])], talks: 0, transcriptsKept: false)
        XCTAssertEqual(none.items[0].facts, ["Daily totals from last night and yesterday"])
    }

    func testTheReceiptShowsNoNumberAndNoJudgement() {
        let text = DayEvidence.build(events: [health(whole)], talks: 0, transcriptsKept: false).items[0].facts.joined(separator: " ")
        XCTAssertNil(text.rangeOfCharacter(from: .decimalDigits), "the numbers themselves are in History")
        for word in ["good", "bad", "poor", "better", "worse", "quality", "score", "enough", "healthy", "normal", "low", "high"] {
            XCTAssertFalse(text.lowercased().contains(word), word)
        }
    }

    func testSampleDataIsLabelledInTheReceipt() {
        let e = DayEvidence.build(events: [health(whole, sim: true)], talks: 0, transcriptsKept: false)
        XCTAssertTrue(e.items[0].practice)
    }

    func testTheChoiceSaysEverythingThatIsReadNow() {
        for lang in [KaikuLanguage.en, .fi] {
            let whole = L10n.shared.string(Signal.watch.wholeKey, lang: lang)
            for part in ["sleep with its stages and time awake", "resting and walking heart rate", "heart rate variability", "steps",
                         "walking and running distance", "exercise minutes", "time in daylight", "daily totals", "never as single readings"] {
                XCTAssertTrue(whole.contains(part), "\(lang): \(part)")
            }
            // No score is read (Apple Health has none) and none is promised.
            for word in ["score", "quality"] { XCTAssertFalse(whole.lowercased().contains(word), word) }
            let short = L10n.shared.string("sig.watch.s", lang: lang)
            for part in ["Sleep", "heart rate", "steps", "daylight", "Apple Health"] { XCTAssertTrue(short.contains(part), "\(lang): \(part)") }
            for key in ["setup.perm.health.d", "evidence.health.d", "evidence.health.read", "saw.watch.read", "saw.watch.none"] {
                XCTAssertTrue(L10n.shared.has(key, lang), "\(key) \(lang)")
            }
        }
        XCTAssertEqual(Signal.watch.lineKey, "sig.watch.s", "the row shows the short line; the whole text stands under the list")
        // The shared copy's own line for this choice is older and says less; no screen of this app shows it.
        XCTAssertEqual(Signal.watch.wholeKey, "sig.watch.full")
        XCTAssertEqual(Signal.camera.wholeKey, "sig.camera.d")
    }
}

// MARK: - History: the new numbers as the person sees them

final class HealthHistoryFormatTests: XCTestCase {
    override func setUp() { L10n.shared.language = .en }

    private func measure(_ key: String, _ title: String, unit: String, decimals: Int = 0, perDay: String = "latest",
                         days: [(String, Double)]) -> HistoryMeasure {
        HistoryMeasure(key: key, title: title, unit: unit, decimals: decimals, per_day: perDay, devices: ["watch"],
                       days: days.map { HistoryDay(date: $0.0, value: $0.1) })
    }

    func testDistanceIsWrittenInKilometresWithTheServicesDecimals() {
        let two = measure("distance", "Distance", unit: "km", decimals: 2, days: [("2026-11-13", 4.66), ("2026-11-14", 0.4)])
        XCTAssertEqual(HistoryFormat.value(4.66, of: two), "4.66 km")
        XCTAssertEqual(HistoryFormat.value(0.4, of: two), "0.40 km")
        XCTAssertEqual(HistoryFormat.value(12, of: two), "12.00 km")
        let one = measure("distance", "Distance", unit: "km", decimals: 1, days: [])
        XCTAssertEqual(HistoryFormat.value(4.66, of: one), "4.7 km")
        XCTAssertEqual(HistoryFormat.span(2.9, 6.14, of: two), "2.90 – 6.14 km")
        // In a session's list the number keeps what it has: two places while small, one from ten, none from a hundred.
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "distance_km", title: "Distance", value: 4.66, unit: "km")), "4.66 km")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "distance_km", title: "Distance", value: 12.34, unit: "km")), "12.3 km")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "distance_km", title: "Distance", value: 5, unit: "km")), "5 km")
    }

    func testMinutesAreWrittenAsHoursAndMinutesWhereTheyAreLong() {
        let deep = measure("sleep_deep", "Deep sleep", unit: "min", days: [])
        XCTAssertEqual(HistoryFormat.value(48, of: deep), "48 min")
        XCTAssertEqual(HistoryFormat.value(60, of: deep), "1 h")
        XCTAssertEqual(HistoryFormat.value(305, of: deep), "5 h 5 min")
        XCTAssertEqual(HistoryFormat.value(0, of: deep), "0 min", "a stage she never reached that night is a real zero")
        XCTAssertEqual(HistoryFormat.span(15, 72, of: deep), "15 min – 1 h 12 min")
        XCTAssertEqual(HistoryFormat.average(52.4, of: deep), "52 min")
        XCTAssertEqual(HistoryFormat.average(7.5, of: deep), "7.5 min", "a small average keeps one place")
    }

    func testAHeartRateIsWrittenInBeatsAMinute() {
        let walking = measure("walking_hr", "Walking heart rate", unit: "bpm", days: [])
        XCTAssertEqual(HistoryFormat.value(98.4, of: walking), "98 bpm")
        XCTAssertEqual(HistoryFormat.span(92, 104, of: walking), "92 – 104 bpm")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "walking_hr_bpm", title: "Walking heart rate", value: 98.4, unit: "bpm")), "98.4 bpm")
    }

    func testAWeekOfANewSeriesAddsUpTheWayTheServiceSaysItsDayIsMade() {
        let today = "2026-11-14"
        let days: [(String, Double)] = [("2026-11-09", 3.1), ("2026-11-10", 4.4), ("2026-11-12", 5.0), ("2026-11-14", 4.66)]
        // One summary a morning: the day is its latest value, so a week is an average of the days that have one.
        let latest = measure("distance", "Distance", unit: "km", decimals: 2, days: days)
        let points = HistoryMath.points(latest.days, in: .ending(today, .week))
        let stats = HistoryMath.stats(points)
        XCTAssertEqual(stats.days, 4, "a day without a summary is absent, not a zero")
        XCTAssertEqual(HistoryMath.headline(stats, rule: latest.rule) ?? 0, 4.29, accuracy: 0.001)
        XCTAssertFalse(HistoryMath.standsOnZero(latest), "a level: drawn as marks at their height")
        // Were the service to say the day is a total, the same week is summed and drawn as bars on zero.
        let total = measure("distance", "Distance", unit: "km", decimals: 2, perDay: "total", days: days)
        XCTAssertEqual(HistoryMath.headline(stats, rule: total.rule) ?? 0, 17.16, accuracy: 0.001)
        XCTAssertTrue(HistoryMath.standsOnZero(total))
        XCTAssertEqual(HistoryMath.domain(days.map(\.1), measure: total).lowerBound, 0)
        XCTAssertEqual(HistoryMath.latest(latest.days)?.value, 4.66)
    }

    /// The service decides which measures exist, their titles and units. A measure or a group this build has never
    /// heard of must decode and draw: nothing in the app lists the watch's measures.
    func testASeriesThisBuildHasNeverHeardOfDecodesAndDraws() throws {
        let json = """
        {"home_id":"h","days":30,"first_day":"2026-10-16","last_day":"2026-11-14","timezone":"Europe/Helsinki","sim":true,"generated_at":"2026-11-14T08:00:00Z",
         "groups":[
          {"key":"sleep_body","title":"Sleep and body","measures":[
            {"key":"some_new_distance","title":"Distance","unit":"km","format":"number","decimals":2,"per_day":"latest","devices":["watch","phone"],
             "days":[{"date":"2026-11-13","value":3.9,"sessions":1,"sim":true},{"date":"2026-11-14","value":4.66,"sessions":1,"sim":true}],
             "sessions":[{"id":"s1","ts":"2026-11-14T06:10:00Z","device":"watch","sim":true,"values":[
               {"key":"sleep_min","title":"Sleep","value":455,"unit":"min"},
               {"key":"sleep_deep_min","title":"Deep sleep","value":60,"unit":"min"},
               {"key":"sleep_rem_min","title":"REM sleep","value":90,"unit":"min"},
               {"key":"sleep_core_min","title":"Core sleep","value":305,"unit":"min"},
               {"key":"sleep_awake_min","title":"Awake in the night","value":15,"unit":"min"},
               {"key":"sleep_midpoint_min","title":"Middle of the night's sleep","value":188,"unit":"","format":"clock"},
               {"key":"resting_hr_bpm","title":"Resting heart rate","value":62,"unit":"bpm"},
               {"key":"walking_hr_bpm","title":"Walking heart rate","value":98.4,"unit":"bpm"},
               {"key":"hrv_sdnn_ms","title":"Heart rate variability","value":48,"unit":"ms"},
               {"key":"steps","title":"Steps","value":6400,"unit":"steps"},
               {"key":"distance_km","title":"Distance","value":4.66,"unit":"km"},
               {"key":"exercise_min","title":"Exercise","value":24,"unit":"min"},
               {"key":"daylight_min","title":"Time in daylight","value":53,"unit":"min"}]}]},
            {"key":"a_rule_from_later","title":"Something newer","unit":"things","per_day":"a_new_rule","days":[{"date":"2026-11-14","value":2}]}]},
          {"key":"a_group_from_later","title":"Something else","measures":[]}]}
        """
        let history = try JSONDecoder().decode(PersonHistory.self, from: Data(json.utf8))
        let group = try XCTUnwrap(history.groups.first)
        XCTAssertEqual(group.symbol, "bed.double.fill")
        let m = try XCTUnwrap(group.measures.first)
        XCTAssertEqual(HistoryFormat.value(try XCTUnwrap(HistoryMath.latest(m.days)).value, of: m), "4.66 km")
        XCTAssertEqual(HistoryDevice.names(m.devices), "Watch, iPhone")
        let written = try XCTUnwrap(m.sessions.first).values.map { "\($0.title) \(HistoryFormat.value($0))" }
        XCTAssertEqual(written, ["Sleep 7 h 35 min", "Deep sleep 1 h", "REM sleep 1 h 30 min", "Core sleep 5 h 5 min", "Awake in the night 15 min",
                                 "Middle of the night's sleep \(HistoryFormat.clock(188))", "Resting heart rate 62 bpm", "Walking heart rate 98.4 bpm",
                                 "Heart rate variability 48 ms", "Steps 6,400", "Distance 4.66 km", "Exercise 24 min", "Time in daylight 53 min"])
        // The session's own number of this measure is found by its unit and its day's value, with no list of keys.
        XCTAssertEqual(HistoryMath.sessionKey(m, zone: history.zone), "distance_km")
        // A per-day rule this build does not know: the measure is still written, and a week is an average of its days.
        let later = group.measures[1]
        XCTAssertNil(later.rule)
        XCTAssertEqual(HistoryFormat.value(2, of: later), "2 things")
        XCTAssertFalse(HistoryMath.standsOnZero(later))
        // A group this build does not know keeps a neutral icon and tone.
        XCTAssertEqual(history.groups[1].symbol, "chart.bar.fill")
        XCTAssertEqual(history.groups[1].tone, .ink)
    }
}

// MARK: - History: a share written as a percentage, minutes written as a duration

/// The service says how a value is to be read (`format`): `percent` (a share from 0 to 1) and `duration` (minutes)
/// beside `number` and `clock`. Every place History writes a value goes through `HistoryFormat`, tested here on
/// stand-in measures; a format this build does not know stays a plain number.
final class HistoryFormatWordsTests: XCTestCase {
    override func setUp() { L10n.shared.language = .en }
    override func tearDown() { L10n.shared.language = .en }

    private func measure(_ format: String, unit: String = "", decimals: Int = 0, perDay: String = "average",
                         days: [(String, Double)] = [], usual: HistoryUsual? = nil, sessions: [HistorySession] = []) -> HistoryMeasure {
        HistoryMeasure(key: "m", title: "Measure", unit: unit, format: format, decimals: decimals, per_day: perDay, devices: ["phone"],
                       days: days.map { HistoryDay(date: $0.0, value: $0.1) }, usual: usual, sessions: sessions)
    }

    func testAShareIsWrittenAsAPercentage() {
        let share = measure("percent", unit: "of the time")
        XCTAssertEqual(share.kind, .percent)
        XCTAssertEqual(HistoryFormat.value(0.14, of: share), "14% of the time")
        XCTAssertEqual(HistoryFormat.value(0, of: share), "0% of the time")
        XCTAssertEqual(HistoryFormat.value(1, of: share), "100% of the time")
        XCTAssertEqual(HistoryFormat.value(0.146, of: share), "15% of the time")
        let bare = measure("percent")
        XCTAssertEqual(HistoryFormat.value(0.14, of: bare), "14%", "no unit: just the percentage")
        XCTAssertEqual(HistoryFormat.value(0.143, of: measure("percent", decimals: 1)), "14.3%", "the decimals are the percentage's")
        XCTAssertEqual(HistoryFormat.value(.nan, of: bare), "–")
    }

    func testAPercentagesRangeAndAverage() {
        let share = measure("percent", unit: "of the time")
        XCTAssertEqual(HistoryFormat.span(0.10, 0.18, of: share), "10% – 18% of the time")       // the usual range, a week's lowest and highest
        XCTAssertEqual(HistoryFormat.span(0.10, 0.18, of: measure("percent")), "10% – 18%")
        XCTAssertEqual(HistoryFormat.span(0.141, 0.144, of: share), "14% of the time", "written the same: one value")
        // A week's average: whole from ten percent up, one place below it (as a small count keeps one).
        XCTAssertEqual(HistoryFormat.average(0.1433, of: share), "14% of the time")
        XCTAssertEqual(HistoryFormat.average(0.045, of: share), "4.5% of the time")
        XCTAssertEqual(HistoryFormat.average(0.05, of: share), "5% of the time")
    }

    func testMinutesAreWrittenAsADuration() {
        let sleep = measure("duration")
        XCTAssertEqual(sleep.kind, .duration)
        XCTAssertEqual(HistoryFormat.value(440, of: sleep), "7 h 20 min")
        XCTAssertEqual(HistoryFormat.value(60, of: sleep), "1 h")
        XCTAssertEqual(HistoryFormat.value(45, of: sleep), "45 min")
        XCTAssertEqual(HistoryFormat.value(59.6, of: sleep), "1 h", "written from what it rounds to")
        XCTAssertEqual(HistoryFormat.value(0, of: sleep), "0 min")
        // The unit is empty on the wire; a unit sent all the same changes nothing.
        XCTAssertEqual(HistoryFormat.value(440, of: measure("duration", unit: "min")), "7 h 20 min")
        XCTAssertEqual(HistoryFormat.value(45, of: measure("duration", unit: "minutes")), "45 min")
    }

    func testADurationsRangeAndAverage() {
        let sleep = measure("duration")
        XCTAssertEqual(HistoryFormat.span(380, 470, of: sleep), "6 h 20 min – 7 h 50 min")
        XCTAssertEqual(HistoryFormat.span(45, 75, of: sleep), "45 min – 1 h 15 min")
        XCTAssertEqual(HistoryFormat.span(20, 45, of: sleep), "20 – 45 min")
        XCTAssertEqual(HistoryFormat.span(45, 45.2, of: sleep), "45 min")
        XCTAssertEqual(HistoryFormat.average(432.6, of: sleep), "7 h 13 min")
        XCTAssertEqual(HistoryFormat.average(52.4, of: sleep), "52 min")
        XCTAssertEqual(HistoryFormat.average(7.5, of: sleep), "7.5 min", "a small average keeps one place")
    }

    func testASessionsNumbersUseTheirOwnFormat() {
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "smile_share", title: "Smiling", value: 0.14, unit: "of the time", format: "percent")), "14% of the time")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "coverage", title: "In view", value: 0.976, format: "percent")), "98%")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "sleep_min", title: "Sleep", value: 455, format: "duration")), "7 h 35 min")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "sleep_awake_min", title: "Awake in the night", value: 15, format: "duration")), "15 min")
        XCTAssertEqual(HistoryFormat.value(HistoryValue(key: "x", title: "Something", value: 3.25, unit: "things", format: "a_format_from_later")), "3.25 things")
    }

    func testAFormatThisBuildDoesNotKnowIsAPlainNumber() {
        let later = measure("a_format_from_later", unit: "things", decimals: 1)
        XCTAssertEqual(later.kind, .number)
        XCTAssertEqual(HistoryFormat.value(3.25, of: later), "3.3 things")
        XCTAssertEqual(HistoryFormat.span(1, 3.25, of: later), "1.0 – 3.3 things")
        XCTAssertEqual(HistoryAxis.label(3, measure: later, hours: false), "3")
    }

    func testTheChartsAxisSpeaksTheMeasuresFormat() {
        let share = measure("percent", unit: "of the time", days: [("2026-11-13", 0.10), ("2026-11-14", 0.18)])
        let domain = HistoryMath.domain([0.10, 0.18], measure: share)
        XCTAssertGreaterThanOrEqual(domain.lowerBound, 0); XCTAssertLessThanOrEqual(domain.upperBound, 1)
        XCTAssertTrue(domain.contains(0.10) && domain.contains(0.18))
        XCTAssertLessThanOrEqual(HistoryMath.domain([0.97, 1.0], measure: share).upperBound, 1, "no room above 100%")
        XCTAssertGreaterThanOrEqual(HistoryMath.domain([0, 0.02], measure: share).lowerBound, 0, "nor below 0%")
        XCTAssertEqual(HistoryAxis.label(0.1, measure: share, hours: false), "10%")
        XCTAssertEqual(HistoryAxis.label(0.125, measure: share, hours: false), "12.5%")
        XCTAssertFalse(HistoryAxis.countsHours(domain, measure: share))
        // Minutes: counted in hours on the axis from two hours up, as a measure in "min" always was.
        let sleep = measure("duration")
        XCTAssertTrue(HistoryAxis.countsHours(0...480, measure: sleep))
        XCTAssertEqual(HistoryAxis.label(240, measure: sleep, hours: true), "4 h")
        XCTAssertFalse(HistoryAxis.countsHours(0...90, measure: sleep))
        XCTAssertEqual(HistoryAxis.label(45, measure: sleep, hours: false), "45")
        XCTAssertTrue(HistoryAxis.countsHours(0...480, measure: measure("number", unit: "min")))
        XCTAssertFalse(HistoryAxis.countsHours(0...480, measure: measure("number", unit: "steps")))
        XCTAssertEqual(HistoryAxis.label(188, measure: measure("clock"), hours: false), HistoryFormat.clock(188))
    }

    func testADurationThatAddsUpStandsOnZeroAndAWeekSumsIt() {
        // Time in daylight, were the service to say the day is a total: bars on zero, and a week is their sum.
        let light = measure("duration", perDay: "total", days: [("2026-11-12", 35), ("2026-11-13", 50), ("2026-11-14", 48)])
        XCTAssertTrue(HistoryMath.standsOnZero(light))
        let stats = HistoryMath.stats(HistoryMath.points(light.days, in: .ending("2026-11-14", .week)))
        XCTAssertEqual(HistoryFormat.value(HistoryMath.headline(stats, rule: light.rule) ?? 0, of: light), "2 h 13 min")
        XCTAssertEqual(HistoryFormat.average(stats.average ?? 0, of: light), "44 min")
    }

    func testAMeasuresOwnSessionNumberIsFoundByItsFormatToo() {
        let session = HistorySession(id: "s", ts: "2026-11-14T06:10:00Z", device: "watch", values: [
            HistoryValue(key: "sleep_min", title: "Sleep", value: 455, format: "duration"),
            HistoryValue(key: "sleep_deep_min", title: "Deep sleep", value: 60, format: "duration"),
            HistoryValue(key: "steps", title: "Steps", value: 6400, unit: "steps"),
        ])
        let deep = measure("duration", perDay: "latest", days: [("2026-11-14", 60)], sessions: [session])
        XCTAssertEqual(HistoryMath.sessionKey(deep, zone: TimeZone(identifier: "Europe/Helsinki")!), "sleep_deep_min")
    }

    func testAMeasureWithoutACountedDaySaysPracticeOnlyWhereAPracticeRoundIsListed() {
        let warm = HistorySession(id: "w", ts: "2026-11-14T08:00:00Z", device: "phone", warmup: true)
        let thin = HistorySession(id: "t", ts: "2026-11-14T08:00:00Z", device: "phone")
        // A game's first sessions: practice rounds, as before.
        XCTAssertEqual(HistoryFormat.emptyKey(measure("number", sessions: [warm]), card: true), "history.card.practice")
        XCTAssertEqual(HistoryFormat.emptyKey(measure("number", sessions: [warm, thin]), card: false), "history.practice")
        // Sessions that are listed and do not count toward a day (too short, or of another kind): not "practice".
        XCTAssertEqual(HistoryFormat.emptyKey(measure("number", sessions: [thin]), card: true), "history.card.uncounted")
        XCTAssertEqual(HistoryFormat.emptyKey(measure("number", sessions: [thin]), card: false), "history.uncounted")
        // Days elsewhere, none in the period on screen.
        XCTAssertEqual(HistoryFormat.emptyKey(measure("number", days: [("2026-10-01", 3)], sessions: [thin]), card: false), "history.none")
        for key in ["history.card.practice", "history.practice", "history.card.uncounted", "history.uncounted", "history.none"] {
            XCTAssertTrue(L10n.shared.has(key, .en) && L10n.shared.has(key, .fi), key)
        }
    }

    func testAPercentageIsWrittenInTheLanguagesOwnWay() {
        L10n.shared.language = .fi
        let fi = HistoryFormat.value(0.14, of: measure("percent"))
        XCTAssertTrue(fi.hasPrefix("14") && fi.hasSuffix("%"), fi)
        XCTAssertEqual(HistoryFormat.value(440, of: measure("duration")), "7 h 20 min")
    }
}

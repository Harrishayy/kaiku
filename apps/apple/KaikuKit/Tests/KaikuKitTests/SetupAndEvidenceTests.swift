import XCTest
@testable import KaikuKit

final class SetupStepTests: XCTestCase {
    func testOrderIsTheFirstRunStory() {
        XCTAssertEqual(SetupStep.allCases, [.welcome, .about, .connect, .choices, .permissions, .hello])
        XCTAssertNil(SetupStep.welcome.previous)
        XCTAssertNil(SetupStep.hello.next)
        var s = SetupStep.welcome, seen = [s]
        while let n = s.next { s = n; seen.append(n) }
        XCTAssertEqual(seen, SetupStep.allCases)
        XCTAssertEqual(SetupStep.hello.number, SetupStep.allCases.count)
    }

    func testLimitsAndChoicesCannotBeSkipped() {
        XCTAssertFalse(SetupStep.about.skippable, "what Kaiku is not must be seen")
        XCTAssertFalse(SetupStep.choices.skippable)
        XCTAssertTrue(SetupStep.connect.skippable, "no service nearby must not block the app")
        XCTAssertTrue(SetupStep.permissions.skippable)
    }

    func testResumeSavedStepAndIgnoreStaleNumbers() {
        XCTAssertEqual(SetupStep.resume(saved: nil, launchArgument: nil), .welcome)
        XCTAssertEqual(SetupStep.resume(saved: 3, launchArgument: nil), .choices)
        XCTAssertEqual(SetupStep.resume(saved: 3, launchArgument: "1"), .about)
        XCTAssertEqual(SetupStep.resume(saved: 99, launchArgument: "x"), .welcome)
        XCTAssertEqual(SetupStep.resume(saved: -1, launchArgument: nil), .welcome)
    }

    func testEveryStepIsAParityScreen() {
        XCTAssertEqual(Set(SetupStep.allCases.map(\.screen)).count, SetupStep.allCases.count)
    }

    @MainActor func testSetupResumesAcrossLaunchesAndCanBeRunAgainWithoutLosingChoices() {
        let suite = UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(suite)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        func make() -> AppModel {
            AppModel(defaults: defaults, pairing: nil, api: APIClient(pairing: nil), queue: OfflineQueue(url: dir.appendingPathComponent("q.json")),
                     episodes: EpisodeOutbox(url: dir.appendingPathComponent("e.json")))
        }
        let first = make()
        XCTAssertFalse(first.onboarded)
        XCTAssertEqual(first.setupStep, SetupStep.welcome.rawValue)
        first.setupStep = SetupStep.permissions.rawValue
        first.consents[.transcripts] = true

        let second = make()   // the app was closed mid-setup
        XCTAssertEqual(second.setupStep, SetupStep.permissions.rawValue)
        XCTAssertEqual(second.consents[.transcripts], true)
        second.finishSetup()
        XCTAssertTrue(second.onboarded)
        XCTAssertEqual(second.selectedTab, .today)

        let third = make()
        XCTAssertTrue(third.onboarded)
        third.restartSetup()   // You → Run setup again
        XCTAssertFalse(third.onboarded)
        XCTAssertEqual(third.setupStep, SetupStep.welcome.rawValue)
        XCTAssertEqual(third.consents[.transcripts], true, "choices survive a re-run")
    }

    @MainActor func testCelebrationCountsEveryCompletion() {
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let app = AppModel(defaults: defaults, pairing: nil, api: APIClient(pairing: nil), queue: OfflineQueue(url: dir.appendingPathComponent("q.json")),
                           episodes: EpisodeOutbox(url: dir.appendingPathComponent("e.json")))
        let before = app.celebration
        app.celebrate(); app.celebrate()
        XCTAssertEqual(app.celebration, before + 2)
        XCTAssertEqual(app.ambientState, .happy)
    }

    func testSparksAreDeterministicAndStayInsideTheView() {
        let a = CelebrationSparks.sparks(seed: 42), b = CelebrationSparks.sparks(seed: 42)
        XCTAssertEqual(a.map(\.x), b.map(\.x))
        XCTAssertEqual(a.count, 18)
        for s in a {
            XCTAssertTrue((0.0...1.0).contains(s.x + s.drift) && (0.0...1.0).contains(s.x))
            XCTAssertLessThan(s.delay, 0.5)
            XCTAssertLessThan(s.rise, 0.78, "never leaves the top of the screen")
        }
    }
}

final class DayEvidenceTests: XCTestCase {
    private func event(_ type: String, source: String, payload: [String: JSONValue] = [:], sim: Bool? = nil) -> AnyEnvelope {
        let p = try! JSONEncoder().encode(JSONValue.object(payload))
        let simText = sim.map { ",\"sim\":\($0)" } ?? ""
        let json = "{\"v\":1,\"id\":\"\(UUID().uuidString)\",\"ts\":\"2026-11-14T10:00:00.000Z\",\"home_id\":\"h\",\"source\":\"\(source)\",\"type\":\"\(type)\",\"payload\":\(String(data: p, encoding: .utf8)!)\(simText)}"
        return try! JSONDecoder().decode(AnyEnvelope.self, from: Data(json.utf8))
    }

    func testEmptyDayClaimsNothing() {
        XCTAssertTrue(DayEvidence.build(events: [], talks: 0, transcriptsKept: false).items.isEmpty)
    }

    func testGlassesWalkSaysWhatWasMeasuredAndNeverThatGlassesSaw() {
        let e = DayEvidence.build(events: [
            event("obs.outing", source: "phone", payload: ["minutes": .number(24.4), "method": .string("dat_imu"), "steps": .number(2100)]),
        ], talks: 0, transcriptsKept: false)
        let walk = try! XCTUnwrap(e.items.first)
        XCTAssertEqual(walk.kind, .outing)
        XCTAssertEqual(walk.facts, ["24 min walking", "2100 steps"], "no daylight line without a reading")
        XCTAssertEqual(walk.sources, ["evidence.src.phone", "evidence.src.glasses"])
        XCTAssertEqual(walk.sharing, .numbers)
        let note = try! XCTUnwrap(walk.note).lowercased()
        XCTAssertTrue(note.contains("did not see"))
        for word in ["saw you", "watched", "looked at", "camera saw"] { XCTAssertFalse(note.contains(word)) }
    }

    func testPhoneOnlyWalkHasNoGlassesClaimAndDaylightOnlyWhenMeasured() {
        let e = DayEvidence.build(events: [
            event("obs.outing", source: "phone", payload: ["minutes": .number(10), "method": .string("steps"), "daylight_min": .number(6)]),
        ], talks: 0, transcriptsKept: false)
        XCTAssertEqual(e.items[0].sources, ["evidence.src.phone"])
        XCTAssertNil(e.items[0].note)
        XCTAssertEqual(e.items[0].facts, ["10 min walking", "6 min in daylight"])
    }

    func testEachKindNamesItsDevicesAndWhatIsShared() {
        let e = DayEvidence.build(events: [
            event("obs.self_report", source: "phone"), event("obs.self_report", source: "laptop"), event("obs.self_report", source: "hub"),
            event("obs.play_session", source: "laptop"),
            event("obs.wearable_daily", source: "phone"),
            event("obs.screen_activity", source: "laptop"),
            event("obs.safety_flag", source: "phone"),
        ], talks: 2, transcriptsKept: false)
        XCTAssertEqual(e.items.map(\.kind), [.checkin, .task, .talk, .health, .mac])
        XCTAssertEqual(e.items[0].facts, ["3 dial answers"])
        XCTAssertEqual(e.items[0].sources, ["evidence.src.phone", "evidence.src.laptop", "evidence.src.robot"])
        XCTAssertEqual(e.items[2].sharing, .wordsNotKept)
        XCTAssertEqual(DayEvidence.build(events: [], talks: 1, transcriptsKept: true).items[0].sharing, .wordsKept)
        XCTAssertFalse(e.items.contains { $0.facts.joined().lowercased().contains("safety") }, "a safety flag is never a list item")
    }

    func testPracticeRecordsAreLabelledOnlyWhenAllAreSimulated() {
        let sim = DayEvidence.build(events: [event("obs.play_session", source: "phone", sim: true)], talks: 0, transcriptsKept: false)
        XCTAssertTrue(sim.items[0].practice)
        let mixed = DayEvidence.build(events: [event("obs.play_session", source: "phone", sim: true), event("obs.play_session", source: "phone")],
                                      talks: 0, transcriptsKept: false)
        XCTAssertFalse(mixed.items[0].practice)
    }

    /// Wording rule (root AGENTS.md): nothing in the setup, evidence or completion copy uses clinical words.
    func testNewCopyHasNoClinicalWords() throws {
        let url = repoRoot.appendingPathComponent("apps/apple/KaikuKit/Sources/KaikuKit/Resources/copy.apple.json")
        let all = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
        let en = all["en"] as! [String: String]
        let banned = ["diagnos", "relapse", "predict", "disorder", "symptom", "depress", "patient"]
        for (k, v) in en where k.hasPrefix("setup.") || k.hasPrefix("evidence.") || k.hasPrefix("celebrate.") {
            for b in banned { XCTAssertFalse(v.lowercased().contains(b), "\(k) contains \(b)") }
        }
        XCTAssertGreaterThan(en.keys.filter { $0.hasPrefix("setup.") }.count, 30)
    }
}

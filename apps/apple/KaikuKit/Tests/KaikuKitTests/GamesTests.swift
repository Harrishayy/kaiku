import XCTest
@testable import KaikuKit

/// The measured games (Lantern, Seed shelf, Watering): trial generation, scoring, validity rules, rotation and
/// payload encoding against the generated schema.
final class MeasuredGamesTests: XCTestCase {
    var rng = SeededGenerator(seed: 42)

    // MARK: Lantern

    func testLanternPlanIsBalanced() {
        for seed in 1...20 {
            var r = SeededGenerator(seed: UInt64(seed))
            let plan = LanternEngine.makePlan(using: &r)
            XCTAssertEqual(plan.count, LanternEngine.practice + LanternEngine.scored)
            let scored = plan.dropFirst(LanternEngine.practice)
            // every wait is used equally often (± the jitter)
            for f in LanternEngine.foreperiods {
                XCTAssertEqual(scored.filter { abs($0 - f) <= LanternEngine.jitter + 1e-9 }.count,
                               LanternEngine.scored / LanternEngine.foreperiods.count)
            }
            XCTAssertTrue(plan.allSatisfy { $0 >= 1.3 - 1e-9 && $0 <= 4.2 + 1e-9 })
        }
        var a = SeededGenerator(seed: 1), b = SeededGenerator(seed: 2)
        XCTAssertNotEqual(LanternEngine.makePlan(using: &a), LanternEngine.makePlan(using: &b))
    }

    /// Plays a whole session: `answer(trialIndex)` gives the reaction in ms, nil = no answer, negative = tap early.
    func playLantern(_ answer: (Int) -> Double?) -> (LanternEngine, PlaySession) {
        var e = LanternEngine(using: &rng)
        var t = 100.0
        e.begin(at: t)
        while e.phase != .done {
            let i = e.index
            if let a = answer(i), a < 0 {
                t += 0.3; XCTAssertEqual(e.respond(at: t), .early)
            } else {
                t += e.plan[i] + 0.001; e.tick(at: t)
                XCTAssertEqual(e.phase, .lit)
                if let a = answer(i) { t += a / 1000; e.respond(at: t) }
                else { t += LanternEngine.timeout + 0.01; e.tick(at: t); XCTAssertEqual(e.last, .missed) }
            }
            XCTAssertEqual(e.respond(at: t + 0.01), .ignored)     // taps during the feedback are ignored
            t += LanternEngine.feedback + 0.02; e.tick(at: t)
        }
        return (e, e.session(device: .phone, input: .touch, at: t))
    }

    func testLanternScoring() {
        // practice (0–2) is not scored; scored trials: 300 ms, except one lapse, one miss, one early, one anticipation
        let p = LanternEngine.practice
        let (e, s) = playLantern { i in
            switch i - p {
            case 3: return 650
            case 5: return nil
            case 7: return -1
            case 9: return 40
            default: return i < p ? 900 : 300
            }
        }
        XCTAssertEqual(s.trials_n, 24)
        XCTAssertEqual(s.valid_n, 21)
        XCTAssertEqual(s.reaction_ms_median ?? 0, 300, accuracy: 1)
        XCTAssertEqual(s.lapses, 2)              // the slow one + the missed one
        XCTAssertEqual(s.false_starts, 2)        // early tap + faster than 100 ms
        XCTAssertEqual(e.stars, 21)
        XCTAssertEqual(s.rt_ms?.count, 24)
        XCTAssertEqual(s.trial_codes?.count, 24)
        let codes = Array(s.trial_codes ?? "")
        XCTAssertEqual(codes[3], "l"); XCTAssertEqual(codes[5], "m"); XCTAssertEqual(codes[7], "a"); XCTAssertEqual(codes[9], "a")
        XCTAssertEqual(s.rt_ms?[5], 0)
        // response speed = mean of 1000 / RT: twenty at 300 ms, one at 650 ms
        XCTAssertEqual(s.response_speed ?? 0, (20 * (1000.0 / 300) + 1000.0 / 650) / 21, accuracy: 0.01)
        XCTAssertGreaterThan(s.reaction_ms_cv ?? 0, 0)
        XCTAssertEqual(s.valid, true)
        XCTAssertNil(s.flags)
        XCTAssertEqual(s.input, .touch)
        XCTAssertEqual(e.trials.filter(\.practice).count, p)
    }

    func testLanternValidityRules() {
        let p = LanternEngine.practice
        var (_, s) = playLantern { i in (i - p) % 2 == 0 ? nil : 320 }           // half missed → too few
        XCTAssertEqual(s.valid, false); XCTAssertEqual(s.flags, [.few_trials])
        (_, s) = playLantern { i in (i - p) >= 0 && (i - p) < 7 ? -1 : 320 }     // seven early taps
        XCTAssertEqual(s.valid, false); XCTAssertEqual(s.flags, [.false_starts])
        XCTAssertEqual(GameHistory.quality(s), 0.2)
        var e = LanternEngine(using: &rng); e.interrupted = true
        XCTAssertTrue(e.flags.contains(.interrupted))
    }

    // MARK: Seed shelf

    func testSeedTrialsAreBalanced() {
        for seed in 1...20 {
            var r = SeededGenerator(seed: UInt64(seed))
            let e = SeedEngine(using: &r)
            XCTAssertEqual(e.key.sorted(), Array(1...9))                         // a permutation: one pot per seed
            for b in stride(from: 0, to: e.queue.count, by: 9) { XCTAssertEqual(e.queue[b..<b + 9].sorted(), Array(0..<9)) }
            XCTAssertFalse(zip(e.queue, e.queue.dropFirst()).contains { $0 == $1 }, "same seed twice in a row")
        }
        var a = SeededGenerator(seed: 1), b = SeededGenerator(seed: 2)
        XCTAssertNotEqual(SeedEngine(using: &a).key, SeedEngine(using: &b).key)
    }

    func testSeedScoringAndTimeLimit() {
        var e = SeedEngine(using: &rng)
        var t = 10.0
        e.begin(at: t)
        // practice: a wrong pot does not move on
        t += 1; XCTAssertEqual(e.pick(e.answer % 9 + 1, at: t), false); XCTAssertEqual(e.index, 0)
        for _ in 0..<SeedEngine.practice { t += 1; XCTAssertEqual(e.pick(e.answer, at: t), true) }
        XCTAssertEqual(e.phase, .scored)
        // 40 answers, 1.5 s each; every 10th is wrong
        for k in 0..<40 {
            t += 1.5
            XCTAssertEqual(e.pick(k % 10 == 9 ? e.answer % 9 + 1 : e.answer, at: t), k % 10 != 9)
        }
        XCTAssertFalse(e.tick(at: t + 1))
        t += 31; XCTAssertTrue(e.tick(at: t))                                    // 90 s after practice ended
        XCTAssertNil(e.pick(1, at: t + 1))
        let s = e.session(device: .mac, input: .keyboard)
        XCTAssertEqual(s.trials_n, 40); XCTAssertEqual(s.valid_n, 36)
        XCTAssertEqual(s.throughput_per_min ?? 0, 36 / 1.5, accuracy: 0.01)
        XCTAssertEqual(s.accuracy ?? 0, 0.9, accuracy: 0.001)
        XCTAssertEqual(s.reaction_ms_median ?? 0, 1500, accuracy: 1)
        XCTAssertEqual(s.trial_codes?.filter { $0 == "x" }.count, 4)
        XCTAssertEqual(s.valid, true)
        XCTAssertEqual(e.correct, 36)
    }

    func testSeedValidityRules() {
        func run(gap: Double, n: Int, wrongEvery: Int) -> PlaySession {
            var e = SeedEngine(using: &rng)
            var t = 0.0
            e.begin(at: t)
            for _ in 0..<SeedEngine.practice { t += 1; e.pick(e.answer, at: t) }
            for k in 0..<n { t += gap; e.pick(k % wrongEvery == 0 ? e.answer % 9 + 1 : e.answer, at: t) }
            e.tick(at: t + 100)
            return e.session(device: .phone, input: .touch)
        }
        XCTAssertEqual(run(gap: 2, n: 8, wrongEvery: 99).flags, [.few_trials])
        XCTAssertEqual(run(gap: 1.5, n: 30, wrongEvery: 2).flags, [.low_accuracy])
        XCTAssertTrue(run(gap: 0.15, n: 100, wrongEvery: 2).flags?.contains(.too_fast) ?? false)   // mashing the pots
        XCTAssertEqual(run(gap: 0.5, n: 150, wrongEvery: 99).rt_ms?.count, SeedEngine.maxSent)       // capped for the payload
    }

    // MARK: Watering

    func testWateringOffersAreCrossedAndBalanced() {
        for seed in 1...20 {
            var r = SeededGenerator(seed: UInt64(seed))
            var e = WateringEngine(using: &r)
            e.begin(at: 0)
            for k in 0..<WateringEngine.calibrationTaps { e.tap(at: Double(k) * 0.25) }      // 4 taps a second
            XCTAssertEqual(e.phase, .choose)
            XCTAssertEqual(e.rate, 4, accuracy: 0.01)
            XCTAssertEqual(e.offers.count, 8)
            for reward in WateringEngine.rewards {
                XCTAssertEqual(Set(e.offers.filter { $0.reward == reward }.map(\.long)), [true, false])
            }
            XCTAssertEqual(e.offers.filter(\.hardOnLeft).count, 4)
            XCTAssertEqual(Set(e.offers.map(\.hardTaps)), [10, 20])                          // 2.5 s and 5 s at this pace
        }
        XCTAssertEqual(WateringEngine.hardTaps(rate: 1, long: false), 8)                     // floors for a slow pace
        XCTAssertEqual(WateringEngine.hardTaps(rate: 12, long: true), 40)                    // caps for a fast one
    }

    func testWateringScoring() {
        var e = WateringEngine(using: &rng)
        var t = 0.0
        e.begin(at: t)
        for _ in 0..<WateringEngine.calibrationTaps { t += 0.2; e.tap(at: t) }
        var expected = 0
        for round in 0..<WateringEngine.rounds {
            XCTAssertEqual(e.phase, .choose)
            let o = e.offer!
            let hard = round < 6                       // six hard, two easy
            t += 1.2; e.choose(hard: hard, at: t)
            XCTAssertEqual(e.need, hard ? o.hardTaps : WateringEngine.easyTaps)
            if round == 0 {
                e.tap(at: t + 0.2)                     // gives up: the deadline passes, one flower all the same
                t += 60; XCTAssertTrue(e.tick(at: t)); expected += 1
            } else {
                for _ in 0..<e.need { t += 0.2; e.tap(at: t) }
                expected += hard ? o.reward : 1
            }
            XCTAssertEqual(e.phase, .bloom)
            t += WateringEngine.bloom + 0.01; e.tick(at: t)
        }
        XCTAssertEqual(e.phase, .done)
        XCTAssertEqual(e.flowers, expected)
        let s = e.session(device: .phone, input: .touch, at: t)
        XCTAssertEqual(s.hard_choice_ratio ?? 0, 0.75, accuracy: 0.001)
        XCTAssertEqual(s.tap_rate_hz ?? 0, 5, accuracy: 0.05)
        XCTAssertEqual(s.trials_n, 8); XCTAssertEqual(s.valid_n, 7)
        XCTAssertEqual(s.trial_codes, "hHHHHHEE")
        XCTAssertEqual(s.rt_ms, Array(repeating: 1200, count: 8))
        XCTAssertEqual(s.valid, true)
    }

    func testWateringTooFastChoicesAreDoubtful() {
        var e = WateringEngine(using: &rng)
        var t = 0.0
        e.begin(at: t)
        for _ in 0..<WateringEngine.calibrationTaps { t += 0.2; e.tap(at: t) }
        for _ in 0..<WateringEngine.rounds {
            t += 0.1; e.choose(hard: false, at: t)
            for _ in 0..<e.need { t += 0.2; e.tap(at: t) }
            t += 1; e.tick(at: t)
        }
        XCTAssertEqual(e.session(device: .mac, input: .keyboard, at: t).flags, [.too_fast])
    }

    // MARK: shared

    func testStatsAndInput() {
        XCTAssertEqual(GameStats.sd([2, 4, 4, 4, 5, 5, 7, 9]) ?? 0, 2.138, accuracy: 0.001)
        XCTAssertEqual(GameStats.cv([100, 100, 100]), 0)
        XCTAssertNil(GameStats.cv([300]))
        var i = InputTracker()
        XCTAssertNil(i.value)
        i.note(.pointer); XCTAssertEqual(i.value, .pointer)
        i.note(.keyboard); XCTAssertEqual(i.value, .mixed)
    }

    func testWarmupSessionsAndQuality() {
        let d = UserDefaults(suiteName: "kaiku.test.games.\(UUID().uuidString)")!
        var s = PlaySession(game: .lantern, device: .phone, duration_s: 90)
        s.valid = true; s.trials_n = 24; s.valid_n = 22
        for n in 1...5 {
            let out = GameHistory.stamp(s, defaults: d)
            XCTAssertEqual(out.session_index, n)
            XCTAssertEqual(out.warmup, n <= GameHistory.warmupSessions)
        }
        // a doubtful session does not use up a session number
        var bad = s; bad.valid = false
        XCTAssertEqual(GameHistory.stamp(bad, defaults: d).session_index, 6)
        XCTAssertEqual(GameHistory.stamp(s, defaults: d).session_index, 6)
        XCTAssertEqual(GameHistory.count(.seeds, defaults: d), 0)                  // counted per game
        XCTAssertEqual(GameHistory.quality(s), 0.92)
        XCTAssertEqual(GameHistory.quality(bad), 0.2)
    }

    func testRotationKeepsTheDayShort() {
        var seen = Set<PlayGame>()
        for day in 1...366 {
            let g = GameRotation.rotating(dayOfYear: day)
            seen.insert(g)
            XCTAssertNotEqual(g, GameRotation.rotating(dayOfYear: day + 1))
            let total = GameRotation.seconds(GameRotation.anchor) + GameRotation.seconds(g)
            XCTAssertTrue((170...300).contains(total), "games take \(total) s")   // about 3–5 minutes
        }
        XCTAssertEqual(seen, Set(GameRotation.cycle))
        XCTAssertEqual(GameRotation.today().first, .lantern)
        XCTAssertTrue(GameRotation.cycle.allSatisfy(GameHistory.measured.contains))
    }

    func testTrialLogKeepsRawTrialsLocally() async {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("kaiku-trials-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        let log = GameTrialLog(url: url)
        let trial = GameTrial(code: "h", rt_ms: 312, detail: ["foreperiod_s": 2.5])
        for _ in 0..<(GameTrialLog.maxSessions + 5) { await log.append(game: .lantern, input: .touch, trials: [trial]) }
        let again = await GameTrialLog(url: url).entries()
        XCTAssertEqual(again.count, GameTrialLog.maxSessions)
        XCTAssertEqual(again.last?.trials, [trial])
        XCTAssertEqual(again.last?.game, "lantern")
    }

    // MARK: payloads

    func testPayloadsMatchSchemaAndEnums() throws {
        let schema = try json("contracts/schemas/obs/play_session.schema.json") as! [String: Any]
        let def = (schema["$defs"] as! [String: Any])["PlaySession"] as! [String: Any]
        let props = def["properties"] as! [String: Any]
        let (_, lantern) = playLantern { _ in 310 }
        var seeds = SeedEngine(using: &rng); seeds.begin(at: 0)
        var water = WateringEngine(using: &rng); water.begin(at: 0)
        let d = UserDefaults(suiteName: "kaiku.test.games.\(UUID().uuidString)")!
        for s in [lantern, seeds.session(device: .mac, input: .keyboard), water.session(device: .phone, input: nil, at: 1)] {
            let stamped = GameHistory.stamp(s, defaults: d)
            let body = try JSONSerialization.jsonObject(with: JSONEncoder().encode(stamped)) as! [String: Any]
            XCTAssertTrue(Set(body.keys).isSubset(of: Set(props.keys)), "extra \(Set(body.keys).subtracting(props.keys))")
            XCTAssertNotNil(body["session_index"]); XCTAssertNotNil(body["warmup"]); XCTAssertNotNil(body["valid"])
        }
        func enumOf(_ name: String) -> Set<String> {
            func find(_ any: Any) -> [String]? {
                if let d = any as? [String: Any] {
                    if let e = d["enum"] as? [String] { return e }
                    for v in d.values { if let e = find(v) { return e } }
                } else if let a = any as? [Any] {
                    for v in a { if let e = find(v) { return e } }
                }
                return nil
            }
            return Set(find(props[name]!) ?? [])
        }
        XCTAssertEqual(enumOf("flags"), Set(PlayFlag.allCases.map(\.rawValue)))
        XCTAssertEqual(enumOf("input"), ["touch", "pointer", "keyboard", "mixed"])
        // the envelope carries the quality the criteria read
        let env = Envelope(home_id: "demo-aino", source: .phone, type: "obs.play_session", payload: lantern, quality: 0.92)
        let any = try JSONSerialization.jsonObject(with: JSONEncoder().encode(AnyEnvelope(env))) as! [String: Any]
        XCTAssertEqual(any["quality"] as? Double, 0.92)
        let plain = Envelope(home_id: "demo-aino", source: .phone, type: "obs.play_session", payload: lantern)
        let none = try JSONSerialization.jsonObject(with: JSONEncoder().encode(AnyEnvelope(plain))) as! [String: Any]
        XCTAssertNil(none["quality"])
    }
}

/// A small deterministic generator for tests (the games themselves use the system generator: no fixed seed).
struct SeededGenerator: RandomNumberGenerator {
    var state: UInt64
    init(seed: UInt64) { state = seed &* 0x9E3779B97F4A7C15 &+ 1 }
    mutating func next() -> UInt64 {
        state &+= 0x9E3779B97F4A7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }
}

import Foundation
import XCTest
@testable import KaikuKit

/// Repo root from this file: apps/apple/KaikuKit/Tests/KaikuKitTests/<file> → five levels up.
let repoRoot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
let kitSources = repoRoot.appendingPathComponent("apps/apple/KaikuKit/Sources/KaikuKit")

func json(_ rel: String) throws -> Any {
    try JSONSerialization.jsonObject(with: Data(contentsOf: repoRoot.appendingPathComponent(rel)))
}

final class SafetyGateTests: XCTestCase {
    /// Same results as the Python matcher (kaiku_contracts.safety) on the shared fixture.
    func testSharedFixture() throws {
        let fx = try json("tools/companion_evals/fixtures/safety_cases.json") as! [String: Any]
        let cases = fx["cases"] as! [[String: Any]]
        XCTAssertGreaterThan(cases.count, 10)
        for c in cases {
            let text = c["text"] as! String
            let hit = SafetyGate.shared.check(text)
            if let want = c["hit"] as? [String: String] {
                XCTAssertEqual(hit, SafetyHit(phrase: want["phrase"]!, language: want["language"]!), "case: \(text)")
            } else {
                XCTAssertNil(hit, "false hit on: \(text) -> \(String(describing: hit))")
            }
        }
    }

    func testEveryPhraseHitsItself() throws {
        let toml = try String(contentsOf: repoRoot.appendingPathComponent("config/safety_phrases.toml"), encoding: .utf8)
        let parsed = MiniTOML.parse(toml)
        var n = 0
        for (section, table) in parsed where section != "script" {
            for (_, v) in table { if case .array(let items) = v { for p in items { n += 1; XCTAssertNotNil(SafetyGate.shared.check("so \(p) now"), p) } } }
        }
        XCTAssertEqual(n, SafetyGate.shared.phraseCount)
        XCTAssertGreaterThan(n, 20)
    }

    func testScriptsAreVerbatim() throws {
        XCTAssertTrue(SafetyGate.shared.script("en").contains("09 2525 0111"))
        XCTAssertTrue(SafetyGate.shared.script("fi").contains("112"))
        XCTAssertEqual(SafetyGate.shared.script("sv"), SafetyGate.shared.script("en"))   // no sv script yet → en
    }

    func testNormalise() {
        XCTAssertEqual(SafetyGate.normalise("  I’m NOT—ok!! "), "i'm not ok")
        XCTAssertEqual(SafetyGate.normalise("self-harm"), "self harm")
    }
}

final class SyncFreshnessTests: XCTestCase {
    /// KaikuKit carries plain copies of design/ + config/ files; scripts/sync_design.sh refreshes them.
    func testCopiesMatchGroundTruth() throws {
        let pairs = [
            ("design/generated/Tokens.swift", "Design/Tokens.swift"),
            ("design/copy.json", "Resources/copy.json"),
            ("design/mascot.spec.json", "Resources/mascot.spec.json"),
            ("config/safety_phrases.toml", "Resources/safety_phrases.toml"),
        ]
        for (truth, copy) in pairs {
            let a = try Data(contentsOf: repoRoot.appendingPathComponent(truth))
            let b = try Data(contentsOf: kitSources.appendingPathComponent(copy))
            XCTAssertEqual(a, b, "\(copy) is stale: run apps/apple/scripts/sync_design.sh")
        }
    }
}

final class L10nTests: XCTestCase {
    func testOverlayHasSameKeysAndPlaceholders() throws {
        let o = try json("apps/apple/KaikuKit/Sources/KaikuKit/Resources/copy.apple.json") as! [String: Any]
        let en = o["en"] as! [String: String], fi = o["fi"] as! [String: String]
        XCTAssertEqual(Set(en.keys), Set(fi.keys))
        let ph = try NSRegularExpression(pattern: "\\{\\w+\\}")
        func places(_ s: String) -> Set<String> {
            Set(ph.matches(in: s, range: NSRange(s.startIndex..., in: s)).map { String(s[Range($0.range, in: s)!]) })
        }
        for (k, v) in en { XCTAssertEqual(places(v), places(fi[k]!), k) }
        // Overlay never shadows design/copy.json (upstreamed keys must be deleted here).
        let base = try json("design/copy.json") as! [String: Any]
        let baseEn = base["en"] as! [String: String]
        XCTAssertTrue(Set(en.keys).isDisjoint(with: baseEn.keys), "overlay duplicates copy.json keys")
    }

    /// Every literal T("key") in the app exists in en and fi.
    func testEveryUsedKeyExists() throws {
        let re = try NSRegularExpression(pattern: "T\\(\"([a-z0-9_.]+)\"")
        var used = Set<String>()
        let e = FileManager.default.enumerator(at: kitSources, includingPropertiesForKeys: nil)!
        for case let url as URL in e where url.pathExtension == "swift" {
            let s = try String(contentsOf: url, encoding: .utf8)
            for m in re.matches(in: s, range: NSRange(s.startIndex..., in: s)) { used.insert(String(s[Range(m.range(at: 1), in: s)!])) }
        }
        XCTAssertGreaterThan(used.count, 80)
        for k in used {
            XCTAssertTrue(L10n.shared.has(k, .en), "missing en: \(k)")
            XCTAssertTrue(L10n.shared.has(k, .fi), "missing fi: \(k)")
        }
        // Interpolated families.
        for item in DialItem.allCases {
            for v in 1...5 { XCTAssertTrue(L10n.shared.has("wx.\(item.rawValue).\(v)", .fi)) }
        }
        for arm in NudgeArm.allCases { XCTAssertTrue(L10n.shared.has("today.suggest.\(arm.rawValue)", .fi), arm.rawValue) }
        for tab in KaikuTab.allCases { XCTAssertTrue(L10n.shared.has("tab.\(tab.rawValue)", .fi)) }
        for s in Signal.allCases { XCTAssertTrue(L10n.shared.has("sig.\(s.rawValue).t", .fi)) }
        for p in ["morning", "afternoon", "evening", "late"] {
            XCTAssertTrue(L10n.shared.has("today.greet.\(p)", .fi)); XCTAssertTrue(L10n.shared.has("today.greet.\(p).noname", .fi))
        }
    }

    func testPlaceholders() {
        XCTAssertEqual(L10n.shared.string("br.count", ["n": "3"], lang: .en), "Breath 3 of 6")
        XCTAssertTrue(L10n.shared.string("today.greet.morning", ["name": "Annemarie-Kristiina"], lang: .fi).contains("Annemarie-Kristiina"))
    }
}

final class ContractTests: XCTestCase {
    func schemaProps(_ obs: String) throws -> (Set<String>, Set<String>) {
        let s = try json("contracts/schemas/obs/\(obs).schema.json") as! [String: Any]
        let defs = s["$defs"] as! [String: Any]
        let d = defs.values.first as! [String: Any]
        return (Set((d["properties"] as! [String: Any]).keys), Set(d["required"] as? [String] ?? []))
    }

    func encoded<P: Codable>(_ p: P) throws -> [String: Any] {
        try JSONSerialization.jsonObject(with: JSONEncoder().encode(p)) as! [String: Any]
    }

    func testPayloadsMatchSchemas() throws {
        var play = PlaySession(game: .pebbles, device: .phone, duration_s: 61)
        play.span_max = 5; play.accuracy = 0.8
        var fire = PlaySession(game: .firefly, device: .mac, duration_s: 60)
        fire.reaction_ms_median = 420; fire.reaction_ms_iqr = 80; fire.lapses = 2; fire.false_taps = 1
        let samples: [(String, [String: Any])] = [
            ("self_report", try encoded(SelfReport(item: .mood, value: 4, channel: .phone))),
            ("play_session", try encoded(play)),
            ("play_session", try encoded(fire)),
            ("safety_flag", try encoded(SafetyFlag(trigger: "manual", handled_locally: true))),
        ]
        for (obs, body) in samples {
            let (props, req) = try schemaProps(obs)
            XCTAssertTrue(Set(body.keys).isSubset(of: props), "\(obs): extra \(Set(body.keys).subtracting(props))")
            XCTAssertTrue(req.isSubset(of: Set(body.keys)), "\(obs): missing \(req.subtracting(body.keys))")
        }
    }

    func testEnvelope() throws {
        let e = Envelope(home_id: "demo-aino", source: .phone, type: "obs.self_report",
                         payload: SelfReport(item: .sleep, value: 2, channel: .phone))
        let a = try AnyEnvelope(e)
        let body = try encoded(a)
        let s = try json("contracts/schemas/envelope.schema.json") as! [String: Any]
        let props = Set((s["properties"] as! [String: Any]).keys)
        XCTAssertTrue(Set(body.keys).isSubset(of: props))
        XCTAssertEqual(body["v"] as? Int, 1)
        XCTAssertTrue((body["ts"] as! String).hasSuffix("Z"))
        XCTAssertNotNil(UUID(uuidString: a.id))
    }

    func testEnumsMatchSchemas() throws {
        let s = try json("contracts/schemas/obs/play_session.schema.json") as! [String: Any]
        let d = (s["$defs"] as! [String: Any]).values.first as! [String: Any]
        let props = d["properties"] as! [String: Any]
        XCTAssertEqual(Set((props["game"] as! [String: Any])["enum"] as! [String]), Set(PlayGame.allCases.map(\.rawValue)))
        let api = try json("contracts/schemas/api/NudgeResponse.schema.json") as! [String: Any]
        let arm = (api["properties"] as! [String: Any])["arm"] as! [String: Any]
        XCTAssertEqual(Set(arm["enum"] as! [String]), Set(NudgeArm.allCases.map(\.rawValue)))
    }

    func testDeviceToolsMatchRegistry() throws {
        let reg = try json("contracts/schemas/companion_tools.json") as! [String: Any]
        let tools = reg["tools"] as! [String: [String: Any]]
        let device = Set(tools.filter { $0.value["executor"] as? String == "device" }.keys)
        XCTAssertEqual(device, ToolExecutor.deviceTools)
    }

    func testDecodesMeExample() throws {
        let ex = try json("contracts/schemas/examples.json") as! [String: Any]
        // examples.json holds obs examples; build a MeResponse the way the cloud serialises one.
        XCTAssertFalse(ex.isEmpty)
        let me = """
        {"home_id":"demo-aino","summary":"x","last_week":[],"what_helps":[],"next_suggestion":{"arm":"breathe","reason":"r","probs":{"breathe":0.5}},
         "phq9_due":false,"mascot":{"mood":"cozy","line_key":null},"highlights":[{"date":"2026-11-12","kind":"good","text":"t","source":"robot"}],
         "garden":{"plants":9,"resting":false},"sim":true}
        """
        let m = try JSONDecoder().decode(MeResponse.self, from: Data(me.utf8))
        XCTAssertEqual(MascotState(mood: m.mascot?.mood), .cozy)
        XCTAssertEqual(m.garden?.plants, 9)
    }
}

final class UUID7Tests: XCTestCase {
    func testVersionVariantAndTime() {
        let now = Date()
        let id = UUID7.make(now)
        let hex = id.replacingOccurrences(of: "-", with: "")
        XCTAssertEqual(Array(hex)[12], "7")
        XCTAssertTrue("89ab".contains(Array(hex)[16]))
        XCTAssertEqual(UUID7.date(of: id)!.timeIntervalSince1970, now.timeIntervalSince1970, accuracy: 0.002)
        XCTAssertNotEqual(UUID7.make(now), UUID7.make(now))
        XCTAssertLessThan(UUID7.make(now), UUID7.make(now.addingTimeInterval(1)))
    }
}

final class PairingTests: XCTestCase {
    func testParse() {
        let p = Pairing.parse("https://kaiku.example/me/?home=demo-aino&t=abc123")
        XCTAssertEqual(p, Pairing(baseURL: URL(string: "https://kaiku.example")!, homeID: "demo-aino", token: "abc123"))
        XCTAssertEqual(Pairing.parse("http://127.0.0.1:8000/?home=demo-aino")?.baseURL.absoluteString, "http://127.0.0.1:8000")
        XCTAssertNil(Pairing.parse("http://127.0.0.1:8000/?home=demo-aino")?.token)
        XCTAssertEqual(Pairing.parse("kaiku://pair?home=h1&t=x&cloud=https://c.example")?.baseURL.host, "c.example")
        XCTAssertNil(Pairing.parse("https://kaiku.example/"))
        XCTAssertNil(Pairing.parse("https://kaiku.example/?home=Bad%20Id"))
        XCTAssertNil(Pairing.parse("ftp://x/?home=a"))
        XCTAssertNil(Pairing.parse("hello"))
    }
}

final class GameLogicTests: XCTestCase {
    func testPebblesGrowAndEndAfterTwoMisses() {
        var e = PebbleEngine()
        var rng = SystemRandomNumberGenerator()
        e.newRound(using: &rng)
        XCTAssertEqual(e.sequence.count, 2)
        for p in e.sequence { _ = e.tap(p) }
        XCTAssertEqual(e.spanMax, 2)
        XCTAssertEqual(e.length, 3)
        e.newRound(using: &rng)
        let wrong = (0..<9).first { $0 != e.sequence[0] }!
        XCTAssertEqual(e.tap(wrong), .miss)
        XCTAssertFalse(e.over)
        e.newRound(using: &rng)
        XCTAssertEqual(e.sequence.count, 3)   // a miss repeats the same length
        _ = e.tap((0..<9).first { $0 != e.sequence[0] }!)
        XCTAssertTrue(e.over)
        XCTAssertEqual(e.accuracy, 2.0 / 4.0, accuracy: 1e-9)
    }

    func testPebblesStopAtNine() {
        var e = PebbleEngine()
        var rng = SystemRandomNumberGenerator()
        while !e.over { e.newRound(using: &rng); for p in e.sequence { _ = e.tap(p) } }
        XCTAssertEqual(e.spanMax, 9)
        XCTAssertEqual(e.accuracy, 1)
    }

    @MainActor func testFireflyScoring() {
        let f = FireflyEngine()
        let t0 = Date()
        f.start(t0)
        f.items = [.init(moth: false, pos: .zero, born: t0, drift: .zero), .init(moth: true, pos: .zero, born: t0, drift: .zero),
                   .init(moth: false, pos: .zero, born: t0, drift: .zero)]
        f.tap(f.items[0].id, at: t0.addingTimeInterval(0.4))
        f.tap(f.items[0].id, at: t0.addingTimeInterval(0.5))   // the moth
        f.tick(t0.addingTimeInterval(1.6))                     // last firefly expires untapped → lapse
        let s = f.session(device: .phone)
        XCTAssertEqual(s.false_taps, 1)
        XCTAssertEqual(s.lapses, 1)
        XCTAssertEqual(s.reaction_ms_median!, 400, accuracy: 1)
        XCTAssertEqual(f.caught, 1)
    }

    func testStats() {
        XCTAssertEqual(Stats.median([3, 1, 2]), 2)
        XCTAssertEqual(Stats.median([1, 2, 3, 4]), 2.5)
        XCTAssertEqual(Stats.iqr([1, 2, 3, 4, 5])!, 2, accuracy: 1e-9)
        XCTAssertNil(Stats.median([]))
    }

    func testSpeechFeatures() {
        // 0.5 s silence, then 3 s of "speech" with 6 bumps (syllables) and a 1 s pause in the middle, then silence.
        var f: [Float] = Array(repeating: -70, count: 25)
        func talk(_ seconds: Double, bumps: Int) {
            let n = Int(seconds / 0.02)
            for i in 0..<n {
                let phase = Double(i) / Double(n) * Double(bumps) * 2 * .pi
                f.append(-30 + Float(8 * sin(phase - .pi / 2)))
            }
        }
        talk(1.5, bumps: 3)
        f += Array(repeating: -70, count: 50)
        talk(1.5, bumps: 3)
        f += Array(repeating: -70, count: 25)
        let r = SpeechFeatures.compute(frameDB: f)
        XCTAssertNotNil(r.speechRate)
        XCTAssertEqual(r.speechRate!, 6.0 / 4.0, accuracy: 0.6)
        XCTAssertEqual(r.pauseRatio!, 0.25, accuracy: 0.1)
        XCTAssertNil(SpeechFeatures.compute(frameDB: Array(repeating: -70, count: 200)).speechRate)
    }
}

final class MascotTests: XCTestCase {
    func testSpecLoadsEveryState() {
        let spec = MascotSpec.shared
        for s in MascotState.allCases { XCTAssertNotNil(spec.states[s.rawValue], s.rawValue) }
        XCTAssertEqual(spec.earAngle(forDial: 1), -32)
        XCTAssertEqual(spec.earAngle(forDial: 5), 32)
        XCTAssertEqual(spec.earAngle(forDial: 3), 0)
        XCTAssertEqual(spec.blinkParts, ["lid-l", "lid-r"])
        XCTAssertEqual(spec.blinkModes["normal"]!.interval, 3...7)
        XCTAssertEqual(spec.ambient["watch"], "cozy")
        func ids(_ p: MascotSpec.Part) -> [String] { [p.id] + p.children.flatMap(ids) }
        let all = Set(ids(spec.root))
        for id in ["body", "shadow", "eye-l", "eye-r", "lid-l", "lid-r", "ear", "glow", "mouth-happy", "mouth-yawn", "scarf", "z"] {
            XCTAssertTrue(all.contains(id), id)
        }
    }

    func testEasingsAndGlow() {
        XCTAssertEqual(KaikuCurve.ease("soft-in-out", 0), 0)
        XCTAssertEqual(KaikuCurve.ease("soft-in-out", 1), 1)
        // cubic-bezier(.45,0,.25,1) at x=0.5 ≈ 0.73 (same as CSS); monotonic
        XCTAssertEqual(KaikuCurve.ease("soft-in-out", 0.5), 0.729, accuracy: 0.01)
        XCTAssertLessThan(KaikuCurve.ease("soft-in-out", 0.3), KaikuCurve.ease("soft-in-out", 0.31))
        XCTAssertGreaterThan(KaikuCurve.ease("overshoot", 0.7), 1)   // springy
        XCTAssertEqual(GlowClock.at(hour: 12).1, 0.9, accuracy: 1e-9)
        XCTAssertEqual(GlowClock.at(hour: 2).1, 0.45, accuracy: 1e-9)
        XCTAssertEqual(GlowClock.at(hour: 23).1, 0.55 - (0.55 - 0.45) / 2 * 1, accuracy: 0.06)
    }

    func testMoodMapping() {
        XCTAssertEqual(MascotState(mood: .cozy), .cozy)
        XCTAssertEqual(MascotState(mood: .idle), .idle)
        XCTAssertEqual(MascotState(mood: nil), .idle)
    }
}

/// Offline queue over a stub URLProtocol: persisted, sent once accepted, kept when the cloud is away.
final class StubProtocol: URLProtocol {
    nonisolated(unsafe) static var status = 200
    nonisolated(unsafe) static var fail = false
    nonisolated(unsafe) static var bodies: [Data] = []
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        if Self.fail { client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)); return }
        if let s = request.httpBodyStream {
            s.open(); var d = Data(); var buf = [UInt8](repeating: 0, count: 4096)
            while s.hasBytesAvailable { let n = s.read(&buf, maxLength: 4096); if n <= 0 { break }; d.append(buf, count: n) }
            Self.bodies.append(d)
        }
        let r = HTTPURLResponse(url: request.url!, statusCode: Self.status, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: r, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(#"{"accepted":1,"duplicates":0,"rejected":[]}"#.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

final class OfflineQueueTests: XCTestCase {
    func testQueuePersistsAndFlushes() async throws {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [StubProtocol.self]
        let api = APIClient(pairing: Pairing(baseURL: URL(string: "http://stub")!, homeID: "demo-aino", token: "t"),
                            maxAttempts: 2, baseDelay: 0.01, session: URLSession(configuration: cfg))
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("outbox-\(UUID()).json")
        let q = OfflineQueue(url: url)
        let e = try AnyEnvelope(Envelope(home_id: "demo-aino", source: .phone, type: "obs.self_report",
                                         payload: SelfReport(item: .mood, value: 4, channel: .phone)))
        await q.enqueue(e)
        await q.enqueue(e)   // same id → once
        StubProtocol.fail = true
        let ok1 = await q.flush(using: api)
        XCTAssertFalse(ok1)
        let n1 = await q.count
        XCTAssertEqual(n1, 1)
        // survives a restart
        let q2 = OfflineQueue(url: url)
        let n2 = await q2.count
        XCTAssertEqual(n2, 1)
        StubProtocol.fail = false
        StubProtocol.bodies = []
        let ok2 = await q2.flush(using: api)
        XCTAssertTrue(ok2)
        let n3 = await q2.count
        XCTAssertEqual(n3, 0)
        let sent = try JSONSerialization.jsonObject(with: StubProtocol.bodies.last ?? Data("{}".utf8)) as? [String: Any]
        XCTAssertEqual(((sent?["events"] as? [[String: Any]])?.first?["id"] as? String), e.id)
    }
}

final class ParityTests: XCTestCase {
    /// Every screen in the parity list is either on both platforms or documented as platform-only in AGENTS.md.
    func testParityTableListsEveryScreen() throws {
        let doc = try String(contentsOf: repoRoot.appendingPathComponent("apps/apple/AGENTS.md"), encoding: .utf8)
        for s in KaikuScreen.allCases { XCTAssertTrue(doc.contains("`\(s.rawValue)`"), "AGENTS.md parity table misses \(s.rawValue)") }
    }
}

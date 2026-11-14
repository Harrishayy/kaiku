@preconcurrency import AVFoundation
import XCTest
@testable import KaikuKit

// The walk companion's device rules: the style the person chose, the spotting goal's count and tool results, and
// when the walk nudges Kaiku. No microphone, camera or glasses: the pure types are tested directly, and the walk
// itself runs on a fake microphone, a fake Live socket and a stubbed service.

final class WalkStyleTests: XCTestCase {
    func testStylesAreTheRegistrysAndCalmIsTheDefault() throws {
        let reg = try json("contracts/schemas/companion_tools.json") as! [String: Any]
        XCTAssertEqual(Set(reg["walk_styles"] as! [String]), Set(WalkStyle.allCases.map(\.rawValue)))
        let defaults = UserDefaults(suiteName: "walk-style-" + UUID().uuidString)!
        XCTAssertEqual(WalkStyle.stored(defaults), .quiet, "nothing chosen yet: Calm")
        WalkStyle.chatty.store(defaults)
        XCTAssertEqual(WalkStyle.stored(defaults), .chatty)
        defaults.set("loud", forKey: WalkStyle.defaultsKey)
        XCTAssertEqual(WalkStyle.stored(defaults), .quiet, "an unknown stored value falls back to Calm")
    }

    func testEveryStyleHasItsWordAndOneShortLine() {
        for style in WalkStyle.allCases {
            for lang in [KaikuLanguage.en, .fi] {
                XCTAssertTrue(L10n.shared.has(style.titleKey, lang), style.titleKey)
                XCTAssertTrue(L10n.shared.has(style.lineKey, lang), style.lineKey)
            }
            let line = L10n.shared.string(style.lineKey, lang: .en)
            XCTAssertLessThanOrEqual(line.count, 80, "one short line, not a paragraph: \(line)")
            XCTAssertLessThanOrEqual(L10n.shared.string(style.titleKey, lang: .en).count, 8)
        }
    }

    func testStyleIsSentOnlyWhenSetAndTheGuideDecodes() throws {
        var req = CompanionSessionRequest(surface: .glasses, home_id: "h", intent: .walk, language: "en")
        req.purpose = .walk
        var body = try JSONSerialization.jsonObject(with: JSONEncoder().encode(req)) as! [String: Any]
        XCTAssertNil(body["walk_style"], "omitted when nil: an older service still accepts the request")
        req.walk_style = .playful
        body = try JSONSerialization.jsonObject(with: JSONEncoder().encode(req)) as! [String: Any]
        XCTAssertEqual(body["walk_style"] as? String, "playful")
        XCTAssertEqual(body["purpose"] as? String, "walk")
        let schema = try json("contracts/schemas/api/CompanionSessionRequest.schema.json") as! [String: Any]
        XCTAssertTrue(Set(body.keys).isSubset(of: Set((schema["properties"] as! [String: Any]).keys)))

        let guide = try JSONDecoder().decode(WalkGuide.self, from: Data(
            #"{"style":"quiet","look_every_s":30,"look_prompt":"A look around.","quiet_after_s":null,"quiet_prompt":null}"#.utf8))
        XCTAssertEqual(guide, WalkGuide(style: .quiet, look_every_s: 30, look_prompt: "A look around."))
        let unknown = try JSONDecoder().decode(WalkGuide.self, from: Data(#"{"style":"brisk","look_every_s":12}"#.utf8))
        XCTAssertEqual(unknown.style, .quiet, "a style this build does not know must not stop the walk's voice")
        XCTAssertEqual(unknown.look_every_s, 12)
        let fields = Set(((try json("contracts/schemas/api/WalkGuide.schema.json") as! [String: Any])["properties"] as! [String: Any]).keys)
        XCTAssertEqual(fields, ["style", "look_every_s", "look_prompt", "quiet_after_s", "quiet_prompt"])
    }
}

final class WalkGoalTests: XCTestCase {
    private func props(_ name: String) throws -> (all: Set<String>, required: Set<String>) {
        let s = try json("contracts/schemas/api/\(name).schema.json") as! [String: Any]
        return (Set((s["properties"] as! [String: Any]).keys), Set(s["required"] as? [String] ?? []))
    }

    func testCountsToTheTargetAndNeverPastIt() throws {
        var g = try XCTUnwrap(WalkGoal(thing: "trees", target: 3))
        XCTAssertEqual([g.found, g.left], [0, 3]); XCTAssertFalse(g.done)
        XCTAssertTrue(g.find())
        XCTAssertEqual([g.found, g.left], [1, 2])
        XCTAssertEqual(g.contextLine, "[spotting game · trees · 1 of 3 found · 2 left]")
        XCTAssertTrue(g.find()); XCTAssertTrue(g.find())
        XCTAssertTrue(g.done); XCTAssertEqual(g.left, 0)
        XCTAssertEqual(g.contextLine, "[spotting game · trees · all 3 found]")
        XCTAssertFalse(g.find(), "a finished game does not count a fourth")
        XCTAssertEqual(g.found, 3)
        XCTAssertEqual(g.title, "Trees")
    }

    func testThingAndTargetStayInsideTheContract() throws {
        XCTAssertNil(WalkGoal(thing: "   ", target: 2), "nothing to look for is not a game")
        XCTAssertEqual(WalkGoal(thing: "birds", target: 9)?.target, 5)
        XCTAssertEqual(WalkGoal(thing: "birds", target: 0)?.target, 1)
        XCTAssertEqual(WalkGoal(thing: "  red   doors \n", target: 2)?.thing, "red doors")
        XCTAssertEqual(WalkGoal(thing: String(repeating: "x", count: 80), target: 2)?.thing.count, WalkGoal.thingMax)
        let tool = ((try json("contracts/schemas/companion_tools.json") as! [String: Any])["tools"] as! [String: [String: Any]])["set_walk_goal"]!
        let p = (tool["parameters"] as! [String: Any])["properties"] as! [String: [String: Any]]
        XCTAssertEqual(p["target"]?["minimum"] as? Int, WalkGoal.targets.lowerBound)
        XCTAssertEqual(p["target"]?["maximum"] as? Int, WalkGoal.targets.upperBound)
        XCTAssertEqual(p["thing"]?["maxLength"] as? Int, WalkGoal.thingMax)
    }

    func testToolResultsHaveTheContractsFields() throws {
        var g = try XCTUnwrap(WalkGoal(thing: "trees", target: 3))
        g.find()
        guard case .object(let goal) = g.goalResult, case .object(let moment) = g.momentResult,
              case .object(let none) = WalkGoal.momentWithoutGoal else { return XCTFail("results are objects") }
        let goalSchema = try props("WalkGoalResult"), momentSchema = try props("WalkMomentResult")
        XCTAssertEqual(Set(goal.keys), goalSchema.all)
        XCTAssertTrue(goalSchema.required.isSubset(of: goal.keys))
        XCTAssertEqual(goal, ["thing": .string("trees"), "target": .number(3), "found": .number(1), "left": .number(2)])
        XCTAssertEqual(Set(moment.keys), momentSchema.all.subtracting(["note"]), "`note` only goes with a find that was not counted")
        XCTAssertEqual(moment, ["ok": .bool(true), "thing": .string("trees"), "found": .number(1), "target": .number(3), "left": .number(2)])
        XCTAssertEqual(Set(none.keys), momentSchema.all)
        XCTAssertEqual(none["ok"], .bool(true))
        for k in ["thing", "found", "target", "left"] { XCTAssertEqual(none[k], .null, "no goal: \(k) is null") }
        // Numbers go out as JSON integers, null as null.
        let wire = String(decoding: try JSONEncoder().encode(g.momentResult), as: UTF8.self)
        XCTAssertTrue(wire.contains(#""left":2"#) && wire.contains(#""found":1"#), wire)
        XCTAssertTrue(String(decoding: try JSONEncoder().encode(WalkGoal.momentWithoutGoal), as: UTF8.self).contains(#""left":null"#))
    }

    func testTheLightHuntIsOneGoal() {
        let hunt = WalkGoal.lightHunt
        XCTAssertEqual(hunt.target, 3)
        XCTAssertTrue(hunt.isLightHunt)
        XCTAssertEqual(hunt.thing, L10n.shared.string("walk.goal.lights"))
        XCTAssertFalse(WalkGoal(thing: "trees", target: 3)!.isLightHunt)
    }
}

final class WalkNudgerTests: XCTestCase {
    private let t0 = Date(timeIntervalSince1970: 1_800_000_000)
    private func at(_ s: TimeInterval) -> Date { t0.addingTimeInterval(s) }
    private let playful = WalkGuide(style: .playful, look_every_s: 20, look_prompt: "LOOK", quiet_after_s: 60, quiet_prompt: "QUIET")
    private func listening(camera: Bool = true, words: Date? = nil) -> WalkNudger.Moment {
        .init(phase: .listening, cameraOn: camera, lastWords: words)
    }

    /// Steps one second at a time from `from` to `to` (inclusive) and returns what was sent, with its second.
    private func run(_ n: inout WalkNudger, _ from: Int, _ to: Int, _ m: (Int) -> WalkNudger.Moment) -> [String] {
        (from...to).compactMap { s in n.next(at: at(Double(s)), m(s)).map { "\(s):\($0.kind)" } }
    }

    func testLookEveryIntervalWhileTheCameraIsOnAndNobodySpeaks() {
        var n = WalkNudger(guide: WalkGuide(style: .quiet, look_every_s: 30, look_prompt: "LOOK"))
        XCTAssertEqual(run(&n, 0, 95) { _ in self.listening() }, ["30:look", "60:look", "90:look"])
        XCTAssertEqual(n.next(at: at(120), listening()), .look("LOOK"), "the line is the guide's, untouched")
    }

    func testCameraOffMeansNoLookPrompt() {
        var n = WalkNudger(guide: playful)
        XCTAssertEqual(run(&n, 0, 59) { _ in self.listening(camera: false) }, [], "no pictures: nothing to look at")
        // The quiet line does not need the camera.
        XCTAssertEqual(run(&n, 60, 60) { _ in self.listening(camera: false) }, ["60:quiet"])
        // The camera comes on after a long silence: the look waits its full interval from that moment.
        XCTAssertEqual(run(&n, 61, 100) { s in self.listening(camera: s >= 70) }, ["90:look"])
        // Off again (phone locked, seeing paused): looks stop at once.
        XCTAssertEqual(run(&n, 101, 160) { _ in self.listening(camera: false) }, [])
    }

    func testNothingIsSentWhileAnyoneSpeaksOrTheConversationIsNotOpen() {
        let blocked: [Conversation.Phase?] = [.hearing, .speaking, .thinking, .muted, .paused, .connecting, .idle, .unavailable, nil]
        for phase in blocked {
            var n = WalkNudger(guide: WalkGuide(style: .chatty, look_every_s: 1, look_prompt: "LOOK", quiet_after_s: 1, quiet_prompt: "QUIET"))
            let sent = run(&n, 0, 200) { _ in .init(phase: phase, cameraOn: true) }
            XCTAssertEqual(sent, [], "\(String(describing: phase)): nothing may be sent")
        }
        var n = WalkNudger(guide: WalkGuide(style: .chatty, look_every_s: 1, look_prompt: "LOOK", quiet_after_s: 1, quiet_prompt: "QUIET"))
        XCTAssertEqual(run(&n, 0, 200) { _ in .init(phase: .listening, cameraOn: true, paused: true) }, [], "Pause everything")
    }

    func testQuietPromptOnlyAfterTheFullSilenceAndOncePerSilence() {
        var n = WalkNudger(guide: WalkGuide(style: .chatty, quiet_after_s: 40, quiet_prompt: "QUIET"))
        XCTAssertEqual(run(&n, 0, 39) { _ in self.listening(camera: false) }, [], "39 s is not the full silence")
        XCTAssertEqual(n.next(at: at(40), listening(camera: false)), .quiet("QUIET"))
        XCTAssertEqual(run(&n, 41, 400) { _ in self.listening(camera: false) }, [], "once: Kaiku stayed quiet, so does the walk")
    }

    func testSpeechStartsTheSilenceAgain() {
        var n = WalkNudger(guide: WalkGuide(style: .chatty, quiet_after_s: 40, quiet_prompt: "QUIET"))
        // 0–29 quiet, the person speaks 30–34, Kaiku answers 35–41, quiet from 42.
        let sent = run(&n, 0, 130) { s in
            .init(phase: (30...34).contains(s) ? .hearing : (35...41).contains(s) ? .speaking : .listening)
        }
        XCTAssertEqual(sent, ["82:quiet"], "40 s after both went quiet at 42, not 40 s after the walk began")
        // Kaiku answered that nudge aloud (speaking 83–88): a new silence, so it may speak first again later.
        let again = run(&n, 131, 260) { s in .init(phase: (131...136).contains(s) ? .speaking : .listening) }
        XCTAssertEqual(again, ["177:quiet"])
    }

    func testWordsBetweenTwoChecksCountAsSpeech() {
        var n = WalkNudger(guide: WalkGuide(style: .chatty, look_every_s: 20, look_prompt: "LOOK", quiet_after_s: 40, quiet_prompt: "QUIET"))
        // A quick "yes" at 15.5 s that began and ended between two one-second checks: only its timestamp shows.
        let sent = run(&n, 0, 60) { s in self.listening(words: s >= 16 ? self.at(15.5) : nil) }
        XCTAssertEqual(sent, ["36:look", "56:quiet"], "both clocks run from the words, not from the start")
    }

    func testLookAndQuietDoNotStack() {
        var n = WalkNudger(guide: playful)
        let sent = run(&n, 0, 125) { _ in self.listening() }
        XCTAssertEqual(sent, ["20:look", "40:look", "60:quiet", "80:look", "100:look", "120:look"],
                       "at 60 s the quiet line goes alone; the next look waits its interval from it")
    }

    func testANullValueMeansNoNudge() {
        var calm = WalkNudger(guide: WalkGuide(style: .quiet, look_every_s: 30, look_prompt: "LOOK", quiet_after_s: nil, quiet_prompt: nil))
        XCTAssertEqual(run(&calm, 0, 100) { _ in self.listening(camera: false) }, [], "Calm has no quiet line")
        var noLine = WalkNudger(guide: WalkGuide(style: .chatty, look_every_s: 5, look_prompt: "  ", quiet_after_s: 5, quiet_prompt: nil))
        XCTAssertEqual(run(&noLine, 0, 100) { _ in self.listening() }, [], "an interval without a line sends nothing")
        var noSeconds = WalkNudger(guide: WalkGuide(style: .chatty, look_prompt: "LOOK", quiet_prompt: "QUIET"))
        XCTAssertEqual(run(&noSeconds, 0, 100) { _ in self.listening() }, [], "a line without an interval sends nothing")
        var none = WalkNudger()
        XCTAssertEqual(run(&none, 0, 100) { _ in self.listening() }, [], "no guide (not a walk, or an older service)")
    }

    func testTimersGoOnThroughAReconnect() {
        // A token renewal: the same conversation is `connecting` for a few seconds (40–43), then listening again.
        var n = WalkNudger(guide: playful)
        let sent = run(&n, 0, 130) { s in .init(phase: (40...43).contains(s) ? .connecting : .listening, cameraOn: !(40...43).contains(s)) }
        XCTAssertEqual(sent, ["20:look", "64:look", "84:look", "104:quiet", "124:look"],
                       "nothing during the reconnect; afterwards the same guide runs on from the new silence")
    }
}

// MARK: - the walk itself, on a fake microphone, a fake Live socket and a stubbed service

private final class WalkAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying: Bool { false }
    func start() throws {}
    func stop() {}
    func setMic(_ on: Bool) {}
    func play(_ pcm: Data) {}
    func flush() {}
}

/// The Live socket: answers `ready` at once and keeps what the walk sent.
private final class WalkLine: ConversationTransport, @unchecked Sendable {
    let onEvent: @Sendable (LiveSession.Event) -> Void
    private let lock = NSLock()
    private var _contexts: [String] = []
    private var _responses: [(name: String, result: JSONValue)] = []
    private var _frames = 0
    var contexts: [String] { lock.lock(); defer { lock.unlock() }; return _contexts }
    var responses: [(name: String, result: JSONValue)] { lock.lock(); defer { lock.unlock() }; return _responses }
    var frames: Int { lock.lock(); defer { lock.unlock() }; return _frames }
    init(_ onEvent: @escaping @Sendable (LiveSession.Event) -> Void) { self.onEvent = onEvent }
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) { onEvent(.ready) }
    func close() {}
    func sendAudio(_ pcm: Data) {}
    func audioStreamEnd() {}
    func sendText(_ text: String) {}
    func sendVideo(_ jpeg: Data) { lock.lock(); _frames += 1; lock.unlock() }
    func sendContext(_ event: String) { lock.lock(); _contexts.append(event); lock.unlock() }
    func respond(id: String, name: String, result: JSONValue) { lock.lock(); _responses.append((name, result)); lock.unlock() }
}

/// Glasses that only do what the walk asks: connected, and two synthetic pictures a second while the camera is on.
private final class WalkGlasses: GlassesAdapter, @unchecked Sendable {
    let kind = "mock"
    private let lock = NSLock()
    private var events: (@Sendable (GlassesEvent) -> Void)?
    private var task: Task<Void, Never>?
    private func keep(_ e: @escaping @Sendable (GlassesEvent) -> Void) { lock.lock(); events = e; lock.unlock() }
    /// Cancels the running feed, stores the next one, and hands back where events go.
    private func swap(_ next: Task<Void, Never>?) -> (@Sendable (GlassesEvent) -> Void)? {
        lock.lock(); defer { lock.unlock() }
        task?.cancel(); task = next
        return events
    }
    func start(_ events: @escaping @Sendable (GlassesEvent) -> Void) async {
        keep(events)
        events(.state(.connected))
    }
    func stop() async { _ = swap(nil) }
    func setCamera(_ on: Bool) async {
        guard let events = swap(nil) else { return }
        guard on else { events(.camera(.off, note: nil)); return }
        _ = swap(Task {
            while !Task.isCancelled {
                events(.frame(GlassesFrame(jpeg: Data([0xFF, 0xD8, 0xFF, 0xD9]), luminance: 0.5, width: 2, height: 2)))
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        })
    }
}

private final class WalkHTTP: URLProtocol {
    static let lock = NSLock()
    nonisolated(unsafe) static var guide = "null"
    /// Seconds the first session's Live token lasts (nil = far away); later tokens are always far away.
    nonisolated(unsafe) static var firstTokenLife: TimeInterval?
    nonisolated(unsafe) static var sessions: [[String: Any]] = []
    static var sessionBodies: [[String: Any]] { lock.lock(); defer { lock.unlock() }; return sessions }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var data = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
        }
        let path = request.url!.path
        var json = #"{"accepted":1,"duplicates":0,"rejected":[]}"#
        if path.hasSuffix("session") {
            Self.lock.lock()
            let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
            Self.sessions.append(body)
            let n = Self.sessions.count
            let guide = Self.guide.replacingOccurrences(of: "STYLE", with: body["walk_style"] as? String ?? "quiet")
            let life = n == 1 ? Self.firstTokenLife : nil
            Self.lock.unlock()
            let expires = life.map { ISO8601DateFormatter().string(from: Date().addingTimeInterval($0)) } ?? "2099-01-01T00:00:00Z"
            json = #"{"session_id":"walk-\#(n)","model":"m","voice":"v","system_instruction":"i","tools":[],"context_card":{"time_of_day":"morning"},"persona_version":"p","safety_phrases_version":"s","live_token":{"token":"t","expires_at":"\#(expires)","new_session_expires_at":"2099-01-01T00:00:00Z"},"walk":\#(guide)}"#
        } else if path.hasSuffix("episode") {
            json = #"{"ok":true,"id":"walk","transcript_stored":false}"#
        } else if path.hasSuffix("events"), request.httpMethod == "GET" { json = #"{"events":[]}"# }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor final class WalkOnAFakeLineTests: XCTestCase {
    private final class Lines: @unchecked Sendable { var all: [WalkLine] = []; var last: WalkLine { all[all.count - 1] } }
    private var wasMuted = false
    private var margin: TimeInterval = 0
    override func setUp() async throws {
        wasMuted = VoiceLines.shared.muted; VoiceLines.shared.muted = true
        margin = Conversation.resumeMargin
    }
    override func tearDown() async throws { VoiceLines.shared.muted = wasMuted; Conversation.resumeMargin = margin }

    private func fixture(guide: String, see: Bool, style: WalkStyle = .quiet, tokenLife: TimeInterval? = nil) -> (WalkModel, AppModel, Lines, URL) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("walk-" + UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        WalkHTTP.lock.lock(); WalkHTTP.guide = guide; WalkHTTP.sessions = []; WalkHTTP.firstTokenLife = tokenLife; WalkHTTP.lock.unlock()
        let pairing = Pairing(baseURL: URL(string: "https://walk.test")!, homeID: "walk-home", token: nil)
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [WalkHTTP.self]
        let defaults = UserDefaults(suiteName: "walk-" + UUID().uuidString)!
        let app = AppModel(defaults: defaults, pairing: pairing, api: APIClient(pairing: pairing, maxAttempts: 1, session: URLSession(configuration: config)),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")))
        app.consents[.see] = see
        style.store(defaults)
        let walk = WalkModel(defaults: defaults)
        walk.draftFile = dir.appendingPathComponent("walk.json")
        let lines = Lines()
        walk.makeConversation = { surface in
            Conversation(surface: surface, intent: .walk, audio: WalkAudio(),
                         transport: { let l = WalkLine($0); lines.all.append(l); return l },
                         permission: { true }, localListener: false, purpose: .walk)
        }
        return (walk, app, lines, dir)
    }

    private func wait(_ seconds: TimeInterval, _ what: String = "", until done: () -> Bool) async {
        let end = Date().addingTimeInterval(seconds)
        while !done() && Date() < end { try? await Task.sleep(nanoseconds: 50_000_000) }
        XCTAssertTrue(done(), "timed out: \(what)")
    }

    private func call(_ line: WalkLine, _ name: String, _ args: [String: JSONValue] = [:]) async -> JSONValue? {
        let before = line.responses.count
        line.onEvent(.toolCall(id: UUID().uuidString, name: name, args: args))
        await wait(2, "tool \(name)") { line.responses.count > before }
        return line.responses.last?.result
    }

    func testOneFindCountsOnceForOneThingThePersonSaid() async throws {
        let (walk, app, lines, dir) = fixture(guide: "null", see: false, style: .playful)
        defer { try? FileManager.default.removeItem(at: dir) }
        walk.begin(app: app, adapter: WalkGlasses())
        await wait(3, "voice") { walk.talking && walk.companion?.phase == .listening }
        let line = lines.last
        _ = await call(line, "set_walk_goal", ["thing": .string("birds"), "target": .number(3)])
        line.onEvent(.userText("Found one!")); line.onEvent(.userTranscriptComplete)
        await wait(2, "the person's words") { walk.companion?.lines.last?.text == "Found one!" }
        let first = await call(line, "log_walk_moment", ["kind": .string("a gull")])
        XCTAssertEqual(first?["found"], .number(1))
        // The model logs the same find again (a duplicated call for the same words): not counted twice.
        let again = await call(line, "log_walk_moment", ["kind": .string("a gull")])
        XCTAssertEqual(again, first, "the second call gets the first's answer")
        XCTAssertEqual(walk.goal?.found, 1)
        // The next thing the person says is the next find.
        line.onEvent(.userText("And there is another one.")); line.onEvent(.userTranscriptComplete)
        await wait(2, "the person's next words") { walk.companion?.lines.last?.text == "And there is another one." }
        let second = await call(line, "log_walk_moment", [:])
        XCTAssertEqual(second?["found"], .number(2)); XCTAssertEqual(second?["left"], .number(1))
        // The person's own button is its own find, and a new game starts clean.
        walk.foundOne()
        XCTAssertEqual(walk.goal?.found, 3)
        _ = await call(line, "set_walk_goal", ["thing": .string("dogs"), "target": .number(2)])
        let fresh = await call(line, "log_walk_moment", [:])
        XCTAssertEqual(fresh?["found"], .number(1), "a new game counts the same words afresh")
    }

    func testStyleGoesWithTheSessionAndKaikuKeepsTheCount() async throws {
        let (walk, app, lines, dir) = fixture(guide: "null", see: false, style: .playful)
        defer { try? FileManager.default.removeItem(at: dir) }
        XCTAssertEqual(walk.style, .playful, "the stored choice")
        walk.begin(app: app, adapter: WalkGlasses())
        await wait(3, "voice") { walk.talking && walk.companion?.phase == .listening }
        let body = try XCTUnwrap(WalkHTTP.sessionBodies.first)
        XCTAssertEqual(body["walk_style"] as? String, "playful")
        XCTAssertEqual(body["purpose"] as? String, "walk")
        XCTAssertEqual(body["intent"] as? String, "walk")
        XCTAssertEqual(body["surface"] as? String, "glasses", "with glasses the voice is in the ear")
        let line = lines.last
        XCTAssertTrue(line.contexts.first?.hasPrefix("[walk started") == true, "\(line.contexts)")
        XCTAssertNil(walk.goal, "no game until Kaiku starts one")

        // A find with no game on: heard, nothing to count.
        let none = await call(line, "log_walk_moment", ["kind": .string("a heron")])
        XCTAssertEqual(none, WalkGoal.momentWithoutGoal)
        XCTAssertNil(walk.goal)

        // Kaiku starts a game from what is around; the device answers with the count it keeps.
        let started = await call(line, "set_walk_goal", ["thing": .string("trees"), "target": .number(3)])
        XCTAssertEqual(started, .object(["thing": .string("trees"), "target": .number(3), "found": .number(0), "left": .number(3)]))
        XCTAssertEqual(walk.goal?.title, "Trees")
        let celebrations = app.celebration
        // `kind` is free text: whatever it says, it is one find for the game that is on.
        let one = await call(line, "log_walk_moment", ["kind": .string("red mailbox")])
        XCTAssertEqual(one?["found"], .number(1)); XCTAssertEqual(one?["left"], .number(2)); XCTAssertEqual(one?["thing"], .string("trees"))
        // The person says it without speaking (the walk screen's button): Kaiku is told the same count.
        walk.foundOne()
        XCTAssertEqual(walk.goal?.found, 2)
        XCTAssertEqual(line.contexts.last, "[spotting game · trees · 2 of 3 found · 1 left]")
        XCTAssertEqual(app.celebration, celebrations, "no completion moment before the last one")
        let last = await call(line, "log_walk_moment", ["kind": .string("an oak")])
        XCTAssertEqual(last?["found"], .number(3)); XCTAssertEqual(last?["left"], .number(0))
        XCTAssertEqual(walk.goal?.done, true)
        XCTAssertEqual(app.celebration, celebrations + 1, "one completion moment when the game is finished")
        let extra = await call(line, "log_walk_moment", ["kind": .string("another")])
        XCTAssertEqual(extra?["found"], .number(3), "nothing counts past the target")
        XCTAssertEqual(app.celebration, celebrations + 1)

        // A new goal replaces the old one; a call without the needed words changes nothing.
        let bad = await call(line, "set_walk_goal", ["thing": .string(" ")])
        XCTAssertEqual(bad?["ok"], .bool(false))
        XCTAssertEqual(walk.goal?.thing, "trees")
        let next = await call(line, "set_walk_goal", ["thing": .string("red doors"), "target": .number(8)])
        XCTAssertEqual(next?["target"], .number(5), "the result says the number that counts")
        XCTAssertEqual(walk.goal?.found, 0)

        // A new way of walking mid-walk: the conversation starts again in it, told the walk and the game go on.
        walk.choose(.chatty)
        await wait(3, "second session") { WalkHTTP.sessionBodies.count == 2 && lines.all.count == 2 && walk.companion?.phase == .listening }
        XCTAssertEqual(WalkHTTP.sessionBodies.last?["walk_style"] as? String, "chatty")
        XCTAssertEqual(walk.style, .chatty)
        let opening = try XCTUnwrap(lines.last.contexts.first)
        XCTAssertTrue(opening.hasPrefix("[walk goes on"), opening)
        XCTAssertTrue(opening.contains("spotting game still on: red doors, 0 of 5 found"), opening)
        XCTAssertFalse(opening.contains("greet them"), opening)
        XCTAssertEqual(walk.goal?.thing, "red doors", "the count is the walk's, not the conversation's")

        await walk.end()
        XCTAssertFalse(FileManager.default.fileExists(atPath: walk.draftFile.path))
    }

    func testLooksOnlyWithPicturesAndNothingOnAQuietWalk() async throws {
        let guide = #"{"style":"STYLE","look_every_s":1,"look_prompt":"LOOK-LINE","quiet_after_s":2,"quiet_prompt":"QUIET-LINE"}"#
        let (walk, app, lines, dir) = fixture(guide: guide, see: false)
        defer { try? FileManager.default.removeItem(at: dir) }
        walk.begin(app: app, adapter: WalkGlasses())
        await wait(3, "voice") { walk.talking && walk.companion?.phase == .listening }
        let line = lines.last
        func sent(_ text: String) -> Int { line.contexts.filter { $0 == text }.count }

        // "Let Kaiku see" is off: no pictures, so no look line; the quiet line comes after its silence, once.
        await wait(5, "quiet line") { sent("QUIET-LINE") == 1 }
        try await Task.sleep(nanoseconds: 2_500_000_000)
        XCTAssertEqual(sent("QUIET-LINE"), 1, "once per silence")
        XCTAssertEqual(sent("LOOK-LINE"), 0, "camera off means no look prompt")
        XCTAssertEqual(line.frames, 0)

        // The person turns seeing on: pictures flow, and the look line follows them.
        app.consents[.see] = true
        await walk.applyVision()
        await wait(5, "pictures") { line.frames > 0 && walk.camera == .streaming }
        await wait(5, "look line") { sent("LOOK-LINE") >= 1 }

        // Quiet walk (muted): nothing more is sent, neither line.
        walk.setTalking(false)
        XCTAssertEqual(walk.companion?.phase, .muted)
        let before = line.contexts.count
        try await Task.sleep(nanoseconds: 2_500_000_000)
        XCTAssertEqual(line.contexts.filter { $0 == "LOOK-LINE" || $0 == "QUIET-LINE" }.count,
                       line.contexts.prefix(before).filter { $0 == "LOOK-LINE" || $0 == "QUIET-LINE" }.count,
                       "muted: no nudges")

        // Everything paused ends the conversation; the walk sends nothing after that either.
        walk.setTalking(true)
        app.pausedAll = true
        await wait(2, "closed by pause") { walk.companion?.isLive != true }
        let after = line.contexts.count
        try await Task.sleep(nanoseconds: 2_000_000_000)
        XCTAssertEqual(line.contexts.count, after)
        app.pausedAll = false
        await walk.end()
    }

    /// A long walk outlives its Live token: the conversation asks for the next one and moves to a new socket. The
    /// request for it must say again that this is a walk and in which style (the cloud sizes the session from
    /// the request), and the walk's nudges must go on over the new socket.
    func testTheNextTokenIsAskedForAsTheSameWalkAndTheNudgesGoOn() async throws {
        let guide = #"{"style":"STYLE","look_every_s":1,"look_prompt":"LOOK-LINE","quiet_after_s":null,"quiet_prompt":null}"#
        let (walk, app, lines, dir) = fixture(guide: guide, see: true, style: .chatty, tokenLife: 7)
        defer { try? FileManager.default.removeItem(at: dir) }
        Conversation.resumeMargin = 2          // the first token ends in 7 s: the next one is asked for after 5
        walk.begin(app: app, adapter: WalkGlasses())
        await wait(3, "voice") { walk.talking && walk.companion?.phase == .listening }
        await wait(4.5, "look on the first socket") { lines.all[0].contexts.contains("LOOK-LINE") }
        await wait(8, "next token") { WalkHTTP.sessionBodies.count == 2 && lines.all.count == 2 }
        let first = try XCTUnwrap(WalkHTTP.sessionBodies.first), next = try XCTUnwrap(WalkHTTP.sessionBodies.last)
        XCTAssertNil(first["resume_session_id"])
        XCTAssertEqual(next["resume_session_id"] as? String, "walk-1")
        for key in ["surface", "intent", "purpose", "walk_style", "home_id"] {
            XCTAssertEqual(next[key] as? String, first[key] as? String, "the resume request repeats \(key)")
        }
        XCTAssertEqual(next["walk_style"] as? String, "chatty")
        XCTAssertEqual(next["purpose"] as? String, "walk")
        XCTAssertEqual(next["surface"] as? String, "glasses")
        // The same conversation, the same guide, a new socket: looks keep arriving there.
        XCTAssertEqual(walk.liveStyle, .chatty)
        await wait(5, "look on the new socket") { lines.all[1].contexts.contains("LOOK-LINE") }
        XCTAssertFalse(lines.all[1].contexts.contains { $0.hasPrefix("[walk started") || $0.hasPrefix("[walk goes on") },
                       "a new token is not a new conversation: nothing is said about starting again")
        await walk.end()
    }

    /// A seeing walk is the first to reach Gemini's limit for a session with camera frames: the setup frame the
    /// walk sends must ask for context compression and session resumption.
    func testAWalksSetupAsksForCompressionAndResumption() throws {
        let session = try JSONDecoder().decode(CompanionSessionResponse.self, from: Data(#"""
        {"session_id":"s","model":"gemini-live","voice":"v","system_instruction":"i","tools":[],"persona_version":"p",
         "safety_phrases_version":"1","context_card":{"time_of_day":"morning"},
         "walk":{"style":"quiet","look_every_s":30,"look_prompt":"LOOK","quiet_after_s":null,"quiet_prompt":null},
         "live_setup":{"contextWindowCompression":{"slidingWindow":{}},"sessionResumption":{},"proactivity":{"proactiveAudio":true}}}
        """#.utf8))
        XCTAssertEqual(session.walk?.look_every_s, 30)
        let setup = try XCTUnwrap(LiveSession.setup(session: session, options: .init(handsFree: true, tuning: .headset, resumeHandle: "h1"))["setup"] as? [String: Any])
        XCTAssertNotNil((setup["contextWindowCompression"] as? [String: Any])?["slidingWindow"], "compression on")
        XCTAssertEqual((setup["sessionResumption"] as? [String: Any])?["handle"] as? String, "h1", "resumption, with the handle on a reconnect")
        XCTAssertEqual((setup["proactivity"] as? [String: Any])?["proactiveAudio"] as? Bool, true)
        let fresh = try XCTUnwrap(LiveSession.setup(session: session, options: .init())["setup"] as? [String: Any])
        XCTAssertNotNil(fresh["sessionResumption"], "asked for from the first connection")
    }

    func testPhoneOnlyWalkSaysItRunsOnThePhone() async throws {
        let (walk, app, lines, dir) = fixture(guide: "null", see: false)
        defer { try? FileManager.default.removeItem(at: dir) }
        walk.begin(app: app, adapter: nil)
        await wait(3, "voice") { walk.talking && walk.companion?.phase == .listening }
        let body = try XCTUnwrap(WalkHTTP.sessionBodies.first)
        // No glasses and (on the test machine) no hands-free headset: the walk runs on the phone surface.
        XCTAssertEqual(body["surface"] as? String, "iphone")
        XCTAssertEqual(body["walk_style"] as? String, "quiet", "Calm unless the person chose otherwise")
        // The fixed light hunt is one instance of the goal: a find with no game on starts it.
        walk.foundOne()
        XCTAssertEqual(walk.goal?.isLightHunt, true)
        XCTAssertEqual(walk.goal?.found, 1)
        XCTAssertEqual(lines.last.contexts.last, WalkGoal.lightHunt.thing.isEmpty ? nil : "[spotting game · \(WalkGoal.lightHunt.thing) · 1 of 3 found · 2 left]")
        await walk.end()
    }
}

#if os(macOS)
import AppKit
import SwiftUI

/// Layout pictures of the new pieces at the widths the simulator run could not show (opt-in):
/// `KAIKU_WALK_RENDER_DIR=<dir> swift test --filter WalkRenderTests` writes PNGs of the spotting card with a short
/// and the longest allowed thing at 320 pt, and the invitation card as the Mac's wide layout shows it. The
/// invitation text is the cloud's own sentence for the seeded person, copied from a real response; nothing is
/// asserted about looks, the pictures are for eyes.
@MainActor final class WalkRenderTests: XCTestCase {
    private func write<V: View>(_ view: V, width: CGFloat, _ name: String, to dir: String) throws {
        let framed = view.frame(width: width).padding(KaikuTokens.Space.s4).background(KaikuTokens.Colors.bg)
            .environment(\.colorScheme, .light)
        let r = ImageRenderer(content: framed)
        r.scale = 2
        let cg = try XCTUnwrap(r.cgImage)
        let data = try XCTUnwrap(NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]))
        try data.write(to: URL(fileURLWithPath: dir).appendingPathComponent(name))
    }

    func testRenderWalkAndInvitationPieces() throws {
        guard let dir = ProcessInfo.processInfo.environment["KAIKU_WALK_RENDER_DIR"] else { throw XCTSkip("set KAIKU_WALK_RENDER_DIR") }
        var trees = try XCTUnwrap(WalkGoal(thing: "trees", target: 3)); trees.find()
        var long = try XCTUnwrap(WalkGoal(thing: "yellow leaves on the ground by the water", target: 5)); long.find(); long.find()
        XCTAssertEqual(long.thing.count, WalkGoal.thingMax)
        try write(WalkGoalCard(goal: trees) {}, width: 288, "goal-trees-320.png", to: dir)
        try write(WalkGoalCard(goal: trees) {}, width: 370, "goal-trees-402.png", to: dir)
        try write(WalkGoalCard(goal: long) {}, width: 288, "goal-long-320.png", to: dir)
        let invitation = Invitation(id: "thread:2", kind: .talk_about,
                                    text: "We left off at the long lake loop with Leena on Saturday. Want to pick it up?",
                                    voice_key: "invite.talk.open", topic: "the long lake loop with Leena on Saturday")
        try write(InvitationCard(invitation: invitation, showsMascot: false, hear: {}, yes: {}, notNow: {}), width: 380, "invitation-mac-wide.png", to: dir)
        try write(InvitationCard(invitation: invitation, showsMascot: false, hear: {}, yes: {}, notNow: {}), width: 256, "invitation-narrow.png", to: dir)
        // You → Settings: the glasses row and the style choice under it, as one section.
        try write(KSection { KRow(icon: "eyeglasses", tint: KaikuTokens.Colors.sage, title: T("gc.title")); KDivider(); WalkStyleSetting() },
                  width: 370, "you-walk-style.png", to: dir)
    }
}
#endif

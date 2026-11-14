import AVFoundation
import XCTest
@testable import KaikuKit

// Talk as a call: mute me and mute Kaiku independently (captions keep coming), the gated nudge, and the planned
// move to the next Live token. The real `Conversation` on a fake Live transport, fake audio and a stubbed cloud.

private final class CallAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying = false
    var mic = false
    var outputMuted = false
    var played: [Data] = []
    func start() throws {}
    func stop() { mic = false }
    func setMic(_ on: Bool) { mic = on }
    func setOutputMuted(_ on: Bool) { outputMuted = on }
    func play(_ pcm: Data) { played.append(pcm); onPlaying?(true) }
    func flush() { onPlaying?(false) }
}

private final class CallLink: ConversationTransport, @unchecked Sendable {
    var event: (@Sendable (LiveSession.Event) -> Void)?
    var contexts: [String] = []
    var text: [String] = []
    var tokens: [String] = []
    var closed = 0
    var frames: [[ToolAnswer]] = []
    var handles: [String?] = []
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) {
        tokens.append(token); handles.append(options.resumeHandle)
    }
    func close() { closed += 1 }
    func sendAudio(_ pcm: Data) {}
    func audioStreamEnd() {}
    func sendText(_ text: String) { self.text.append(text) }
    func sendContext(_ event: String) { contexts.append(event) }
    func respond(id: String, name: String, result: JSONValue) {}
    func respond(_ answers: [ToolAnswer]) { frames.append(answers) }
    var alive = true
    var pings = 0
    var turns: [String] = []
    func ping(timeout: TimeInterval, _ done: @escaping @Sendable (Bool) -> Void) {
        pings += 1
        let alive = alive, event = event
        if !alive { event?(.closed) }               // a socket that does not answer reports itself closed
        done(alive)
    }
    func sendTurn(_ text: String) { turns.append(text) }
}

private final class CallHTTP: URLProtocol {
    static let lock = NSLock()
    nonisolated(unsafe) static var sessions: [String] = []
    nonisolated(unsafe) static var closes: [String] = []
    nonisolated(unsafe) static var expires = "2099-01-01T00:00:00Z"
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
        Self.lock.lock()
        if path.hasSuffix("session") { Self.sessions.append(String(decoding: data, as: UTF8.self)) }
        if path.hasSuffix("close") { Self.closes.append(String(decoding: data, as: UTF8.self)) }
        let n = Self.sessions.count, expires = Self.expires
        Self.lock.unlock()
        var json = #"{"accepted":1,"duplicates":0,"rejected":[]}"#
        if path.hasSuffix("session") {
            json = #"{"session_id":"call-session","model":"m","voice":"v","system_instruction":"s","tools":[],"context_card":{"time_of_day":"morning"},"persona_version":"p","safety_phrases_version":"s","max_session_seconds":1800,"idle_end_s":180,"live_token":{"token":"token-\#(n)","expires_at":"\#(n == 1 ? expires : "2099-01-01T00:00:00Z")","new_session_expires_at":"2099-01-01T00:00:00Z"}}"#
        } else if path.hasSuffix("episode") { json = #"{"ok":true,"id":"call-session"}"# }
        else if path.hasSuffix("close") { json = #"{"ok":true,"session_id":"call-session","settled":1,"billed_minutes":1}"# }
        else if path.hasSuffix("events"), request.httpMethod == "GET" { json = #"{"events":[]}"# }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor final class CallTests: XCTestCase {
    private var margin: TimeInterval = 0

    override func setUp() async throws {
        margin = Conversation.resumeMargin
        UserDefaults.standard.removeObject(forKey: Conversation.voiceMutedKey)
        CallHTTP.lock.lock(); CallHTTP.sessions = []; CallHTTP.closes = []; CallHTTP.expires = "2099-01-01T00:00:00Z"; CallHTTP.lock.unlock()
    }

    override func tearDown() async throws {
        Conversation.resumeMargin = margin
        UserDefaults.standard.removeObject(forKey: Conversation.voiceMutedKey)
    }

    private func fixture(home: String = "synthetic") -> (AppModel, CallAudio, CallLink, Conversation, URL) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let p = Pairing(baseURL: URL(string: "https://call.test")!, homeID: home, token: "synthetic-pairing-token")
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [CallHTTP.self]
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        let app = AppModel(defaults: defaults, pairing: p, api: APIClient(pairing: p, maxAttempts: 1, session: URLSession(configuration: config)),
                           queue: OfflineQueue(url: dir.appendingPathComponent("events.json")),
                           episodes: EpisodeOutbox(url: dir.appendingPathComponent("episodes.json")))
        let audio = CallAudio(), link = CallLink()
        let c = Conversation(surface: .iphone, intent: .talk, audio: audio, transport: { event in link.event = event; return link },
                             permission: { true }, localListener: false, purpose: .talk, typedWithoutMic: true)
        return (app, audio, link, c, dir)
    }

    private func settle() async { try? await Task.sleep(nanoseconds: 80_000_000) }
    private let chunk = Data([1, 0, 2, 0])

    private func open(_ c: Conversation, _ app: AppModel, _ link: CallLink) async {
        _ = await c.start(app: app)
        link.event?(.ready); await settle()
    }

    // MARK: the end is reported, once

    func testEveryEndTellsTheCloudHowLongTheConversationRan() async throws {
        // (Other tests' conversations end in the background too: this one has a home of its own.)
        func closes() -> [String] { CallHTTP.lock.lock(); defer { CallHTTP.lock.unlock() }; return CallHTTP.closes.filter { $0.contains("close-home") } }
        let (app, _, link, c, dir) = fixture(home: "close-home")
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(c, app, link)
        try? await Task.sleep(nanoseconds: 300_000_000)
        c.stop(outcome: .completed)
        c.stop()                                                    // a second stop is not a second conversation
        try? await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertEqual(closes().count, 1)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: Data((closes().first ?? "{}").utf8)) as? [String: Any])
        XCTAssertEqual(body["home_id"] as? String, "close-home")
        XCTAssertEqual(body["session_id"] as? String, "call-session", "the first session id, whatever token it ended on")
        let elapsed = try XCTUnwrap(body["elapsed_s"] as? Double)
        XCTAssertTrue(elapsed > 0.2 && elapsed < 5, "\(elapsed)")
        XCTAssertEqual(Set(body.keys), ["home_id", "session_id", "elapsed_s"])

        // A conversation that never got a session (no service) has nothing to report.
        let (app2, _, _, c2, dir2) = fixture(home: "close-home")
        defer { try? FileManager.default.removeItem(at: dir2) }
        app2.pausedAll = true
        _ = await c2.start(app: app2)
        c2.stop()
        try? await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(closes().count, 1)
    }

    // MARK: Kaiku's own turns: held until a real word, also when the marker comes in pieces

    func testAMarkerInPiecesIsNeverHeardNeverShownAndNeverStored() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        app.consents[.transcripts] = true
        await open(c, app, link)
        // A turn nobody asked for (it answers a context event): `<no speech>` arrives as `<no`, ` speech`, `>`.
        c.context("[glasses camera on]")
        XCTAssertEqual(link.contexts, ["[glasses camera on]"])
        link.event?(.modelOutput); link.event?(.audio(chunk))
        for piece in ["<no", " speech", ">"] { link.event?(.kaikuText(piece)); link.event?(.audio(chunk)); await settle() }
        link.event?(.kaikuTranscriptComplete); link.event?(.turnComplete); await settle()
        XCTAssertTrue(audio.played.isEmpty, "not one chunk of that turn is heard")
        XCTAssertTrue(c.lines.isEmpty, "and there is no bubble")
        // Other ways the pieces fall: the brace marker, a marker that never closes, a marker after white space.
        for pieces in [["{pa", "use}"], ["<no speech"], [" ", "<noise", ">", " "], ["<no", " speech>{", "pause}"]] {
            link.event?(.modelOutput); link.event?(.audio(chunk))
            for piece in pieces { link.event?(.kaikuText(piece)) }
            link.event?(.turnComplete); await settle()
        }
        XCTAssertTrue(audio.played.isEmpty)
        XCTAssertTrue(c.lines.isEmpty)
        // A real word after a marker in pieces is too late for this turn's sound (the marker decided it), and the
        // next turn with words is heard from its first chunk.
        link.event?(.audio(chunk)); link.event?(.kaikuText("Oh, ")); link.event?(.audio(chunk)); link.event?(.kaikuText("a heron."))
        link.event?(.kaikuTranscriptComplete); link.event?(.turnComplete); await settle()
        XCTAssertEqual(audio.played.count, 2)
        XCTAssertEqual(c.lines.map(\.text), ["Oh, a heron."])
        // The person's side: a marker in pieces inside their words leaves only the words.
        for piece in ["It is ", "<noi", "se>", "lovely."] { link.event?(.userText(piece)) }
        link.event?(.userTranscriptComplete); await settle()
        XCTAssertEqual(c.lines.last?.text, "It is lovely.")
        XCTAssertFalse(c.lines.contains { $0.text.contains("<") || $0.text.contains(">") || $0.text.contains("{") })
        // Stored: only what was said. Typed text is kept as typed.
        let stored = Conversation.transcript([.init(text: "<no speech>", me: false), .init(text: "{pause} ×", me: false),
                                              .init(text: "Hello <noise> there", me: false), .init(text: "I <3 walks", me: true, typed: true)])
        XCTAssertEqual(stored.map(\.text), ["Hello  there", "I <3 walks"])
        XCTAssertEqual(Heard("<no"), .undecided); XCTAssertEqual(Heard("<no speech"), .undecided)
        XCTAssertEqual(Heard("<no speech>"), .notSpeech); XCTAssertEqual(Heard("<no speech> {pau"), .undecided)
        XCTAssertEqual(Heard(" × -"), .undecided); XCTAssertEqual(Heard("<noise> yes"), .word); XCTAssertEqual(Heard("3"), .word)
    }

    func testOnlyTurnsThePersonCausedPlayAtOnce() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)
        // The person speaks: the answer plays from its first chunk, before any transcription.
        link.event?(.userText("What is that bird?")); link.event?(.userTranscriptComplete); await settle()
        link.event?(.modelOutput); link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 1)
        // A context event while Kaiku is answering waits (a client turn would cut the answer off) …
        c.context("[walk · 10 min]")
        XCTAssertTrue(link.contexts.isEmpty)
        link.event?(.kaikuText("A heron, I think.")); link.event?(.kaikuTranscriptComplete); link.event?(.turnComplete); await settle()
        // … and goes out once the turn is over. The turn that answers IT is Kaiku's own: held.
        XCTAssertEqual(link.contexts, ["[walk · 10 min]"])
        link.event?(.modelOutput); link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 1, "held")
        link.event?(.kaikuText("Ten minutes already.")); link.event?(.turnComplete); await settle()
        XCTAssertEqual(audio.played.count, 2, "it had words: heard from its start")
        // A tool the person's words set off keeps the answer theirs (it comes after the tool).
        link.event?(.userText("What did I say about the lake?")); link.event?(.userTranscriptComplete)
        link.event?(.toolCall(id: "t", name: "suggest_activity", args: ["kind": .string("drum")])); link.event?(.turnComplete); await settle()
        link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 3, "played at once")
        link.event?(.kaikuText("You love it there.")); link.event?(.turnComplete); await settle()
        // The model stayed silent after the person's words (an empty turn): the credit is gone, the next turn is its own.
        link.event?(.userText("Mm.")); link.event?(.userTranscriptComplete); link.event?(.turnComplete); await settle()
        link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 3, "held")
        link.event?(.turnComplete); await settle()
        // Something the person did on screen is their turn too.
        c.personDid("The person put the breathe card aside.")
        XCTAssertEqual(link.contexts.last, "The person put the breathe card aside.")
        link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 4)
        link.event?(.kaikuText("No problem.")); link.event?(.turnComplete); await settle()
        // Two context events that had to wait go out as one turn.
        link.event?(.userText("And that one?")); link.event?(.audio(chunk)); await settle()
        c.context("[glasses camera off]"); c.context("[walk · 20 min]")
        XCTAssertEqual(link.contexts.count, 2, "both wait for the answer to finish")
        link.event?(.kaikuText("A gull.")); link.event?(.turnComplete); await settle()
        XCTAssertEqual(link.contexts.last, "[glasses camera off]\n[walk · 20 min]")
    }

    // MARK: the calls of one frame are answered in one frame

    func testTwoCallsInOneFrameGetExactlyOneResponseFrameWithBothIds() async {
        let patience = Conversation.toolFramePatience
        defer { Conversation.toolFramePatience = patience }
        let (app, _, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        var slow: CheckedContinuation<Void, Never>?
        c.deviceTool = { name, _ in
            if name == "start_activity" { await withCheckedContinuation { slow = $0 } }      // one tool takes its time
            return .object(["ok": .bool(true), "tool": .string(name)])
        }
        await open(c, app, link)
        // The parser marks a frame with several calls (and only such a frame).
        let frame: [String: Any] = ["toolCall": ["functionCalls": [["id": "a", "name": "start_activity", "args": [String: Any]()],
                                                                   ["id": "b", "name": "log_walk_moment", "args": [String: Any]()]]]]
        let events = LiveSession.parse(frame)
        XCTAssertEqual(events.first, .toolFrame(ids: ["a", "b"]))
        XCTAssertEqual(events.count, 3)
        XCTAssertFalse(LiveSession.parse(["toolCall": ["functionCalls": [["id": "x", "name": "express", "args": [String: Any]()]]]])
            .contains { if case .toolFrame = $0 { return true } else { return false } })
        events.forEach { link.event?($0) }
        await settle()
        XCTAssertTrue(link.frames.isEmpty, "the fast result waits for the other call of its frame")
        slow?.resume(); await settle()
        XCTAssertEqual(link.frames.count, 1, "exactly one response frame")
        XCTAssertEqual(link.frames.first?.map(\.id), ["a", "b"], "carrying both ids, in the order they were called")
        XCTAssertEqual(link.frames.first?.last?.result, .object(["ok": .bool(true), "tool": .string("log_walk_moment")]))
        // One wire frame, each response with its own scheduling.
        let wire = LiveSession.functionResponse(id: "f", name: "feel", result: .object(["stance": .string("comfort"), "scheduling": .string("SILENT")]), background: true)
        XCTAssertEqual((wire["response"] as? [String: Any])?["scheduling"] as? String, "SILENT")

        // A call cancelled meanwhile is left out; the rest of its frame still goes as one.
        link.frames = []
        [.toolFrame(ids: ["c", "d", "e"]), .toolCall(id: "c", name: "start_activity", args: [:]), .toolCall(id: "d", name: "express", args: [:]),
         .toolCall(id: "e", name: "express", args: [:])].forEach { link.event?($0) }
        await settle()
        link.event?(.toolCancelled(["c"])); await settle()
        XCTAssertEqual(link.frames.map { $0.map(\.id) }, [["d", "e"]])
        slow?.resume()

        // A single call is answered at once, as before.
        link.frames = []
        link.event?(.toolCall(id: "s", name: "express", args: [:])); await settle()
        XCTAssertEqual(link.frames.map { $0.map(\.id) }, [["s"]])

        // A slow tool does not hold a fast result back for good: after the patience what is there goes out.
        Conversation.toolFramePatience = 0.3
        link.frames = []
        [.toolFrame(ids: ["g", "h"]), .toolCall(id: "g", name: "start_activity", args: [:]), .toolCall(id: "h", name: "express", args: [:])]
            .forEach { link.event?($0) }
        try? await Task.sleep(nanoseconds: 700_000_000)
        XCTAssertEqual(link.frames.map { $0.map(\.id) }, [["h"]])
        slow?.resume(); await settle()
        XCTAssertEqual(link.frames.map { $0.map(\.id) }, [["h"], ["g"]])
    }

    // MARK: two mutes, captions always

    func testMutingKaikuSilencesItsVoiceAndKeepsItsWords() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)
        XCTAssertFalse(c.voiceMuted)
        XCTAssertFalse(audio.outputMuted)
        c.setVoiceMuted(true)
        XCTAssertTrue(c.voiceMuted)
        XCTAssertTrue(audio.outputMuted, "at once, mid-sentence too")
        link.event?(.audio(chunk)); link.event?(.kaikuText("Still here, just quiet.")); await settle()
        XCTAssertEqual(c.lines.last?.text, "Still here, just quiet.", "the words keep coming as captions")
        XCTAssertEqual(audio.played.count, 1, "the audio modality stays on (unheard), so timing and barge-in are unchanged")
        XCTAssertTrue(c.kaikuSpeaking)
        XCTAssertTrue(audio.mic, "muting Kaiku does not mute me")
        XCTAssertTrue(UserDefaults.standard.bool(forKey: Conversation.voiceMutedKey), "the choice is remembered on this device")

        let (_, audio2, link2, c2, dir2) = fixture()
        defer { try? FileManager.default.removeItem(at: dir2); c2.stop() }
        XCTAssertTrue(c2.voiceMuted, "and the next call starts the same way")
        await open(c2, app, link2)
        XCTAssertTrue(audio2.outputMuted)
        c2.setVoiceMuted(false)
        XCTAssertFalse(audio2.outputMuted)
    }

    func testMutingMeKeepsKaikuAnsweringWhatIsTyped() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)
        c.setMuted(true)
        XCTAssertTrue(c.micMuted)
        XCTAssertFalse(audio.mic)
        XCTAssertFalse(c.voiceMuted, "the two mutes are independent")
        c.send(text: "I'm on the bus, typing.")
        XCTAssertEqual(link.text, ["I'm on the bus, typing."])
        link.event?(.audio(chunk)); link.event?(.kaikuText("Typing is fine.")); await settle()
        XCTAssertEqual(audio.played.count, 1, "Kaiku still answers aloud")
        XCTAssertTrue(c.kaikuSpeaking)
        XCTAssertEqual(CallStatus(c), .speaking)
        audio.onPlaying?(false); await settle()
        XCTAssertEqual(CallStatus(c), .muted)
        c.setMuted(false)
        XCTAssertTrue(audio.mic)
        XCTAssertEqual(CallStatus(c), .listening)
    }

    // MARK: the gated nudge

    // MARK: a line the person wrote is always answered (the take in which Kaiku went silent, 2026-11-14)

    func testAWrittenLineThatArrivesWhileAHeldTurnIsPendingStillGetsItsAnswerHeard() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(c, app, link)
        var notes: [String] = []
        c.noted = { event, fields in notes.append(event + (fields["after_a_dropped_turn"] != nil ? "+rescued" : "")) }

        // Kaiku's own turn (nobody asked): sound with no word yet, so it is held. The server never says it is over.
        c.nudge("[walk · 10 min]")
        link.event?(.audio(chunk)); link.event?(.audio(chunk)); await settle()
        XCTAssertTrue(audio.played.isEmpty, "held until a word")
        // The person writes. The held turn is theirs to take; no `interrupted`, no `turnComplete` arrive.
        c.send(text: "It has been a hard day.")
        XCTAssertTrue(c.awaitingAnswer)
        XCTAssertEqual(CallStatus(c), .thinking, "the bar says Kaiku is on it, not just that the microphone is off")
        try? await Task.sleep(nanoseconds: UInt64((Conversation.supersededGap + 0.15) * 1_000_000_000))
        // The answer starts well within the old three-second window of the dropped turn.
        link.event?(.audio(chunk)); link.event?(.kaikuText("That sounds heavy.")); link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 2, "the answer plays at once and in full")
        XCTAssertEqual(c.lines.last?.text, "That sounds heavy.")
        XCTAssertFalse(c.awaitingAnswer)
        XCTAssertTrue(notes.contains("turn_dropped_for_person"))
        XCTAssertTrue(notes.contains("turn+rescued"), "the trace says the old gate would have swallowed this answer: \(notes)")
    }

    func testFramesStillInFlightFromTheDroppedTurnAreNotMistakenForTheAnswer() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(c, app, link)
        c.nudge("[walk · 10 min]")
        link.event?(.audio(chunk)); await settle()
        c.send(text: "Wait.")
        link.event?(.audio(chunk)); link.event?(.kaikuText("<no speech>")); link.event?(.audio(chunk)); await settle()
        XCTAssertTrue(audio.played.isEmpty, "what was already on its way belongs to the turn the person took over")
        XCTAssertFalse(c.lines.contains { !$0.me })
    }

    func testTheEndOfAnInterruptedTurnDoesNotUseUpThePersonsAnswer() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(c, app, link)
        link.event?(.userText("Tell me something.")); link.event?(.userTranscriptComplete)
        link.event?(.audio(chunk)); link.event?(.kaikuText("Well, once upon")); await settle()
        let before = audio.played.count
        // The person writes over Kaiku: the server interrupts that turn and then closes it.
        c.send(text: "Sorry, my mother would have turned ninety today.")
        link.event?(.interrupted); link.event?(.turnComplete); await settle()
        // Their answer starts with a sound that is not a word. It is still theirs: never held, never dropped.
        link.event?(.modelOutput); link.event?(.audio(chunk)); link.event?(.kaikuText("<sigh>")); link.event?(.audio(chunk))
        link.event?(.kaikuText(" I am so sorry.")); await settle()
        XCTAssertEqual(audio.played.count, before + 2, "an answer to the person is never held back")
        XCTAssertEqual(c.lines.last?.text, "I am so sorry.")
    }

    func testAnAnswerThatComesLongAfterTheLineBecauseOfASlowToolIsStillThePersons() async {
        let window = Conversation.answerWindow
        Conversation.answerWindow = 0.25
        defer { Conversation.answerWindow = window }
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(c, app, link)
        var whose: [String] = []
        c.noted = { event, fields in if event == "turn" { whose.append("\(fields["whose"] ?? "")") } }
        c.send(text: "I could not face baking today.")
        try? await Task.sleep(nanoseconds: 400_000_000)          // the wait for an answer has run out
        link.event?(.toolCall(id: "f1", name: "feel", args: [:]))  // the model was reading the feeling all along
        link.event?(.turnComplete)
        try? await Task.sleep(nanoseconds: 150_000_000)          // the tool has answered (the fake cloud is quick)
        link.event?(.modelOutput); link.event?(.audio(chunk)); link.event?(.kaikuText("<sigh>")); link.event?(.audio(chunk))
        link.event?(.kaikuText(" That is completely understandable.")); await settle()
        XCTAssertEqual(whose.last, "the person's answer", "the tool renews the wait, also the quiet one")
        XCTAssertEqual(audio.played.count, 2, "so the answer is not held, and a sound at its start cannot drop it")
        XCTAssertEqual(c.lines.last?.text, "That is completely understandable.")
    }

    func testWordsAfterASoundInKaikusOwnTurnAreHeardFromThere() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(c, app, link)
        c.nudge("[walk · 10 min]")
        link.event?(.audio(chunk)); link.event?(.kaikuText("<sigh>")); link.event?(.audio(chunk)); await settle()
        XCTAssertTrue(audio.played.isEmpty, "the sound itself is not played")
        link.event?(.kaikuText(" Ten minutes already.")); link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 1, "the words that follow are")
        XCTAssertEqual(c.lines.last?.text, "Ten minutes already.")
    }

    func testAWrittenLineOnADeadSocketIsNoticedAndSentAgainOnTheNextOne() async {
        let patience = Conversation.answerPatience
        Conversation.answerPatience = 0.3
        defer { Conversation.answerPatience = patience }
        let (app, _, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(c, app, link)
        link.event?(.resumable(handle: "h-1")); await settle()
        var notes: [String] = []
        c.noted = { event, _ in notes.append(event) }
        link.alive = false
        c.send(text: "Are you there?")
        try? await Task.sleep(nanoseconds: 700_000_000)
        XCTAssertEqual(link.pings, 1, "silence after a written line: the socket is checked, once")
        XCTAssertTrue(notes.contains("typed_unanswered") && notes.contains("live_dropped"), "\(notes)")
        XCTAssertEqual(link.tokens.count, 2, "a dead socket is replaced")
        link.alive = true
        link.event?(.ready); await settle()
        XCTAssertEqual(link.text, ["Are you there?", "Are you there?"], "and the line goes out again on the new one")
        XCTAssertTrue(c.isLive)
    }

    func testAWrittenLineTheModelLeavesInTotalSilenceIsPutToItOnceMore() async {
        let patience = Conversation.answerPatience
        Conversation.answerPatience = 0.3
        defer { Conversation.answerPatience = patience }
        let (app, _, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(c, app, link)
        c.send(text: "I do not really know what to do with the evening.")
        try? await Task.sleep(nanoseconds: 1_200_000_000)
        XCTAssertEqual(link.pings, 1)
        XCTAssertEqual(link.turns, ["I do not really know what to do with the evening."], "once, as a whole turn")
        XCTAssertEqual(link.tokens.count, 1, "the socket answered: no reconnect")

        // A line that gets any sign of life is left alone.
        c.send(text: "Thank you.")
        link.event?(.toolCall(id: "f1", name: "feel", args: [:]))
        try? await Task.sleep(nanoseconds: 700_000_000)
        XCTAssertEqual(link.pings, 1)
        XCTAssertEqual(link.turns.count, 1)
    }

    func testANudgeIsHeardOnlyOnceARealWordArrives() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)
        c.nudge("[ten minutes in: you may point out one thing to look for]")
        XCTAssertEqual(link.contexts.last, "[ten minutes in: you may point out one thing to look for]")
        link.event?(.modelOutput); link.event?(.audio(chunk)); link.event?(.audio(chunk)); await settle()
        XCTAssertTrue(audio.played.isEmpty, "held: nothing is heard before the first transcription")
        link.event?(.kaikuText(" ")); await settle()
        XCTAssertTrue(audio.played.isEmpty, "an empty fragment decides nothing")
        link.event?(.kaikuText("Look, ")); await settle()                      // the word arrives late
        XCTAssertEqual(audio.played.count, 2, "the held audio plays, in order")
        link.event?(.audio(chunk)); link.event?(.kaikuText("a red door.")); link.event?(.turnComplete); await settle()
        XCTAssertEqual(audio.played.count, 3)
        XCTAssertEqual(c.lines.last?.text, "Look, a red door.")
    }

    func testADeclinedNudgeMakesNoSoundAndNoBubble() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)
        for marker in ["<no speech>{pause}", "<no speech detected>", "×"] {
            c.nudge("[a nudge]")
            link.event?(.modelOutput); link.event?(.audio(chunk)); link.event?(.kaikuText(marker)); link.event?(.audio(chunk))
            link.event?(.turnComplete); await settle()
        }
        XCTAssertTrue(audio.played.isEmpty, "markers only: the whole turn's audio is dropped")
        XCTAssertTrue(c.lines.isEmpty, "and nothing shows")

        c.nudge("[a nudge]")                                                   // an empty turn
        link.event?(.modelOutput); link.event?(.audio(chunk)); link.event?(.audio(chunk)); link.event?(.turnComplete); await settle()
        XCTAssertTrue(audio.played.isEmpty, "a turn that completes with no transcription is dropped too")

        link.event?(.audio(chunk)); link.event?(.kaikuText("Anyway, how was the walk?")); await settle()
        XCTAssertEqual(audio.played.count, 1, "the next turn is ordinary again")
        XCTAssertTrue(Conversation.hasRealWord("<noise> yes"))
        XCTAssertFalse(Conversation.hasRealWord("<no speech>{pause} ×"))
    }

    func testAnOrdinaryTurnIsNeverGated() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)

        // The person speaks before the nudge's turn began: the gate is cancelled, the answer plays at once.
        c.nudge("[a nudge]")
        link.event?(.userText("Wait, I wanted to ask you something.")); link.event?(.userTranscriptComplete); await settle()
        link.event?(.modelOutput); link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 1, "the answer to the person is not held")
        link.event?(.kaikuText("Of course, ask.")); link.event?(.turnComplete); await settle()

        // The person speaks during a gated turn: what was held is dropped, the answer after the interruption plays.
        c.nudge("[a nudge]")
        link.event?(.modelOutput); link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 1, "held")
        link.event?(.userText("Sorry, one more thing.")); await settle()
        link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 1, "the rest of the gated turn is dropped")
        link.event?(.interrupted); link.event?(.userTranscriptComplete); await settle()
        link.event?(.modelOutput); link.event?(.audio(chunk)); link.event?(.kaikuText("Go on.")); await settle()
        XCTAssertEqual(audio.played.count, 2, "the turn the person started is ordinary")

        // Typing counts as the person's turn too.
        c.nudge("[a nudge]")
        c.send(text: "Typed instead.")
        link.event?(.modelOutput); link.event?(.audio(chunk)); await settle()
        XCTAssertEqual(audio.played.count, 3)
    }

    // MARK: a socket that ends by itself mid-call (a reset, or two minutes of sending nothing while muted)

    func testAMidCallDropComesBackQuietlyOnceThenVisibly() async {
        let (app, audio, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)
        link.event?(.resumable(handle: "h1"))
        link.event?(.kaikuText("Take your time.")); link.event?(.kaikuTranscriptComplete); link.event?(.turnComplete); await settle()
        c.setMuted(true)
        let since = c.liveSince
        var reconnected = 0
        c.onReconnected = { reconnected += 1 }

        link.event?(.closed); await settle()                              // e.g. close 1008 "client inactivity"
        XCTAssertEqual(c.phase, .muted, "nothing on screen changes: not \"connecting\"")
        XCTAssertTrue(c.isLive)
        XCTAssertEqual(link.tokens, ["token-1", "token-1"], "the same token while it lasts, with the resumption handle")
        XCTAssertEqual(CallHTTP.sessions.count, 1, "no new session request")
        link.event?(.ready); await settle()
        XCTAssertEqual(c.phase, .muted, "still muted, as the person left it")
        XCTAssertFalse(audio.mic)
        XCTAssertEqual(c.liveSince, since)
        XCTAssertEqual(reconnected, 0)
        XCTAssertEqual(c.lines.last?.text, "Take your time.")

        // The quiet try does not answer: the next close is an honest, visible reconnect.
        link.event?(.closed); await settle()
        XCTAssertNotEqual(c.phase, .connecting, "first try: quiet")
        link.event?(.closed); await settle()
        XCTAssertEqual(c.phase, .connecting, "second in a row: the person is told")
    }

    func testAResumptionThatKeepsBeingRefusedEndsOnAFreshLineNotInSilence() async {
        func sessions() -> Int { CallHTTP.lock.lock(); defer { CallHTTP.lock.unlock() }; return CallHTTP.sessions.filter { $0.contains("fresh-home") }.count }
        let (app, _, link, c, dir) = fixture(home: "fresh-home")
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)
        link.event?(.resumable(handle: "h1"))
        c.send(text: "My mother would have turned ninety today.")
        link.event?(.modelOutput); link.event?(.kaikuText("That must feel heavy.")); link.event?(.kaikuTranscriptComplete)
        link.event?(.turnComplete); await settle()

        link.event?(.closed); await settle()                              // the quiet try, with the handle
        XCTAssertEqual(link.handles.last ?? nil, "h1")
        link.event?(.closed)                                              // refused: the visible try, with the handle
        try? await Task.sleep(nanoseconds: 1_100_000_000)
        XCTAssertEqual(link.handles.last ?? nil, "h1")
        XCTAssertEqual(sessions(), 1)
        link.event?(.closed)                                              // refused again: a fresh line
        try? await Task.sleep(nanoseconds: 1_600_000_000)
        XCTAssertEqual(sessions(), 2, "a new token is asked for")
        XCTAssertNil(link.handles.last ?? nil, "and the last try carries no handle")
        XCTAssertEqual(c.phase, .connecting)
        link.event?(.ready); await settle()
        XCTAssertTrue(c.isLive, "the call is back instead of \"Kaiku can't talk right now\"")
        let told = link.contexts.last ?? ""
        XCTAssertTrue(told.contains("the person: My mother would have turned ninety today.") && told.contains("you: That must feel heavy."),
                      "Kaiku is told what was just said: \(told)")
        XCTAssertTrue(told.contains("do not greet again"))
        XCTAssertEqual(c.lines.count, 2, "the words on screen stay")
    }

    func testADropBeforeAnyHandleIsAVisibleReconnect() async {
        let (app, _, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)
        link.event?(.closed); await settle()
        XCTAssertEqual(c.phase, .connecting, "nothing to resume from: an ordinary reconnect")
    }

    // MARK: a long call moves to the next token without anyone noticing

    func testThePlannedResumeAtTheTokensEndIsSeamless() async {
        Conversation.resumeMargin = 0.2
        let soon = ISO8601DateFormatter().string(from: Date().addingTimeInterval(1.5))
        CallHTTP.lock.lock(); CallHTTP.expires = soon; CallHTTP.lock.unlock()
        let (app, _, link, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir); c.stop() }
        await open(c, app, link)
        link.event?(.resumable(handle: "h1"))
        link.event?(.kaikuText("We were talking about the lake.")); link.event?(.kaikuTranscriptComplete); link.event?(.turnComplete); await settle()
        let since = c.liveSince
        var phases: [Conversation.Phase] = []
        var reconnected = 0
        c.onReconnected = { reconnected += 1 }
        let watch = Task { @MainActor in
            for _ in 0..<60 { phases.append(c.phase); try? await Task.sleep(nanoseconds: 50_000_000) }
        }
        try? await Task.sleep(nanoseconds: 2_200_000_000)
        XCTAssertEqual(link.tokens, ["token-1", "token-2"], "the cloud minted the next token and the call moved to it")
        XCTAssertTrue(CallHTTP.sessions.last?.contains(#""resume_session_id":"call-session""#) == true)
        link.event?(.ready); await settle()
        await watch.value
        XCTAssertFalse(phases.contains(.connecting), "no reconnecting drama")
        XCTAssertFalse(phases.contains(.unavailable))
        XCTAssertEqual(c.lines.first?.text, "We were talking about the lake.", "the captions stay")
        XCTAssertEqual(c.liveSince, since, "the call's clock keeps counting")
        XCTAssertEqual(reconnected, 0, "not a reconnect: nothing is re-sent")
        XCTAssertEqual(c.session?.idle_end_s, 180)
        // Typed while the call is between sockets: held, and sent once the new one answers.
        link.event?(.goAway); await settle()
        try? await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertEqual(link.tokens.count, 3, "the server's go-away moves the call the same quiet way")
        c.send(text: "Typed during the switch.")
        XCTAssertFalse(link.text.contains("Typed during the switch."))
        link.event?(.ready); await settle()
        XCTAssertEqual(link.text.last, "Typed during the switch.")
        XCTAssertEqual(c.lines.last?.text, "Typed during the switch.")
    }
}

/// The walk's Lock Screen and Dynamic Island say the spotting game's own thing and target, or nothing about a game.
final class WalkSurfaceTests: XCTestCase {
    func testTheWalkSurfacesShowTheGoalsOwnThingAndTargetOrNothing() throws {
        let trees = try XCTUnwrap(WalkGoalLine(thing: "Trees", target: 3, found: 1))
        XCTAssertEqual(trees.text(.en), "Trees 1 of 3")
        XCTAssertEqual(WalkGoalLine(thing: "Red doors", target: 5, found: 9)?.text(.en), "Red doors 5 of 5", "never past its target")
        XCTAssertNil(WalkGoalLine(thing: nil, target: nil, found: 0), "no game on: nothing about a goal")
        XCTAssertNil(WalkGoalLine(thing: "Trees", target: nil, found: 2))
        XCTAssertNil(WalkGoalLine(thing: "", target: 3, found: 0))
        #if os(iOS)
        // An activity started by an older build (no goal fields) still decodes.
        let old = try JSONDecoder().decode(WalkActivityAttributes.ContentState.self, from: Data(#"{"minutes":4,"found":1,"glasses":false}"#.utf8))
        XCTAssertNil(old.thing)
        #endif
    }
}

/// The moving lines beside "Listening" (`CallWave`): they must visibly move while the microphone is open, follow
/// the voice, and stay inside their box.
final class CallWaveTests: XCTestCase {
    func testAQuietRoomStillMovesWhileListening() {
        let heights = stride(from: 0.0, to: 2.0, by: 0.05).map { CallWave.height(line: 2, voice: 0, time: $0, moving: true) }
        XCTAssertGreaterThan(heights.max()! - heights.min()!, 1.0, "a quiet, open microphone should still show movement")
        XCTAssertTrue(heights.allSatisfy { $0 >= 3 && $0 <= 14 })
    }

    func testAVoiceLiftsTheLines() {
        for i in 0..<5 {
            let quiet = (0..<40).map { CallWave.height(line: i, voice: 0, time: Double($0) * 0.05, moving: true) }.max()!
            let loud = (0..<40).map { CallWave.height(line: i, voice: 1, time: Double($0) * 0.05, moving: true) }.max()!
            XCTAssertGreaterThan(loud, quiet + 2, "line \(i)")
            XCTAssertLessThanOrEqual(loud, 14)
        }
    }

    func testStillWhenNotMoving() {
        // Reduce Motion, or a state that is not listening or speaking: the same height at every moment, and only
        // the dot it rests as when there is no voice.
        let a = CallWave.height(line: 1, voice: 0.6, time: 0.1, moving: false)
        let b = CallWave.height(line: 1, voice: 0.6, time: 7.3, moving: false)
        XCTAssertEqual(a, b)
        XCTAssertEqual(CallWave.height(line: 1, voice: 0, time: 3, moving: false), 3)
    }

    func testLevelMapping() {
        XCTAssertEqual(CallStatus.level(db: -90), 0)
        XCTAssertEqual(CallStatus.level(db: 0), 1)
        XCTAssertEqual(CallStatus.level(db: -35), 0.5, accuracy: 0.001)
    }
}

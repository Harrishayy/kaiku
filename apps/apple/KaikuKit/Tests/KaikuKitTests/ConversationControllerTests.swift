@preconcurrency import AVFoundation
import XCTest
@testable import KaikuKit

private final class ControllerAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying = false
    var mic = false
    var running = false
    var played: [Data] = []
    func start() throws { running = true }
    func stop() { running = false; mic = false }
    func setMic(_ on: Bool) { mic = on }
    func play(_ pcm: Data) { played.append(pcm); isPlaying = true; onPlaying?(true) }
    func flush() { isPlaying = false; onPlaying?(false) }
}
private final class ControllerTransport: ConversationTransport, @unchecked Sendable {
    var event: (@Sendable (LiveSession.Event) -> Void)?
    var sent: [Data] = []
    var text: [String] = []
    var results: [String] = []
    var contexts: [String] = []
    var closed = false
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) {}
    func close() { closed = true }
    func sendAudio(_ pcm: Data) { sent.append(pcm) }
    func audioStreamEnd() {}
    func sendText(_ text: String) { self.text.append(text) }
    func sendContext(_ event: String) { contexts.append(event) }
    func respond(id: String, name: String, result: JSONValue) { results.append(name) }
}
/// Counts provider turn boundaries independently of playback buffers. Audio arrival is not completion.
private final class LiveTurnProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    private var inputCount = 0
    private var outputCount = 0
    var inputFinished: Int { lock.lock(); defer { lock.unlock() }; return inputCount }
    var outputFinished: Int { lock.lock(); defer { lock.unlock() }; return outputCount }
    var completed: Int { lock.lock(); defer { lock.unlock() }; return count }
    func receive(_ event: LiveSession.Event) {
        lock.lock(); defer { lock.unlock() }
        switch event {
        case .turnComplete: count += 1
        case .userTranscriptComplete: inputCount += 1
        case .kaikuTranscriptComplete: outputCount += 1
        default: break
        }
    }
}

private final class ConversationHTTP: URLProtocol {
    static let lock = NSLock()
    nonisolated(unsafe) static var offlineEpisodes = false
    nonisolated(unsafe) static var sessionLimit: Int?
    nonisolated(unsafe) static var sessionExtra: String?
    nonisolated(unsafe) static var eventsJSON = #"{"events":[]}"#
    nonisolated(unsafe) static var holdMemories = false
    nonisolated(unsafe) static var heldMemory: (() -> Void)?
    nonisolated(unsafe) static var requests: [(String, String?, Data)] = []
    static var hasHeldMemory: Bool { lock.lock(); defer { lock.unlock() }; return heldMemory != nil }
    static func releaseMemory() { lock.lock(); let response = heldMemory; heldMemory = nil; lock.unlock(); response?() }
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
        Self.requests.append((path, request.value(forHTTPHeaderField: "Authorization"), data))
        let offline = Self.offlineEpisodes
        Self.lock.unlock()
        if offline && path.hasSuffix("episode") { client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)); return }
        var json: String
        if path.hasSuffix("session") {
            json = #"{"session_id":"controller-session","model":"test-model","voice":"test-voice","system_instruction":"test","tools":[],"context_card":{"time_of_day":"morning"},"persona_version":"p","safety_phrases_version":"s","live_token":{"token":"synthetic-token","expires_at":"2099-01-01T00:00:00Z","new_session_expires_at":"2099-01-01T00:00:00Z"}}"#
        } else if path.hasSuffix("tool") {
            json = #"{"ok":true,"name":"end_session","result":{"ok":true}}"#
        } else if path.hasSuffix("episode") {
            json = #"{"ok":true,"id":"controller-session","transcript_stored":true}"#
        } else if path.hasSuffix("transcripts"), request.httpMethod == "GET" {
            json = #"{"home_id":"synthetic","transcripts":[{"episode_id":"saved-one","surface":"iphone","intent":"talk","start":"2026-11-14T00:00:00Z","turns":[{"role":"person","text":"A quiet walk"},{"role":"kaiku","text":"What stood out to you?"}]}]}"#
        } else if path.hasSuffix("transcripts"), request.httpMethod == "DELETE" {
            json = #"{"deleted":1}"#
        } else if path.hasSuffix("memories") {
            json = #"{"home_id":"synthetic","remember":false,"memories":[{"id":1,"category":"name","text":"Old home name","created":"2026-11-14T00:00:00Z"}]}"#
        } else if path.hasSuffix("events"), request.httpMethod == "GET" { json = Self.eventsJSON }
        else { json = #"{"accepted":1,"duplicates":0,"rejected":[]}"# }
        if path.hasSuffix("session"), let limit = Self.sessionLimit {
            json.removeLast(); json += ",\"max_session_seconds\":\(limit)}"
        }
        if path.hasSuffix("session"), let extra = Self.sessionExtra {
            json.removeLast(); json += ",\(extra)}"
        }
        if path.hasSuffix("memories"), Self.holdMemories {
            let response = json
            Self.lock.lock(); Self.heldMemory = { [self] in deliver(response) }; Self.lock.unlock()
            return
        }
        deliver(json)
    }
    private func deliver(_ json: String) {
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor final class ConversationControllerTests: XCTestCase {
    private var grace: TimeInterval = 0
    // These tests end conversations on purpose-built fakes: no goodbye is playing, so nothing needs waiting for.
    override func setUp() async throws { grace = Conversation.closeGrace; Conversation.closeGrace = 0 }
    override func tearDown() async throws { Conversation.closeGrace = grace }

    private func fixture() -> (AppModel, ControllerAudio, ControllerTransport, Conversation, URL) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let p = Pairing(baseURL: URL(string: "https://controller.test")!, homeID: "synthetic", token: "synthetic-pairing-token")
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ConversationHTTP.self]
        let api = APIClient(pairing: p, maxAttempts: 1, session: URLSession(configuration: config))
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        let app = AppModel(defaults: defaults, pairing: p, api: api, queue: OfflineQueue(url: dir.appendingPathComponent("events.json")),
                           episodes: EpisodeOutbox(url: dir.appendingPathComponent("episodes.json")))
        let audio = ControllerAudio(), live = ControllerTransport()
        let conversation = Conversation(surface: .iphone, intent: .talk, audio: audio,
            transport: { event in live.event = event; return live }, permission: { true }, localListener: false)
        ConversationHTTP.lock.lock(); ConversationHTTP.requests = []; ConversationHTTP.offlineEpisodes = false; ConversationHTTP.sessionLimit = nil; ConversationHTTP.sessionExtra = nil; ConversationHTTP.eventsJSON = #"{"events":[]}"#; ConversationHTTP.holdMemories = false; ConversationHTTP.heldMemory = nil; ConversationHTTP.lock.unlock()
        return (app, audio, live, conversation, dir)
    }
    private func settle() async { try? await Task.sleep(nanoseconds: 50_000_000) }

    func testActualControllerStreamsMicPlaysReplyMutesPausesAndDurablyCompletes() async throws {
        let (app, audio, live, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        app.consents[.transcripts] = true
        let started = await c.start(app: app); XCTAssertTrue(started)
        let pcm = Data([0, 1, 0, 2])
        audio.onPCM?(pcm); await settle(); XCTAssertTrue(live.sent.isEmpty, "setup must finish before capturing")
        live.event?(.ready); await settle()
        XCTAssertTrue(audio.mic)
        audio.onPCM?(pcm); await settle(); XCTAssertEqual(live.sent, [pcm], "production controller must wire capture into Live")
        live.event?(.audio(pcm)); await settle(); XCTAssertTrue(audio.played.isEmpty, "a turn of Kaiku's own is held until its first real word")
        live.event?(.kaikuText("Hello. ")); await settle(); XCTAssertEqual(audio.played, [pcm])
        live.event?(.interrupted); await settle(); XCTAssertFalse(audio.isPlaying)
        c.setMuted(true); audio.onPCM?(pcm); await settle(); XCTAssertEqual(live.sent.count, 1)
        c.pause(); c.setMuted(false); audio.onPCM?(pcm); await settle(); XCTAssertEqual(c.phase, .paused); XCTAssertEqual(live.sent.count, 1)
        c.resume(); audio.onPCM?(pcm); await settle(); XCTAssertEqual(live.sent.count, 2)
        live.event?(.userText("A pleasant walk today.")); live.event?(.kaikuText("I'm glad you enjoyed it.")); await settle()
        ConversationHTTP.offlineEpisodes = true
        live.event?(.toolCall(id: "end", name: "end_session", args: [:])); await settle()
        XCTAssertEqual(c.phase, .idle); XCTAssertTrue(live.closed); XCTAssertFalse(audio.running)
        XCTAssertEqual(app.episodes.entries.count, 1)
        let reloaded = EpisodeOutbox(url: dir.appendingPathComponent("episodes.json"))
        XCTAssertEqual(reloaded.entries.first?.episode.transcript?.count, 2)
        XCTAssertEqual(reloaded.entries.first?.episode.outcome, .completed)
        ConversationHTTP.offlineEpisodes = false
        let flushed = await reloaded.flush(using: app.api); XCTAssertTrue(flushed); XCTAssertTrue(reloaded.entries.isEmpty)
        XCTAssertTrue(ConversationHTTP.requests.allSatisfy { $0.1 == "Bearer synthetic-pairing-token" })
        audio.onPCM?(pcm); await settle(); XCTAssertEqual(live.sent.count, 2)
    }

    func testUnpairedVoiceExplainsConnectionBeforeRequestingMicrophone() async {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: nil, api: APIClient(pairing: nil),
                           queue: OfflineQueue(url: directory.appendingPathComponent("events.json")),
                           episodes: EpisodeOutbox(url: directory.appendingPathComponent("episodes.json")))
        let audio = ControllerAudio(), live = ControllerTransport()
        var microphoneRequested = false
        let c = Conversation(surface: .iphone, intent: .talk, audio: audio, transport: { event in live.event = event; return live },
                             permission: { microphoneRequested = true; return true }, localListener: false)
        let started = await c.start(app: app)
        XCTAssertFalse(started); XCTAssertFalse(microphoneRequested); XCTAssertFalse(audio.running)
        XCTAssertEqual(c.unavailableReason, .pairing)
    }

    func testAudioRouteFailureStopsSessionHonestly() async throws {
        let (app, audio, live, c, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        _ = await c.start(app: app); live.event?(.ready); await settle()
        audio.onFailure?(); await settle()
        XCTAssertEqual(c.phase, .unavailable); XCTAssertTrue(live.closed); XCTAssertFalse(audio.running)
    }

    func testGlobalPrivacyPauseStopsLiveWithoutAnotherAudioFrameAndRequiresExplicitRestart() async throws {
        let (app, audio, live, c, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        ConversationHTTP.offlineEpisodes = true
        _ = await c.start(app: app); live.event?(.ready); await settle()
        XCTAssertTrue(audio.running); XCTAssertTrue(audio.mic)
        app.pausedAll = true
        await settle()
        XCTAssertTrue(live.closed); XCTAssertFalse(audio.running); XCTAssertFalse(audio.mic)
        XCTAssertEqual(c.unavailableReason, .paused)
        XCTAssertEqual(app.episodes.entries.first?.episode.outcome, .ended_early)
        audio.onPCM?(Data([1, 0])); await settle(); XCTAssertTrue(live.sent.isEmpty)
        app.pausedAll = false
        await settle(); XCTAssertFalse(audio.running, "privacy stop must not reopen the microphone automatically")
    }

    func testPausedStartDoesNotRequestAudioOrMintSession() async {
        let (app, audio, _, c, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        app.pausedUntil = Date().addingTimeInterval(3600)
        let started = await c.start(app: app)
        XCTAssertFalse(started); XCTAssertFalse(audio.running); XCTAssertEqual(c.unavailableReason, .paused)
        XCTAssertFalse(ConversationHTTP.requests.contains { $0.0.hasSuffix("session") })
    }

    func testWalkUploadsRequireOriginalHomeAndOriginAndDraftNeverContainsToken() async throws {
        let (app, _, _, _, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        let original = app.pairing!
        let outing = Outing(minutes: 12, method: .steps)
        let wrongHome = WalkModel.WalkScope(Pairing(baseURL: original.baseURL, homeID: "another-home", token: nil))
        let wrongServer = WalkModel.WalkScope(Pairing(baseURL: URL(string: "https://another.test")!, homeID: original.homeID, token: nil))
        for scope in [wrongHome, wrongServer] {
            let sent = await WalkModel.emitOuting(outing, id: UUID7.make(), start: Date(), simulated: false, scope: scope, app: app)
            XCTAssertFalse(sent)
        }
        XCTAssertFalse(ConversationHTTP.requests.contains { $0.0 == "/v1/events" })
        let scope = WalkModel.WalkScope(original)
        let draft = WalkModel.Draft(id: UUID7.make(), start: Date(), lastSeen: Date(), outing: outing, scope: scope)
        let data = try JSONEncoder().encode(draft)
        XCTAssertFalse(String(decoding: data, as: UTF8.self).contains(original.token!))
        let url = dir.appendingPathComponent("walk.json")
        try data.write(to: url)
        await WalkModel.recover(app: app, from: url)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
        let posts = ConversationHTTP.requests.filter { $0.0 == "/v1/events" }
        XCTAssertEqual(posts.count, 1)
        let body = try JSONSerialization.jsonObject(with: posts[0].2) as! [String: Any]
        let event = (body["events"] as! [[String: Any]])[0]
        XCTAssertEqual(event["id"] as? String, draft.id)
        XCTAssertEqual(event["home_id"] as? String, original.homeID)
    }

    func testWalkRecoveryQuarantinesDifferentHomeOriginAndLegacyDrafts() async throws {
        let (app, _, _, _, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        let original = app.pairing!
        let scopes: [WalkModel.WalkScope?] = [nil,
            WalkModel.WalkScope(Pairing(baseURL: original.baseURL, homeID: "another-home", token: nil)),
            WalkModel.WalkScope(Pairing(baseURL: URL(string: "https://another.test")!, homeID: original.homeID, token: nil))]
        for scope in scopes {
            let draft = WalkModel.Draft(id: UUID7.make(), start: Date(), lastSeen: Date(), outing: Outing(minutes: 12, method: .steps), scope: scope)
            let url = dir.appendingPathComponent("walk.json")
            try JSONEncoder().encode(draft).write(to: url)
            await WalkModel.recover(app: app, from: url)
            XCTAssertTrue(FileManager.default.fileExists(atPath: url.path), "draft remains local until its original pairing returns")
        }
        XCTAssertFalse(ConversationHTTP.requests.contains { $0.0 == "/v1/events" })
    }

    func testPairingChangeClearsPrivateCacheAndRejectsDelayedOldNotebookResponse() async throws {
        let (app, _, _, _, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        app.me = try JSONDecoder().decode(MeResponse.self, from: Data(#"{"home_id":"synthetic","summary":"old private summary","garden":{"plants":3},"highlights":[{"date":"2026-11-14","kind":"good","text":"old private moment","source":"phone"}]}"#.utf8))
        app.memories = [Memory(id: 1, category: .name, text: "Old home name", created: "2026-11-14T00:00:00Z")]
        app.nudge = NudgeResponse(arm: .breathe, reason: "old home suggestion")
        app.conversationsKept = 4; app.memoriesLoaded = true; app.remember = false; app.healthState = .connected
        app.marks = ["2026-11-14": .good]; app.playedDays = ["tell": "2026-11-14"]; app.weatherDoneDay = "2026-11-14"
        app.phq9Requested = true; app.showCrisis = true; app.toast = "old household message"
        app.language = .fi; app.pace = .slow
        ConversationHTTP.holdMemories = true
        let read = Task { await app.loadMemories() }
        let deadline = Date().addingTimeInterval(2)
        while !ConversationHTTP.hasHeldMemory && Date() < deadline { await settle() }
        XCTAssertTrue(ConversationHTTP.hasHeldMemory)
        let next = Pairing(baseURL: URL(string: "https://another.test")!, homeID: "another-home", token: "new-synthetic-token")
        await app.updatePairing(next)
        XCTAssertNil(app.me); XCTAssertNil(app.nudge); XCTAssertTrue(app.memories.isEmpty)
        XCTAssertNil(app.conversationsKept); XCTAssertFalse(app.memoriesLoaded); XCTAssertTrue(app.remember)
        XCTAssertEqual(app.healthState, .off); XCTAssertTrue(app.marks.isEmpty); XCTAssertTrue(app.playedDays.isEmpty)
        XCTAssertNil(app.weatherDoneDay); XCTAssertFalse(app.phq9Requested); XCTAssertFalse(app.showCrisis); XCTAssertNil(app.toast)
        XCTAssertEqual(app.language, .en); XCTAssertEqual(app.pace, .slow)
        ConversationHTTP.releaseMemory(); await read.value
        XCTAssertTrue(app.memories.isEmpty, "a late old-home response must not repopulate the new home's notebook")
        XCTAssertFalse(app.memoriesLoaded); XCTAssertTrue(app.remember)
        await app.updatePairing(nil)
    }

    func testPairingChangeClosesLiveAndClearsVisiblePrivateConversation() async {
        let (app, audio, live, c, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        _ = await c.start(app: app); live.event?(.ready); await settle()
        c.send(text: "Private words for the original home")
        XCTAssertFalse(c.lines.isEmpty)
        let next = Pairing(baseURL: app.pairing!.baseURL, homeID: "another-home", token: nil)
        await app.updatePairing(next); await settle()
        XCTAssertTrue(live.closed); XCTAssertFalse(audio.running); XCTAssertTrue(c.lines.isEmpty)
        XCTAssertEqual(c.unavailableReason, .pairing)
    }

    func testDelayedHealthQueryCannotUploadAfterHomeOrOriginSwitch() async {
        for differentOrigin in [false, true] {
            let (app, _, _, _, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
            app.consents[.watch] = true
            let original = app.pairing!
            let next = Pairing(baseURL: differentOrigin ? URL(string: "https://another.test")! : original.baseURL,
                               homeID: differentOrigin ? original.homeID : "another-home", token: nil)
            var queries = 0
            await HealthDelivery.sync(app: app) { _ in
                queries += 1
                await app.updatePairing(next)
                var value = WearableDaily(date: "2026-11-14", device: .apple_watch); value.steps = 3000
                return value
            }
            XCTAssertEqual(queries, 1, "stop querying the old health snapshot after destination changes")
            XCTAssertEqual(app.healthState, .off)
            XCTAssertFalse(ConversationHTTP.requests.contains { $0.0 == "/v1/events" })
        }
    }

    func testHealthDeliveryRechecksConsentAndKeepsOriginalHomeForValidSummaries() async throws {
        let (app, _, _, _, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        app.consents[.watch] = true
        await HealthDelivery.sync(app: app) { morning in
            var value = WearableDaily(date: AppModel.dayKey(morning), device: .apple_watch); value.steps = 3000
            return value
        }
        let posts = ConversationHTTP.requests.filter { $0.0 == "/v1/events" }
        XCTAssertEqual(posts.count, 2); XCTAssertEqual(app.healthState, .connected)
        for post in posts {
            let body = try JSONSerialization.jsonObject(with: post.2) as! [String: Any]
            let event = (body["events"] as! [[String: Any]])[0]
            XCTAssertEqual(event["home_id"] as? String, "synthetic")
            XCTAssertEqual(event["type"] as? String, "obs.wearable_daily")
        }
        let count = posts.count
        await HealthDelivery.sync(app: app) { morning in
            app.consents[.watch] = false
            return WearableDaily(date: AppModel.dayKey(morning), device: .apple_watch)
        }
        XCTAssertEqual(ConversationHTTP.requests.filter { $0.0 == "/v1/events" }.count, count)
    }

    /// D60: a visible expression cue reaches Kaiku as ONE fixed sentence, only in a quiet moment, only in a check-in
    /// the service allowed it for, only with the camera choice on; a cue that finds no quiet moment is dropped.
    func testAnExpressionCueIsHandedOverOnlyWhenBothSidesAreQuietAndOnlyAsTheFixedSentence() async throws {
        let (app, audio, live, _, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        app.consents[.camera] = true; app.cameraChoice.agree()
        func checkIn() -> Conversation {
            Conversation(surface: .iphone, intent: .checkin, audio: audio,
                         transport: { event in live.event = event; return live }, permission: { true }, localListener: false,
                         purpose: .check_in)
        }
        // The service did not send the thresholds: nothing is ever handed over.
        var c = checkIn()
        _ = await c.start(app: app); live.event?(.ready); await settle()
        c.expressionCue(.lower); await settle()
        XCTAssertTrue(live.contexts.filter { ExpressionCueText.all.contains($0) }.isEmpty)
        c.stop(); await settle()

        ConversationHTTP.sessionExtra = #""expression_cue":{"enabled":true,"speak":true}"#
        live.contexts = []
        c = checkIn()
        _ = await c.start(app: app); live.event?(.ready); await settle()
        let before = live.contexts.count
        live.event?(.audio(Data([0, 0]))); live.event?(.kaikuText("One moment. ")); live.event?(.turnComplete); await settle()
        c.expressionCue(.lower); await settle()
        XCTAssertEqual(live.contexts.count, before, "Kaiku is speaking: it waits")
        XCTAssertFalse(c.handCue(now: Date()))
        audio.flush(); await settle()
        XCTAssertTrue(c.handCue(now: Date()) || live.contexts.count == before + 1)
        XCTAssertEqual(live.contexts.count, before + 1)
        XCTAssertEqual(live.contexts.last, ExpressionCueText.text(.lower), "the fixed sentence and nothing else")
        XCTAssertEqual(c.cuesHanded, 1)
        XCTAssertFalse(c.handCue(now: Date()), "once")

        // A cue that found no quiet moment in time is dropped, not sent late.
        live.event?(.audio(Data([0, 0]))); live.event?(.kaikuText("And another thing. ")); live.event?(.turnComplete); await settle()
        c.expressionCue(.tense, now: Date().addingTimeInterval(-ExpressionCueText.staleAfter - 1))
        audio.flush(); await settle()
        XCTAssertFalse(c.handCue(now: Date()))
        XCTAssertEqual(live.contexts.count, before + 1)

        // The camera choice was withdrawn: nothing more crosses.
        app.consents[.camera] = false
        c.expressionCue(.brighter); await settle()
        XCTAssertEqual(live.contexts.count, before + 1)
        c.stop()
    }

    func testNewSourceContextWaitsForQuietAndContainsNoPayload() async throws {
        let (app, audio, live, c, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        _ = await c.start(app: app); live.event?(.ready); await settle()
        ConversationHTTP.eventsJSON = #"{"events":[{"v":1,"id":"event1","ts":"2026-11-14T00:00:00Z","home_id":"synthetic","source":"hub","type":"obs.self_report","sim":false,"payload":{"item":"mood","value":1,"private":"sensitive words"}}]}"#
        live.event?(.audio(Data([0, 0]))); live.event?(.kaikuText("One moment. ")); live.event?(.turnComplete); await settle()
        await c.refreshContext(); XCTAssertTrue(live.contexts.isEmpty)
        audio.flush(); await settle()
        XCTAssertEqual(live.contexts.count, 1)
        XCTAssertTrue(live.contexts[0].contains("home robot"))
        XCTAssertTrue(live.contexts[0].contains("ask_mind"))
        XCTAssertFalse(live.contexts[0].contains("mood")); XCTAssertFalse(live.contexts[0].contains("sensitive words"))
        await c.refreshContext(); XCTAssertEqual(live.contexts.count, 1, "new observation acknowledged once")
        c.stop()
    }

    func testCloudDurationLimitClosesCaptureAndQueuesEpisode() async throws {
        let (app, audio, live, c, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        ConversationHTTP.sessionLimit = 1; ConversationHTTP.offlineEpisodes = true
        _ = await c.start(app: app); live.event?(.ready); await settle()
        try await Task.sleep(nanoseconds: 1_100_000_000)
        XCTAssertTrue(live.closed); XCTAssertFalse(audio.running)
        XCTAssertEqual(app.episodes.entries.first?.episode.outcome, .ended_early)
    }

    func testReconnectBootstrapsSameEpisode() async throws {
        let (app, _, live, c, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        _ = await c.start(app: app); live.event?(.ready); await settle()
        live.event?(.goAway); try await Task.sleep(nanoseconds: 600_000_000)
        let sessions = ConversationHTTP.requests.filter { $0.0.hasSuffix("session") }
        XCTAssertEqual(sessions.count, 2)
        let body = try JSONSerialization.jsonObject(with: sessions.last!.2) as! [String: Any]
        XCTAssertEqual(body["resume_session_id"] as? String, "controller-session")
        c.stop()
    }

    func testObservationOutboxNeverCrossesServerOrHome() async throws {
        let (app, _, _, _, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        let event = try AnyEnvelope(Envelope(home_id: "synthetic", source: .phone, type: "obs.self_report",
                                            payload: SelfReport(item: .mood, value: 3, channel: .phone)))
        await app.queue.enqueue(event, server: URL(string: "https://other-server.test")!)
        await app.flush()
        let pending = await app.queue.count
        XCTAssertEqual(pending, 1)
        XCTAssertFalse(ConversationHTTP.requests.contains { $0.0 == "/v1/events" })
    }

    func testCrisisStopsBeforeModelAndDoesNotPersistWords() async throws {
        let (app, audio, live, c, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        app.consents[.transcripts] = true; ConversationHTTP.offlineEpisodes = true
        _ = await c.start(app: app); live.event?(.ready); await settle()
        c.send(text: "I want to kill myself")
        await settle()
        XCTAssertTrue(live.closed); XCTAssertFalse(audio.running); XCTAssertTrue(live.text.isEmpty)
        XCTAssertEqual(app.episodes.entries.first?.episode.outcome, .crisis)
        XCTAssertNil(app.episodes.entries.first?.episode.transcript)
    }

    func testDialConsentAndTranscriptRevocationAndScope() async throws {
        let (app, _, live, c, dir) = fixture(); defer { try? FileManager.default.removeItem(at: dir) }
        app.pausedAll = true
        let paused = await app.recordDial(item: .mood, value: 3); XCTAssertFalse(paused)
        app.pausedAll = false; app.consents[.checkins] = false
        let optedOut = await app.recordDial(item: .mood, value: 3); XCTAssertFalse(optedOut)
        app.consents[.transcripts] = true; ConversationHTTP.offlineEpisodes = true
        _ = await c.start(app: app); live.event?(.ready); await settle()
        c.send(text: "I enjoyed the park."); c.stop(); await settle()
        XCTAssertNotNil(app.episodes.entries.first?.episode.transcript)
        app.consents[.transcripts] = false
        XCTAssertNil(app.episodes.entries.first?.episode.transcript)
        let other = Pairing(baseURL: URL(string: "https://other.test")!, homeID: "synthetic", token: nil)
        await app.api.setPairing(other); ConversationHTTP.offlineEpisodes = false
        _ = await app.episodes.flush(using: app.api)
        XCTAssertEqual(app.episodes.entries.count, 1, "never replay a home conversation to another server")
    }
    /// Opt-in real service check: only the capture/playback edge is synthetic; production Conversation,
    /// LiveSession, authenticated APIClient, tool dispatcher and durable episode outbox all run unchanged.
    func testRealCloudAndGeminiThroughActualController() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let cloud = env["KAIKU_CONTROLLER_TEST_CLOUD"], let url = URL(string: cloud),
              let path = env["KAIKU_CONTROLLER_TEST_SPEECH"] else {
            throw XCTSkip("Set KAIKU_CONTROLLER_TEST_CLOUD and KAIKU_CONTROLLER_TEST_SPEECH for paid integration")
        }
        let surfaceName = env["KAIKU_CONTROLLER_TEST_SURFACE"] ?? "iphone"
        guard ["iphone", "mac"].contains(surfaceName), let surface = CompanionSurface(rawValue: surfaceName) else {
            XCTFail("KAIKU_CONTROLLER_TEST_SURFACE must be iphone or mac"); return
        }
        let speech = try Data(contentsOf: URL(fileURLWithPath: path))
        guard speech.count > 32000, speech.contains(where: { $0 != 0 }) else {
            XCTFail("synthetic speech must contain at least one second of non-silent 16 kHz PCM before minting a session")
            return
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("controller-real-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let pairing = Pairing(baseURL: url, homeID: env["KAIKU_CONTROLLER_TEST_HOME"] ?? "demo-aino",
                              token: env["KAIKU_CONTROLLER_TEST_TOKEN"])
        let api = APIClient(pairing: pairing, timeout: 30)
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: pairing, api: api,
                           queue: OfflineQueue(url: directory.appendingPathComponent("events.json")),
                           episodes: EpisodeOutbox(url: directory.appendingPathComponent("episodes.json")))
        app.consents[.transcripts] = true
        let audio = ControllerAudio()
        let turnProbe = LiveTurnProbe()
        let c = Conversation(surface: surface, intent: .talk, audio: audio,
                             transport: { onEvent in LiveSession(onEvent: { event in
                                 turnProbe.receive(event); onEvent(event)
                             }) }, permission: { true }, localListener: false)
        defer { c.stop() }
        let started = await c.start(app: app); guard started else { XCTFail("real session bootstrap unavailable"); return }
        let readyDeadline = Date().addingTimeInterval(15)
        while c.phase == .connecting && Date() < readyDeadline { await settle() }
        XCTAssertTrue(c.isLive); XCTAssertTrue(audio.mic, "Gemini setup must acknowledge before mic streams")
        for offset in stride(from: 0, to: speech.count, by: 3200) {
            audio.onPCM?(speech.subdata(in: offset..<min(offset + 3200, speech.count)))
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        for _ in 0..<20 { audio.onPCM?(Data(count: 3200)); try await Task.sleep(nanoseconds: 100_000_000) }
        let answerDeadline = Date().addingTimeInterval(30)
        while Date() < answerDeadline && (!c.lines.contains(where: \.me) || audio.played.isEmpty || turnProbe.completed < 1 || turnProbe.inputFinished < 1 || turnProbe.outputFinished < 1 || c.hasPendingTranscription) { await settle() }
        XCTAssertTrue(c.lines.contains(where: \.me), "speech must reach Gemini through Conversation.onPCM")
        XCTAssertFalse(audio.played.isEmpty, "Gemini voice must reach Conversation playback")
        XCTAssertGreaterThanOrEqual(turnProbe.completed, 1, "finish the initial provider turn before asking the mind")
        var mindResult: CompanionToolResult?
        var audioAtMindResult = Int.max
        XCTAssertGreaterThanOrEqual(turnProbe.inputFinished, 1, "input transcription must be explicitly final")
        XCTAssertGreaterThanOrEqual(turnProbe.outputFinished, 1, "output transcription must be explicitly final")
        var completedAtMindResult = Int.max
        var outputFinishedAtMindResult = Int.max
        c.onToolResult = { name, result in
            if name == "ask_mind" {
                mindResult = result; audioAtMindResult = audio.played.count
                completedAtMindResult = turnProbe.completed
                outputFinishedAtMindResult = turnProbe.outputFinished
            }
        }
        c.send(text: "Please use ask_mind to suggest a gentle activity for this afternoon based on what you know about me.")
        let mindDeadline = Date().addingTimeInterval(125)
        while Date() < mindDeadline && (mindResult == nil || audio.played.count <= audioAtMindResult || turnProbe.completed <= completedAtMindResult || turnProbe.outputFinished <= outputFinishedAtMindResult || c.hasPendingTranscription) { await settle() }
        XCTAssertTrue(c.toolsUsed.contains("ask_mind"), "voice companion must reach the cloud intelligence tool")
        XCTAssertEqual(mindResult?.ok, true, "cloud intelligence must return successfully")
        XCTAssertEqual(mindResult?.result?["route"]?.string, "gemma", "reasoning must come from primary Gemma, not a fallback")
        XCTAssertGreaterThan(audio.played.count, audioAtMindResult, "Gemini must voice an answer AFTER the mind result")
        XCTAssertGreaterThan(turnProbe.completed, completedAtMindResult,
                             "wait for the explicit provider turnComplete after the mind result, not its first audio chunk")
        XCTAssertGreaterThan(turnProbe.outputFinished, outputFinishedAtMindResult,
                             "audio turnComplete cannot stand in for final output transcription")
        XCTAssertFalse(c.hasPendingTranscription, "all transcription callbacks must be consumed before storing")
        let episodeID = c.session?.session_id
        let expectedTurns = Conversation.transcript(c.lines)
        XCTAssertTrue(expectedTurns.contains { $0.role == .kaiku })
        c.stop(); await app.flush()
        let flushDeadline = Date().addingTimeInterval(10)
        while !app.episodes.entries.isEmpty && Date() < flushDeadline { await settle(); await app.flush() }
        XCTAssertTrue(app.episodes.entries.isEmpty, "completion must be acknowledged by real cloud")
        let stored = try await api.transcripts()
        let retained = stored.transcripts.first { $0.episode_id == episodeID }
        XCTAssertEqual(retained?.surface, surface)
        XCTAssertEqual(retained?.turns, expectedTurns, "retained turn text and speaker boundaries must match the controller")
        print("SYNTHETIC_CONTROLLER_PROOF surface=\(surfaceName) route=\(mindResult?.result?["route"]?.string ?? "none") pcm_chunks=\(audio.played.count) completed_turns=\(turnProbe.completed) transcript_turns=\(retained?.turns.count ?? 0)")
    }

}


extension ConversationControllerTests {
    func testTranscriptFragmentsCoalescePerSpeakerAndSeparateCompletedTurns() async {
        let (app, _, live, c, dir) = fixture()
        defer { c.stop(); try? FileManager.default.removeItem(at: dir) }
        _ = await c.start(app: app); live.event?(.ready); await settle()
        live.event?(.userText("I went")); live.event?(.kaikuText("That sounds"))
        live.event?(.userText(" for a walk.")); live.event?(.kaikuText("That sounds peaceful."))
        await settle()
        XCTAssertEqual(c.lines.count, 2)
        XCTAssertEqual(c.lines[0].text, "I went for a walk.")
        XCTAssertEqual(c.lines[1].text, "That sounds peaceful.")
        live.event?(.userTranscriptComplete); live.event?(.kaikuTranscriptComplete)
        live.event?(.turnComplete); live.event?(.userText("Yes.")); await settle()
        XCTAssertEqual(c.lines.count, 3)
        XCTAssertEqual(c.lines.last?.text, "Yes.")
        live.event?(.userTranscriptComplete)
        live.event?(.kaikuText("Let us")); live.event?(.interrupted); live.event?(.kaikuTranscriptComplete)
        live.event?(.userText("Actually, wait.")); live.event?(.kaikuText("Of course.")); await settle()
        XCTAssertEqual(c.lines.suffix(3).map(\.text), ["Let us", "Actually, wait.", "Of course."])
    }

    func testSavedConversationReaderAndDeletionClearPrivateCacheOnPairingChange() async {
        let (app, _, _, _, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await app.loadConversations()
        XCTAssertEqual(app.conversationsKept, 1)
        XCTAssertEqual(app.savedConversations.first?.turns.count, 2)
        XCTAssertFalse(app.conversationsFailed)
        await app.forgetConversations()
        XCTAssertEqual(app.conversationsKept, 0); XCTAssertTrue(app.savedConversations.isEmpty)
        await app.loadConversations()
        await app.updatePairing(Pairing(baseURL: URL(string: "https://other.test")!, homeID: "other", token: nil))
        XCTAssertTrue(app.savedConversations.isEmpty)
        await app.loadConversations() // Deliberately mismatched server response must not populate another home.
        XCTAssertTrue(app.savedConversations.isEmpty); XCTAssertTrue(app.conversationsFailed)
    }

    func testScriptedReplyCannotAppearAfterLeavingTalkAndEnglishIsFixed() async {
        let (app, _, _, c, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        app.language = .fi
        XCTAssertEqual(app.language, .en)
        let model = TalkModel(makeConversation: { c }); model.app = app
        model.send("A quiet afternoon")
        XCTAssertEqual(model.lines.count, 1)
        model.stop()
        try? await Task.sleep(nanoseconds: 1_000_000_000)
        XCTAssertTrue(model.lines.isEmpty)
    }
}


extension ConversationControllerTests {
    func testInspectionModeNeverBootstrapsOrStartsCapture() async {
        let (app, audio, _, c, dir) = fixture()
        let previous = UserDefaults.standard.object(forKey: "kaikuInspectOnly")
        UserDefaults.standard.set(true, forKey: "kaikuInspectOnly")
        defer {
            if let previous { UserDefaults.standard.set(previous, forKey: "kaikuInspectOnly") }
            else { UserDefaults.standard.removeObject(forKey: "kaikuInspectOnly") }
            try? FileManager.default.removeItem(at: dir)
        }
        let model = TalkModel(makeConversation: { c })
        await model.start(app: app)
        XCTAssertFalse(audio.running)
        XCTAssertFalse(audio.mic)
        XCTAssertTrue(ConversationHTTP.requests.isEmpty)
        XCTAssertEqual(model.mode, .ended)
    }
}


extension ConversationControllerTests {
    func testLiveProofCompletionRequiresProviderBoundaryNotAudioOrTranscriptFragments() {
        let probe = LiveTurnProbe()
        probe.receive(.audio(Data([0, 1])))
        probe.receive(.kaikuText("An unfinished"))
        probe.receive(.interrupted)
        XCTAssertEqual(probe.completed, 0)
        probe.receive(.turnComplete)
        XCTAssertEqual(probe.completed, 1)
        probe.receive(.audio(Data([0, 1])))
        XCTAssertEqual(probe.completed, 1)
        probe.receive(.turnComplete)
        XCTAssertEqual(probe.completed, 2)
    }
}


extension ConversationControllerTests {
    func testLateFinalTranscriptionStaysWithOriginalSpeakerAfterAudioTurnAndTypedInput() async {
        let (app, _, live, c, dir) = fixture()
        defer { c.stop(); try? FileManager.default.removeItem(at: dir) }
        _ = await c.start(app: app); live.event?(.ready); await settle()
        live.event?(.userText("Morning.")); live.event?(.userTranscriptComplete)
        live.event?(.kaikuText("Morning, Aino! It")); live.event?(.turnComplete); await settle()
        XCTAssertTrue(c.hasPendingTranscription)
        XCTAssertNil(Conversation.transcript(c.lines).last?.complete, "audio completion without final markers is unknown")
        c.send(text: "One more thing.")
        live.event?(.kaikuText(" sounds peaceful.")); live.event?(.kaikuTranscriptComplete); await settle()
        XCTAssertEqual(c.lines.map(\.text), ["Morning.", "Morning, Aino! It sounds peaceful.", "One more thing."])
        XCTAssertTrue(c.lines.allSatisfy(\.transcriptFinished))
        XCTAssertFalse(c.hasPendingTranscription)
        live.event?(.kaikuText("A new answer.")); live.event?(.interrupted)
        live.event?(.kaikuText(" Still received.")); live.event?(.kaikuTranscriptComplete); await settle()
        XCTAssertEqual(c.lines.last?.text, "A new answer. Still received.")
        XCTAssertEqual(c.lines.last?.interrupted, true)
        XCTAssertEqual(Conversation.transcript(c.lines).last?.complete, false)
    }

    func testParserPreservesIndependentTranscriptFinalMarkersWithoutText() {
        let events = LiveSession.parse(["serverContent": ["turnComplete": true,
            "inputTranscription": ["finished": true], "outputTranscription": ["text": "Done.", "finished": true]]])
        XCTAssertEqual(events, [.kaikuText("Done."), .userTranscriptComplete, .kaikuTranscriptComplete, .turnComplete])
        let legacy = try! JSONDecoder().decode(TranscriptTurn.self, from: Data(#"{"role":"kaiku","text":"Old words"}"#.utf8))
        XCTAssertNil(legacy.complete)
    }
}


extension ConversationControllerTests {
    func testLegacyWithoutFinishedSeparatesNextPhysicalTurnAndRetainsUnknownStatus() async {
        let (app, _, live, c, dir) = fixture()
        defer { c.stop(); try? FileManager.default.removeItem(at: dir) }
        _ = await c.start(app: app); live.event?(.ready); await settle()
        live.event?(.userText("First question.")); live.event?(.kaikuText("First answer.")); live.event?(.turnComplete)
        for event in LiveSession.parse(["serverContent": [
            "inputTranscription": ["text": "Second question."], "outputTranscription": ["text": "Second answer."],
            "modelTurn": ["parts": [["text": "model media frame"]]]]]) { live.event?(event) }
        await settle()
        XCTAssertEqual(c.lines.map(\.text), ["First question.", "First answer.", "Second question.", "Second answer."])
        let turns = Conversation.transcript(c.lines)
        XCTAssertNil(turns[0].complete); XCTAssertNil(turns[1].complete)
        XCTAssertEqual(turns[2].complete, false); XCTAssertEqual(turns[3].complete, false)
    }

    /// Targeted paid proof of transcription finality only. It deliberately makes no Gemma handoff claim.
    func testRealTranscriptionFinalityThroughActualController() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let cloud = env["KAIKU_CONTROLLER_TEST_CLOUD"], let url = URL(string: cloud),
              let path = env["KAIKU_CONTROLLER_TEST_SPEECH"] else {
            throw XCTSkip("Set cloud and generated PCM for the paid transcription-only proof")
        }
        let pcm = try Data(contentsOf: URL(fileURLWithPath: path))
        guard pcm.count > 32000, pcm.contains(where: { $0 != 0 }) else { XCTFail("invalid generated PCM"); return }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let paired = Pairing(baseURL: url, homeID: "demo-aino", token: nil)
        let api = APIClient(pairing: paired, timeout: 30)
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: paired, api: api,
                           queue: OfflineQueue(url: directory.appendingPathComponent("obs.json")),
                           episodes: EpisodeOutbox(url: directory.appendingPathComponent("episodes.json")))
        app.consents[.transcripts] = true
        let audio = ControllerAudio(), probe = LiveTurnProbe()
        let c = Conversation(surface: .iphone, intent: .talk, audio: audio,
                             transport: { onEvent in LiveSession(onEvent: { event in probe.receive(event); onEvent(event) }) },
                             permission: { true }, localListener: false)
        defer { c.stop() }
        guard await c.start(app: app) else { XCTFail("bootstrap failed"); return }
        let readyDeadline = Date().addingTimeInterval(15)
        while c.phase == .connecting && Date() < readyDeadline { await settle() }
        XCTAssertTrue(audio.mic)
        for offset in stride(from: 0, to: pcm.count, by: 3200) {
            audio.onPCM?(pcm.subdata(in: offset..<min(offset + 3200, pcm.count)))
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        for _ in 0..<20 { audio.onPCM?(Data(count: 3200)); try await Task.sleep(nanoseconds: 100_000_000) }
        let deadline = Date().addingTimeInterval(45)
        while Date() < deadline && (probe.completed < 1 || probe.inputFinished < 1 || probe.outputFinished < 1 ||
                                   c.hasPendingTranscription || audio.played.isEmpty) { await settle() }
        XCTAssertGreaterThan(probe.completed, 0)
        XCTAssertGreaterThan(probe.inputFinished, 0, "provider must explicitly finish input transcription")
        XCTAssertGreaterThan(probe.outputFinished, 0, "provider must explicitly finish output transcription")
        XCTAssertFalse(c.hasPendingTranscription)
        let expected = Conversation.transcript(c.lines)
        XCTAssertTrue(expected.contains { $0.role == .person }); XCTAssertTrue(expected.contains { $0.role == .kaiku })
        XCTAssertTrue(expected.allSatisfy { $0.complete == true }, "no unfinished words may be described as final")
        let id = c.session?.session_id
        c.stop(); await app.flush()
        let saved = try await api.transcripts().transcripts.first { $0.episode_id == id }
        XCTAssertEqual(saved?.turns, expected)
        print("TRANSCRIPTION_FINALITY_PROOF input_finished=\(probe.inputFinished) output_finished=\(probe.outputFinished) audio_turns=\(probe.completed) saved_turns=\(saved?.turns.count ?? 0)")
    }
}


extension ConversationControllerTests {
    func testLegacyLateTextAfterTypedInputAndNextModelGenerationRemainSeparate() async {
        let (app, _, live, c, dir) = fixture()
        defer { c.stop(); try? FileManager.default.removeItem(at: dir) }
        _ = await c.start(app: app); live.event?(.ready); await settle()
        live.event?(.userText("Hello.")); live.event?(.modelOutput)
        live.event?(.kaikuText("Morning! It")); live.event?(.turnComplete); await settle()
        c.send(text: "Another question.")
        live.event?(.kaikuText(" sounds peaceful.")); await settle()
        XCTAssertEqual(c.lines[1].text, "Morning! It sounds peaceful.")
        live.event?(.modelOutput); live.event?(.kaikuText("A separate answer.")); live.event?(.turnComplete); await settle()
        XCTAssertEqual(c.lines.map(\.text), ["Hello.", "Morning! It sounds peaceful.", "Another question.", "A separate answer."])
        let turns = Conversation.transcript(c.lines)
        XCTAssertNil(turns[1].complete); XCTAssertNil(turns[3].complete)
        XCTAssertEqual(turns[2].complete, true)
    }
}

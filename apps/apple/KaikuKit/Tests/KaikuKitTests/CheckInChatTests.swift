import AVFoundation
import XCTest
@testable import KaikuKit

// The daily check-in as a small passing chat: pure state, the `feel` plan, and the chat on the real conversation
// engine with a fake Live transport and a stubbed cloud (no microphone, no network, no model).

final class CheckInStateTests: XCTestCase {
    func testAnOrdinaryDayClosesWarmlyAndTicksOnce() {
        var s = CheckInState()
        XCTAssertEqual(s.apply(.personSpoke), [])
        XCTAssertEqual(s.apply(.personSpoke), [])
        XCTAssertEqual(s.depth, .brief)
        XCTAssertEqual(s.apply(.closed), [.tick])
        XCTAssertEqual(s.end, .chat)
        XCTAssertEqual(s.apply(.closed), [], "a second close changes nothing")
        XCTAssertEqual(s.apply(.dials(mood: 3, energy: 3, sleep: 3)), [], "the dials afterwards do not tick twice")
    }

    func testStayKeepsGoingWithoutAnyEndPressure() {
        var s = CheckInState()
        _ = s.apply(.personSpoke)
        XCTAssertEqual(s.apply(.plan(FeelPlan(stance: "comfort", depth: .stay))), [])
        XCTAssertTrue(s.staying)
        for _ in 0..<40 { XCTAssertEqual(s.apply(.personSpoke), []) }
        XCTAssertNil(s.end, "no number of turns ends a day that asked for time")
        XCTAssertFalse(s.ticked)
        _ = s.apply(.plan(FeelPlan(stance: "steady", depth: .brief)))
        XCTAssertFalse(s.staying, "the latest plan decides the depth")
        XCTAssertNil(s.end, "and even then only a close ends the chat")
        XCTAssertEqual(s.apply(.closed), [.tick])
        XCTAssertEqual(s.end, .chat)
    }

    func testDialsOnlyCountsAndGetsOneWarmLine() {
        var s = CheckInState()
        XCTAssertEqual(s.apply(.dials(mood: 2, energy: 3, sleep: 3)), [.tick])
        XCTAssertEqual(s.end, .dials("checkin.dials.low"))
        XCTAssertTrue(s.dialsDone)
        XCTAssertEqual(s.personTurns, 0)
        XCTAssertEqual(CheckInState.dialLine(mood: 5, energy: 4, sleep: 4), "checkin.dials.bright")
        XCTAssertEqual(CheckInState.dialLine(mood: 3, energy: 3, sleep: 1), "checkin.dials.tired")
        XCTAssertEqual(CheckInState.dialLine(mood: 3, energy: 3, sleep: 3), "checkin.dials.mid")
        XCTAssertEqual(CheckInState.dialLine(mood: 1, energy: 5, sleep: 5), "checkin.dials.low")
    }

    func testOpeningTheCardCounts() {
        var s = CheckInState()
        _ = s.apply(.personSpoke)
        XCTAssertEqual(s.apply(.cardOpened), [.tick], "the person asked: the check-in counts")
        XCTAssertEqual(s.end, .offer)
    }

    func testTheActivityCardIsOneComponentForBothSources() {
        // from the tool
        XCTAssertEqual(ActivityCard(kind: "lantern", phone: true)?.route, .lantern)
        XCTAssertEqual(ActivityCard(kind: "seeds", phone: true)?.route, .seeds)
        XCTAssertEqual(ActivityCard(kind: "watering", phone: false)?.route, .watering)
        XCTAssertEqual(ActivityCard(kind: "walk", phone: true)?.route, .walk)
        XCTAssertNil(ActivityCard(kind: "walk", phone: false), "the Mac has no walk")
        XCTAssertNil(ActivityCard(kind: "drum", phone: true), "the drum is the robot's")
        XCTAssertNil(ActivityCard(kind: "light_hunt", phone: true))
        let breathe = ActivityCard(kind: "breathe", line: " A few slow breaths? ")
        XCTAssertEqual(breathe?.line, "A few slow breaths?")
        XCTAssertEqual(breathe?.minutes, 1)
        XCTAssertEqual(breathe?.openedText, "The person opened the breathe card.")
        XCTAssertEqual(breathe?.asideText, "The person put the breathe card aside.")
        XCTAssertEqual(ActivityCard(kind: "pebbles")?.minutes, 2)
        // from the plan
        XCTAssertNil(ActivityCard(plan: FeelPlan(stance: "celebrate")), "nothing offered: no card")
        XCTAssertNil(ActivityCard(plan: FeelPlan(offerActivity: "breathe")), "no words for it: no card")
        let walk = ActivityCard(plan: FeelPlan(mayOffer: "a short walk in daylight", offerActivity: "walk"), phone: true)
        XCTAssertEqual(walk?.route, .walk)
        XCTAssertEqual(walk?.line, "A short walk in daylight?")
        // An offer with no screen on this device stays Kaiku's spoken words: no card.
        XCTAssertNil(ActivityCard(plan: FeelPlan(mayOffer: "sitting quietly together for a minute")), "offer_activity is null")
        XCTAssertNil(ActivityCard(plan: FeelPlan(mayOffer: "a short drum jam with the robot", offerActivity: "drum"), phone: true))
        XCTAssertNil(ActivityCard(plan: FeelPlan(mayOffer: "a short walk", offerActivity: "walk"), phone: false))
    }

    func testTheCallHasOneShortStateAndTheIdleScreenOneLineAndOneAction() {
        typealias S = CallStatus
        XCTAssertEqual(S(phase: .connecting, listens: true, micMuted: false, kaikuSpeaking: false), .connecting)
        XCTAssertEqual(S(phase: .listening, listens: true, micMuted: false, kaikuSpeaking: false), .listening)
        XCTAssertEqual(S(phase: .hearing, listens: true, micMuted: false, kaikuSpeaking: false), .listening)
        XCTAssertEqual(S(phase: .muted, listens: true, micMuted: true, kaikuSpeaking: false), .muted)
        XCTAssertEqual(S(phase: .muted, listens: true, micMuted: true, kaikuSpeaking: true), .speaking, "Kaiku speaking shows even while I am muted")
        XCTAssertEqual(S(phase: .muted, listens: false, micMuted: true, kaikuSpeaking: false), .micOff)
        XCTAssertEqual(S(phase: .paused, listens: true, micMuted: false, kaikuSpeaking: true), .paused)
        XCTAssertEqual(S(phase: .thinking, listens: true, micMuted: false, kaikuSpeaking: false), .thinking)

        typealias R = Conversation.UnavailableReason
        func idle(_ mode: TalkModel.Mode, _ reason: R?, paired: Bool = true, lines: Bool = false, live: Bool = false) -> (String, TalkView.IdleAction?) {
            let s = TalkView.idleState(mode: mode, reason: reason, paired: paired, hasLines: lines, everLive: live)
            return (s.line, s.action)
        }
        XCTAssertTrue(idle(.connecting, nil) == ("talk.connecting", nil))
        XCTAssertTrue(idle(.scripted, R.pairing, paired: false) == ("call.line.unpaired", .connect))
        XCTAssertTrue(idle(.denied, R.microphone) == ("talk.unavailable.microphone", .settings))
        XCTAssertTrue(idle(.scripted, R.paused) == ("call.line.paused", nil))
        XCTAssertTrue(idle(.scripted, R.connection) == ("call.line.connection", .retry))
        XCTAssertTrue(idle(.scripted, R.voice) == ("call.line.voice", .retry))
        XCTAssertTrue(idle(.scripted, R.connection, lines: true, live: true) == ("talk.unavailable.dropped", .retry))
        XCTAssertTrue(idle(.ended, nil) == ("call.ended", .call))

        // The Lock Screen caption is the newest words, never cut mid-word.
        XCTAssertEqual(CallSurface.tail("Good to see you."), "Good to see you.")
        let long = "That sounds like a gentle way to spend the time. Do you want company on your walk, or would you prefer to just have your thoughts?"
        let tail = CallSurface.tail(long, limit: 60)
        XCTAssertTrue(tail.hasPrefix("…") && tail.hasSuffix("have your thoughts?"))
        XCTAssertLessThanOrEqual(tail.count, 61)
        XCTAssertTrue(long.contains(" " + tail.dropFirst()), "it starts at a word")
    }

    func testAnActivityStartsOnlyOnThePersonsWord() {
        // seen live: none of these may start anything
        XCTAssertFalse(TalkModel.asked(for: "tell", in: "Honestly it's been a really hard day. My cat died last night and I can't stop crying."))
        XCTAssertFalse(TalkModel.asked(for: "breathe", in: "Maybe. I just miss her so much."))
        XCTAssertFalse(TalkModel.asked(for: "breathe", in: "I don't know"))
        XCTAssertFalse(TalkModel.asked(for: "walk", in: "Not now."))
        XCTAssertFalse(TalkModel.asked(for: "breathe", in: "Ehkä myöhemmin"))
        XCTAssertFalse(TalkModel.asked(for: "walk", in: "Nej, inte nu"))
        XCTAssertFalse(TalkModel.asked(for: "breathe", in: "I don't want to breathe right now"))
        XCTAssertFalse(TalkModel.asked(for: "firefly", in: "I had a nosebleed"), "whole words only")
        XCTAssertFalse(TalkModel.asked(for: "breathe", in: nil))
        // a clear yes, or asking for it
        XCTAssertTrue(TalkModel.asked(for: "breathe", in: "Yes."))
        XCTAssertTrue(TalkModel.asked(for: "breathe", in: "Okay, maybe a short one"), "a yes wins over the hedge beside it")
        XCTAssertTrue(TalkModel.asked(for: "walk", in: "Could we go for a walk?"))
        XCTAssertTrue(TalkModel.asked(for: "breathe", in: "Let’s breathe together"))
        XCTAssertTrue(TalkModel.asked(for: "breathe", in: "Hengitetään yhdessä"))
        XCTAssertTrue(TalkModel.asked(for: "walk", in: "Joo, mennään"))
        XCTAssertTrue(TalkModel.asked(for: "breathe", in: "Ja, gärna"))
        XCTAssertTrue(TalkModel.asked(for: "pebbles", in: "A game would be nice"))
    }

    func testAChatTheCloudOpensWithTimeNeverClosesFirst() {
        var s = CheckInState()
        XCTAssertEqual(s.apply(.opened(.brief)), [])
        XCTAssertFalse(s.staying)
        XCTAssertEqual(s.apply(.opened(.stay)), [])
        XCTAssertTrue(s.staying)
    }

    func testGoodNewsSparklesOnce() {
        var s = CheckInState()
        _ = s.apply(.personSpoke)
        XCTAssertEqual(s.apply(.plan(FeelPlan(stance: "celebrate", depth: .stay))), [.sparkle])
        XCTAssertEqual(s.apply(.plan(FeelPlan(stance: "celebrate", depth: .stay))), [])
        XCTAssertEqual(s.apply(.plan(FeelPlan(stance: "comfort"))), [])
    }

    func testClosingBeforeThePersonSaidAnythingTicksNothing() {
        var s = CheckInState()
        XCTAssertEqual(s.apply(.closed), [])
        XCTAssertEqual(s.end, .quiet)
        XCTAssertFalse(s.ticked)
        XCTAssertEqual(s.apply(.dials(mood: 4, energy: 4, sleep: 4)), [.tick], "the dials still work afterwards")
        XCTAssertEqual(s.apply(.keepTalking), [])
        XCTAssertNil(s.end)
    }

    func testAllThreeDialsSaidOutLoudCount() {
        var s = CheckInState()
        XCTAssertEqual(s.apply(.allDialsSpoken), [.tick])
        XCTAssertTrue(s.dialsDone)
        XCTAssertNil(s.end, "the chat itself carries on")
    }

    func testFeelPlanReadsTheToolResult() {
        let plan = FeelPlan(result: .object([
            "stance": .string("comfort"), "depth": .string("stay"), "reflect_hint": .string("Give back the thing."),
            "recall": .string("They told you this helps them."), "may_offer": .string("a few slow breaths together"),
            "offer_note": .string("Offer it once."), "offer_activity": .string("breathe"),
            "follow_up_saved": .bool(false), "scheduling": .string("SILENT")]))
        XCTAssertEqual(plan, FeelPlan(stance: "comfort", depth: .stay, mayOffer: "a few slow breaths together", offerActivity: "breathe"))
        let glad = FeelPlan(result: .object(["stance": .string("celebrate"), "depth": .string("stay"), "may_offer": .null, "offer_activity": .null]))
        XCTAssertTrue(glad?.isGoodNews == true)
        XCTAssertNil(glad.flatMap { ActivityCard(plan: $0) })
        let card = try? JSONDecoder().decode(ContextCard.self, from: Data(#"{"time_of_day":"morning","purpose":"check_in","chat_depth":"stay","open_items":["sleep"],"today_facts":["a short night"],"last_reflection":{"when":"yesterday evening","valence":"low","themes":["sleep"],"declined":false,"tone":["flat"],"energy":null,"heard":null}}"#.utf8))
        XCTAssertEqual(card?.purpose, "check_in")
        XCTAssertEqual(card?.chat_depth, "stay")
        XCTAssertEqual(card?.open_items, ["sleep"])
        XCTAssertEqual(card?.last_reflection?.valence, "low")
        XCTAssertEqual(FeelPlan(result: .object(["stance": .string("steady"), "depth": .string("unheard-of")]))?.depth, .brief)
        XCTAssertNil(FeelPlan(result: .object(["ok": .bool(true)])), "not a plan")
        XCTAssertNil(FeelPlan(result: nil))
    }

    func testFeelIsAnsweredSilentlySoKaikuIsNotMadeToSpeakAgain() {
        let frame = LiveSession.toolResponse(id: "1", name: "feel", result: .object(["stance": .string("comfort"), "scheduling": .string("SILENT")]), background: true)
        let fr = ((frame["toolResponse"] as? [String: Any])?["functionResponses"] as? [[String: Any]])?.first?["response"] as? [String: Any]
        XCTAssertEqual(fr?["scheduling"] as? String, "SILENT")
        XCTAssertNil((fr?["result"] as? [String: Any])?["scheduling"], "the delivery hint is for the frame, not the model")
        XCTAssertEqual((fr?["result"] as? [String: Any])?["stance"] as? String, "comfort")
        let ask = LiveSession.toolResponse(id: "2", name: "ask_mind", result: .object(["answer": .string("x")]), background: true)
        let ar = ((ask["toolResponse"] as? [String: Any])?["functionResponses"] as? [[String: Any]])?.first?["response"] as? [String: Any]
        XCTAssertEqual(ar?["scheduling"] as? String, "WHEN_IDLE")
        let tool = CompanionTool(name: "feel", description: "d", parameters: .object([:]), behavior: "NON_BLOCKING")
        let session = CompanionSessionResponse(session_id: "s", model: "m", voice: "v", system_instruction: "i", tools: [tool],
                                               context_card: ContextCard(time_of_day: "morning"), persona_version: "p", safety_phrases_version: "s")
        let setup = (LiveSession.setup(session: session, options: .init())["setup"] as? [String: Any])?["tools"] as? [[String: Any]]
        let decl = (setup?.first?["functionDeclarations"] as? [[String: Any]])?.first
        XCTAssertEqual(decl?["behavior"] as? String, "NON_BLOCKING", "the cloud's declared behaviour reaches Live")
    }
}

// MARK: the chat on the real engine

private final class ChatAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying = false
    var mic = false
    var captures = true
    func start() throws {}
    func stop() { mic = false }
    func setMic(_ on: Bool) { mic = on }
    func setCapture(_ on: Bool) { captures = on }
    func play(_ pcm: Data) {}
    func flush() {}
}

private final class ChatTransport: ConversationTransport, @unchecked Sendable {
    var event: (@Sendable (LiveSession.Event) -> Void)?
    var text: [String] = []
    var contexts: [String] = []
    var results: [String] = []
    var values: [JSONValue] = []
    var closed = false
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) {}
    func close() { closed = true }
    func sendAudio(_ pcm: Data) {}
    func audioStreamEnd() {}
    func sendText(_ text: String) { self.text.append(text) }
    func sendContext(_ event: String) { contexts.append(event) }
    func respond(id: String, name: String, result: JSONValue) { results.append(name); values.append(result) }
}

private final class ChatHTTP: URLProtocol {
    static let lock = NSLock()
    nonisolated(unsafe) static var offline = false
    nonisolated(unsafe) static var rejectPurpose = false
    nonisolated(unsafe) static var feel = #"{"stance":"comfort","depth":"stay","reflect_hint":"Give it back softly.","recall":"They told you this helps them.","may_offer":"a few slow breaths together","offer_note":"Offer it once.","offer_activity":"breathe","follow_up_saved":false,"scheduling":"SILENT"}"#
    nonisolated(unsafe) static var sessions: [String] = []
    nonisolated(unsafe) static var events = 0
    static func reset() {
        lock.lock(); offline = false; rejectPurpose = false; sessions = []; events = 0
        feel = #"{"stance":"comfort","depth":"stay","reflect_hint":"Give it back softly.","recall":"They told you this helps them.","may_offer":"a few slow breaths together","offer_note":"Offer it once.","offer_activity":"breathe","follow_up_saved":false,"scheduling":"SILENT"}"#
        lock.unlock()
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var data = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
        }
        let body = String(decoding: data, as: UTF8.self)
        let path = request.url!.path
        Self.lock.lock()
        let offline = Self.offline, reject = Self.rejectPurpose, feel = Self.feel
        if path.hasSuffix("session") { Self.sessions.append(body) }
        if path.hasSuffix("events"), request.httpMethod == "POST" { Self.events += 1 }
        Self.lock.unlock()
        if offline { client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)); return }
        var status = 200
        var json = #"{"accepted":1,"duplicates":0,"rejected":[]}"#
        if path.hasSuffix("session") {
            if reject && body.contains("purpose") { status = 422; json = #"{"detail":"extra fields not permitted"}"# }
            else {
                json = #"{"session_id":"checkin-session","model":"m","voice":"v","system_instruction":"s","tools":[{"name":"feel","description":"d","parameters":{},"behavior":"NON_BLOCKING"}],"context_card":{"time_of_day":"morning","today_facts":["a short night"],"last_reflection":{"when":"yesterday evening","valence":"low","themes":["sleep"]}},"persona_version":"p","safety_phrases_version":"s","chat_shape":{"purpose":"check_in","depth":"brief","open_items":["energy","sleep"]},"live_token":{"token":"t","expires_at":"2099-01-01T00:00:00Z","new_session_expires_at":"2099-01-01T00:00:00Z"}}"#
            }
        } else if path.hasSuffix("tool") {
            json = body.contains("\"feel\"") ? #"{"ok":true,"name":"feel","result":\#(feel)}"# : #"{"ok":true,"name":"end_session","result":{"ok":true}}"#
        } else if path.hasSuffix("episode") {
            json = #"{"ok":true,"id":"checkin-session"}"#
        } else if path.hasSuffix("events"), request.httpMethod == "GET" { json = #"{"events":[]}"# }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor final class CheckInChatTests: XCTestCase {
    private var grace: TimeInterval = 0

    override func setUp() async throws {
        grace = Conversation.closeGrace
        Conversation.closeGrace = 0
        ChatHTTP.reset()
    }

    override func tearDown() async throws { Conversation.closeGrace = grace }

    private func fixture(mic: Bool = true) -> (AppModel, ChatAudio, ChatTransport, CheckInChat, URL) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let p = Pairing(baseURL: URL(string: "https://checkin.test")!, homeID: "synthetic", token: "synthetic-pairing-token")
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ChatHTTP.self]
        let api = APIClient(pairing: p, maxAttempts: 1, session: URLSession(configuration: config))
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        let app = AppModel(defaults: defaults, pairing: p, api: api, queue: OfflineQueue(url: dir.appendingPathComponent("events.json")),
                           episodes: EpisodeOutbox(url: dir.appendingPathComponent("episodes.json")))
        let audio = ChatAudio(), live = ChatTransport()
        let talk = TalkModel(opening: CheckInChat.opening) {
            Conversation(surface: .iphone, intent: .checkin, audio: audio, transport: { event in live.event = event; return live },
                         permission: { mic }, localListener: false, purpose: .check_in, typedWithoutMic: true)
        }
        return (app, audio, live, CheckInChat(talk: talk), dir)
    }

    private func settle() async { try? await Task.sleep(nanoseconds: 80_000_000) }

    /// Opens the chat and lets the person say one line that Kaiku answers.
    private func open(_ chat: CheckInChat, _ app: AppModel, _ live: ChatTransport, saying line: String) async {
        await chat.start(app: app)
        live.event?(.ready); await settle()
        live.event?(.kaikuText("Oh, hello. How is today going?")); live.event?(.kaikuTranscriptComplete); live.event?(.turnComplete)
        live.event?(.userText(line)); live.event?(.userTranscriptComplete)
        await settle()
    }

    func testAnOrdinaryDayWrapsItselfUpAndTicksTheFirstStop() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(chat, app, live, saying: "Fine. A normal day.")
        XCTAssertTrue(ChatHTTP.sessions.first?.contains(#""purpose":"check_in""#) == true, "the engine is opened as a check-in")
        XCTAssertTrue(ChatHTTP.sessions.first?.contains(#""intent":"checkin""#) == true)
        XCTAssertEqual(live.contexts.first, CheckInChat.opening)
        XCTAssertEqual(chat.talk.conversation.session?.context_card.today_facts, ["a short night"])
        XCTAssertEqual(chat.talk.conversation.session?.openCheckInItems, [.energy, .sleep])
        XCTAssertEqual(chat.talk.conversation.session?.tools.first?.behavior, "NON_BLOCKING")
        XCTAssertFalse(chat.state.staying, "chat_shape.depth brief: an ordinary day")
        XCTAssertEqual(chat.state.personTurns, 1)
        XCTAssertNil(chat.state.end)
        XCTAssertFalse(app.weatherDoneToday)
        let before = app.celebration

        live.event?(.kaikuText("Good to see you. Take care.")); live.event?(.kaikuTranscriptComplete)
        live.event?(.toolCall(id: "1", name: "end_session", args: ["outcome": .string("completed")])); await settle()
        XCTAssertEqual(chat.state.end, .chat, "the model's close is the end of an ordinary day")
        XCTAssertTrue(app.weatherDoneToday, "the stop is ticked without a single dial")
        XCTAssertEqual(app.celebration, before + 1, "the completion moment plays once")
        XCTAssertEqual(app.todayPath.first?.done, true)
    }

    func testKaikusGoodbyeIsNeverCutOffByItsOwnClose() async {
        let (app, audio, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(chat, app, live, saying: "All fine today.")
        audio.isPlaying = true                               // Kaiku is still saying "good to see you"
        live.event?(.toolCall(id: "1", name: "end_session", args: [:])); await settle()
        XCTAssertEqual(chat.state.end, .chat, "the warm end shows at once")
        XCTAssertFalse(live.closed, "but the voice is allowed to finish")
        XCTAssertFalse(audio.mic, "and nothing more is listened to")
        audio.isPlaying = false
        try? await Task.sleep(nanoseconds: 700_000_000)
        XCTAssertTrue(live.closed)
        XCTAssertEqual(chat.phase, .idle)
    }

    func testTheGoodbyeSaidAfterTheCloseIsHeardAndMarkersNeverBecomeLines() async {
        Conversation.closeGrace = 0.3
        let (app, audio, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(chat, app, live, saying: "All fine today.")
        live.event?(.turnComplete)
        live.event?(.toolCall(id: "1", name: "end_session", args: [:])); await settle()
        XCTAssertEqual(chat.state.end, .chat)
        XCTAssertFalse(live.closed, "the model speaks its goodbye once the tool has answered")
        live.event?(.kaikuText("<no speech>{pause}")); await settle()
        audio.isPlaying = true
        live.event?(.audio(Data([0, 0]))); live.event?(.kaikuText("Good to see you. I'm around later.")); await settle()
        XCTAssertFalse(live.closed)
        audio.isPlaying = false
        live.event?(.kaikuTranscriptComplete); live.event?(.turnComplete)
        try? await Task.sleep(nanoseconds: 900_000_000)
        XCTAssertTrue(live.closed)
        XCTAssertEqual(chat.lines.last?.text, "Good to see you. I'm around later.")
        XCTAssertFalse(chat.lines.contains { $0.text.contains("<") || $0.text.contains("{") })
        XCTAssertEqual(Conversation.spoken(" lovely <noise> day"), " lovely  day")
    }

    func testFillerAfterTheGoodbyeTurnIsDropped() async {
        Conversation.closeGrace = 0.3
        let (app, audio, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(chat, app, live, saying: "Just a quiet evening.")
        audio.isPlaying = true                               // the goodbye was said first this time
        live.event?(.kaikuText("A quiet evening sounds restful. I am around later.")); await settle()
        live.event?(.toolCall(id: "1", name: "end_session", args: [:])); await settle()
        live.event?(.turnComplete); await settle()
        live.event?(.audio(Data([0, 0]))); live.event?(.kaikuText("-")); await settle()   // seen live after the tool answer
        XCTAssertEqual(chat.lines.last?.text, "A quiet evening sounds restful. I am around later.")
        XCTAssertFalse(live.closed, "the goodbye is still playing")
        audio.isPlaying = false
        try? await Task.sleep(nanoseconds: 700_000_000)
        XCTAssertTrue(live.closed, "and the chat ends as soon as it has been heard")
        XCTAssertEqual(chat.lines.filter { !$0.me }.count, 2)
    }

    func testAnActivityNeverStartsOnAMaybe() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(chat, app, live, saying: "Maybe. I just miss her so much.")
        live.event?(.toolCall(id: "a", name: "start_activity", args: ["kind": .string("breathe")])); await settle()
        XCTAssertNil(app.deepLink, "seen live: the model started breathing on a maybe")
        XCTAssertNil(chat.state.end)
        live.event?(.turnComplete)
        live.event?(.userText("My cat died last night.")); live.event?(.userTranscriptComplete); await settle()
        live.event?(.toolCall(id: "t", name: "start_activity", args: ["kind": .string("tell")])); await settle()
        XCTAssertNil(app.deepLink, "seen live: the model opened Tell Kaiku on the first sad sentence")
        XCTAssertNil(chat.state.end)
        live.event?(.turnComplete)
        live.event?(.userText("Okay, let's breathe.")); live.event?(.userTranscriptComplete); await settle()
        live.event?(.toolCall(id: "b", name: "start_activity", args: ["kind": .string("breathe")])); await settle()
        XCTAssertEqual(app.deepLink, .breathe, "on their word it starts")
        XCTAssertEqual(chat.state.end, .chat)
        XCTAssertTrue(app.weatherDoneToday)
    }

    func testAPassingChatNeverOpensTheQuestionnaire() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(chat, app, live, saying: "A quiet evening ahead.")
        live.event?(.toolCall(id: "q", name: "start_phq9", args: [:])); await settle()
        XCTAssertFalse(app.phq9Requested)
        XCTAssertEqual(live.results, ["start_phq9"], "the model is told no")
        XCTAssertNil(chat.state.end)
    }

    func testAHardDayStaysAndShowsOneSoftOfferWithoutASpinner() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(chat, app, live, saying: "Honestly, a really hard one.")
        live.event?(.toolCall(id: "f", name: "feel", args: ["feeling": .string("low")]))
        XCTAssertNotEqual(chat.phase, .thinking, "feel never shows a thinking state")
        await settle()
        XCTAssertNotEqual(chat.phase, .thinking)
        XCTAssertEqual(live.results, ["feel"], "the plan goes back to the model")
        XCTAssertTrue(chat.state.staying)
        XCTAssertNil(chat.card, "Kaiku meets the feeling first")
        XCTAssertEqual(chat.talk.conversation.toolsUsed, ["feel"])

        // Ignored: the person just carries on, for as long as they like; the chip waits quietly.
        for i in 0..<6 {
            live.event?(.turnComplete)
            live.event?(.userText("And another thing, \(i).")); live.event?(.userTranscriptComplete); await settle()
        }
        XCTAssertEqual(chat.card?.kind, "breathe")
        XCTAssertEqual(chat.card?.line, "A few slow breaths together?")
        XCTAssertNil(chat.state.end)
        XCTAssertTrue(chat.state.staying)
        XCTAssertFalse(app.weatherDoneToday, "nothing is ticked while the chat is still going")

        // Taken: the activity starts and the check-in counts.
        chat.openCard()
        XCTAssertEqual(live.contexts.last, "The person opened the breathe card.")
        XCTAssertEqual(app.deepLink, .breathe)
        XCTAssertEqual(chat.state.end, .offer)
        XCTAssertTrue(app.weatherDoneToday)
    }

    func testGoodNewsGetsTheSparkleOnce() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        ChatHTTP.feel = #"{"stance":"celebrate","depth":"stay","reflect_hint":"Be glad out loud.","recall":null,"may_offer":null,"offer_note":null,"offer_activity":null,"follow_up_saved":true,"scheduling":"SILENT"}"#
        await open(chat, app, live, saying: "I got the job!")
        let before = app.celebration
        live.event?(.toolCall(id: "a", name: "feel", args: [:])); await settle()
        live.event?(.toolCall(id: "b", name: "feel", args: [:])); await settle()
        XCTAssertEqual(app.celebration, before + 1)
        XCTAssertNil(chat.card)
        XCTAssertTrue(chat.state.staying)
    }

    func testDialsOnlyStillWorksOfflineWithAKindLine() async {
        let (app, _, _, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        ChatHTTP.offline = true
        await chat.start(app: app)
        XCTAssertFalse(chat.hasLive)
        XCTAssertEqual(chat.unavailable, .connection)
        XCTAssertEqual(chat.greeting, T("checkin.hello"), "Kaiku's hello is on screen as text either way")

        chat.send("Are you there?"); await settle()
        XCTAssertEqual(chat.state.personTurns, 0, "words nobody could answer do not count as the check-in")
        XCTAssertFalse(app.weatherDoneToday)

        chat.values = [.mood: 2, .energy: 2, .sleep: 3]
        await chat.submitDials()
        XCTAssertEqual(chat.state.end, .dials("checkin.dials.low"))
        XCTAssertEqual(chat.dialReply, T("checkin.dials.low"))
        XCTAssertTrue(app.weatherDoneToday)
        let waiting = await app.queue.count
        XCTAssertEqual(waiting, 3, "the three dial answers wait in the offline queue")
    }

    func testDialsWithKaikuListeningGetAnAnswerInItsOwnVoiceAndTheConversationClosesItself() async {
        Conversation.closeGrace = 0.3                       // the real path: Kaiku's line is said, then it closes
        let (app, audio, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await chat.start(app: app)
        live.event?(.ready); await settle()
        XCTAssertTrue(audio.mic)
        chat.values = [.mood: 5, .energy: 4, .sleep: 4]
        await chat.submitDials()
        XCTAssertEqual(chat.state.end, .dials("checkin.dials.bright"))
        XCTAssertFalse(audio.mic, "an end screen never has an open microphone")
        chat.toggleMic(); chat.talk.toggleMic()             // the screen's button, and the Lock Screen's
        XCTAssertFalse(audio.mic, "and nothing opens it again while Kaiku says its line")
        let told = live.contexts.last ?? ""
        XCTAssertTrue(told.contains("Clear sky") && told.contains("Good") && told.contains("Well"), told)
        XCTAssertNil(told.range(of: #"\d"#, options: .regularExpression), "the dial words, never the numbers")
        XCTAssertEqual(chat.dialReply, T("checkin.dials.bright"))
        live.event?(.kaikuText("That sounds like a lovely day.")); await settle()
        XCTAssertEqual(chat.dialReply, "That sounds like a lovely day.", "Kaiku's own answer takes over once it is said")
        XCTAssertEqual(chat.state.personTurns, 0)
        // The end screen has no call bar, so the conversation does not stay open behind it.
        live.event?(.turnComplete)
        try? await Task.sleep(nanoseconds: 900_000_000)
        XCTAssertFalse(chat.hasLive, "closed by itself once the line was said")
        XCTAssertTrue(live.closed)
        XCTAssertEqual(chat.dialReply, "That sounds like a lovely day.", "the line stays on the end screen")
        XCTAssertEqual(chat.state.end, .dials("checkin.dials.bright"))
    }

    // MARK: an ended check-in is over (2026-11-14: one left on its tab opened a hidden conversation)

    func testAnEndedCheckInNeverOpensAConversationAgainExceptByKeepTalking() async {
        let (app, audio, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        chat.talk.screenAppeared()
        await open(chat, app, live, saying: "Fine. A normal day.")
        chat.enough(); await settle()
        XCTAssertEqual(chat.state.end, .chat)
        XCTAssertEqual(ChatHTTP.sessions.count, 1)

        // Its screen comes back (the tab reappears, the app returns from the background): nothing starts.
        chat.talk.screenAppeared()
        await chat.start(app: app); await settle()
        XCTAssertEqual(ChatHTTP.sessions.count, 1, "no new conversation is asked for")
        XCTAssertFalse(chat.hasLive)
        XCTAssertFalse(chat.connecting)
        XCTAssertFalse(audio.mic)
        chat.toggleMic()
        XCTAssertFalse(audio.mic)

        // The person's own "keep talking" is the one way back in.
        await chat.keepTalking()
        XCTAssertEqual(ChatHTTP.sessions.count, 2)
        XCTAssertNil(chat.state.end)
    }

    func testACheckInThatWasLeftIsOverForGood() async {
        let (app, audio, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        chat.talk.screenAppeared()
        await open(chat, app, live, saying: "A bit tired.")
        chat.leave()                                        // another tab, back, "Up next": the screen is gone
        XCTAssertEqual(chat.state.end, .chat, "a chat she took part in counts")
        XCTAssertTrue(app.weatherDoneToday)
        XCTAssertTrue(chat.left)
        XCTAssertTrue(live.closed)

        // Whatever brings the screen back before it is popped: no conversation, no microphone, no way to restart.
        chat.talk.screenAppeared()
        await chat.start(app: app)
        await chat.keepTalking()
        chat.talk.restart(); await settle()
        XCTAssertEqual(ChatHTTP.sessions.count, 1)
        XCTAssertFalse(chat.hasLive)
        XCTAssertFalse(audio.mic)
    }

    func testNoConversationStartsBehindAScreenThatIsNotShowing() async {
        let (app, audio, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        let talk = chat.talk                                // the same model Talk runs on
        talk.screenAppeared()
        await talk.start(app: app)
        live.event?(.ready); await settle()
        XCTAssertTrue(talk.hasLive)
        XCTAssertTrue(audio.mic)

        talk.screenDisappeared()                            // another tab is showing now
        XCTAssertFalse(talk.hasLive)
        XCTAssertFalse(audio.mic)
        XCTAssertTrue(live.closed)
        // The app comes back from the background while that tab is still hidden; someone calls restart.
        await talk.start(app: app)
        talk.restart(); await settle()
        XCTAssertEqual(ChatHTTP.sessions.count, 1, "nothing is asked of the service from a hidden screen")
        XCTAssertFalse(talk.hasLive)
        XCTAssertFalse(audio.mic)

        talk.screenAppeared()                               // the screen is back in front
        await talk.start(app: app)
        XCTAssertEqual(ChatHTTP.sessions.count, 2)
    }

    func testEndingTheCallAwayFromTheScreenEndsTheCheckInLikeThatsEnough() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(chat, app, live, saying: "It was a long day.")
        XCTAssertNil(chat.state.end)
        chat.talk.end()                                     // what End on the Lock Screen and the pocket rule call
        await settle()
        XCTAssertEqual(chat.state.end, .chat, "the end screen, as after \"That's enough for now\"")
        XCTAssertTrue(app.weatherDoneToday, "she took part: the stop is ticked")
        XCTAssertFalse(chat.hasLive)

        // Ended the same way before she said anything: the quiet end, nothing ticked.
        let (app2, _, live2, chat2, dir2) = fixture()
        defer { try? FileManager.default.removeItem(at: dir2) }
        await chat2.start(app: app2)
        live2.event?(.ready); await settle()
        chat2.talk.end(); await settle()
        XCTAssertEqual(chat2.state.end, .quiet)
        XCTAssertFalse(app2.weatherDoneToday)
    }

    func testWritingWorksLikeSpeakingEvenWithoutTheMicrophone() async {
        let (app, audio, live, chat, dir) = fixture(mic: false)
        defer { try? FileManager.default.removeItem(at: dir) }
        await chat.start(app: app)
        live.event?(.ready); await settle()
        XCTAssertTrue(chat.hasLive, "no microphone permission: the conversation still opens")
        XCTAssertTrue(chat.typedOnly)
        XCTAssertFalse(audio.captures, "nothing is captured")
        XCTAssertFalse(audio.mic)
        XCTAssertFalse(chat.micOn)
        chat.send("I walked to the lake today.")
        XCTAssertEqual(live.text, ["I walked to the lake today."], "typed words take the same road as spoken ones")
        XCTAssertEqual(chat.state.personTurns, 1)
        chat.toggleMic(); await settle()
        XCTAssertFalse(audio.mic, "the microphone cannot be opened without permission")
        live.event?(.toolCall(id: "f", name: "feel", args: [:])); await settle()
        XCTAssertTrue(chat.state.staying, "and the plan works the same")
        chat.send("It has been a long week.")
        XCTAssertEqual(chat.card?.kind, "breathe")
    }

    func testTalkShowsOneCardFromEitherSourceAndAsideIsFinal() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        let talk = chat.talk                                  // the model Talk uses, on its own (the chat never starts)
        await talk.start(app: app)
        live.event?(.ready); await settle()
        live.event?(.userText("It has been a rough week.")); live.event?(.userTranscriptComplete); live.event?(.turnComplete); await settle()
        XCTAssertNil(talk.activityCard)

        // from the tool: shown at once, opened by the person
        live.event?(.toolCall(id: "s", name: "suggest_activity", args: ["kind": .string("lantern"), "line": .string("A little lantern game?")])); await settle()
        XCTAssertEqual(talk.activityCard?.kind, "lantern")
        XCTAssertEqual(live.results.last, "suggest_activity")
        XCTAssertEqual(live.values.last, .object(["ok": .bool(true), "shown": .bool(true)]))
        XCTAssertNil(app.deepLink, "a card starts nothing by itself")
        talk.putCardAside()
        XCTAssertNil(talk.activityCard)
        XCTAssertEqual(live.contexts.last, "The person put the lantern card aside.")
        live.event?(.toolCall(id: "s2", name: "suggest_activity", args: ["kind": .string("lantern")])); await settle()
        XCTAssertNil(talk.activityCard, "put aside is final for this conversation")
        XCTAssertEqual(live.values.last, .object(["ok": .bool(true), "shown": .bool(false)]), "and Kaiku is told it was not shown")
        live.event?(.toolCall(id: "s3", name: "suggest_activity", args: ["kind": .string("drum")])); await settle()
        XCTAssertNil(talk.activityCard, "not on this device: no card")
        XCTAssertEqual(live.values.last, .object(["ok": .bool(true), "shown": .bool(false)]))

        // from the plan: after the person's next words; the same kind from the tool is still one card
        live.event?(.toolCall(id: "f", name: "feel", args: [:])); await settle()
        XCTAssertNil(talk.activityCard, "not in the first reply to the feeling")
        live.event?(.userText("It just keeps piling up.")); live.event?(.userTranscriptComplete); live.event?(.turnComplete); await settle()
        XCTAssertEqual(talk.activityCard?.kind, "breathe")
        live.event?(.toolCall(id: "s4", name: "suggest_activity", args: ["kind": .string("breathe")])); await settle()
        XCTAssertEqual(talk.activityCard?.kind, "breathe", "never two cards for the same kind")
        talk.openCard()
        XCTAssertEqual(live.contexts.last, "The person opened the breathe card.")
        XCTAssertEqual(app.deepLink, .breathe)
        XCTAssertNil(talk.activityCard, "opened once")

        ChatHTTP.feel = #"{"stance":"celebrate","depth":"stay","reflect_hint":"h","may_offer":null,"offer_activity":null,"scheduling":"SILENT"}"#
        let before = app.celebration
        live.event?(.toolCall(id: "h", name: "feel", args: [:])); await settle()
        talk.planArrived(); talk.planArrived()
        XCTAssertEqual(app.celebration, before + 1, "good news sparkles once")
    }

    func testACallLeftInAPocketEndsByItself() async {
        let limit = TalkModel.backgroundQuietLimit
        TalkModel.backgroundQuietLimit = 0.6
        defer { TalkModel.backgroundQuietLimit = limit }
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        let talk = chat.talk
        await talk.start(app: app)
        live.event?(.ready); await settle()
        XCTAssertTrue(talk.hasLive)
        let pocket = Task { await talk.backgrounded() }                  // the app left the screen
        try? await Task.sleep(nanoseconds: 350_000_000)
        live.event?(.userText("Still here, walking.")); await settle()   // the person is there: the clock starts again
        try? await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertTrue(talk.hasLive, "heard a moment ago: the call goes on out of sight")
        try? await Task.sleep(nanoseconds: 700_000_000)
        await pocket.value
        XCTAssertFalse(talk.hasLive, "nothing heard for the quiet limit: the call ended by itself")
        XCTAssertTrue(live.closed, "and the socket is closed")
        XCTAssertEqual(talk.conversation.phase, .idle)

        // Back in the app before the limit: the watch is cancelled, the call stays.
        talk.restart()
        try? await Task.sleep(nanoseconds: 200_000_000)
        live.event?(.ready); await settle()
        let again = Task { await talk.backgrounded() }
        try? await Task.sleep(nanoseconds: 200_000_000)
        again.cancel()
        try? await Task.sleep(nanoseconds: 800_000_000)
        XCTAssertTrue(talk.hasLive)
        talk.stop()
    }

    func testStartActivityKnowsEveryGameOnThisDevice() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await chat.talk.start(app: app)
        live.event?(.ready); await settle()
        live.event?(.userText("Yes, a game please.")); live.event?(.userTranscriptComplete); await settle()
        live.event?(.toolCall(id: "a", name: "start_activity", args: ["kind": .string("watering")])); await settle()
        XCTAssertEqual(app.deepLink, .watering)
    }

    func testLeavingAfterTakingPartCountsAndThatsEnoughClosesAtOnce() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await open(chat, app, live, saying: "Just passing by.")
        chat.enough()
        XCTAssertEqual(chat.state.end, .chat)
        XCTAssertTrue(app.weatherDoneToday)
        XCTAssertTrue(live.closed)

        let (app2, _, live2, chat2, dir2) = fixture()
        defer { try? FileManager.default.removeItem(at: dir2) }
        await chat2.start(app: app2)
        live2.event?(.ready); await settle()
        chat2.leave()
        XCTAssertFalse(app2.weatherDoneToday, "opening the screen and leaving is not a check-in")
    }

    func testACrisisPhraseTypedInTheCheckInGoesToTheCrisisPathFirst() async {
        let (app, _, live, chat, dir) = fixture()
        defer { try? FileManager.default.removeItem(at: dir) }
        await chat.start(app: app)
        live.event?(.ready); await settle()
        // The first phrase of config/safety_phrases.toml that the local gate knows (never written into this file).
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let toml = (try? String(contentsOf: root.appendingPathComponent("config/safety_phrases.toml"), encoding: .utf8)) ?? ""
        let quoted = toml.split(separator: "\"").enumerated().filter { $0.offset % 2 == 1 }.map { String($0.element) }
        guard let phrase = quoted.first(where: { $0.count < 60 && SafetyGate.shared.check($0) != nil }) else {
            return XCTFail("no crisis phrase found")
        }
        chat.send(phrase); await settle()
        XCTAssertTrue(app.showCrisis)
        XCTAssertTrue(live.text.isEmpty, "nothing goes to the model")
        XCTAssertFalse(app.weatherDoneToday)
        // The conversation ended (the crisis path stops it), but not as a check-in that went well: no end screen,
        // no tick, also once the chat has seen that the call is over.
        XCTAssertTrue(chat.talk.conversation.endedInCrisis)
        try? await Task.sleep(nanoseconds: 300_000_000)
        chat.sync()
        XCTAssertNil(chat.state.end, "a crisis is not \"Good to see you\"")
        XCTAssertFalse(app.weatherDoneToday)
    }
}

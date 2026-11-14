#if DEBUG
import AVFoundation
import Foundation

/// `-kaikuTalkDemo <state>` (Debug builds): Talk and the check-in chat on a scripted Live, with no network, no
/// microphone and no sound, so every call state can be looked at and photographed:
/// `connecting | live | speaking | muted | voicemuted | paused | denied | card | ended | closed`.
/// The real `Conversation` and `TalkModel` run; only the socket and the audio are stand-ins.
@MainActor
enum TalkDemo {
    static var state: String? { UserDefaults.standard.string(forKey: "kaikuTalkDemo") }

    /// The stand-in conversation for a demo run (nil in a normal run).
    static func conversation(intent: CompanionIntent, purpose: CompanionPurpose) -> Conversation? {
        guard let state else { return nil }
        let link = DemoLink()
        let c = Conversation(surface: KaikuPlatform.surface, intent: intent, audio: DemoAudio(),
                             transport: { event in link.event = event; return link },
                             permission: { state != "denied" }, localListener: false, purpose: purpose, typedWithoutMic: true)
        links[ObjectIdentifier(c)] = link
        return c
    }

    private static var links: [ObjectIdentifier: DemoLink] = [:]

    static let session = CompanionSessionResponse(
        session_id: "demo", model: "demo", voice: "demo", system_instruction: "",
        tools: [], context_card: ContextCard(time_of_day: "afternoon"), persona_version: "demo", safety_phrases_version: "demo",
        live_token: LiveToken(token: "demo", expires_at: "2099-01-01T00:00:00Z", new_session_expires_at: "2099-01-01T00:00:00Z"))

    /// Plays the scripted events that lead to `state`.
    static func run(_ state: String, conversation c: Conversation, app: AppModel, checkIn: Bool) async {
        guard let link = links[ObjectIdentifier(c)] else { return }
        func emit(_ events: LiveSession.Event...) async {
            for e in events { link.event?(e) }
            try? await Task.sleep(nanoseconds: 120_000_000)
        }
        c.adoptForTest(session: session, app: app, listens: state != "denied")
        guard state != "connecting" else { return }
        await emit(.ready)
        await emit(.kaikuText(checkIn ? "Hello, you. How is the day treating you so far?" : "Hi. Good to hear you. What's on your mind?"),
                   .kaikuTranscriptComplete, .turnComplete)
        await emit(.userText("A bit tired, but I went out for a coffee this morning."), .userTranscriptComplete)
        await emit(.kaikuText("Out for a coffee, even tired. That counts for something."), .kaikuTranscriptComplete, .turnComplete)
        switch state {
        case "speaking":
            (c.audioForDemo as? DemoAudio)?.hold = true
            await emit(.kaikuText("Tell me, what was the best bit of the morning?"), .audio(Data(count: 4800)))
        case "muted": c.setMuted(true)
        case "voicemuted": c.setVoiceMuted(true)
        case "paused": c.pause()
        case "card":
            await emit(.userText("Maybe something small would help."), .userTranscriptComplete)
            await emit(.toolCall(id: "demo-card", name: "suggest_activity",
                                 args: ["kind": .string("breathe"), "line": .string("A few slow breaths together?")]))
            await emit(.kaikuText("We could breathe slowly together for a minute, if you like."), .kaikuTranscriptComplete, .turnComplete)
        case "ended": c.stop(outcome: .completed)
        case "closed":
            await emit(.kaikuText("Good to see you. I'm around later."), .kaikuTranscriptComplete)
            await emit(.toolCall(id: "demo-end", name: "end_session", args: [:]))
        default: break
        }
    }
}

/// A socket that goes nowhere: the demo plays its events by hand.
final class DemoLink: ConversationTransport, @unchecked Sendable {
    var event: (@Sendable (LiveSession.Event) -> Void)?
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) {}
    func close() {}
    func sendAudio(_ pcm: Data) {}
    func audioStreamEnd() {}
    func sendText(_ text: String) {}
    func sendContext(_ event: String) {}
    func respond(id: String, name: String, result: JSONValue) {}
}

/// Audio that captures nothing and plays nothing; `hold` keeps "Kaiku is speaking" on screen.
final class DemoAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var hold = false
    var isPlaying = false
    func start() throws {}
    func stop() { isPlaying = false }
    func setMic(_ on: Bool) {}
    func play(_ pcm: Data) { if hold { isPlaying = true; onPlaying?(true) } }
    func flush() { isPlaying = false; onPlaying?(false) }
}
#endif

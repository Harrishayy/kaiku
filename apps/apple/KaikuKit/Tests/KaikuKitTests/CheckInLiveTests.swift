import AVFoundation
import XCTest
@testable import KaikuKit

/// Opt-in, paid: the check-in chat on the real voice path (the app's own `CheckInChat`, `Conversation` and
/// `LiveSession`, a private cloud with a model key), with typed input and no microphone. Kaiku's real reply audio
/// is counted, never played. Skipped unless set, so `swift test` stays free and offline:
///   KAIKU_CHECKIN_LIVE_CLOUD   e.g. http://127.0.0.1:18043
///   KAIKU_CHECKIN_LIVE_SCRIPT  "ordinary" | "hard" | "good"
///   KAIKU_CHECKIN_LIVE_OUT     evidence folder (<script>.txt)
@MainActor final class CheckInLiveTests: XCTestCase {
    /// Receives Kaiku's voice like a speaker would: "playing" lasts as long as the audio it was handed.
    private final class TimedAudio: ConversationAudioIO, @unchecked Sendable {
        var onPCM: ((Data) -> Void)?
        var onBuffer: ((AVAudioPCMBuffer) -> Void)?
        var onLevel: ((Float) -> Void)?
        var onPlaying: ((Bool) -> Void)?
        var onFailure: (() -> Void)?
        private let lock = NSLock()
        private var until = Date.distantPast
        private var total = 0
        private var generation = 0
        var bytes: Int { lock.lock(); defer { lock.unlock() }; return total }
        var isPlaying: Bool { lock.lock(); defer { lock.unlock() }; return Date() < until }
        func start() throws {}
        func stop() { flush() }
        func setMic(_ on: Bool) {}
        func play(_ pcm: Data) {
            lock.lock()
            let was = Date() < until
            total += pcm.count
            until = max(until, Date()).addingTimeInterval(Double(pcm.count) / 48_000)   // 24 kHz PCM16 mono
            generation += 1
            let g = generation, end = until
            lock.unlock()
            if !was { onPlaying?(true) }
            DispatchQueue.global().asyncAfter(deadline: .now() + end.timeIntervalSinceNow + 0.02) { [weak self] in
                guard let self else { return }
                self.lock.lock(); let latest = g == self.generation; self.lock.unlock()
                if latest { self.onPlaying?(false) }
            }
        }
        func flush() { lock.lock(); until = .distantPast; generation += 1; lock.unlock(); onPlaying?(false) }
    }

    static let scripts: [String: [String]] = [
        "ordinary": ["Pretty ordinary day. I did some laundry and had a coffee.",
                     "Nothing special planned, just a quiet evening.",
                     "That's about it. Thanks, see you later."],
        "hard": ["Honestly it's been a really hard day. My cat died last night and I can't stop crying.",
                 "She was with me for fourteen years. The flat feels so empty without her.",
                 "I don't really know what to do with myself tonight.",
                 "Maybe. I just miss her so much."],
        "good": ["I have news! I got the job I interviewed for last week. I start in January!",
                 "I'm so relieved. I really didn't think they'd pick me."],
    ]

    func testRealCheckInChat() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let cloud = env["KAIKU_CHECKIN_LIVE_CLOUD"].flatMap(URL.init(string:)), let out = env["KAIKU_CHECKIN_LIVE_OUT"] else {
            throw XCTSkip("Set KAIKU_CHECKIN_LIVE_CLOUD and KAIKU_CHECKIN_LIVE_OUT for the paid check-in proof")
        }
        let name = env["KAIKU_CHECKIN_LIVE_SCRIPT"] ?? "ordinary"
        let script = try XCTUnwrap(Self.scripts[name])
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("checkin-real-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
        let pairing = Pairing(baseURL: cloud, homeID: "checkin-\(name)-" + UUID().uuidString.prefix(6).lowercased(), token: nil)
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        let app = AppModel(defaults: defaults, pairing: pairing, api: APIClient(pairing: pairing, timeout: 30),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")))
        let audio = TimedAudio()
        let talk = TalkModel(opening: CheckInChat.opening) {
            Conversation(surface: .iphone, intent: .checkin, audio: audio, transport: { LiveSession(onEvent: $0) },
                         permission: { false }, localListener: false, purpose: .check_in, typedWithoutMic: true)
        }
        let chat = CheckInChat(talk: talk)
        var log: [String] = []
        let t0 = Date()
        func note(_ s: String) { log.append(String(format: "%5.1fs  %@", Date().timeIntervalSince(t0), s)) }
        var turnsDone = 0
        func quiet(_ limit: Double, after turns: Int) async {   // Kaiku finished a turn and its voice has played out
            let end = Date().addingTimeInterval(limit)
            while Date() < end {
                try? await Task.sleep(nanoseconds: 200_000_000)
                if chat.state.end != nil || (turnsDone > turns && !audio.isPlaying) { return }
            }
        }

        var lastKind = ""
        chat.talk.conversation.trace = { ev in
            let kind: String
            switch ev {
            case .audio: kind = "audio"
            case .kaikuText(let t): kind = "kaikuText(\(t))"
            case .userText(let t): kind = "userText(\(t))"
            case .toolCall(_, let n, let a): kind = "toolCall \(n) \(a)"
            default: kind = String(describing: ev)
            }
            if case .turnComplete = ev { turnsDone += 1 }
            if kind == "audio" && lastKind == "audio" { return }
            if kind == "modelOutput" { return }
            lastKind = kind
            if env["KAIKU_CHECKIN_LIVE_TRACE"] != nil { note("   · " + kind) }
        }
        await chat.start(app: app)
        XCTAssertTrue(chat.hasLive, "bootstrap: \(String(describing: chat.unavailable))")
        guard chat.hasLive else { return }
        note("opened: purpose check_in, depth \(chat.talk.conversation.session?.openingDepth?.rawValue ?? "-"), typed only \(chat.typedOnly)")
        let ready = Date().addingTimeInterval(20)
        while chat.connecting && Date() < ready { try await Task.sleep(nanoseconds: 100_000_000) }
        await quiet(15, after: 0)
        var shown = 0
        func flush() {
            for l in chat.lines.dropFirst(shown) { note((l.me ? "PERSON: " : "KAIKU:  ") + l.text) }
            shown = chat.lines.count
        }
        flush()
        for line in script where chat.state.end == nil {
            let plans = chat.talk.conversation.planCount
            let turns = turnsDone
            chat.send(line)
            await quiet(25, after: turns)
            flush()
            if chat.talk.conversation.planCount > plans, let p = chat.talk.conversation.plan {
                note("FEEL → stance \(p.stance ?? "-"), depth \(p.depth.rawValue), may_offer \(p.mayOffer ?? "none"), activity \(p.offerActivity ?? "none"); card: \(chat.card?.kind ?? "none")")
            }
            note("state: turns \(chat.state.personTurns), staying \(chat.state.staying), end \(String(describing: chat.state.end)), ticked \(app.weatherDoneToday)")
        }
        // Give a close that was just called the time to be said.
        let closing = Date().addingTimeInterval(14)
        while chat.phase != .idle && chat.state.end != nil && Date() < closing { try await Task.sleep(nanoseconds: 200_000_000) }
        flush()
        note("tools: \(chat.talk.conversation.toolsUsed)  ·  Kaiku's voice: \(audio.bytes / 48_000) s of audio  ·  end \(String(describing: chat.state.end))  ·  stop ticked \(app.weatherDoneToday)")
        chat.leave()
        let text = log.joined(separator: "\n") + "\n"
        try text.write(toFile: out + "/\(name).txt", atomically: true, encoding: .utf8)
        print(text)
        XCTAssertGreaterThan(audio.bytes, 24_000, "Kaiku answered out loud")
    }
}

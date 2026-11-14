import AVFoundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import KaikuKit

/// Opt-in, paid (about a minute and a half of real Gemini Live): a walk-style conversation in which Kaiku is told
/// things nobody said (camera on, look nudges) while it gets a dull, featureless picture once a second. With
/// proactive audio the model declines such turns with a second of non-speech sound; this checks on the real voice
/// path (the app's own `Conversation` + `LiveSession`, a private cloud with a model key, typed input, no
/// microphone) that none of that sound is played and none of it becomes a line, and writes the raw frames:
///   KAIKU_GATE_LIVE_CLOUD   e.g. http://127.0.0.1:18043
///   KAIKU_GATE_LIVE_OUT     evidence folder (gate-raw.txt, gate-summary.txt)
@MainActor final class GateLiveTests: XCTestCase {
    /// Counts what would have come out of the speaker; "playing" lasts as long as the audio it was handed.
    private final class Speaker: ConversationAudioIO, @unchecked Sendable {
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

    /// One model turn as the socket delivered it.
    private struct Turn {
        var cause: String
        var fragments: [String] = []
        var received = 0
        var firstAudio: Date?
        var firstText: Date?
        var playedBefore = 0
        var played = 0
    }

    /// A flat grey picture: nothing to remark on.
    private static func dullFrame() -> Data {
        let ctx = CGContext(data: nil, width: 360, height: 640, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
        ctx.setFillColor(CGColor(red: 0.55, green: 0.55, blue: 0.55, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: 360, height: 640))
        let data = NSMutableData()
        let dest = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil)!
        CGImageDestinationAddImage(dest, ctx.makeImage()!, [kCGImageDestinationLossyCompressionQuality: 0.6] as CFDictionary)
        CGImageDestinationFinalize(dest)
        return data as Data
    }

    func testADullViewIsDeclinedWithNoSoundAndNoBubble() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let cloud = env["KAIKU_GATE_LIVE_CLOUD"].flatMap(URL.init(string:)), let out = env["KAIKU_GATE_LIVE_OUT"] else {
            throw XCTSkip("Set KAIKU_GATE_LIVE_CLOUD and KAIKU_GATE_LIVE_OUT for the paid gate proof")
        }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("gate-real-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
        let pairing = Pairing(baseURL: cloud, homeID: "gate-" + UUID().uuidString.prefix(6).lowercased(), token: nil)
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        let app = AppModel(defaults: defaults, pairing: pairing, api: APIClient(pairing: pairing, timeout: 30),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")))
        app.consents[.see] = true
        app.consents[.transcripts] = true
        let speaker = Speaker()
        let c = Conversation(surface: .glasses, intent: .walk, audio: speaker, transport: { LiveSession(onEvent: $0) },
                             permission: { true }, localListener: false, purpose: .walk)
        c.walkStyle = .playful

        let t0 = Date()
        var raw: [String] = []
        var turns: [Turn] = []
        var open: Turn?
        var cause = "the walk's opening line"
        func stamp() -> String { String(format: "%6.2fs", Date().timeIntervalSince(t0)) }
        func begin() { if open == nil { open = Turn(cause: cause, playedBefore: speaker.bytes) } }
        c.trace = { ev in
            switch ev {
            case .audio(let d):
                begin(); open?.received += d.count
                if open?.firstAudio == nil { open?.firstAudio = Date(); raw.append("\(stamp())  audio begins") }
            case .kaikuText(let s):
                begin(); open?.fragments.append(s)
                if open?.firstText == nil { open?.firstText = Date() }
                raw.append("\(stamp())  outputTranscription \(String(reflecting: s))")
            case .userText(let s): raw.append("\(stamp())  inputTranscription \(String(reflecting: s))")
            case .turnComplete:
                raw.append("\(stamp())  turnComplete  (audio received \(open?.received ?? 0) bytes)")
                if var t = open { t.played = speaker.bytes - t.playedBefore; turns.append(t); open = nil }
            case .interrupted: raw.append("\(stamp())  interrupted")
            case .toolCall(_, let name, _): raw.append("\(stamp())  toolCall \(name)")
            case .ready: raw.append("\(stamp())  setupComplete")
            default: break
            }
        }
        func quiet(_ seconds: Double) async {               // a walk's pace: the next thing comes after this long
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            let until = Date().addingTimeInterval(6)        // and never into Kaiku's sentence
            while Date() < until, speaker.isPlaying || c.phase == .thinking { try? await Task.sleep(nanoseconds: 200_000_000) }
        }
        func say(_ context: String, as what: String) { cause = what; raw.append("\(stamp())  → context \(what)"); c.context(context) }

        c.onReady = { [weak c] in c?.context("[walk started · playful · the person is walking with their phone]") }
        let started = await c.start(app: app)
        XCTAssertTrue(started, "the private cloud answered with a Live token")
        for _ in 0..<200 where c.liveSince == nil { try? await Task.sleep(nanoseconds: 200_000_000) }
        XCTAssertNotNil(c.liveSince, "Live setup completed")
        await quiet(8)
        cause = "the person's typed line"
        raw.append("\(stamp())  → typed")
        c.send(text: "Hello Kaiku. Let's just walk quietly for a while, no need to talk.")
        await quiet(9)

        // Pictures start: a flat grey view, about one a second, for the rest of the run.
        let frame = Self.dullFrame()
        let frames = Task { @MainActor in
            while !Task.isCancelled { _ = c.sendFrame(frame); try? await Task.sleep(nanoseconds: 1_000_000_000) }
        }
        say("[glasses camera on · you now get about one still picture a second of what the person is looking at]", as: "camera-on context")
        await quiet(9)
        let look = c.session?.walk?.look_prompt ?? "[a look around: if something in the picture is worth a few warm words, say them; otherwise stay silent]"
        for n in 1...4 {
            cause = "look nudge \(n)"
            raw.append("\(stamp())  → nudge \(n)")
            c.nudge(look)
            await quiet(10)
        }
        say("[spotting game · birds · 1 of 3 found · 2 left]", as: "walk event context")
        await quiet(9)
        frames.cancel()
        let lines = c.lines
        let stored = Conversation.transcript(lines)
        c.stop(outcome: .completed)
        try? await Task.sleep(nanoseconds: 1_500_000_000)

        var summary = ["cloud \(cloud.absoluteString)  home \(pairing.homeID)  frames sent \(c.framesSent)", "",
                       "turn  cause                       raw transcription                                  received  played   audio→text"]
        var declined = 0
        for (i, t) in turns.enumerated() {
            let said = t.fragments.joined()
            let word = Heard(said) == .word
            if !word { declined += 1 }
            let lag = t.firstAudio.flatMap { a in t.firstText.map { String(format: "%.2fs", $0.timeIntervalSince(a)) } } ?? "-"
            summary.append(String(format: "%3d   %@ %@ %6.2fs  %6.2fs   %@", i + 1, t.cause.padding(toLength: 27, withPad: " ", startingAt: 0),
                                  String(reflecting: t.fragments).prefix(50).padding(toLength: 50, withPad: " ", startingAt: 0),
                                  Double(t.received) / 48_000, Double(t.played) / 48_000, lag))
            if !word { XCTAssertEqual(t.played, 0, "turn \(i + 1) (\(t.cause)) had no real word and must not be heard: \(t.fragments)") }
            else if t.received > 0 { XCTAssertGreaterThan(t.played, 0, "turn \(i + 1) had words and must be heard: \(said)") }
        }
        summary += ["", "turns without a real word: \(declined) of \(turns.count); sound played for them: 0 s",
                    "", "lines on screen:"] + lines.map { "  \($0.me ? "person" : "kaiku "): \($0.text)" }
        summary += ["", "stored transcript:"] + stored.map { "  \($0.role.rawValue): \($0.text)" }
        try raw.joined(separator: "\n").write(toFile: out + "/gate-raw.txt", atomically: true, encoding: .utf8)
        try summary.joined(separator: "\n").write(toFile: out + "/gate-summary.txt", atomically: true, encoding: .utf8)
        print(summary.joined(separator: "\n"))

        for l in lines {
            XCTAssertFalse(l.text.contains("<") || l.text.contains(">") || l.text.contains("{"), "a marker reached the screen: \(l.text)")
            XCTAssertTrue(l.text.contains(where: { $0.isLetter || $0.isNumber }), "a line with no word: \(String(reflecting: l.text))")
        }
        XCTAssertFalse(stored.contains { $0.text.contains("<") || $0.text.contains("{") })
        XCTAssertGreaterThan(c.framesSent, 20, "the dull pictures really went out")
    }
}

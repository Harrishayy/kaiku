@preconcurrency import AVFoundation
import CoreGraphics
import CoreText
import XCTest
@testable import KaikuKit

private final class QuietAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying: Bool { false }
    private let lock = NSLock()
    private var bytes = 0
    var playedBytes: Int { lock.lock(); defer { lock.unlock() }; return bytes }
    var mic = false
    func start() throws {}
    func stop() {}
    func setMic(_ on: Bool) { mic = on }
    func play(_ pcm: Data) { lock.lock(); bytes += pcm.count; lock.unlock() }
    func flush() {}
}

private final class CountingTransport: ConversationTransport, @unchecked Sendable {
    let onEvent: @Sendable (LiveSession.Event) -> Void
    private let lock = NSLock()
    private var _frames: [Data] = []
    private var _contexts: [String] = []
    var frames: [Data] { lock.lock(); defer { lock.unlock() }; return _frames }
    var contexts: [String] { lock.lock(); defer { lock.unlock() }; return _contexts }
    init(_ onEvent: @escaping @Sendable (LiveSession.Event) -> Void) { self.onEvent = onEvent }
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) { onEvent(.ready) }
    func close() {}
    func sendAudio(_ pcm: Data) {}
    func audioStreamEnd() {}
    func sendText(_ text: String) {}
    func sendVideo(_ jpeg: Data) { lock.lock(); _frames.append(jpeg); lock.unlock() }
    func sendContext(_ event: String) { lock.lock(); _contexts.append(event); lock.unlock() }
    func respond(id: String, name: String, result: JSONValue) {}
}

private func picture(_ text: String? = nil, w: Int = 360, h: Int = 640, gray: CGFloat = 0.8) -> CGImage {
    let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    ctx.setFillColor(red: gray, green: gray, blue: gray, alpha: 1)
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    if let text {
        ctx.setFillColor(red: 0.1, green: 0.35, blue: 0.75, alpha: 1)
        ctx.fill(CGRect(x: 20, y: h / 2 - 90, width: w - 40, height: 180))
        let font = CTFontCreateWithName("Helvetica-Bold" as CFString, 56, nil)
        let attr = NSAttributedString(string: text, attributes: [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(red: 1, green: 1, blue: 1, alpha: 1)])
        let line = CTLineCreateWithAttributedString(attr)
        ctx.textPosition = CGPoint(x: 40, y: h / 2 - 20)
        CTLineDraw(line, ctx)
    }
    return ctx.makeImage()!
}

final class GlassesVisionTests: XCTestCase {
    func testVideoFrameIsARealtimeJPEGBlob() throws {
        let jpeg = try XCTUnwrap(GlassesVision.encode(picture())).jpeg
        let m = LiveSession.video(jpeg)
        let video = try XCTUnwrap((m["realtimeInput"] as? [String: Any])?["video"] as? [String: Any])
        XCTAssertEqual(video["mimeType"] as? String, "image/jpeg")
        XCTAssertEqual(Data(base64Encoded: try XCTUnwrap(video["data"] as? String)), jpeg)
        XCTAssertEqual(Array(jpeg.prefix(2)), [0xFF, 0xD8], "JPEG start marker")
    }

    func testEncodeKeepsStreamSizeAndShrinksLargePhotos() throws {
        let small = try XCTUnwrap(GlassesVision.encode(picture()))
        XCTAssertEqual([small.width, small.height], [360, 640])
        let big = try XCTUnwrap(GlassesVision.encode(picture(w: 1440, h: 2560)))
        XCTAssertEqual(max(big.width, big.height), GlassesVision.maxSide)
        XCTAssertLessThan(big.jpeg.count, 200_000)
    }

    func testLuminanceFollowsBrightness() {
        XCTAssertEqual(GlassesVision.luminance(picture(gray: 0.9)), 0.9, accuracy: 0.03)
        XCTAssertEqual(GlassesVision.luminance(picture(gray: 0.1)), 0.1, accuracy: 0.03)
    }

    func testSelfTestLevelBar() {
        XCTAssertEqual(GlassesSelfTest.bar(-90), 0)
        XCTAssertEqual(GlassesSelfTest.bar(-30), 0.5, accuracy: 0.001)
        XCTAssertEqual(GlassesSelfTest.bar(3), 1)
    }

    func testLogIsJSONLinesWithoutMedia() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("glasses-log-\(UUID().uuidString).jsonl")
        defer { try? FileManager.default.removeItem(at: url) }
        let log = GlassesLog(url: url)
        log.log("audio_route", ["in": "Ray-Ban Meta", "settled": true, "n": 3, "level": 0.12345, "blob": Data([1, 2, 3])])
        log.log("error", ["where": "test", "error": String(repeating: "x", count: 900)])
        let lines = try String(contentsOf: url, encoding: .utf8).split(separator: "\n")
        XCTAssertEqual(lines.count, 2)
        let first = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(lines[0].utf8)) as? [String: Any])
        XCTAssertEqual(first["event"] as? String, "audio_route")
        XCTAssertEqual(first["settled"] as? Bool, true)
        XCTAssertNotNil(first["ts"])
        XCTAssertEqual(first["blob"] as? String, "3 bytes", "binary values are never written, only their description")
        let second = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(lines[1].utf8)) as? [String: Any])
        XCTAssertEqual((second["error"] as? String)?.count, 300, "long text is cut")
        XCTAssertEqual(log.recent(1).count, 1)
    }

    func testRouteWords() {
        var r = TalkAudio.Route()
        XCTAssertFalse(r.active)
        r.input = "Ray-Ban Meta"; r.inputType = "BluetoothHFP"; r.output = "Ray-Ban Meta"; r.outputType = "BluetoothHFP"
        XCTAssertTrue(r.inTheEar && r.headsetMic && r.headsetOut)
        r.input = "iPhone Microphone"; r.inputType = "MicrophoneBuiltIn"; r.outputType = "BluetoothA2DPOutput"
        XCTAssertTrue(r.headsetOut); XCTAssertFalse(r.inTheEar)
    }
}

/// Frames reach Live only with the person's choice on, an open unmuted conversation, and nothing paused.
@MainActor final class GlassesFrameGateTests: XCTestCase {
    private func make() async throws -> (Conversation, CountingTransport, AppModel) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("gate-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let pairing = Pairing(baseURL: URL(string: "http://127.0.0.1:9")!, homeID: "gate", token: nil)
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: pairing, api: APIClient(pairing: pairing, timeout: 1),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")))
        var transport: CountingTransport?
        let c = Conversation(surface: .glasses, intent: .walk, audio: QuietAudio(),
                             transport: { let t = CountingTransport($0); transport = t; return t },
                             permission: { true }, localListener: false)
        let session = try JSONDecoder().decode(CompanionSessionResponse.self, from: Data(#"""
        {"session_id":"s1","model":"m","voice":"v","system_instruction":"i","tools":[],"persona_version":"p",
         "safety_phrases_version":"1","context_card":{"time_of_day":"morning"},
         "live_token":{"token":"t","expires_at":"2099-01-01T00:00:00Z","new_session_expires_at":"2099-01-01T00:00:00Z"}}
        """#.utf8))
        c.adoptForTest(session: session, app: app)
        let end = Date().addingTimeInterval(2)
        while c.phase != .listening && Date() < end { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertEqual(c.phase, .listening)
        return (c, try XCTUnwrap(transport), app)
    }

    func testFramesOnlyWithChoiceOpenAndUnmuted() async throws {
        let (c, t, app) = try await make()
        let jpeg = try XCTUnwrap(GlassesVision.encode(picture())).jpeg
        XCTAssertFalse(c.sendFrame(jpeg), "the choice is off by default")
        XCTAssertFalse(Signal.see.defaultOn)
        app.consents[.see] = true
        XCTAssertTrue(c.sendFrame(jpeg))
        XCTAssertEqual(t.frames, [jpeg]); XCTAssertEqual(c.framesSent, 1)
        c.setMuted(true)
        XCTAssertFalse(c.sendFrame(jpeg), "quiet walk: nothing is sent")
        c.setMuted(false)
        c.pause()
        XCTAssertFalse(c.sendFrame(jpeg), "phone call: nothing is sent")
        c.resume()
        XCTAssertTrue(c.sendFrame(jpeg))
        app.pausedAll = true
        XCTAssertFalse(c.sendFrame(jpeg), "pause everything: nothing is sent")
        app.pausedAll = false
        app.consents[.see] = false
        XCTAssertFalse(c.sendFrame(jpeg))
        app.consents[.see] = true
        c.stop()
        XCTAssertFalse(c.sendFrame(jpeg), "closed conversation: nothing is sent")
        XCTAssertEqual(t.frames.count, 2)
    }
}

/// Paid proof without a microphone or glasses: a generated picture of a sign + a synthetic spoken question go
/// through the production `Conversation` + `LiveSession` to the real cloud bootstrap (glasses surface) and Gemini
/// Live; Kaiku's answer must contain the word on the sign.
///   KAIKU_VISION_TEST_CLOUD=http://127.0.0.1:<port> KAIKU_VISION_TEST_WAV48=<48 kHz mono PCM16, "what does the sign say">
///   swift test --filter RealGlassesVisionTests
@MainActor final class RealGlassesVisionTests: XCTestCase {
    func testKaikuAnswersFromThePictureAndTheSpokenQuestion() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let cloud = env["KAIKU_VISION_TEST_CLOUD"].flatMap(URL.init(string:)), let path = env["KAIKU_VISION_TEST_WAV48"] else {
            throw XCTSkip("Set KAIKU_VISION_TEST_CLOUD and KAIKU_VISION_TEST_WAV48 for the paid vision proof")
        }
        let word = env["KAIKU_VISION_TEST_WORD"] ?? "HARBOR"
        let speech = try Data(contentsOf: URL(fileURLWithPath: path))
        XCTAssertGreaterThan(speech.count, 96_000)
        let frame = try XCTUnwrap(GlassesVision.encode(picture(word)))
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("vision-real-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let pairing = Pairing(baseURL: cloud, homeID: "vision-proof-" + UUID().uuidString.prefix(8).lowercased(), token: nil)
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: pairing, api: APIClient(pairing: pairing, timeout: 30),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")))
        app.consents[.see] = true
        let audio = QuietAudio()
        let c = Conversation(surface: .glasses, intent: .walk, audio: audio, transport: { LiveSession(onEvent: $0) },
                             permission: { true }, localListener: false)
        defer { c.stop() }
        let started = await c.start(app: app)
        XCTAssertTrue(started, "bootstrap: \(String(describing: c.unavailableReason))")
        guard started else { return }
        let ready = Date().addingTimeInterval(20)
        while c.phase == .connecting && Date() < ready { try await Task.sleep(nanoseconds: 50_000_000) }
        XCTAssertTrue(c.isLive)
        c.context("[glasses camera on · you now get about one still picture a second of what the person is looking at]")
        // one frame a second, before and during the question
        let frames = Task { @MainActor in
            while !Task.isCancelled { c.sendFrame(frame.jpeg); try? await Task.sleep(nanoseconds: 1_000_000_000) }
        }
        try await Task.sleep(nanoseconds: 6_000_000_000)   // let any greeting finish
        let samples: [Float] = speech.withUnsafeBytes { $0.bindMemory(to: Int16.self).map { Float($0) / 32768 } }
        let down = MicDownsampler()
        for start in stride(from: 0, to: samples.count, by: 1024) {
            if let pcm = down.convert(samples: Array(samples[start..<min(start + 1024, samples.count)]), sampleRate: 48_000) { audio.onPCM?(pcm) }
            try await Task.sleep(nanoseconds: 21_000_000)
        }
        for _ in 0..<25 { audio.onPCM?(Data(count: 3200)); try await Task.sleep(nanoseconds: 100_000_000) }
        let deadline = Date().addingTimeInterval(40)
        func answered() -> Bool {
            guard let i = c.lines.firstIndex(where: \.me) else { return false }
            return c.lines[i...].contains { !$0.me && $0.text.lowercased().contains(word.lowercased()) }
        }
        while Date() < deadline && !answered() { try await Task.sleep(nanoseconds: 200_000_000) }
        frames.cancel()
        let person = c.lines.filter(\.me).map(\.text).joined(separator: " ")
        let kaiku = c.lines.filter { !$0.me }.map(\.text).joined(separator: " | ")
        print("VISION-PROOF person=\(person) || kaiku=\(kaiku) || frames=\(c.framesSent) audio_s=\(Double(audio.playedBytes / 2) / 24_000) tools=\(c.toolsUsed)")
        XCTAssertFalse(person.isEmpty, "the spoken question was transcribed")
        XCTAssertGreaterThan(c.framesSent, 3)
        XCTAssertGreaterThan(audio.playedBytes, 24_000, "Kaiku's voice audio arrived")
        XCTAssertTrue(answered(), "Kaiku's answer should contain the word on the sign (\(word)): \(kaiku)")
    }
}

@preconcurrency import AVFoundation
import XCTest
@testable import KaikuKit

/// The mic → 16 kHz PCM16 path on every hardware format the apps meet, without opening a microphone:
/// synthetic buffers shaped like a Mac's 48 kHz mic, a Mac voice-processing input (several channels), a 44.1 kHz
/// stereo interface and a Bluetooth HFP headset (glasses) at 16 kHz / 8 kHz.
final class MicDownsamplerTests: XCTestCase {
    /// A 440 Hz tone on channel 0; other channels carry loud noise that must not leak into the result.
    private func buffer(rate: Double, channels: UInt32, interleaved: Bool = false, seconds: Double = 0.5) -> AVAudioPCMBuffer {
        let fmt: AVAudioFormat
        if channels <= 2 {
            fmt = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate, channels: channels, interleaved: interleaved)!
        } else {
            let layout = AVAudioChannelLayout(layoutTag: kAudioChannelLayoutTag_DiscreteInOrder | channels)!
            fmt = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate, interleaved: interleaved, channelLayout: layout)
        }
        let n = AVAudioFrameCount(rate * seconds)
        let b = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: n)!
        b.frameLength = n
        for i in 0..<Int(n) {
            let tone = Float(0.5 * sin(2 * Double.pi * 440 * Double(i) / rate))
            if interleaved {
                let p = b.floatChannelData![0]
                p[i * Int(channels)] = tone
                for c in 1..<Int(channels) { p[i * Int(channels) + c] = 0.9 }
            } else {
                b.floatChannelData![0][i] = tone
                for c in 1..<Int(channels) { b.floatChannelData![c][i] = 0.9 }
            }
        }
        return b
    }

    /// Zero crossings per second / 2 ≈ the tone's frequency.
    private func frequency(_ pcm: Data) -> Double {
        let s = pcm.withUnsafeBytes { Array($0.bindMemory(to: Int16.self)) }
        var crossings = 0
        for i in 1..<s.count where (s[i - 1] < 0) != (s[i] < 0) { crossings += 1 }
        return Double(crossings) / 2 / (Double(s.count) / 16_000)
    }

    private func check(_ b: AVAudioPCMBuffer, _ name: String, file: StaticString = #filePath, line: UInt = #line) {
        guard let pcm = MicDownsampler().convert(b) else { return XCTFail("\(name): no audio", file: file, line: line) }
        let seconds = Double(pcm.count / 2) / 16_000
        XCTAssertEqual(seconds, 0.5, accuracy: 0.03, "\(name): duration", file: file, line: line)
        XCTAssertEqual(frequency(pcm), 440, accuracy: 25, "\(name): tone survives, other channels do not leak", file: file, line: line)
        let peak = pcm.withUnsafeBytes { $0.bindMemory(to: Int16.self).map { abs(Int($0)) }.max() ?? 0 }
        XCTAssertGreaterThan(peak, 12_000, "\(name): level kept", file: file, line: line)
        XCTAssertLessThan(peak, 20_000, "\(name): not clipped by a channel mix", file: file, line: line)
    }

    func testMacBuiltInMic48kMono() { check(buffer(rate: 48_000, channels: 1), "48k mono") }
    func testStereoInterface44k() { check(buffer(rate: 44_100, channels: 2), "44.1k stereo") }
    func testInterleavedStereo() { check(buffer(rate: 48_000, channels: 2, interleaved: true), "48k interleaved stereo") }
    func testMacVoiceProcessingMultiChannelInput() {
        check(buffer(rate: 48_000, channels: 3), "48k 3-channel voice processing")
        check(buffer(rate: 44_100, channels: 5), "44.1k 5-channel voice processing")
        check(buffer(rate: 48_000, channels: 9), "48k 9-channel voice processing")
    }
    func testBluetoothHFPGlasses() {
        check(buffer(rate: 16_000, channels: 1), "16k HFP")
        check(buffer(rate: 8_000, channels: 1), "8k HFP")
    }

    /// A route change mid-conversation (Mac mic → glasses) changes the rate; the same instance keeps working.
    func testRateChangeRebuildsConverter() {
        let d = MicDownsampler()
        let a = d.convert(buffer(rate: 48_000, channels: 1))
        let b = d.convert(buffer(rate: 16_000, channels: 1))
        XCTAssertNotNil(a); XCTAssertNotNil(b)
        XCTAssertEqual(frequency(b!), 440, accuracy: 25)
    }

    /// Streaming many small tap buffers must not lose or duplicate audio (the Live VAD needs a steady stream).
    func testStreamingChunksKeepDuration() {
        let d = MicDownsampler()
        var total = 0
        for _ in 0..<100 { total += (d.convert(buffer(rate: 48_000, channels: 1, seconds: 1024.0 / 48_000))?.count ?? 0) / 2 }
        XCTAssertEqual(Double(total) / 16_000, 100 * 1024.0 / 48_000, accuracy: 0.02)
    }

    func testLevelAndEmpty() {
        XCTAssertEqual(MicDownsampler.level([]), -120)
        XCTAssertEqual(MicDownsampler.level([Float](repeating: 0.5, count: 100)), -6.02, accuracy: 0.1)
        XCTAssertNil(MicDownsampler().convert(samples: [], sampleRate: 48_000))
        XCTAssertNil(MicDownsampler().convert(samples: [0.1], sampleRate: 0))
    }
}

private final class FakeAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying = false
    var mic = false
    var resumed = 0
    func start() throws {}
    func stop() { mic = false }
    func setMic(_ on: Bool) { mic = on }
    func play(_ pcm: Data) {}
    func flush() {}
    func resumeAfterInterruption() { resumed += 1 }
}
private final class FakeTransport: ConversationTransport, @unchecked Sendable {
    var event: (@Sendable (LiveSession.Event) -> Void)?
    var connects = 0
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) { connects += 1 }
    func close() {}
    func sendAudio(_ pcm: Data) {}
    func audioStreamEnd() {}
    func sendText(_ text: String) {}
    func sendContext(_ event: String) {}
    func respond(id: String, name: String, result: JSONValue) {}
}
private final class SessionHTTP: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let json = request.url!.path.hasSuffix("session")
            ? #"{"session_id":"s","model":"m","voice":"v","system_instruction":"t","tools":[],"context_card":{"time_of_day":"morning"},"persona_version":"p","safety_phrases_version":"s","live_token":{"token":"synthetic","expires_at":"2099-01-01T00:00:00Z","new_session_expires_at":"2099-01-01T00:00:00Z"}}"#
            : #"{"ok":true,"id":"s","accepted":1,"duplicates":0,"rejected":[],"events":[]}"#
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

/// Failure states of a Live conversation end in a specific, retryable reason — never a stuck "connecting".
@MainActor final class SpeechRobustnessTests: XCTestCase {
    private func fixture() -> (AppModel, FakeAudio, FakeTransport, Conversation) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let p = Pairing(baseURL: URL(string: "https://speech.test")!, homeID: "synthetic", token: nil)
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [SessionHTTP.self]
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        let app = AppModel(defaults: defaults, pairing: p, api: APIClient(pairing: p, maxAttempts: 1, session: URLSession(configuration: config)),
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")))
        let audio = FakeAudio(), live = FakeTransport()
        let c = Conversation(surface: .mac, intent: .talk, audio: audio, transport: { e in live.event = e; return live },
                             permission: { true }, localListener: false)
        return (app, audio, live, c)
    }
    private func wait(_ seconds: Double) async { try? await Task.sleep(nanoseconds: UInt64(seconds * 1e9)) }

    func testSetupNeverAcknowledgedEndsInRetryableVoiceReasonNotEndlessConnecting() async {
        let old = Conversation.readyTimeout
        Conversation.readyTimeout = 0.05
        defer { Conversation.readyTimeout = old }
        let (app, audio, live, c) = fixture()
        let started = await c.start(app: app)
        XCTAssertTrue(started)
        XCTAssertEqual(c.phase, .connecting)
        for _ in 0..<80 where c.phase != .unavailable { await wait(0.1) }
        XCTAssertEqual(c.phase, .unavailable)
        XCTAssertEqual(c.unavailableReason, .voice)
        XCTAssertGreaterThanOrEqual(live.connects, 2, "retried before giving up")
        XCTAssertFalse(audio.mic)
        // …and the person can simply try again.
        Conversation.readyTimeout = 30
        let again = await c.start(app: app)
        XCTAssertTrue(again)
        live.event?(.ready); await wait(0.05)
        XCTAssertEqual(c.phase, .listening)
        c.stop()
    }

    func testDropAfterAWorkingConversationReportsConnection() async {
        let (app, _, live, c) = fixture()
        _ = await c.start(app: app)
        live.event?(.ready); await wait(0.05)
        XCTAssertEqual(c.phase, .listening)
        for _ in 0..<4 {
            live.event?(.closed)
            for _ in 0..<40 where c.phase == .listening { await wait(0.05) }
            await wait(1.5)
        }
        XCTAssertEqual(c.phase, .unavailable)
        XCTAssertEqual(c.unavailableReason, .connection)
    }

    func testPhoneCallInterruptionRestartsAudioAndMicOnResume() async {
        let (app, audio, live, c) = fixture()
        _ = await c.start(app: app)
        live.event?(.ready); await wait(0.05)
        XCTAssertTrue(audio.mic)
        c.pause()
        XCTAssertEqual(c.phase, .paused); XCTAssertFalse(audio.mic)
        c.resume()
        XCTAssertEqual(audio.resumed, 1, "the engine is restarted, not only the audio session")
        XCTAssertTrue(audio.mic); XCTAssertEqual(c.phase, .listening)
        c.stop()
    }
}

private final class RecordingAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying = false
    var mic = false
    private let lock = NSLock()
    private var bytes = 0
    var playedBytes: Int { lock.lock(); defer { lock.unlock() }; return bytes }
    func start() throws {}
    func stop() { mic = false }
    func setMic(_ on: Bool) { mic = on }
    func play(_ pcm: Data) { lock.lock(); bytes += pcm.count; lock.unlock() }
    func flush() {}
}

/// Paid, opt-in: the whole speech path against a real cloud + Gemini Live, with a synthetic voice instead of a
/// microphone. The fixture is 48 kHz (a Mac mic's rate) and goes through the production `MicDownsampler` in
/// tap-sized buffers, then the production `Conversation` + `LiveSession`:
///   person audio in → person transcript → Kaiku audio + Kaiku transcript → stored only with the opt-in.
///   KAIKU_SPEECH_TEST_CLOUD=http://127.0.0.1:18041 KAIKU_SPEECH_TEST_WAV48=/path/person48k.pcm \
///   [KAIKU_SPEECH_TEST_SURFACE=iphone|mac] [KAIKU_SPEECH_TEST_EXPECT=walk] swift test --filter RealSpeechPathTests
@MainActor final class RealSpeechPathTests: XCTestCase {
    private func converse(cloud: URL, speech48k: Data, surface: CompanionSurface, keepWords: Bool, home: String)
        async throws -> (person: String, kaiku: String, audioSeconds: Double, episode: String?, api: APIClient) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("speech-real-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let pairing = Pairing(baseURL: cloud, homeID: home, token: nil)
        let api = APIClient(pairing: pairing, timeout: 30)
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: pairing, api: api,
                           queue: OfflineQueue(url: dir.appendingPathComponent("e.json")), episodes: EpisodeOutbox(url: dir.appendingPathComponent("p.json")))
        app.consents[.transcripts] = keepWords
        let audio = RecordingAudio()
        let c = Conversation(surface: surface, intent: .talk, audio: audio, transport: { LiveSession(onEvent: $0) },
                             permission: { true }, localListener: false)
        defer { c.stop() }
        let started = await c.start(app: app)
        XCTAssertTrue(started, "bootstrap: \(String(describing: c.unavailableReason))")
        guard started else { return ("", "", 0, nil, api) }
        let ready = Date().addingTimeInterval(20)
        while c.phase == .connecting && Date() < ready { try await Task.sleep(nanoseconds: 50_000_000) }
        XCTAssertTrue(c.isLive && audio.mic, "Live setup acknowledged, mic open")
        // 48 kHz mono PCM16 → float tap buffers of 1024 frames → the production downsampler → onPCM, in real time.
        let samples: [Float] = speech48k.withUnsafeBytes { $0.bindMemory(to: Int16.self).map { Float($0) / 32768 } }
        let down = MicDownsampler()
        var sent = 0
        for start in stride(from: 0, to: samples.count, by: 1024) {
            let chunk = Array(samples[start..<min(start + 1024, samples.count)])
            if let pcm = down.convert(samples: chunk, sampleRate: 48_000) { audio.onPCM?(pcm); sent += pcm.count }
            try await Task.sleep(nanoseconds: 21_000_000)
        }
        XCTAssertEqual(Double(sent / 2) / 16_000, Double(samples.count) / 48_000, accuracy: 0.05, "no audio lost in conversion")
        for _ in 0..<25 { audio.onPCM?(Data(count: 3200)); try await Task.sleep(nanoseconds: 100_000_000) }   // trailing quiet → VAD end
        // Kaiku greets on opening and answers the question; wait until it has replied after the person's words.
        let deadline = Date().addingTimeInterval(40)
        func kaikuAfterPerson() -> Bool {
            guard let i = c.lines.firstIndex(where: \.me) else { return false }
            return c.lines[i...].contains { !$0.me && !$0.text.isEmpty }
        }
        while Date() < deadline && !(kaikuAfterPerson() && c.phase == .listening) { try await Task.sleep(nanoseconds: 100_000_000) }
        try await Task.sleep(nanoseconds: 1_500_000_000)
        let person = c.lines.filter(\.me).map(\.text).joined(separator: " ")
        let kaiku = c.lines.filter { !$0.me }.map(\.text).joined(separator: " ")
        let episode = c.session?.session_id
        let seconds = Double(audio.playedBytes / 2) / 24_000
        c.stop(); await app.flush()
        let flushed = Date().addingTimeInterval(10)
        while !app.episodes.entries.isEmpty && Date() < flushed { try await Task.sleep(nanoseconds: 200_000_000); await app.flush() }
        XCTAssertTrue(app.episodes.entries.isEmpty, "episode acknowledged by the cloud")
        return (person, kaiku, seconds, episode, api)
    }

    func testPersonAndKaikuSpeechBothWaysAndTranscriptOnlyWithConsent() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let cloud = env["KAIKU_SPEECH_TEST_CLOUD"].flatMap(URL.init(string:)), let path = env["KAIKU_SPEECH_TEST_WAV48"] else {
            throw XCTSkip("Set KAIKU_SPEECH_TEST_CLOUD and KAIKU_SPEECH_TEST_WAV48 (48 kHz mono PCM16) for the paid speech proof")
        }
        let speech = try Data(contentsOf: URL(fileURLWithPath: path))
        XCTAssertGreaterThan(speech.count, 96_000, "at least one second of 48 kHz speech")
        let surface = CompanionSurface(rawValue: env["KAIKU_SPEECH_TEST_SURFACE"] ?? "mac") ?? .mac
        let expect = (env["KAIKU_SPEECH_TEST_EXPECT"] ?? "walk").lowercased()
        let home = "speech-proof-" + UUID().uuidString.prefix(8).lowercased()

        let kept = try await converse(cloud: cloud, speech48k: speech, surface: surface, keepWords: true, home: home)
        XCTAssertTrue(kept.person.lowercased().contains(expect), "person transcript should contain '\(expect)': \(kept.person)")
        XCTAssertFalse(kept.kaiku.isEmpty, "Kaiku's words are transcribed")
        XCTAssertGreaterThan(kept.audioSeconds, 1, "Kaiku's voice audio arrived")
        let stored = try await kept.api.transcripts()
        let saved = stored.transcripts.first { $0.episode_id == kept.episode }
        XCTAssertNotNil(saved, "opted in → the conversation is stored")
        XCTAssertTrue(saved?.turns.contains { $0.role == .person } ?? false)
        XCTAssertTrue(saved?.turns.contains { $0.role == .kaiku } ?? false)

        let notKept = try await converse(cloud: cloud, speech48k: speech, surface: surface, keepWords: false, home: home)
        XCTAssertFalse(notKept.person.isEmpty); XCTAssertFalse(notKept.kaiku.isEmpty)
        let after = try await notKept.api.transcripts()
        XCTAssertNil(after.transcripts.first { $0.episode_id == notKept.episode }, "not opted in → no words stored")
        XCTAssertEqual(after.transcripts.count, stored.transcripts.count)
        print("REAL_SPEECH_PROOF surface=\(surface.rawValue) person_chars=\(kept.person.count) kaiku_chars=\(kept.kaiku.count) kaiku_audio_s=\(String(format: "%.1f", kept.audioSeconds)) stored_turns=\(saved?.turns.count ?? 0) unconsented_stored=0")
    }
}

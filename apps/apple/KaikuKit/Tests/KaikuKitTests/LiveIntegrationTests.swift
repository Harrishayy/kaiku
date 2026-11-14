import Foundation
import XCTest
@testable import KaikuKit

/// Opt-in, paid: a real Gemini Live conversation with the app's own LiveSession, through the local cloud
/// (bootstrap + ephemeral token + tool calls). Run via `apps/apple/scripts/live_e2e.sh`, which starts the cloud
/// with `.env`, makes the speech clips with `say`, and sets:
///   KAIKU_LIVE_TEST_CLOUD   e.g. http://127.0.0.1:18040
///   KAIKU_LIVE_TEST_SPEECH  16 kHz mono PCM16 clip of the person interrupting + asking a memory question
///   KAIKU_LIVE_TEST_OUT     evidence folder (events.jsonl, kaiku.wav)
/// Skipped without them, so `swift test` stays free and offline.
final class LiveIntegrationTests: XCTestCase {
    final class Log: @unchecked Sendable {
        private let lock = NSLock()
        private(set) var events: [(t: Double, ev: LiveSession.Event)] = []
        private var audio = Data()
        let t0 = Date()
        func add(_ e: LiveSession.Event) {
            lock.lock(); defer { lock.unlock() }
            events.append((Date().timeIntervalSince(t0), e))
            if case .audio(let d) = e { audio.append(d) }
        }
        func snapshot() -> [(t: Double, ev: LiveSession.Event)] { lock.lock(); defer { lock.unlock() }; return events }
        func pcm() -> Data { lock.lock(); defer { lock.unlock() }; return audio }
    }

    private func wait(_ log: Log, timeout: Double, _ cond: ([(t: Double, ev: LiveSession.Event)]) -> Bool) async -> Bool {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            if cond(log.snapshot()) { return true }
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        return false
    }

    private func post<T: Decodable>(_ cloud: URL, _ path: String, _ body: [String: Any], as: T.Type) async throws -> T {
        var r = URLRequest(url: cloud.appendingPathComponent(path))
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "content-type")
        r.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (d, _) = try await URLSession.shared.data(for: r)
        return try JSONDecoder().decode(T.self, from: d)
    }

    func testRealConversationWithBargeInAndMindTool() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let c = env["KAIKU_LIVE_TEST_CLOUD"], let cloud = URL(string: c), let speechPath = env["KAIKU_LIVE_TEST_SPEECH"],
              let outPath = env["KAIKU_LIVE_TEST_OUT"] else { throw XCTSkip("set KAIKU_LIVE_TEST_* (scripts/live_e2e.sh)") }
        let surface = env["KAIKU_LIVE_TEST_SURFACE"] ?? "iphone"
        let speech = try Data(contentsOf: URL(fileURLWithPath: speechPath))
        let out = URL(fileURLWithPath: outPath)
        try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

        let session = try await post(cloud, "v1/companion/session",
                                     ["surface": surface, "home_id": "demo-aino", "intent": surface == "glasses" ? "walk" : "talk", "language": "en"],
                                     as: CompanionSessionResponse.self)
        let token = try XCTUnwrap(session.live_token?.token, "cloud minted no live token (GEMINI_API_KEY?)")

        let log = Log()
        var toolsAnswered: [String] = []
        var live: LiveSession!
        live = LiveSession { ev in log.add(ev) }
        live.connect(token: token, session: session, options: .init(handsFree: true, tuning: .headset))
        defer { live.close() }

        let ready = await wait(log, timeout: 15) { $0.contains { $0.ev == .ready } }
        XCTAssertTrue(ready, "setup frame not accepted (socket closed before setupComplete)")
        guard ready else { return dump(log, out, toolsAnswered, live.closeReason) }

        // 1) Kaiku talks first (a long answer, so there is something to interrupt).
        live.sendText("Please tell me a calm, slow story about a forest. Use at least eight sentences.")
        let speaking = await wait(log, timeout: 20) { $0.contains { if case .audio = $0.ev { return true }; return false } }
        XCTAssertTrue(speaking, "Kaiku never spoke")

        // 2) The person cuts in, in real time (100 ms chunks), then silence so VAD ends the turn.
        try? await Task.sleep(nanoseconds: 600_000_000)
        let chunk = 3200   // 100 ms of 16 kHz PCM16
        var i = 0
        while i < speech.count {
            live.sendAudio(speech.subdata(in: i..<min(i + chunk, speech.count)))
            i += chunk
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        for _ in 0..<20 { live.sendAudio(Data(count: chunk)); try? await Task.sleep(nanoseconds: 100_000_000) }

        // 3) Tool calls → the cloud mind (knowledge graph) → back into Live.
        let deadline = Date().addingTimeInterval(30)
        var handled = Set<String>()
        while Date() < deadline {
            for (_, ev) in log.snapshot() {
                guard case .toolCall(let id, let name, let args) = ev, !handled.contains(id) else { continue }
                handled.insert(id)
                let call: [String: Any] = ["home_id": "demo-aino", "surface": surface, "name": name,
                                           "args": JSONValue.object(args).any, "session_id": session.session_id]
                let r = try await post(cloud, "v1/companion/tool", call, as: CompanionToolResult.self)
                live.respond(id: id, name: name, result: r.result ?? .object(["ok": .bool(r.ok)]))
                toolsAnswered.append(name)
            }
            let evs = log.snapshot()
            if let lastTool = evs.lastIndex(where: { if case .toolCall = $0.ev { return true }; return false }),
               evs[lastTool...].contains(where: { $0.ev == .turnComplete }) { break }
            try? await Task.sleep(nanoseconds: 200_000_000)
        }
        try? await Task.sleep(nanoseconds: 4_000_000_000)

        let evs = log.snapshot()
        // The (simulated) person's conversation goes in as an opt-in transcript, like the app sends it.
        var turns: [[String: String]] = []
        for (_, ev) in evs {
            let (role, text): (String, String)
            switch ev { case .userText(let t): (role, text) = ("person", t); case .kaikuText(let t): (role, text) = ("kaiku", t); default: continue }
            if let last = turns.last, last["role"] == role { turns[turns.count - 1]["text"]! += text } else { turns.append(["role": role, "text": text]) }
        }
        let f = ISO8601DateFormatter()
        let stored = try await post(cloud, "v1/companion/episode",
                                    ["id": session.session_id, "home_id": "demo-aino", "surface": surface,
                                     "intent": surface == "glasses" ? "walk" : "talk", "start": f.string(from: log.t0),
                                     "end": f.string(from: Date()), "outcome": "completed", "tools_used": toolsAnswered,
                                     "transcript": turns], as: EpisodeResult.self)
        XCTAssertEqual(stored.transcript_stored, true, "opt-in transcript not stored")
        try? JSONSerialization.data(withJSONObject: turns, options: [.prettyPrinted]).write(to: out.appendingPathComponent("transcript.json"))
        XCTAssertTrue(evs.contains { $0.ev == .interrupted }, "no barge-in: the server never sent interrupted")
        XCTAssertTrue(evs.contains { if case .userText = $0.ev { return true }; return false }, "no input transcription")
        XCTAssertFalse(toolsAnswered.isEmpty, "the model never asked the mind (ask_mind / recall)")
        dump(log, out, toolsAnswered, live.closeReason)
    }

    /// Evidence: one JSON line per event (audio as byte counts) + Kaiku's whole voice as a WAV.
    private func dump(_ log: Log, _ out: URL, _ tools: [String], _ closeReason: String?) {
        var lines: [String] = []
        for (t, ev) in log.snapshot() {
            var o: [String: Any] = ["t": (t * 1000).rounded() / 1000]
            switch ev {
            case .ready: o["ev"] = "ready"
            case .userText(let s): o["ev"] = "user_text"; o["text"] = s
            case .kaikuText(let s): o["ev"] = "kaiku_text"; o["text"] = s
            case .modelOutput: o["ev"] = "model_output"
            case .audio(let d): o["ev"] = "audio"; o["bytes"] = d.count
            case .interrupted: o["ev"] = "interrupted"
            case .turnComplete: o["ev"] = "turn_complete"
            case .userTranscriptComplete: o["ev"] = "user_transcript_complete"
            case .kaikuTranscriptComplete: o["ev"] = "kaiku_transcript_complete"
            case .toolCall(_, let n, let a): o["ev"] = "tool_call"; o["name"] = n; o["args"] = JSONValue.object(a).any
            case .toolCancelled(let ids): o["ev"] = "tool_cancelled"; o["n"] = ids.count
            case .resumable: o["ev"] = "resumption_handle"
            case .goAway: o["ev"] = "go_away"
            case .closed: o["ev"] = "closed"; o["reason"] = closeReason ?? ""
            }
            if let d = try? JSONSerialization.data(withJSONObject: o), let s = String(data: d, encoding: .utf8) { lines.append(s) }
        }
        try? (lines.joined(separator: "\n") + "\n").write(to: out.appendingPathComponent("events.jsonl"), atomically: true, encoding: .utf8)
        try? Self.wav(log.pcm(), rate: 24_000).write(to: out.appendingPathComponent("kaiku.wav"))
        try? tools.joined(separator: "\n").write(to: out.appendingPathComponent("tools.txt"), atomically: true, encoding: .utf8)
    }

    static func wav(_ pcm: Data, rate: UInt32) -> Data {
        var d = Data()
        func u32(_ v: UInt32) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 4)) }
        func u16(_ v: UInt16) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 2)) }
        d.append("RIFF".data(using: .ascii)!); u32(36 + UInt32(pcm.count)); d.append("WAVEfmt ".data(using: .ascii)!)
        u32(16); u16(1); u16(1); u32(rate); u32(rate * 2); u16(2); u16(16)
        d.append("data".data(using: .ascii)!); u32(UInt32(pcm.count)); d.append(pcm)
        return d
    }
}

@preconcurrency import AVFoundation
import Foundation

/// Gemini Live over a raw WebSocket, authenticated only with the cloud-minted ephemeral token (the app never holds
/// a Gemini key — root rule 5). Protocol per the Gemini docs (geminiDocs MCP, "Get started with Live API using
/// WebSockets" + Live API reference, checked 2026-11-14):
///   wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token=<token>
///   first frame {"setup": {model, generationConfig{responseModalities, speechConfig}, systemInstruction, tools,
///   realtimeInputConfig{automaticActivityDetection{disabled:true}}, inputAudioTranscription, outputAudioTranscription}}
///   hold-to-talk: realtimeInput.activityStart → realtimeInput.audio {data b64, mimeType audio/pcm;rate=16000} → activityEnd
///   server: setupComplete · serverContent{modelTurn.parts[].inlineData (24 kHz PCM), input/outputTranscription,
///   turnComplete, interrupted} · toolCall{functionCalls[{id,name,args}]} → client toolResponse{functionResponses}
/// Not exercised against the real API here (no key in dev); the cloud returns live_token = null without one.
public final class LiveSession: NSObject, @unchecked Sendable, URLSessionWebSocketDelegate {
    public enum Event: Sendable {
        case ready
        case userText(String)
        case kaikuText(String)
        case speaking(Bool)
        case toolCall(id: String, name: String, args: [String: JSONValue])
        case closed
    }

    static let endpoint = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained"

    private var task: URLSessionWebSocketTask?
    private var urlSession: URLSession?
    private let onEvent: @Sendable (Event) -> Void
    private let player = AVAudioPlayerNode()
    private let engine = AVAudioEngine()
    private let playFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000, channels: 1, interleaved: false)!
    private var engineReady = false

    public init(onEvent: @escaping @Sendable (Event) -> Void) {
        self.onEvent = onEvent
    }

    public func connect(token: String, session: CompanionSessionResponse, language: String) {
        var c = URLComponents(string: Self.endpoint)!
        c.queryItems = [URLQueryItem(name: "access_token", value: token)]
        let s = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
        urlSession = s
        let t = s.webSocketTask(with: c.url!)
        task = t
        t.resume()
        let model = session.model.hasPrefix("models/") ? session.model : "models/\(session.model)"
        let decls: [[String: Any]] = session.tools.map { ["name": $0.name, "description": $0.description, "parameters": $0.parameters.any] }
        let setup: [String: Any] = ["setup": [
            "model": model,
            "generationConfig": [
                "responseModalities": ["AUDIO"],
                "speechConfig": ["voiceConfig": ["prebuiltVoiceConfig": ["voiceName": session.voice]]],
            ],
            "systemInstruction": ["parts": [["text": session.system_instruction]]],
            "tools": [["functionDeclarations": decls]],
            "realtimeInputConfig": ["automaticActivityDetection": ["disabled": true]],
            "inputAudioTranscription": [String: Any](),
            "outputAudioTranscription": [String: Any](),
        ]]
        send(setup)
        receive()
    }

    public func close() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        player.stop()
        if engine.isRunning { engine.stop() }
    }

    public func activityStart() { send(["realtimeInput": ["activityStart": [String: Any]()]]) }
    public func activityEnd() { send(["realtimeInput": ["activityEnd": [String: Any]()]]) }

    public func sendAudio(_ pcm16k: Data) {
        send(["realtimeInput": ["audio": ["data": pcm16k.base64EncodedString(), "mimeType": "audio/pcm;rate=16000"]]])
    }

    public func sendText(_ text: String) { send(["realtimeInput": ["text": text]]) }

    public func respond(id: String, name: String, result: JSONValue) {
        send(["toolResponse": ["functionResponses": [["id": id, "name": name, "response": ["result": result.any]]]]])
    }

    private func send(_ obj: [String: Any]) {
        guard let task, let data = try? JSONSerialization.data(withJSONObject: obj),
              let s = String(data: data, encoding: .utf8) else { return }
        task.send(.string(s)) { err in if err != nil { kaikuLog.notice("live_send_failed") } }
    }

    private func receive() {
        task?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure:
                self.onEvent(.closed)
            case .success(let msg):
                var data: Data?
                switch msg {
                case .string(let s): data = s.data(using: .utf8)
                case .data(let d): data = d
                @unknown default: break
                }
                if let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] { self.handle(obj) }
                self.receive()
            }
        }
    }

    private func handle(_ m: [String: Any]) {
        if m["setupComplete"] != nil { onEvent(.ready) }
        if let sc = m["serverContent"] as? [String: Any] {
            if let it = (sc["inputTranscription"] as? [String: Any])?["text"] as? String, !it.isEmpty { onEvent(.userText(it)) }
            if let ot = (sc["outputTranscription"] as? [String: Any])?["text"] as? String, !ot.isEmpty { onEvent(.kaikuText(ot)) }
            if let parts = (sc["modelTurn"] as? [String: Any])?["parts"] as? [[String: Any]] {
                for p in parts {
                    if let inline = p["inlineData"] as? [String: Any], let b64 = inline["data"] as? String, let d = Data(base64Encoded: b64) {
                        play(d)
                    }
                }
            }
            if sc["interrupted"] as? Bool == true { player.stop(); onEvent(.speaking(false)) }
            if sc["turnComplete"] as? Bool == true { onEvent(.speaking(false)) }
        }
        if let tc = m["toolCall"] as? [String: Any], let calls = tc["functionCalls"] as? [[String: Any]] {
            for c in calls {
                let args = (JSONValue(any: c["args"]))
                var dict: [String: JSONValue] = [:]
                if case .object(let o) = args { dict = o }
                onEvent(.toolCall(id: c["id"] as? String ?? "", name: c["name"] as? String ?? "", args: dict))
            }
        }
    }

    /// 24 kHz little-endian PCM16 → Float32 buffer → player.
    private func play(_ pcm: Data) {
        if !engineReady {
            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: playFormat)
            try? engine.start()
            engineReady = true
        }
        let count = pcm.count / 2
        guard count > 0, let buf = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: AVAudioFrameCount(count)) else { return }
        buf.frameLength = AVAudioFrameCount(count)
        pcm.withUnsafeBytes { raw in
            let src = raw.bindMemory(to: Int16.self)
            let dst = buf.floatChannelData![0]
            for i in 0..<count { dst[i] = Float(Int16(littleEndian: src[i])) / 32768 }
        }
        onEvent(.speaking(true))
        player.scheduleBuffer(buf, completionHandler: nil)
        if !player.isPlaying { player.play() }
    }

    public func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        onEvent(.closed)
    }
}

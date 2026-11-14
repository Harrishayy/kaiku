import Foundation

/// Gemini Live over a raw WebSocket, authenticated only with the cloud-minted ephemeral token (the app never holds
/// a Gemini key — root rule 5). This type is the protocol only: it builds the setup frame, sends input, and turns
/// server frames into `Event`s. Audio I/O lives in `ConversationAudio`; the conversation logic in `Conversation`.
///
/// Field names checked in the Gemini docs (geminiDocs MCP, 2026-11-14: Live API reference "BidiGenerateContentSetup",
/// "RealtimeInputConfig", "AutomaticActivityDetection"; capabilities guide "VAD / interruptions", "Affective dialog",
/// "Proactive audio" — affective dialog rejected in practice, see setup; session-management guide "Session resumption", "Context window compression"; tools guide
/// "Asynchronous function calling"; ephemeral-tokens guide; and the installed google-genai `_live_converters.py`,
/// which puts `enable_affective_dialog` at `setup.generationConfig.enableAffectiveDialog`):
///   wss://…/v1beta.GenerativeService.BidiGenerateContentConstrained?access_token=<token>
///   hands-free: server VAD on, `activityHandling: START_OF_ACTIVITY_INTERRUPTS` (barge-in: the person talks over
///   Kaiku → the server cancels the turn and sends `serverContent.interrupted`; the client must flush playback);
///   push-to-talk: VAD off + `activityStart` / `activityEnd`.
///   `sessionResumption` → `sessionResumptionUpdate{newHandle, resumable}`; reconnect with `{handle}` after `goAway`
///   or a drop — the same ephemeral token works for that even with `uses: 1` (valid until its expireTime).
///   `contextWindowCompression.slidingWindow` → audio sessions longer than 15 min (a walk).
///   `behavior: NON_BLOCKING` tools (ask_mind) keep the conversation going; reply with `scheduling: WHEN_IDLE`.
public final class LiveSession: NSObject, @unchecked Sendable, URLSessionWebSocketDelegate {
    public enum Event: Sendable, Equatable {
        case ready
        case userText(String)
        case kaikuText(String)
        case userTranscriptComplete
        case kaikuTranscriptComplete
        /// A frame has model media; after turnComplete this starts a new model generation.
        case modelOutput
        /// 24 kHz little-endian PCM16 from the model.
        case audio(Data)
        /// The person started talking over Kaiku: the server dropped the rest of the turn. Flush playback now.
        case interrupted
        case turnComplete
        case toolCall(id: String, name: String, args: [String: JSONValue])
        /// The server dropped pending tool calls (after an interruption); their responses must not be sent.
        case toolCancelled([String])
        /// Several function calls arrived in one frame (comes before their `toolCall` events): their results go
        /// back together, in one frame.
        case toolFrame(ids: [String])
        case resumable(handle: String)
        /// The server will close this connection soon: reconnect with the last handle.
        case goAway
        case closed
    }

    /// Voice-activity tuning (server VAD). Start sensitivity per route: the glasses' HFP mics are beamformed to the
    /// wearer's voice, so HIGH there; on a loudspeaker LOW, so Kaiku's own echo leftovers don't count as an
    /// interruption. End: LOW + 800 ms silence, so a slow speaker with long pauses isn't cut off mid-thought.
    public struct Tuning: Sendable, Equatable {
        public var startOfSpeech: String
        public var endOfSpeech: String
        public var prefixPaddingMs: Int
        public var silenceDurationMs: Int

        public static let headset = Tuning(startOfSpeech: "START_SENSITIVITY_HIGH", endOfSpeech: "END_SENSITIVITY_LOW",
                                           prefixPaddingMs: 100, silenceDurationMs: 800)
        public static let loudspeaker = Tuning(startOfSpeech: "START_SENSITIVITY_LOW", endOfSpeech: "END_SENSITIVITY_LOW",
                                               prefixPaddingMs: 200, silenceDurationMs: 800)
    }

    public struct Options: Sendable, Equatable {
        public var handsFree: Bool = true
        public var tuning: Tuning = .loudspeaker
        public var resumeHandle: String?
        /// Tools the model may run in the background while it keeps talking.
        public var nonBlocking: Set<String> = ["ask_mind"]
        public init(handsFree: Bool = true, tuning: Tuning = .loudspeaker, resumeHandle: String? = nil) {
            self.handsFree = handsFree
            self.tuning = tuning
            self.resumeHandle = resumeHandle
        }
    }

    static let endpoint = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained"

    private var task: URLSessionWebSocketTask?
    private var urlSession: URLSession?
    private let onEvent: @Sendable (Event) -> Void
    private let lock = NSLock()
    private var cancelled: Set<String> = []
    /// Tools declared NON_BLOCKING in this session (the cloud's `behavior`, plus ask_mind).
    private var nonBlocking: Set<String> = Options().nonBlocking
    private var closedReported = false
    /// Why the server closed the socket (close code + reason text from Gemini), for logs and tests.
    public private(set) var closeReason: String?

    public init(onEvent: @escaping @Sendable (Event) -> Void) {
        self.onEvent = onEvent
    }

    public func connect(token: String, session: CompanionSessionResponse, options: Options) {
        lock.lock()
        nonBlocking = options.nonBlocking.union(session.tools.filter { $0.behavior == "NON_BLOCKING" }.map(\.name))
        lock.unlock()
        var c = URLComponents(string: Self.endpoint)!
        c.queryItems = [URLQueryItem(name: "access_token", value: token)]
        let s = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
        urlSession = s
        let t = s.webSocketTask(with: c.url!)
        t.maximumMessageSize = 16 * 1024 * 1024
        task = t
        t.resume()
        send(Self.setup(session: session, options: options))
        receive()
        keepAlive(t)
    }

    /// A WebSocket ping every 20 s: a silently dead network (Wi-Fi → cellular, tunnel, sleep) otherwise looks like
    /// Kaiku simply not answering until TCP gives up minutes later. A failed ping reports `closed` → reconnect.
    private func keepAlive(_ t: URLSessionWebSocketTask) {
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 20) { [weak self, weak t] in
            guard let self, let t, self.task === t else { return }
            t.sendPing { [weak self] error in
                guard let self, self.task === t else { return }
                if error != nil {
                    if self.closeReason == nil { self.closeReason = "ping failed" }
                    self.reportClosed()
                } else { self.keepAlive(t) }
            }
        }
    }

    public func close() {
        lock.lock(); closedReported = true; lock.unlock()
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        urlSession?.invalidateAndCancel()
        urlSession = nil
    }

    // MARK: input

    public func activityStart() { send(["realtimeInput": ["activityStart": [String: Any]()]]) }
    public func activityEnd() { send(["realtimeInput": ["activityEnd": [String: Any]()]]) }
    /// Mic muted / paused: tells server VAD the stream stopped (no half-finished turn left hanging).
    public func audioStreamEnd() { send(["realtimeInput": ["audioStreamEnd": true]]) }

    public func sendAudio(_ pcm16k: Data) {
        send(["realtimeInput": ["audio": ["data": pcm16k.base64EncodedString(), "mimeType": "audio/pcm;rate=16000"]]])
    }

    /// One still picture of what the glasses camera sees (Gemini Live docs, "Sending video": individual JPEG
    /// frames in `realtimeInput.video`, at most one a second). Frames alone never start a model turn.
    public func sendVideo(_ jpeg: Data) { send(Self.video(jpeg)) }

    static func video(_ jpeg: Data) -> [String: Any] {
        ["realtimeInput": ["video": ["data": jpeg.base64EncodedString(), "mimeType": "image/jpeg"]]]
    }

    public func sendText(_ text: String) { send(["realtimeInput": ["text": text]]) }

    /// A context event from Kaiku's senses (`[walk · 10 min]`), appended as a turn the model may react to — or,
    /// with proactive audio, stay quiet about. Same wording as the hub's `send_context`.
    public func sendContext(_ text: String) { send(Self.context(text)) }

    public func respond(id: String, name: String, result: JSONValue) {
        respond([ToolAnswer(id: id, name: name, result: result)])
    }

    /// All the results of one `toolCall` frame in one `toolResponse` frame (a call cancelled meanwhile is left
    /// out). Seen on the real model: answered one frame per call, it issued the same call again in a later frame.
    func respond(_ answers: [ToolAnswer]) {
        lock.lock()
        let responses = answers.filter { cancelled.remove($0.id) == nil }.map {
            Self.functionResponse(id: $0.id, name: $0.name, result: $0.result, background: nonBlocking.contains($0.name))
        }
        lock.unlock()
        if !responses.isEmpty { send(["toolResponse": ["functionResponses": responses]]) }
    }

    // MARK: pure frames (tested)

    static func setup(session: CompanionSessionResponse, options: Options) -> [String: Any] {
        let model = session.model.hasPrefix("models/") ? session.model : "models/\(session.model)"
        let decls: [[String: Any]] = session.tools.map { t in
            var d: [String: Any] = ["name": t.name, "description": t.description, "parameters": t.parameters.any]
            if options.nonBlocking.contains(t.name) || t.behavior == "NON_BLOCKING" { d["behavior"] = "NON_BLOCKING" }
            return d
        }
        let realtime: [String: Any]
        if options.handsFree {
            let t = options.tuning
            // On the loudspeaker the cloud's tuning (config/kaiku.toml [live], sent as `live_setup`) wins, so turn
            // detection is tuned in one place; a headset (glasses, AirPods) keeps its more eager start.
            let cloudVAD = session.live_setup?["realtimeInputConfig"]?["automaticActivityDetection"]?.any
            realtime = [
                "automaticActivityDetection": (t == .loudspeaker ? cloudVAD : nil) ?? [
                    "disabled": false,
                    "startOfSpeechSensitivity": t.startOfSpeech,
                    "endOfSpeechSensitivity": t.endOfSpeech,
                    "prefixPaddingMs": t.prefixPaddingMs,
                    "silenceDurationMs": t.silenceDurationMs,
                ],
                "activityHandling": "START_OF_ACTIVITY_INTERRUPTS",
            ]
        } else {
            realtime = ["automaticActivityDetection": ["disabled": true]]
        }
        // Resumption and context compression are what let a call outlive one socket (about ten minutes) and one
        // context window (an audio session ends at about fifteen minutes without compression): always sent, the
        // cloud's settings (`live_setup`) when it gives them, plus this conversation's handle.
        var resumption = session.live_setup?["sessionResumption"]?.any as? [String: Any] ?? [:]
        if let h = options.resumeHandle { resumption["handle"] = h }
        let compression = session.live_setup?["contextWindowCompression"]?.any as? [String: Any] ?? ["slidingWindow": [String: Any]()]
        return ["setup": [
            "model": model,
            "generationConfig": [
                "responseModalities": ["AUDIO"],
                "speechConfig": ["voiceConfig": ["prebuiltVoiceConfig": ["voiceName": session.voice]]],
                // No `enableAffectiveDialog`: tried live 2026-11-14, gemini-3.8-live closes the socket with
                // 1007 "invalid argument" on the first turn when it is true (SDK + raw key, and token endpoint).
            ] as [String: Any],
            "systemInstruction": ["parts": [["text": session.system_instruction]]],
            "tools": [["functionDeclarations": decls]],
            "realtimeInputConfig": realtime,
            "sessionResumption": resumption,
            "contextWindowCompression": compression,
            // the cloud's choice when it sends one (`live_setup.proactivity`), otherwise proactive audio on
            "proactivity": session.live_setup?["proactivity"]?.any ?? ["proactiveAudio": true],
            "inputAudioTranscription": [String: Any](),
            "outputAudioTranscription": [String: Any](),
        ] as [String: Any]]
    }

    static func context(_ text: String) -> [String: Any] {
        ["clientContent": [
            "turns": [["role": "user", "parts": [["text":
                "(context from Kaiku's senses, not said by the person; react briefly only if it feels natural) \(text)"]]]],
            "turnComplete": true,
        ] as [String: Any]]
    }

    static func toolResponse(id: String, name: String, result: JSONValue, background: Bool) -> [String: Any] {
        ["toolResponse": ["functionResponses": [functionResponse(id: id, name: name, result: result, background: background)]]]
    }

    static func functionResponse(id: String, name: String, result: JSONValue, background: Bool) -> [String: Any] {
        // A non-blocking tool's result may say how to deliver it (`scheduling`: feel → SILENT, so Kaiku is not
        // made to speak again); that field is for this frame, not for the model.
        var body = result
        var scheduling = "WHEN_IDLE"
        if background, case .object(var o) = result, let s = o["scheduling"]?.string,
           ["INTERRUPT", "WHEN_IDLE", "SILENT"].contains(s) {
            scheduling = s
            o["scheduling"] = nil
            body = .object(o)
        }
        var response: [String: Any] = ["result": body.any]
        if background { response["scheduling"] = scheduling }
        return ["id": id, "name": name, "response": response]
    }

    /// One server frame → events, in the order a client must act on them (interrupted before more audio).
    static func parse(_ m: [String: Any]) -> [Event] {
        var out: [Event] = []
        if m["setupComplete"] != nil { out.append(.ready) }
        if let sc = m["serverContent"] as? [String: Any] {
            if sc["interrupted"] as? Bool == true { out.append(.interrupted) }
            if let it = (sc["inputTranscription"] as? [String: Any])?["text"] as? String, !it.isEmpty { out.append(.userText(it)) }
            if let parts = (sc["modelTurn"] as? [String: Any])?["parts"] as? [[String: Any]], !parts.isEmpty {
                out.append(.modelOutput)
            }
            if let ot = (sc["outputTranscription"] as? [String: Any])?["text"] as? String, !ot.isEmpty { out.append(.kaikuText(ot)) }
            if (sc["inputTranscription"] as? [String: Any])?["finished"] as? Bool == true { out.append(.userTranscriptComplete) }
            if (sc["outputTranscription"] as? [String: Any])?["finished"] as? Bool == true { out.append(.kaikuTranscriptComplete) }
            if let parts = (sc["modelTurn"] as? [String: Any])?["parts"] as? [[String: Any]] {
                for p in parts {
                    if let inline = p["inlineData"] as? [String: Any], let b64 = inline["data"] as? String,
                       let d = Data(base64Encoded: b64) { out.append(.audio(d)) }
                }
            }
            if sc["turnComplete"] as? Bool == true { out.append(.turnComplete) }
        }
        if let tc = m["toolCall"] as? [String: Any], let calls = tc["functionCalls"] as? [[String: Any]] {
            if calls.count > 1 { out.append(.toolFrame(ids: calls.map { $0["id"] as? String ?? "" })) }
            for c in calls {
                var dict: [String: JSONValue] = [:]
                if case .object(let o) = JSONValue(any: c["args"]) { dict = o }
                out.append(.toolCall(id: c["id"] as? String ?? "", name: c["name"] as? String ?? "", args: dict))
            }
        }
        if let ids = (m["toolCallCancellation"] as? [String: Any])?["ids"] as? [String], !ids.isEmpty {
            out.append(.toolCancelled(ids))
        }
        if let u = m["sessionResumptionUpdate"] as? [String: Any], u["resumable"] as? Bool == true,
           let h = u["newHandle"] as? String, !h.isEmpty { out.append(.resumable(handle: h)) }
        if m["goAway"] != nil { out.append(.goAway) }
        return out
    }

    // MARK: transport

    private func send(_ obj: [String: Any]) {
        guard let task, let data = try? JSONSerialization.data(withJSONObject: obj),
              let s = String(data: data, encoding: .utf8) else { return }
        task.send(.string(s)) { err in if err != nil { kaikuLog.notice("live_send_failed") } }
    }

    private func receive() {
        task?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let e):
                if self.closeReason == nil { self.closeReason = "receive failed: \(e.localizedDescription)" }
                self.reportClosed()
            case .success(let msg):
                var data: Data?
                switch msg {
                case .string(let s): data = s.data(using: .utf8)
                case .data(let d): data = d
                @unknown default: break
                }
                if let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    for ev in Self.parse(obj) {
                        if case .toolCancelled(let ids) = ev { self.lock.lock(); self.cancelled.formUnion(ids); self.lock.unlock() }
                        self.onEvent(ev)
                    }
                }
                self.receive()
            }
        }
    }

    private func reportClosed() {
        lock.lock()
        let first = !closedReported
        closedReported = true
        lock.unlock()
        if first { onEvent(.closed) }
    }

    public func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                           didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        let text = reason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
        closeReason = "\(closeCode.rawValue) \(text)"
        kaikuLog.notice("live_closed \(closeCode.rawValue) \(text, privacy: .public)")
        GlassesLog.shared.log("live_socket_closed", ["code": closeCode.rawValue, "reason": text])
        reportClosed()
    }
}

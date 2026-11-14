import Foundation
import Observation

/// One spoken conversation with Kaiku, the same on every Apple surface (Talk on iPhone/Mac, the walk through Meta
/// glasses). The pipeline:
///
///   mic (glasses HFP / phone / Mac) → ConversationAudio (voice processing, 16 kHz) → Gemini Live (server VAD)
///   ← Kaiku's voice (24 kHz) ← Live; the person can talk over Kaiku at any time: Live sends `interrupted`, the
///   queued voice is flushed at once and Live listens.
///   Bootstrap: POST /v1/companion/session {surface, intent} → the mind's persona + surface rules + context card
///   (≤ 3 memories from the graph, open thread, today's suggestion, tone) + tools + an ephemeral token.
///   Tools: device tools run here (`deviceTool`); cloud tools (recall, remember, ask_mind → memory / knowledge
///   graph / Flash / Argon) go to POST /v1/companion/tool and the answer goes back into the live conversation.
///   `ask_mind` is non-blocking: Kaiku keeps talking ("let me think…") and weaves the answer in when idle.
///   Safety: every input transcript + the on-device listener run the local safety gate first; a hit ends the
///   conversation and hands over to the crisis screen (`onCrisis`), nothing goes to the model.
///   Long sessions: session resumption handle + context compression; on `goAway` / a drop, reconnect with the
///   handle (same token while valid, else a fresh token from the cloud). No audio, transcript or text is stored.
@Observable @MainActor
public final class Conversation {
    public enum Phase: Equatable, Sendable {
        case idle, connecting
        case listening      // mic open, nobody talking
        case hearing        // the person is talking (input transcription arriving)
        case thinking       // a tool call (e.g. ask_mind) in flight
        case speaking       // Kaiku's voice is playing
        case muted, paused
        case unavailable    // no Live (offline, no key, no mic): callers fall back to scripted lines
    }

    public struct Line: Identifiable, Equatable, Sendable {
        public let id = UUID()
        public var text: String
        public let me: Bool
    }

    public let surface: CompanionSurface
    public let intent: CompanionIntent
    public private(set) var phase: Phase = .idle
    public private(set) var lines: [Line] = []
    public private(set) var session: CompanionSessionResponse?
    public private(set) var level: Float = -90
    public private(set) var lastSpokenDial: Int?
    public private(set) var toolsUsed: [String] = []

    /// Device tools (express, record_dial, start_activity, log_walk_moment, look_at_this…). Return the tool result.
    @ObservationIgnored public var deviceTool: (@MainActor (String, [String: JSONValue]) async -> JSONValue)?
    @ObservationIgnored public var onCrisis: (@MainActor () -> Void)?
    /// Called once when Live is ready (first connect only), e.g. to send a `[walk started]` context event.
    @ObservationIgnored public var onReady: (@MainActor () -> Void)?

    @ObservationIgnored private weak var app: AppModel?
    @ObservationIgnored private var live: LiveSession?
    @ObservationIgnored private let audio = ConversationAudio()
    @ObservationIgnored private let listener = OnDeviceListener()
    @ObservationIgnored private var listenerTask: Task<Void, Never>?
    @ObservationIgnored private var handle: String?
    @ObservationIgnored private var started = Date()
    @ObservationIgnored private var stopped = false
    @ObservationIgnored private var everReady = false
    @ObservationIgnored private var failures = 0
    @ObservationIgnored private var reconnecting = false
    @ObservationIgnored private var muted = false
    @ObservationIgnored private var pendingTools = 0

    public init(surface: CompanionSurface, intent: CompanionIntent) {
        self.surface = surface
        self.intent = intent
    }

    public var isLive: Bool { live != nil && phase != .unavailable }

    // MARK: lifecycle

    /// Opens the conversation. Returns false when Live isn't possible (not paired, offline, no token, no mic):
    /// the caller keeps its scripted path.
    @discardableResult
    public func start(app: AppModel) async -> Bool {
        self.app = app
        guard phase == .idle || phase == .unavailable else { return isLive }
        stopped = false
        started = Date()
        phase = .connecting
        guard await Self.micGranted() else { phase = .unavailable; return false }
        guard app.isPaired, let s = await bootstrap(), let token = s.live_token?.token else {
            phase = .unavailable
            return false
        }
        session = s
        if !OnDeviceListener.authorized { _ = await OnDeviceListener.requestAuthorization() }
        do { try startAudio() } catch { phase = .unavailable; return false }
        connect(token: token)
        return true
    }

    /// Ends the conversation and closes the cloud episode (tool names and times only — never a transcript).
    public func stop(outcome: EpisodeOutcome? = nil) {
        guard !stopped else { return }
        stopped = true
        live?.close()
        live = nil
        audio.stop()
        stopListener()
        phase = .idle
        guard let app, let s = session else { return }
        let out = outcome ?? (lines.contains(where: \.me) ? .completed : .skipped)
        var ep = EpisodeIn(id: s.session_id, home_id: app.pairing?.homeID ?? "", surface: surface, intent: intent,
                           start: KaikuTime.iso(started), end: KaikuTime.iso(Date()), outcome: out, tools_used: toolsUsed)
        // Opt-in only, never after a crisis (the cloud also drops any transcript with a crisis phrase).
        if app.allowed(.transcripts), out != .crisis, !lines.isEmpty {
            ep.transcript = Self.transcript(lines)
        }
        session = nil
        Task { _ = try? await app.api.companionEpisode(ep) }
    }

    // MARK: input

    public func setMuted(_ on: Bool) {
        guard isLive else { return }
        muted = on
        audio.setMic(!on)
        if on { live?.audioStreamEnd(); phase = .muted } else { phase = audio.isPlaying ? .speaking : .listening }
    }

    /// Phone call / Siri / alarm: silence both ways; `resume()` afterwards.
    public func pause() {
        guard isLive else { return }
        audio.setMic(false)
        audio.flush()
        live?.audioStreamEnd()
        phase = .paused
    }

    public func resume() {
        guard phase == .paused else { return }
        try? TalkAudio.activate()
        audio.setMic(!muted)
        phase = muted ? .muted : .listening
    }

    /// Typed text (Talk composer). The local safety gate runs first.
    public func send(text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        lines.append(Line(text: t, me: true))
        if SafetyGate.shared.check(t) != nil { crisis(); return }
        live?.sendText(t)
    }

    /// A short bracketed context event from the device's senses, from a fixed vocabulary (`[walk · 10 min]`).
    public func context(_ event: String) {
        live?.sendContext(event)
    }

    // MARK: private — connection

    private func bootstrap() async -> CompanionSessionResponse? {
        guard let app else { return nil }
        let req = CompanionSessionRequest(surface: surface, home_id: app.pairing?.homeID ?? "", intent: intent,
                                          language: app.language.rawValue)
        return try? await app.api.companionSession(req)
    }

    private func connect(token: String) {
        guard let s = session else { return }
        let l = LiveSession { [weak self] ev in Task { @MainActor in self?.handle(ev) } }
        live = l
        let tuning: LiveSession.Tuning = ConversationAudio.headsetRoute ? .headset : .loudspeaker
        l.connect(token: token, session: s, options: .init(handsFree: true, tuning: tuning, resumeHandle: handle))
    }

    /// goAway / drop: reconnect with the resumption handle. The same token keeps working until its expireTime;
    /// after that (or with no handle yet) the cloud mints a fresh one. Three failures in a row → unavailable.
    private func reconnect() {
        guard !stopped, !reconnecting else { return }
        reconnecting = true
        live?.close()
        live = nil
        audio.flush()
        failures += 1
        guard failures <= 3 else { reconnecting = false; phase = .unavailable; return }
        Task {
            defer { reconnecting = false }
            try? await Task.sleep(nanoseconds: UInt64(400_000_000 * failures))
            guard !stopped else { return }
            if let t = session?.live_token, handle != nil, !Self.expired(t.expires_at, margin: 60) {
                connect(token: t.token)
                return
            }
            guard let fresh = await bootstrap(), let token = fresh.live_token?.token else { phase = .unavailable; return }
            // keep the first session id: tools and the episode belong to the conversation the person is in
            session?.live_token = fresh.live_token
            if handle == nil { session = fresh }
            connect(token: token)
        }
    }

    /// The on-screen lines as transcript turns (pure; tested).
    nonisolated static func transcript(_ lines: [Line]) -> [TranscriptTurn] {
        lines.compactMap { l in
            let t = l.text.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : TranscriptTurn(role: l.me ? .person : .kaiku, text: String(t.prefix(2000)))
        }
    }

    nonisolated static func expired(_ iso: String, margin: TimeInterval, now: Date = Date()) -> Bool {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let d = f.date(from: iso) ?? ISO8601DateFormatter().date(from: iso)
        guard let d else { return true }
        return d.timeIntervalSince(now) < margin
    }

    private func startAudio() throws {
        audio.onPlaying = { [weak self] on in Task { @MainActor in self?.playing(on) } }
        audio.onLevel = { [weak self] db in Task { @MainActor in self?.level = db } }
        let listener = listener
        audio.onBuffer = { b in listener.append(b) }
        try audio.start()
        listener.onHit = { [weak self] hit in Task { @MainActor in self?.onDeviceHit(hit) } }
        startListener()
    }

    /// The on-device recognizer is restarted every 50 s (recognition tasks end on their own on long sessions).
    private func startListener() {
        guard let lang = app?.language else { return }
        listener.start(lang: lang)
        listenerTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 50_000_000_000)
                guard let self, !self.stopped else { return }
                self.listener.stop()
                self.listener.start(lang: lang)
            }
        }
    }

    private func stopListener() {
        listenerTask?.cancel()
        listenerTask = nil
        listener.stop()
    }

    // MARK: private — events

    private func handle(_ ev: LiveSession.Event) {
        guard !stopped else { return }
        switch ev {
        case .ready:
            failures = 0
            if phase == .connecting || phase == .unavailable { phase = .listening }
            if !everReady { everReady = true; onReady?() }
        case .audio(let pcm):
            guard phase != .paused else { return }
            audio.play(pcm)
        case .interrupted:
            audio.flush()
            if phase != .muted && phase != .paused { phase = .hearing }
        case .userText(let t):
            if SafetyGate.shared.check(t) != nil { crisis(); return }
            if SafetyGate.shared.check((lines.last(where: \.me)?.text ?? "") + t) != nil { crisis(); return }
            append(t, me: true)
            if phase == .listening { phase = .hearing }
        case .kaikuText(let t):
            append(t, me: false)
        case .turnComplete:
            if !audio.isPlaying && pendingTools == 0 && (phase == .hearing || phase == .speaking) { phase = .listening }
        case .toolCall(let id, let name, let args):
            Task { await tool(id: id, name: name, args: args) }
        case .toolCancelled:
            pendingTools = 0
        case .resumable(let h):
            handle = h
        case .goAway, .closed:
            reconnect()
        }
    }

    private func playing(_ on: Bool) {
        guard !stopped, phase != .paused, phase != .muted else { return }
        if on { phase = .speaking } else if phase == .speaking { phase = pendingTools > 0 ? .thinking : .listening }
    }

    private func append(_ t: String, me: Bool) {
        if let last = lines.last, last.me == me {
            lines[lines.count - 1].text = last.text + t
        } else {
            lines.append(Line(text: t, me: me))
        }
    }

    private func tool(id: String, name: String, args: [String: JSONValue]) async {
        toolsUsed.append(name)
        guard let app, let s = session else { return }
        if ToolExecutor.isDevice(name) {
            let result = await deviceTool?(name, args) ?? .object(["ok": .bool(false), "error": .string("not on this device")])
            live?.respond(id: id, name: name, result: result)
            return
        }
        pendingTools += 1
        if !audio.isPlaying { phase = .thinking }
        defer {
            pendingTools = max(0, pendingTools - 1)
            if phase == .thinking && pendingTools == 0 { phase = .listening }
        }
        let call = CompanionToolCall(home_id: app.pairing?.homeID ?? "", surface: surface, name: name, args: args,
                                     session_id: s.session_id)
        guard let r = try? await app.api.companionTool(call) else {
            live?.respond(id: id, name: name, result: .object(["ok": .bool(false), "error": .string("offline")]))
            return
        }
        if r.crisis == true { crisis(); return }
        live?.respond(id: id, name: name, result: r.result ?? .object(["ok": .bool(r.ok)]))
    }

    private func onDeviceHit(_ hit: OnDeviceListener.Hit) {
        switch hit {
        case .crisis: crisis()
        case .dial(let n): lastSpokenDial = n
        }
    }

    private func crisis() {
        stop(outcome: .crisis)
        onCrisis?()
    }

    static func micGranted() async -> Bool {
        switch AudioCapture.permission {
        case .granted: return true
        case .denied: return false
        case .undetermined: return await AudioCapture.request()
        }
    }
}

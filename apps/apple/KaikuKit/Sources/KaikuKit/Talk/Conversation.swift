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
///   handle (same token while valid, else a fresh token from the cloud). Raw audio is never stored; opt-in transcripts are queued durably when the conversation ends.
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

    public enum UnavailableReason: Equatable, Sendable { case microphone, pairing, connection, voice, audio, paused }
    public private(set) var unavailableReason: UnavailableReason?

    public struct Line: Identifiable, Equatable, Sendable {
        public let id = UUID()
        public var text: String
        public let me: Bool
        public var transcriptFinished = false
        public var interrupted = false
        public var completionUnknown = false
    }

    public let surface: CompanionSurface
    public let intent: CompanionIntent
    public private(set) var phase: Phase = .idle {
        didSet { if oldValue != phase { notePhase() } }
    }
    /// The conversation reached the cloud's session length limit (the caller may offer to start again).
    public private(set) var endedByLimit = false
    /// Camera frames handed to Live in this conversation (glasses walk, only with the person's choice on).
    public private(set) var framesSent = 0
    public private(set) var lastPersonAt: Date?
    public private(set) var lastKaikuAt: Date?
    public private(set) var lines: [Line] = []
    private var personTurnID: UUID?
    private var kaikuTurnID: UUID?
    private var inputFinalObserved = false
    private var outputFinalObserved = false
    private var audioTurnEnded = false
    public var hasPendingTranscription: Bool { personTurnID != nil || kaikuTurnID != nil }
    @ObservationIgnored private var eventTask: Task<Void, Never>?
    @ObservationIgnored private var eventContinuation: AsyncStream<LiveSession.Event>.Continuation?
    public private(set) var session: CompanionSessionResponse?
    public private(set) var level: Float = -90
    public private(set) var lastSpokenDial: Int?
    public private(set) var toolsUsed: [String] = []

    /// Device tools (express, record_dial, start_activity, log_walk_moment, look_at_this…). Return the tool result.
    @ObservationIgnored public var deviceTool: (@MainActor (String, [String: JSONValue]) async -> JSONValue)?
    @ObservationIgnored var onToolResult: ((String, CompanionToolResult) -> Void)?
    @ObservationIgnored public var onCrisis: (@MainActor () -> Void)?
    /// Called once when Live is ready (first connect only), e.g. to send a `[walk started]` context event.
    @ObservationIgnored public var onReady: (@MainActor () -> Void)?
    /// Called when Live is ready again after a reconnect (context the model may have lost can be sent again).
    @ObservationIgnored public var onReconnected: (@MainActor () -> Void)?

    @ObservationIgnored private weak var app: AppModel?
    @ObservationIgnored private var live: (any ConversationTransport)?
    @ObservationIgnored private let audio: any ConversationAudioIO
    @ObservationIgnored private let transport: (@escaping @Sendable (LiveSession.Event) -> Void) -> any ConversationTransport
    @ObservationIgnored private let permission: () async -> Bool
    @ObservationIgnored private let localListener: Bool
    @ObservationIgnored private var sessionPairing: Pairing?
    @ObservationIgnored private var connectionGeneration = 0
    @ObservationIgnored private let listener = OnDeviceListener()
    @ObservationIgnored private var contextTask: Task<Void, Never>?
    @ObservationIgnored private var seenEvents = Set<String>()
    @ObservationIgnored private var pendingContext: [AnyEnvelope] = []
    @ObservationIgnored private var limitTask: Task<Void, Never>?
    @ObservationIgnored private var readyTask: Task<Void, Never>?
    @ObservationIgnored private var listenerTask: Task<Void, Never>?
    @ObservationIgnored private var handle: String?
    @ObservationIgnored private var started = Date()
    @ObservationIgnored private var stopped = false
    @ObservationIgnored private var everReady = false
    @ObservationIgnored private var failures = 0
    @ObservationIgnored private var reconnecting = false
    @ObservationIgnored private var muted = false
    @ObservationIgnored private var pendingTools = 0
    @ObservationIgnored private var pauseGeneration = 0
    @ObservationIgnored private var pairingRevision = 0

    public convenience init(surface: CompanionSurface, intent: CompanionIntent) {
        self.init(surface: surface, intent: intent, audio: ConversationAudio(),
                  transport: { LiveSession(onEvent: $0) }, permission: { await Self.micGranted() })
    }

    init(surface: CompanionSurface, intent: CompanionIntent, audio: any ConversationAudioIO,
         transport: @escaping (@escaping @Sendable (LiveSession.Event) -> Void) -> any ConversationTransport,
         permission: @escaping () async -> Bool, localListener: Bool = true) {
        self.surface = surface; self.intent = intent; self.audio = audio
        self.transport = transport; self.permission = permission; self.localListener = localListener
    }

    public var isLive: Bool { live != nil && phase != .unavailable }
    /// Live setup was acknowledged at least once in this conversation.
    public private(set) var wasLive = false

    /// Tests: open the conversation on an already-made session, without the bootstrap request.
    func adoptForTest(session s: CompanionSessionResponse, app: AppModel) {
        self.app = app
        stopped = false; sessionPairing = app.pairing; pairingRevision = app.pairingRevision
        session = s; started = Date(); phase = .connecting
        try? startAudio()
        connect(token: s.live_token?.token ?? "")
    }

    // MARK: lifecycle

    /// Opens the conversation. Returns false when Live isn't possible (not paired, offline, no token, no mic):
    /// the caller keeps its scripted path.
    @discardableResult
    public func start(app: AppModel) async -> Bool {
        self.app = app
        guard phase == .idle || phase == .unavailable else { return isLive }
        stopped = false
        unavailableReason = nil
        endedByLimit = false; framesSent = 0; lastPersonAt = nil; lastKaikuAt = nil
        lines = []; personTurnID = nil; kaikuTurnID = nil
        inputFinalObserved = false; outputFinalObserved = false; audioTurnEnded = false
        toolsUsed = []; everReady = false; wasLive = false; failures = 0; muted = false; handle = nil
        sessionPairing = app.pairing
        pairingRevision = app.pairingRevision
        seenEvents = []; pendingContext = []
        started = Date()
        phase = .connecting
        guard app.isPaired else { unavailableReason = .pairing; phase = .unavailable; return false }
        guard !app.isPaused else { unavailableReason = .paused; phase = .unavailable; return false }
        pauseGeneration += 1
        observeGlobalPause(generation: pauseGeneration)
        guard await permission() else { unavailableReason = .microphone; phase = .unavailable; return false }
        guard !stopped, !app.isPaused else { return false }
        guard let s = await bootstrap() else {
            note("live_bootstrap_failed", ["reason": String(describing: unavailableReason)])
            phase = .unavailable
            return false
        }
        note("live_bootstrap_ok", ["token": s.live_token != nil, "model": s.model, "tools": s.tools.count,
                                   "limit_s": s.max_session_seconds ?? 0])
        guard !stopped, app.pairing == sessionPairing else { return false }
        session = s
        guard let token = s.live_token?.token else { stop(outcome: .offline); unavailableReason = .voice; phase = .unavailable; return false }
        if let seconds = s.max_session_seconds, seconds > 0 {
            limitTask?.cancel()
            limitTask = Task { [weak self] in
                do { try await Task.sleep(nanoseconds: UInt64(seconds) * 1_000_000_000) } catch { return }
                guard let self, !self.stopped else { return }
                self.endedByLimit = true
                self.note("live_time_limit", ["seconds": seconds])
                self.stop(outcome: .ended_early)
            }
        }
        if localListener && !OnDeviceListener.authorized { _ = await OnDeviceListener.requestAuthorization() }
        guard !stopped else { return false }
        do { try startAudio() } catch {
            note("audio_start_failed", ["error": error.localizedDescription])
            stop(outcome: .offline); unavailableReason = .audio; phase = .unavailable; return false
        }
        connect(token: token)
        return true
    }

    /// Ends the conversation and durably queues its episode, with transcript only when opted in.
    public func stop(outcome: EpisodeOutcome? = nil) {
        guard !stopped else { return }
        stopped = true
        pauseGeneration += 1
        limitTask?.cancel(); limitTask = nil
        readyTask?.cancel(); readyTask = nil
        contextTask?.cancel(); contextTask = nil; pendingContext = []
        connectionGeneration += 1
        eventContinuation?.finish(); eventContinuation = nil
        eventTask?.cancel(); eventTask = nil
        live?.close()
        live = nil
        audio.stop()
        stopListener()
        phase = .idle
        guard let app, let s = session, let pairing = sessionPairing else { return }
        let out = outcome ?? (lines.contains(where: \.me) ? .completed : .skipped)
        var ep = EpisodeIn(id: s.session_id, home_id: pairing.homeID, surface: surface, intent: intent,
                           start: KaikuTime.iso(started), end: KaikuTime.iso(Date()), outcome: out, tools_used: toolsUsed)
        // Opt-in only, never after a crisis (the cloud also drops any transcript with a crisis phrase).
        if app.allowed(.transcripts), out != .crisis, !lines.isEmpty {
            ep.transcript = Self.transcript(lines)
        }
        session = nil
        app.finishEpisode(ep, pairing: pairing)
    }

    // MARK: input

    public func setMuted(_ on: Bool) {
        guard isLive else { return }
        muted = on
        audio.setMic(!on && phase != .paused && phase != .connecting)
        guard phase != .paused && phase != .connecting else { return }
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
        audio.resumeAfterInterruption()   // the system stopped the engine for the call; it never restarts itself
        audio.setMic(!muted)
        phase = muted ? .muted : .listening
    }

    /// Typed text (Talk composer). The local safety gate runs first.
    public func send(text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, isLive, phase != .paused, app?.pairing == sessionPairing else { return }
        // Typed text is complete locally and must not steal an unfinished audio-transcription stream.
        let line = Line(text: t, me: true, transcriptFinished: true)
        lines.append(line)
        if SafetyGate.shared.check(t) != nil { crisis(); return }
        live?.sendText(t)
    }

    /// One camera frame from the glasses → Live (`realtimeInput.video`). Only while the conversation is open and
    /// listening both ways: nothing is sent when muted, paused, connecting, closed, re-paired, or without the
    /// person's "Let Kaiku see" choice. The frame is not kept here.
    @discardableResult
    public func sendFrame(_ jpeg: Data) -> Bool {
        guard !stopped, !muted, isLive, let app, !app.isPaused, app.allowed(.see), app.pairing == sessionPairing,
              [.listening, .hearing, .thinking, .speaking].contains(phase), !jpeg.isEmpty else { return false }
        live?.sendVideo(jpeg)
        framesSent += 1
        return true
    }

    private func note(_ event: String, _ fields: [String: Any] = [:]) {
        guard surface == .glasses else { return }
        GlassesLog.shared.log(event, fields)
    }

    private func notePhase() {
        guard surface == .glasses else { return }
        var f: [String: Any] = ["phase": String(describing: phase)]
        if phase == .unavailable, let r = unavailableReason { f["reason"] = String(describing: r) }
        GlassesLog.shared.log("live_phase", f)
        GlassesStatus.shared.live = String(describing: phase)
    }

    /// A short bracketed context event from the device's senses, from a fixed vocabulary (`[walk · 10 min]`).
    public func context(_ event: String) {
        guard !stopped, app?.pairing == sessionPairing else { return }
        live?.sendContext(event)
    }

    // MARK: private — connection

    private func bootstrap() async -> CompanionSessionResponse? {
        guard let app else { return nil }
        var req = CompanionSessionRequest(surface: surface, home_id: app.pairing?.homeID ?? "", intent: intent,
                                          language: app.language.rawValue)
        req.resume_session_id = session?.session_id
        do { return try await app.api.companionSession(req) }
        catch APIError.http(let status) where status == 401 || status == 403 { unavailableReason = .pairing; return nil }
        catch { unavailableReason = .connection; return nil }
    }

    private func connect(token: String) {
        guard let s = session else { return }
        connectionGeneration += 1
        let generation = connectionGeneration
        eventContinuation?.finish(); eventTask?.cancel()
        let (events, continuation) = AsyncStream<LiveSession.Event>.makeStream()
        eventContinuation = continuation
        eventTask = Task { [weak self] in
            for await event in events {
                guard !Task.isCancelled, let self, self.connectionGeneration == generation else { return }
                self.handle(event)
            }
        }
        let l = transport { event in continuation.yield(event) }
        live = l
        let tuning: LiveSession.Tuning = ConversationAudio.headsetRoute ? .headset : .loudspeaker
        l.connect(token: token, session: s, options: .init(handsFree: true, tuning: tuning, resumeHandle: handle))
        // Setup must be acknowledged: a socket that opens but never says `setupComplete` would leave Talk on
        // "connecting" for good. Treat it like a drop (bounded by the same three attempts).
        readyTask?.cancel()
        readyTask = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: UInt64(Self.readyTimeout * 1_000_000_000)) } catch { return }
            guard let self, !self.stopped, self.connectionGeneration == generation, self.phase == .connecting else { return }
            self.reconnect()
        }
    }

    static var readyTimeout: TimeInterval = 12

    /// Ends the conversation (episode queued as offline) and leaves a specific, retryable reason on screen.
    private func unavailable(_ reason: UnavailableReason) {
        stop(outcome: .offline)
        unavailableReason = reason
        phase = .unavailable
        notePhase()
    }

    /// goAway / drop: reconnect with the resumption handle. The same token keeps working until its expireTime;
    /// after that (or with no handle yet) the cloud mints a fresh one. Three failures in a row → unavailable.
    private func reconnect() {
        guard !stopped, !reconnecting else { return }
        reconnecting = true
        live?.close()
        live = nil
        audio.flush()
        audio.setMic(false)
        phase = .connecting
        failures += 1
        guard failures <= 3 else { reconnecting = false; unavailable(everReady ? .connection : .voice); return }
        Task {
            defer { reconnecting = false }
            try? await Task.sleep(nanoseconds: UInt64(400_000_000 * failures))
            guard !stopped else { return }
            if let t = session?.live_token, handle != nil, !Self.expired(t.expires_at, margin: 60) {
                connect(token: t.token)
                return
            }
            guard let fresh = await bootstrap(), let token = fresh.live_token?.token else {
                unavailable(unavailableReason ?? .connection); return
            }
            guard !stopped else { return }
            // keep the first session id: tools and the episode belong to the conversation the person is in
            session?.live_token = fresh.live_token

            connect(token: token)
        }
    }

    /// The on-screen lines as transcript turns (pure; tested).
    nonisolated static func transcript(_ lines: [Line]) -> [TranscriptTurn] {
        lines.compactMap { l in
            let t = l.text.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : TranscriptTurn(role: l.me ? .person : .kaiku, text: String(t.prefix(2000)), complete: l.interrupted || t.count > 2000 ? false : (l.completionUnknown ? nil : l.transcriptFinished))
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
        audio.onFailure = { [weak self] in Task { @MainActor in
            guard let self, !self.stopped else { return }
            self.stop(outcome: .offline); self.unavailableReason = .audio; self.phase = .unavailable
        } }
        audio.onPCM = { [weak self] pcm in Task { @MainActor in
            if let self, self.app?.isPaused == true { self.stopForGlobalPause(); return }
            guard let self, !self.stopped, !self.muted,
                  self.phase != .paused, self.phase != .connecting, self.phase != .unavailable,
                  self.app?.pairing == self.sessionPairing else { return }
            self.live?.sendAudio(pcm)
        } }
        audio.setMic(false)
        audio.onPlaying = { [weak self] on in Task { @MainActor in self?.playing(on) } }
        audio.onLevel = { [weak self] db in Task { @MainActor in self?.level = db } }
        let listener = listener
        audio.onBuffer = localListener ? { b in listener.append(b) } : nil
        try audio.start()
        listener.onHit = { [weak self] hit in Task { @MainActor in self?.onDeviceHit(hit) } }
        if localListener { startListener() }
    }

    /// Global privacy pause closes an already-open Live microphone. Unpausing never resumes it silently.
    private func observeGlobalPause(generation: Int) {
        guard !stopped, generation == pauseGeneration, let app else { return }
        let state = withObservationTracking { (app.isPaused, app.pairingRevision) } onChange: { [weak self] in
            Task { @MainActor in self?.observeGlobalPause(generation: generation) }
        }
        if state.1 != pairingRevision {
            stop(outcome: .ended_early)
            lines = []; toolsUsed = []; lastSpokenDial = nil
            unavailableReason = .pairing; phase = .unavailable
        } else if state.0 { stopForGlobalPause() }
    }

    private func stopForGlobalPause() {
        guard !stopped else { return }
        stop(outcome: .ended_early)
        unavailableReason = .paused
        phase = .unavailable
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
        guard app?.pairing == sessionPairing else { stop(outcome: .ended_early); return }
        switch ev {
        case .ready:
            readyTask?.cancel(); readyTask = nil
            failures = 0
            if phase == .connecting || phase == .unavailable { phase = muted ? .muted : .listening }
            audio.setMic(!muted && phase != .paused)
            wasLive = true
            if !everReady { everReady = true; onReady?(); startContextRefresh() } else { onReconnected?() }
        case .modelOutput:
            if audioTurnEnded {
                if !outputFinalObserved { closeUnknownTranscript(me: false) }
                audioTurnEnded = false
            }
        case .audio(let pcm):
            guard phase != .paused else { return }
            audio.play(pcm)
        case .interrupted:
            if let id = kaikuTurnID, let index = lines.firstIndex(where: { $0.id == id }) {
                lines[index].interrupted = true
                lines[index].completionUnknown = false
            }
            audio.flush()
            if phase != .muted && phase != .paused { phase = .hearing }
        case .userText(let t):
            // Older providers omit finished. A new physical-input turn after audio completion is then a
            // boundary, but never evidence that the older transcript was final. Typed input is independent.
            if audioTurnEnded {
                if !inputFinalObserved { closeUnknownTranscript(me: true) }
                if !outputFinalObserved { closeUnknownTranscript(me: false) }
                audioTurnEnded = false
            }
            if SafetyGate.shared.check(t) != nil { crisis(); return }
            if SafetyGate.shared.check((lines.last(where: \.me)?.text ?? "") + t) != nil { crisis(); return }
            append(t, me: true)
            if phase == .listening { phase = .hearing }
        case .kaikuText(let t):
            append(t, me: false)
        case .userTranscriptComplete:
            inputFinalObserved = true
            finishTranscript(me: true)
        case .kaikuTranscriptComplete:
            outputFinalObserved = true
            finishTranscript(me: false)
        case .turnComplete:
            audioTurnEnded = true
            if !inputFinalObserved { markUnknownTranscript(me: true) }
            if !outputFinalObserved { markUnknownTranscript(me: false) }
            // Audio generation and transcript finalisation are independent protocol boundaries.
            if !audio.isPlaying && pendingTools == 0 && (phase == .hearing || phase == .speaking) { phase = .listening }
            flushPendingContext()
        case .toolCall(let id, let name, let args):
            Task { await tool(id: id, name: name, args: args) }
        case .toolCancelled:
            pendingTools = 0
        case .resumable(let h):
            handle = h
        case .goAway, .closed:
            note("live_dropped", ["go_away": ev == .goAway, "attempt": failures + 1])
            reconnect()
        }
    }

    private func playing(_ on: Bool) {
        guard !stopped, phase != .paused, phase != .muted else { return }
        if on { phase = .speaking } else if phase == .speaking { phase = pendingTools > 0 ? .thinking : .listening }
        if !on { flushPendingContext() }
    }

    /// Live can interleave person/model transcription fragments. Keep one bubble per speaker per turn.
    private func append(_ t: String, me: Bool) {
        guard !t.isEmpty else { return }
        if me { lastPersonAt = Date() } else { lastKaikuAt = Date() }
        if surface == .glasses {
            if me { GlassesStatus.shared.lastPersonAt = lastPersonAt } else { GlassesStatus.shared.lastKaikuAt = lastKaikuAt }
        }
        let id = me ? personTurnID : kaikuTurnID
        if let id, let index = lines.firstIndex(where: { $0.id == id }) {
            lines[index].text = Self.mergeTranscript(lines[index].text, t)
        } else {
            let line = Line(text: t, me: me)
            lines.append(line)
            if me { personTurnID = line.id } else { kaikuTurnID = line.id }
        }
    }

    private func markUnknownTranscript(me: Bool) {
        if let id = me ? personTurnID : kaikuTurnID, let index = lines.firstIndex(where: { $0.id == id }),
           !lines[index].interrupted { lines[index].completionUnknown = true }
    }

    private func closeUnknownTranscript(me: Bool) {
        markUnknownTranscript(me: me)
        if me { personTurnID = nil } else { kaikuTurnID = nil }
    }

    private func finishTranscript(me: Bool) {
        if let id = me ? personTurnID : kaikuTurnID, let index = lines.firstIndex(where: { $0.id == id }) {
            lines[index].transcriptFinished = true
            lines[index].completionUnknown = false
        }
        if me { personTurnID = nil } else { kaikuTurnID = nil }
    }

    nonisolated static func mergeTranscript(_ existing: String, _ incoming: String) -> String {
        if incoming.hasPrefix(existing) { return incoming }
        if incoming == existing { return existing }
        return existing + incoming
    }

    private func tool(id: String, name: String, args: [String: JSONValue]) async {
        toolsUsed.append(name)
        guard let app, let s = session, app.pairing == sessionPairing else { return }
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
        guard !stopped, app.pairing == sessionPairing else { return }
        onToolResult?(name, r)
        if r.crisis == true { crisis(); return }
        live?.respond(id: id, name: name, result: r.result ?? .object(["ok": .bool(r.ok)]))
        if name == "end_session", r.ok {
            stop(outcome: args["outcome"]?.string.flatMap(EpisodeOutcome.init(rawValue:)) ?? .completed)
        }
    }

    private func startContextRefresh() {
        guard let seconds = session?.context_refresh_seconds, seconds > 0 else { return }
        contextTask?.cancel()
        contextTask = Task { [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: UInt64(seconds) * 1_000_000_000) } catch { return }
                guard let self, !self.stopped else { return }
                await self.refreshContext()
            }
        }
    }

    /// Only completion labels and source provenance enter the voice session. Health, scores, free text,
    /// private notes and transcripts never leave through this path. Interpretation belongs to ask_mind.
    func refreshContext() async {
        guard !stopped, seenEvents.count < 2000, let app, !app.isPaused, app.pairing == sessionPairing,
              phase != .paused, phase != .muted,
              let response = try? await app.api.todaysEvents(since: started) else { return }
        guard !stopped, app.pairing == sessionPairing else { return }
        for event in response.events where event.home_id == sessionPairing?.homeID && !seenEvents.contains(event.id) {
            seenEvents.insert(event.id)
            if Self.contextLabel(event, app: app) != nil, pendingContext.count < 5 { pendingContext.append(event) }
        }
        flushPendingContext()
    }

    static func contextLabel(_ event: AnyEnvelope, app: AppModel) -> String? {
        guard event.sim != true, event.source != KaikuPlatform.source.rawValue else { return nil }
        let source = ["hub": "home robot", "head": "home robot", "sensors": "home robot",
                      "glasses": "glasses", "laptop": "laptop", "phone": "phone"][event.source]
        guard let source else { return nil }
        let activity: String
        switch event.type {
        case "obs.self_report" where app.allowed(.checkins): activity = "a check-in was recorded"
        case "obs.play_session", "obs.drum_session", "obs.ritual_complete":
            guard app.allowed(.checkins) else { return nil }; activity = "an activity was completed"
        case "obs.outing" where app.allowed(.walks): activity = "a walk was completed"
        default: return nil
        }
        return "\(source): \(activity)"
    }

    private func flushPendingContext() {
        guard !stopped, phase == .listening, !audio.isPlaying, pendingTools == 0,
              let app, !app.isPaused, !pendingContext.isEmpty else { return }
        let labels = pendingContext.compactMap { Self.contextLabel($0, app: app) }.joined(separator: "; ")
        pendingContext = []
        guard !labels.isEmpty else { return }
        context("[New activity received: \(labels). This is source context, not a clinical conclusion. Use ask_mind if interpretation is useful. Do not interrupt or announce scores.]")
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

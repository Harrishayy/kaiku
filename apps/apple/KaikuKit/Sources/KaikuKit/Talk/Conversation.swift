import Foundation
import Observation
#if os(iOS) && DEBUG
import UIKit
#endif

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
        /// Typed by the person (their own characters, kept as they are), not transcribed speech.
        public var typed = false
    }

    public let surface: CompanionSurface
    public let intent: CompanionIntent
    /// Why the conversation was opened; the cloud shapes the chat with it (a check-in is a small passing chat).
    public let purpose: CompanionPurpose?
    /// Walk conversations: how Kaiku walks with the person, sent as `walk_style` (set before `start`; nil elsewhere).
    @ObservationIgnored public var walkStyle: WalkStyle?
    /// The latest plan from the cloud's `feel` tool (the voice model noticed a feeling or news). `planCount`
    /// goes up with each one, so a view can react to a new plan that equals the previous one.
    public private(set) var plan: FeelPlan?
    public private(set) var planCount = 0
    /// How many things the person had said when the latest plan arrived (an offer lasts until they carry on).
    public private(set) var planTurns = 0
    /// The model closed the conversation itself (`end_session`): a passing chat that wrapped up warmly.
    public private(set) var closedByModel = false
    /// Kaiku's voice is muted: nothing is played, its words keep arriving as captions (the audio modality and the
    /// output transcription stay on). Independent of the microphone mute. Remembered on this device.
    public private(set) var voiceMuted = UserDefaults.standard.bool(forKey: Conversation.voiceMutedKey)
    public static let voiceMutedKey = "kaiku.talk.voiceMuted"
    /// When Live first answered in this conversation (the call's clock starts here).
    public private(set) var liveSince: Date?
    /// False when the conversation runs without the microphone (permission off): Kaiku still speaks and answers
    /// typed messages; nothing is captured.
    public private(set) var listens = true
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
    @ObservationIgnored private var closeTask: Task<Void, Never>?
    @ObservationIgnored private var resumeTask: Task<Void, Never>?
    /// A new socket is open and has not answered yet (first connect, reconnect or planned resume).
    @ObservationIgnored private var awaitingReady = false
    /// A planned move to the next token is under way (not a reconnect: nothing on screen changes).
    @ObservationIgnored private var resuming = false
    /// Set while a conversation the model closed is letting Kaiku's goodbye finish.
    @ObservationIgnored private var closing: (sawOutput: Bool, turnDone: Bool)?
    @ObservationIgnored private var listenerTask: Task<Void, Never>?
    @ObservationIgnored private var handle: String?
    @ObservationIgnored private var started = Date()
    @ObservationIgnored private var stopped = false
    @ObservationIgnored private var everReady = false
    @ObservationIgnored private var failures = 0
    @ObservationIgnored private var reconnecting = false
    /// The person muted their microphone (or it is not allowed): observable, independent of what Kaiku is doing.
    public private(set) var micMuted = false
    @ObservationIgnored private var muted: Bool { get { micMuted } set { if micMuted != newValue { micMuted = newValue } } }
    /// Kaiku's voice is playing right now (also while the person is muted, and while its voice is muted).
    public private(set) var kaikuSpeaking = false
    @ObservationIgnored private var pendingTools = 0
    @ObservationIgnored private var pauseGeneration = 0
    @ObservationIgnored private var pairingRevision = 0

    public convenience init(surface: CompanionSurface, intent: CompanionIntent, purpose: CompanionPurpose? = nil,
                            typedWithoutMic: Bool = false) {
        self.init(surface: surface, intent: intent, audio: ConversationAudio(),
                  transport: { LiveSession(onEvent: $0) }, permission: { await Self.micGranted() },
                  purpose: purpose, typedWithoutMic: typedWithoutMic)
    }

    init(surface: CompanionSurface, intent: CompanionIntent, audio: any ConversationAudioIO,
         transport: @escaping (@escaping @Sendable (LiveSession.Event) -> Void) -> any ConversationTransport,
         permission: @escaping () async -> Bool, localListener: Bool = true, purpose: CompanionPurpose? = nil,
         typedWithoutMic: Bool = false) {
        self.surface = surface; self.intent = intent; self.audio = audio
        self.transport = transport; self.permission = permission; self.localListener = localListener
        self.purpose = purpose; self.typedWithoutMic = typedWithoutMic
    }

    /// Without microphone permission the conversation still opens, with the microphone closed: writing works
    /// like speaking and Kaiku answers in its voice. Off by default (Talk and the walk need the microphone).
    @ObservationIgnored private let typedWithoutMic: Bool
    /// Cloud tools that must not look like waiting: Kaiku keeps talking and no "thinking" state is shown.
    nonisolated static let quietTools: Set<String> = ["feel"]

    public var isLive: Bool { live != nil && phase != .unavailable }
    /// Live setup was acknowledged at least once in this conversation.
    public private(set) var wasLive = false

    #if DEBUG
    var audioForDemo: any ConversationAudioIO { audio }
    #endif

    /// Tests: open the conversation on an already-made session, without the bootstrap request.
    func adoptForTest(session s: CompanionSessionResponse, app: AppModel, listens hears: Bool = true) {
        self.app = app
        listens = hears; if !hears { muted = true }
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
        plan = nil; planCount = 0; planTurns = 0; closedByModel = false; listens = true; liveSince = nil
        turn = nil; answerOwed = false; toolsThisTurn = 0; heldContext = []; kaikuMarks.reset(); personMarks.reset()
        sessionPairing = app.pairing
        pairingRevision = app.pairingRevision
        seenEvents = []; pendingContext = []
        started = Date()
        phase = .connecting
        guard app.isPaired else { unavailableReason = .pairing; phase = .unavailable; return false }
        guard !app.isPaused else { unavailableReason = .paused; phase = .unavailable; return false }
        pauseGeneration += 1
        observeGlobalPause(generation: pauseGeneration)
        if !(await permission()) {
            guard typedWithoutMic else { unavailableReason = .microphone; phase = .unavailable; return false }
            listens = false; muted = true
        }
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
        if localListener && listens && !OnDeviceListener.authorized { _ = await OnDeviceListener.requestAuthorization() }
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
        note("live_stop", ["outcome": outcome?.rawValue ?? "-", "lines": lines.count])
        pauseGeneration += 1
        limitTask?.cancel(); limitTask = nil
        readyTask?.cancel(); readyTask = nil
        closeTask?.cancel(); closeTask = nil; closing = nil
        resumeTask?.cancel(); resumeTask = nil; resuming = false; awaitingReady = false; turn = nil; heldText = []
        contextDrain?.cancel(); contextDrain = nil; heldContext = []; answerOwed = false; toolFrames = []; cancelledCalls = []
        contextTask?.cancel(); contextTask = nil; pendingContext = []
        connectionGeneration += 1
        eventContinuation?.finish(); eventContinuation = nil
        eventTask?.cancel(); eventTask = nil
        live?.close()
        live = nil
        audio.stop()
        stopListener()
        kaikuSpeaking = false
        phase = .idle
        guard let app, let s = session, let pairing = sessionPairing else { return }
        // The cloud never sees the audio socket: tell it the conversation is over and how long it ran (every way a
        // conversation ends comes through here, once), so its budget hold comes down to the time really used.
        // Not awaited, never retried, any answer is fine.
        if app.pairing == pairing {
            let api = app.api
            let close = SessionClose(home_id: pairing.homeID, session_id: s.session_id, elapsed_s: max(0, Date().timeIntervalSince(started)))
            Task { _ = try? await api.companionClose(close) }
        }
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

    /// Mute / unmute Kaiku's voice, at once (mid-sentence too). Captions are not affected.
    public func setVoiceMuted(_ on: Bool) {
        voiceMuted = on
        UserDefaults.standard.set(on, forKey: Self.voiceMutedKey)
        audio.setOutputMuted(on)
    }

    public func setMuted(_ on: Bool) {
        guard isLive, listens else { return }
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
        let line = Line(text: t, me: true, transcriptFinished: true, typed: true)
        lines.append(line)
        lastPersonAt = Date()
        personTookTheTurn()
        if SafetyGate.shared.check(t) != nil { crisis(); return }
        // Typed in the second or two a call spends moving to its next socket: sent as soon as that one answers.
        if awaitingReady { heldText.append(t) } else { live?.sendText(t) }
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
        #if DEBUG
        Self.debugTrace(event, fields)
        #endif
        guard surface == .glasses else { return }
        GlassesLog.shared.log(event, fields)
    }

    #if DEBUG
    /// `-kaikuCallTrace <file>`: one line per connection event (start, ready, the move to the next token, drops,
    /// the end) with the time; never words, audio or tokens. For checking a real call from outside the app.
    private static let traceFile = UserDefaults.standard.string(forKey: "kaikuCallTrace").map(URL.init(fileURLWithPath:))
    private static func debugTrace(_ event: String, _ fields: [String: Any]) {
        guard let traceFile else { return }
        let f = fields.sorted { $0.key < $1.key }.map { "\($0.key)=\($0.value)" }.joined(separator: " ")
        #if os(iOS)
        let state = ["active", "inactive", "background"][UIApplication.shared.applicationState.rawValue]
        #else
        let state = "mac"
        #endif
        let line = "\(KaikuTime.iso(Date())) \(event) \(f) app=\(state)\n"
        if let h = try? FileHandle(forWritingTo: traceFile) { h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close() }
        else { try? Data(line.utf8).write(to: traceFile) }
    }
    #endif

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
        if heldContext.isEmpty { heldContextSince = Date() }
        heldContext.append(event)
        drainContext()
    }

    // MARK: private — connection

    private func bootstrap() async -> CompanionSessionResponse? {
        guard let app else { return nil }
        var req = CompanionSessionRequest(surface: surface, home_id: app.pairing?.homeID ?? "", intent: intent,
                                          language: app.language.rawValue)
        req.resume_session_id = session?.session_id
        req.purpose = purpose
        req.walk_style = walkStyle
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
        endedWhileResuming = false
        let tuning: LiveSession.Tuning = ConversationAudio.headsetRoute ? .headset : .loudspeaker
        l.connect(token: token, session: s, options: .init(handsFree: true, tuning: tuning, resumeHandle: handle))
        // Setup must be acknowledged: a socket that opens but never says `setupComplete` would leave Talk on
        // "connecting" for good. Treat it like a drop (bounded by the same three attempts).
        awaitingReady = true
        readyTask?.cancel()
        readyTask = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: UInt64(Self.readyTimeout * 1_000_000_000)) } catch { return }
            guard let self, !self.stopped, self.connectionGeneration == generation, self.awaitingReady else { return }
            self.resuming = false
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

    /// How long before a Live token ends the conversation moves to the next one.
    static var resumeMargin: TimeInterval = 45
    @ObservationIgnored private var endedWhileResuming = false
    @ObservationIgnored private var heldText: [String] = []

    /// One Live token covers a limited stretch (about ten minutes); a longer call goes on with the next one. At
    /// the token's end (and when the server says the socket is about to close) the conversation asks the cloud
    /// for the next token (`resume_session_id`) and moves to a new socket with the resumption handle, between
    /// sentences. Nothing on screen changes: the captions stay, the call's clock keeps counting, the phase is
    /// not "connecting", and it is not a failed attempt. If the new socket never answers, the ordinary
    /// reconnect takes over.
    private func scheduleTokenResume() {
        resumeTask?.cancel()
        guard let t = session?.live_token, let end = Self.date(t.expires_at) else { return }
        let wait = end.timeIntervalSinceNow - Self.resumeMargin
        resumeTask = Task { [weak self] in
            if wait > 0 { do { try await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000)) } catch { return } }
            // between sentences, but never later than the margin allows
            var waited = 0.0
            while waited < Self.resumeMargin * 0.6 {
                guard let self, !self.stopped else { return }
                if !self.audio.isPlaying && self.personTurnID == nil && self.pendingTools == 0 { break }
                do { try await Task.sleep(nanoseconds: 250_000_000) } catch { return }
                waited += 0.25
            }
            self?.plannedResume()
        }
    }

    private func plannedResume() {
        guard !stopped, !reconnecting, !resuming, isLive, phase != .connecting else { return }
        resuming = true
        note("live_next_token", ["handle": handle != nil])
        Task {
            guard let fresh = await bootstrap(), let token = fresh.live_token?.token, !stopped, resuming else {
                // The cloud did not answer: the socket's own end reconnects (now, if it has ended meanwhile).
                note("live_next_token_failed", [:])
                let ended = endedWhileResuming
                resuming = false; endedWhileResuming = false
                if ended, !stopped { reconnect() }
                return
            }
            session?.live_token = fresh.live_token
            let old = live
            connect(token: token)                     // events of the old socket are ignored from here
            old?.close()
        }
    }

    /// The socket ended by itself in the middle of a call. That is ordinary: the server resets a connection after
    /// about ten minutes and closes one that has sent nothing for about two (a muted microphone, a typed
    /// conversation; seen live as close 1008 "client inactivity"). With a resumption handle the first try is
    /// quiet like a planned move: same token while it lasts, nothing on screen changes, the microphone stays as
    /// it was. It still counts as an attempt: if the new socket does not answer, the visible reconnect follows.
    private func quietReconnect() {
        failures += 1
        resuming = true
        Task {
            if let t = session?.live_token, !Self.expired(t.expires_at, margin: 60) {
                connect(token: t.token)
                return
            }
            guard let fresh = await bootstrap(), let token = fresh.live_token?.token, !stopped, resuming else {
                resuming = false
                if !stopped { reconnect() }
                return
            }
            session?.live_token = fresh.live_token
            connect(token: token)
        }
    }

    nonisolated static func date(_ iso: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: iso) ?? ISO8601DateFormatter().date(from: iso)
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
            // Typed lines are the person's own characters. A transcribed line never keeps a transcription marker,
            // and one that is only markers or marks was not said by anyone: it is not stored.
            let t = (l.typed ? l.text : MarkerFilter.clean(l.text)).trimmingCharacters(in: .whitespacesAndNewlines)
            let said = l.typed ? !t.isEmpty : t.contains(where: { $0.isLetter || $0.isNumber })
            return !said ? nil : TranscriptTurn(role: l.me ? .person : .kaiku, text: String(t.prefix(2000)), complete: l.interrupted || t.count > 2000 ? false : (l.completionUnknown ? nil : l.transcriptFinished))
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
        audio.setCapture(listens)
        audio.setOutputMuted(voiceMuted)
        audio.onPlaying = { [weak self] on in Task { @MainActor in self?.playing(on) } }
        audio.onLevel = { [weak self] db in Task { @MainActor in self?.level = db } }
        let listener = listener
        audio.onBuffer = localListener && listens ? { b in listener.append(b) } : nil
        try audio.start()
        listener.onHit = { [weak self] hit in Task { @MainActor in self?.onDeviceHit(hit) } }
        if localListener && listens { startListener() }
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

    /// Something Kaiku may say on its own initiative (a walk prompt, a reminder): the text goes to the model as a
    /// context turn (`context(_:)`), and like every model turn the person did not cause, the answer is held until
    /// its first real word (see `ModelTurn`). The name is the walk's.
    public func nudge(_ text: String) {
        guard isLive else { return }
        context(text)
    }

    /// Something the person did on the screen (opened a card, put it aside, set the dials): the model is told at
    /// once, and what it says back is the person's answer (played at once, like an answer to their words).
    public func personDid(_ text: String) {
        guard !stopped, isLive, app?.pairing == sessionPairing else { return }
        personTookTheTurn()
        live?.sendContext(text)
    }

    /// One model turn. A turn that answers the person plays at once. Any other turn is Kaiku's own initiative: it
    /// answers a context event, a nudge, a tool result, or nothing at all. With proactive audio on, the model
    /// often declines those with a second of non-speech sound (transcribed as `<no speech>`, `{pause}`, `×`, or
    /// not at all; seen in 9 of 14 real sessions and on a real walk). So such a turn's audio is held until its
    /// transcription has a real word, then played from the start; a turn whose transcription is a marker, or
    /// that ends without a word, is never heard and shows no bubble.
    private struct ModelTurn {
        var gated: Bool
        var held: [Data] = []
        /// nil = not known yet (audio is held), true = playing, false = the rest of this turn is dropped.
        var play: Bool?
        var said = ""
        /// Audio or transcription arrived in this turn.
        var sound = false
        /// When its latest frame arrived.
        var last = Date()
    }
    /// A turn streams without gaps. The server does not always say that a declined turn is over (seen live: a
    /// `<no speech>` turn with no `turnComplete` for half a minute), so a turn with no frame for this long is over:
    /// it no longer holds context events back, and the next frame starts a new turn.
    static var turnGap: TimeInterval = 3
    private var turnOpen: Bool { turn.map { Date().timeIntervalSince($0.last) < Self.turnGap } ?? false }
    @ObservationIgnored private var turn: ModelTurn?
    /// The person spoke or typed and the model has not answered since: its next turn is theirs. The credit is
    /// used up by a turn with sound, or by a turn that ends with nothing at all (the model chose to stay quiet);
    /// a turn that only called a tool keeps it (the answer comes after the tool).
    @ObservationIgnored private var answerOwed = false
    @ObservationIgnored private var toolsThisTurn = 0
    @ObservationIgnored private var owedAt = Date.distantPast
    /// How long after the person's last words (or a tool they caused) a model turn still counts as their answer.
    static var answerWindow: TimeInterval = 15
    private var owesAnswer: Bool { answerOwed && Date().timeIntervalSince(owedAt) < Self.answerWindow }

    private func modelTurn() -> ModelTurn {
        if let t = turn, turnOpen { turn?.last = Date(); return t }
        let owed = owesAnswer || closing != nil          // the goodbye of a conversation the model closed is an answer too
        let t = ModelTurn(gated: !owed, play: owed ? true : nil)
        turn = t
        return t
    }

    /// A letter or digit outside `<…>` and `{…}`: something was really said.
    nonisolated static func hasRealWord(_ fragment: String) -> Bool { Heard(fragment) == .word }

    /// The person spoke or typed: the model's next turn is their answer. A held turn of Kaiku's own that had not
    /// been heard yet is theirs to interrupt (it is dropped).
    private func personTookTheTurn() {
        answerOwed = true
        owedAt = Date()
        if let t = turn, t.gated, t.play != true { turn?.play = false; turn?.held = [] }
    }

    /// Context events wait while Kaiku is speaking, a tool is running, or the person is owed an answer: a context
    /// turn sent then would cut Kaiku off (a client turn interrupts the generation) or take the person's answer.
    @ObservationIgnored private var heldContext: [String] = []
    @ObservationIgnored private var heldContextSince = Date.distantPast
    @ObservationIgnored private var contextDrain: Task<Void, Never>?
    /// The longest a context event waits for a quiet moment before it is sent anyway.
    static var contextPatience: TimeInterval = 20

    private var busyForContext: Bool {
        turnOpen || audio.isPlaying || owesAnswer || phase == .hearing || pendingTools > 0 || awaitingReady
    }

    private func drainContext() {
        guard !stopped, !heldContext.isEmpty else { contextDrain?.cancel(); contextDrain = nil; return }
        if busyForContext && Date().timeIntervalSince(heldContextSince) < Self.contextPatience {
            guard contextDrain == nil else { return }
            contextDrain = Task { [weak self] in
                while !Task.isCancelled {
                    do { try await Task.sleep(nanoseconds: 300_000_000) } catch { return }
                    guard let self, !self.stopped, !self.heldContext.isEmpty else { return }
                    if !self.busyForContext || Date().timeIntervalSince(self.heldContextSince) >= Self.contextPatience {
                        self.contextDrain = nil
                        self.drainContext()
                        return
                    }
                }
            }
            return
        }
        contextDrain?.cancel(); contextDrain = nil
        let text = heldContext.joined(separator: "\n")
        heldContext = []
        answerOwed = false                      // what the model says next answers this, not the person
        live?.sendContext(text)
    }

    // MARK: private — events

    /// Tests: every Live event as it is handled (the opt-in real runs write their evidence from it).
    @ObservationIgnored var trace: ((LiveSession.Event) -> Void)?

    private func handle(_ ev: LiveSession.Event) {
        guard !stopped else { return }
        trace?(ev)
        guard app?.pairing == sessionPairing else { stop(outcome: .ended_early); return }
        switch ev {
        case .ready:
            readyTask?.cancel(); readyTask = nil
            failures = 0
            awaitingReady = false
            let planned = resuming
            resuming = false
            note(planned ? "live_next_socket_ready" : "live_ready", ["handle": handle != nil])
            let held = heldText
            heldText = []
            held.forEach { live?.sendText($0) }
            scheduleTokenResume()
            if phase == .connecting || phase == .unavailable { phase = muted ? .muted : .listening }
            audio.setMic(!muted && phase != .paused)
            wasLive = true
            if liveSince == nil { liveSince = Date() }
            if !everReady { everReady = true; onReady?(); startContextRefresh() } else if !planned { onReconnected?() }
        case .modelOutput:
            _ = modelTurn()
            if audioTurnEnded {
                if !outputFinalObserved { closeUnknownTranscript(me: false) }
                audioTurnEnded = false
            }
        case .audio(let pcm):
            guard phase != .paused else { return }
            if let c = closing {
                if c.turnDone { return }
                closing?.sawOutput = true
            }
            let play = modelTurn().play
            turn?.sound = true
            switch play {
            case nil: turn?.held.append(pcm)                              // held until the first word, or dropped
            case false?: break
            case true?: audio.play(pcm)
            }
        case .interrupted:
            if let id = kaikuTurnID, let index = lines.firstIndex(where: { $0.id == id }) {
                lines[index].interrupted = true
                lines[index].completionUnknown = false
            }
            audio.flush()
            turn = nil
            kaikuMarks.reset()
            if phase != .muted && phase != .paused { phase = .hearing }
        case .userText(let raw):
            guard let t = words(raw, me: true) else { return }
            personTookTheTurn()
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
        case .kaikuText(let raw):
            let now = modelTurn()
            turn?.sound = true
            if now.play == nil {
                let said = Self.mergeTranscript(now.said, raw)
                turn?.said = said
                switch Heard(said) {
                case .word:
                    turn?.play = true
                    turn?.held = []
                    now.held.forEach { audio.play($0) }
                case .notSpeech: turn?.play = false; turn?.held = []          // sound, not speech
                case .undecided: break
                }
            }
            let text = words(raw, me: false)
            if turn?.play == false { return }                                  // an unheard turn shows nothing
            guard let t = text else { return }
            if let c = closing {
                if c.turnDone { return }               // filler after the goodbye turn
                closing?.sawOutput = true
            }
            // A turn never starts with a stray mark ("-"): that is transcription noise, not a line.
            if kaikuTurnID == nil && !t.contains(where: { $0.isLetter || $0.isNumber }) { return }
            append(t, me: false)
        case .userTranscriptComplete:
            inputFinalObserved = true
            finishTranscript(me: true)
        case .kaikuTranscriptComplete:
            outputFinalObserved = true
            finishTranscript(me: false)
        case .turnComplete:
            // The turn is over: unheard if it never had a word. A turn with words was the person's answer.
            if let t = turn { if t.play == true && t.sound { answerOwed = false } }
            else if toolsThisTurn == 0 && pendingTools == 0 { answerOwed = false }
            turn = nil
            toolsThisTurn = 0
            kaikuMarks.reset()
            if closing?.sawOutput == true { closing?.turnDone = true }
            audioTurnEnded = true
            if !inputFinalObserved { markUnknownTranscript(me: true) }
            if !outputFinalObserved { markUnknownTranscript(me: false) }
            // Audio generation and transcript finalisation are independent protocol boundaries.
            if !audio.isPlaying && pendingTools == 0 && (phase == .hearing || phase == .speaking) { phase = .listening }
            flushPendingContext()
            drainContext()
        case .toolCall(let id, let name, let args):
            toolsThisTurn += 1
            Task { await tool(id: id, name: name, args: args) }
        case .toolFrame(let ids):
            toolFrames.append(ToolFrame(ids: ids))
        case .toolCancelled(let ids):
            pendingTools = 0
            cancelledCalls.formUnion(ids)
            for i in toolFrames.indices { toolFrames[i].ids.removeAll(where: ids.contains) }
            sendCompleteToolFrames()
        case .resumable(let h):
            handle = h
        case .goAway:
            // The server says this socket is about to end: move to a new one before it does.
            note("live_go_away", [:])
            plannedResume()
        case .closed:
            note("live_dropped", ["attempt": failures + 1, "quiet": everReady && handle != nil && failures == 0])
            if resuming && !awaitingReady { endedWhileResuming = true }            // the next token is on its way
            else if everReady, handle != nil, failures == 0, phase != .connecting { quietReconnect() }
            else { resuming = false; reconnect() }
        }
    }

    private func playing(_ on: Bool) {
        if kaikuSpeaking != (on && !stopped) { kaikuSpeaking = on && !stopped }
        guard !stopped, phase != .paused, phase != .muted else { return }
        if on { phase = .speaking } else if phase == .speaking { phase = pendingTools > 0 ? .thinking : .listening }
        if !on { flushPendingContext(); drainContext() }
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

    @ObservationIgnored private var kaikuMarks = MarkerFilter()
    @ObservationIgnored private var personMarks = MarkerFilter()

    /// The words of a transcription fragment. Every transcribed line of either speaker passes through here:
    /// markers are taken out, also when one arrives in pieces. Nil when nothing spoken is left.
    private func words(_ raw: String, me: Bool) -> String? {
        let wasInMarker = me ? personMarks.inMarker : kaikuMarks.inMarker
        let out = me ? personMarks.feed(raw) : kaikuMarks.feed(raw)
        guard !out.isEmpty else { return nil }
        let cut = wasInMarker || out.count != raw.count
        return cut && out.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : out
    }

    /// A turn's line is closed: its marker state goes with it, and a line that holds no word after all (only
    /// marks) is not a line.
    private func closeLine(me: Bool) {
        if me { personMarks.reset() } else { kaikuMarks.reset() }
        guard let id = me ? personTurnID : kaikuTurnID, let index = lines.firstIndex(where: { $0.id == id }) else { return }
        if !MarkerFilter.clean(lines[index].text).contains(where: { $0.isLetter || $0.isNumber }) { lines.remove(at: index) }
    }

    private func markUnknownTranscript(me: Bool) {
        if let id = me ? personTurnID : kaikuTurnID, let index = lines.firstIndex(where: { $0.id == id }),
           !lines[index].interrupted { lines[index].completionUnknown = true }
    }

    private func closeUnknownTranscript(me: Bool) {
        markUnknownTranscript(me: me)
        closeLine(me: me)
        if me { personTurnID = nil } else { kaikuTurnID = nil }
    }

    private func finishTranscript(me: Bool) {
        if let id = me ? personTurnID : kaikuTurnID, let index = lines.firstIndex(where: { $0.id == id }) {
            lines[index].transcriptFinished = true
            lines[index].completionUnknown = false
        }
        closeLine(me: me)
        if me { personTurnID = nil } else { kaikuTurnID = nil }
    }

    /// One whole fragment without its markers (`<no speech>`, `{pause}`, `<noise>`; pure). Nil when nothing spoken
    /// is left. The conversation itself uses `words(_:me:)`, which also follows a marker across fragments.
    nonisolated static func spoken(_ fragment: String) -> String? {
        guard fragment.contains("<") || fragment.contains("{") else { return fragment.isEmpty ? nil : fragment }
        let cleaned = MarkerFilter.clean(fragment)
        return cleaned.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : cleaned
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
            answer(id: id, name: name, result: result)
            return
        }
        let quiet = Self.quietTools.contains(name)
        if !quiet {
            pendingTools += 1
            if !audio.isPlaying && phase != .muted && phase != .paused { phase = .thinking }
        }
        defer {
            if !quiet {
                pendingTools = max(0, pendingTools - 1)
                if phase == .thinking && pendingTools == 0 { phase = .listening }
            }
        }
        let call = CompanionToolCall(home_id: app.pairing?.homeID ?? "", surface: surface, name: name, args: args,
                                     session_id: s.session_id)
        guard let r = try? await app.api.companionTool(call) else {
            answer(id: id, name: name, result: .object(["ok": .bool(false), "error": .string("offline")]))
            return
        }
        guard !stopped, app.pairing == sessionPairing else { return }
        onToolResult?(name, r)
        if r.crisis == true { crisis(); return }
        if answerOwed && !quiet { owedAt = Date() }       // the answer the person is waiting for comes after this tool
        answer(id: id, name: name, result: r.result ?? .object(["ok": .bool(r.ok)]))
        if name == "feel", r.ok, let p = FeelPlan(result: r.result) {
            plan = p; planTurns = lines.filter(\.me).count; planCount += 1
        }
        if name == "end_session", r.ok {
            closedByModel = true
            closeAfterGoodbye(args["outcome"]?.string.flatMap(EpisodeOutcome.init(rawValue:)) ?? .completed)
        }
    }

    /// Calls that arrived in one `toolCall` frame are answered in one `toolResponse` frame, device and cloud tools
    /// alike (answered one by one, the real model issued a call again and the device stood one ahead of what
    /// Kaiku said). A result waits for the others of its frame, at most `toolFramePatience`: a slow cloud tool
    /// (the mind can think for two minutes) must not hold a fast device result back for long; after that what is
    /// there goes out and the rest follows when it comes.
    private struct ToolFrame {
        var ids: [String]
        var answers: [ToolAnswer] = []
        var since: Date?
    }
    @ObservationIgnored private var toolFrames: [ToolFrame] = []
    @ObservationIgnored private var cancelledCalls: Set<String> = []
    static var toolFramePatience: TimeInterval = 10

    private func answer(id: String, name: String, result: JSONValue) {
        if cancelledCalls.remove(id) != nil { return }                 // the model no longer waits for this one
        guard let i = toolFrames.firstIndex(where: { $0.ids.contains(id) }) else {
            live?.respond([ToolAnswer(id: id, name: name, result: result)])
            return
        }
        toolFrames[i].answers.append(ToolAnswer(id: id, name: name, result: result))
        if toolFrames[i].since == nil {
            toolFrames[i].since = Date()
            let first = id
            Task { [weak self] in
                try? await Task.sleep(nanoseconds: UInt64(Self.toolFramePatience * 1_000_000_000))
                self?.sendCompleteToolFrames(overdue: first)
            }
        }
        sendCompleteToolFrames()
    }

    /// Sends every frame whose calls have all been answered (in the order they were called); `overdue` also
    /// sends what a frame has so far once its first answer has waited long enough.
    private func sendCompleteToolFrames(overdue: String? = nil) {
        guard !stopped else { toolFrames = []; return }
        for i in toolFrames.indices.reversed() {
            var f = toolFrames[i]
            let answered = Set(f.answers.map(\.id))
            let complete = f.ids.allSatisfy(answered.contains)
            let late = overdue.map { o in f.answers.contains { $0.id == o } } ?? false
            guard complete || late else { continue }
            let order = f.ids
            let out = f.answers.filter { order.contains($0.id) }
                .sorted { (order.firstIndex(of: $0.id) ?? 0) < (order.firstIndex(of: $1.id) ?? 0) }
            if !out.isEmpty { live?.respond(out) }
            f.ids.removeAll(where: answered.contains)
            f.answers = []
            f.since = nil
            if f.ids.isEmpty { toolFrames.remove(at: i) } else { toolFrames[i] = f }
        }
    }

    /// How long Kaiku's voice must have been quiet before a conversation the model closed really ends.
    static var closeGrace: TimeInterval = 1.5

    /// `end_session` lands just before Kaiku's goodbye (the model speaks it once the tool has answered) or right
    /// after it (its voice is still playing): both were seen live. Stop listening at once and let the goodbye be
    /// heard (bounded), then end: it is never cut off and never skipped. Whatever the model produces after the
    /// goodbye turn is filler (seen live: seconds of silent audio, transcribed as "-"), so that is dropped.
    private func closeAfterGoodbye(_ outcome: EpisodeOutcome) {
        guard Self.closeGrace > 0 || audio.isPlaying else { stop(outcome: outcome); return }
        muted = true
        audio.setMic(false)
        live?.audioStreamEnd()
        closing = (sawOutput: audio.isPlaying, turnDone: false)
        closeTask?.cancel()
        closeTask = Task { [weak self] in
            let grace = Self.closeGrace
            var quiet = 0.0, waited = 0.0
            while waited < 15 {
                do { try await Task.sleep(nanoseconds: 200_000_000) } catch { return }
                waited += 0.2
                guard let self, !self.stopped, let c = self.closing else { return }
                quiet = self.audio.isPlaying ? 0 : quiet + 0.2
                if c.sawOutput {
                    // the goodbye turn ended and its voice has played out (or it simply went quiet)
                    if (c.turnDone && quiet >= max(0.2, grace * 0.4)) || quiet >= max(0.2, grace * 2) { break }
                } else if waited >= grace * 3 && quiet >= max(0.2, grace) { break }   // it had already said goodbye
            }
            self?.stop(outcome: outcome)
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

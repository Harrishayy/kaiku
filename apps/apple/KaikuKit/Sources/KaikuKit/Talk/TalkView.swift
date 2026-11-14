import SwiftUI

/// Talk: an open spoken conversation (Conversation: server VAD, barge-in, the mind's tools) + bubbles + composer.
/// Starts with POST /v1/companion/session {surface: iphone|mac, intent: talk}. Tap Kaiku to stop / start listening.
/// Without Live (offline, no key, no mic): "Kaiku can talk once it's online" + typed messages that run the local
/// safety gate and get short scripted replies (copy keys; no AI pretending).
@Observable @MainActor
final class TalkModel {
    struct Line: Identifiable, Equatable { let id: UUID; let text: String; let me: Bool; var interrupted = false }
    enum Mode: Equatable { case connecting, live, scripted, listening, thinking, speaking, denied, paused, muted, ended }

    var expression: MascotState?
    private var scripted: [Line] = []
    private var scriptedThinking = false
    private var scriptedIndex = 0
    private var scriptedTask: Task<Void, Never>?
    private var replyGeneration = 0
    private(set) var conversation: Conversation
    private let makeConversation: @MainActor () -> Conversation
    init(makeConversation: @escaping @MainActor () -> Conversation = { Conversation(surface: KaikuPlatform.surface, intent: .talk) }) {
        self.makeConversation = makeConversation
        conversation = makeConversation()
    }
    weak var app: AppModel?
    private var audioTokens: [NSObjectProtocol] = []
    private var routeAnnounced = false
    private var started = false
    private var denied = false

    var hasLive: Bool { conversation.isLive }
    var lastSpokenDial: Int? { conversation.lastSpokenDial }

    var lines: [Line] {
        conversation.lines.map { Line(id: $0.id, text: $0.text, me: $0.me, interrupted: $0.interrupted) } + scripted
    }

    var mode: Mode {
        if denied { return .denied }
        if scriptedThinking { return .thinking }
        switch conversation.phase {
        case .idle: return started ? .ended : .connecting
        case .connecting: return .connecting
        case .listening: return .live
        case .hearing: return .listening
        case .thinking: return .thinking
        case .speaking: return .speaking
        case .muted: return .muted
        case .paused: return .paused
        case .unavailable: return .scripted
        }
    }

    func start(app: AppModel) async {
        self.app = app
        #if DEBUG
        // Inspect a real window without opening capture or minting a provider session.
        if UserDefaults.standard.bool(forKey: "kaikuInspectOnly") { started = true; return }
        #endif
        if denied && AudioCapture.permission != .denied { started = false }
        guard !started else { return }
        started = true
        if audioTokens.isEmpty {
            audioTokens = TalkAudio.observe { [weak self] ev in self?.audioEvent(ev) }
        }
        let c = conversation
        c.deviceTool = { [weak self] name, args in await self?.deviceTool(name, args) ?? .object(["ok": .bool(false)]) }
        c.onCrisis = { [weak self] in self?.app?.crisis(trigger: "phrase") }
        c.onReady = { [weak c] in c?.context("[the person just opened Talk]") }   // Kaiku greets in its live voice
        denied = AudioCapture.permission == .denied
        await app.ensureServiceConnection()
        guard started else { return }
        let ok = await c.start(app: app)
        denied = AudioCapture.permission == .denied
        if !ok {
            // No Live: Kaiku still says hello in its own Gemini voice (cached / fetched line; silent offline).
            VoiceLines.shared.play(Self.greetingKey(), lang: app.language)
        }
    }

    func stop() {
        replyGeneration += 1
        scriptedTask?.cancel(); scriptedTask = nil
        scriptedThinking = false; scripted = []
        conversation.stop()
        audioTokens.forEach(NotificationCenter.default.removeObserver)
        audioTokens = []
        VoiceLines.shared.stop()
        TalkAudio.deactivate()
        started = false
        conversation = makeConversation()
    }

    // MARK: input

    func send(_ raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        if hasLive { conversation.send(text: text); return }
        scripted.append(Line(id: UUID(), text: text, me: true))
        if SafetyGate.shared.check(text) != nil { app?.crisis(trigger: "phrase"); return }
        scriptedReply()
    }

    /// Tap Kaiku: stop listening ↔ listen again (Kaiku may finish its sentence).
    func toggleListening() {
        guard hasLive else {
            if let app { started = false; Task { await start(app: app) } }
            return
        }
        conversation.setMuted(mode != .muted)
    }

    /// The mic is open (Live, not muted / paused).
    var micOn: Bool { hasLive && mode != .muted && mode != .paused }

    private func scriptedReply() {
        scriptedThinking = true
        let keys = ["talk.scripted.1", "talk.scripted.2", "talk.scripted.3"]
        let key = keys[scriptedIndex % keys.count]
        scriptedIndex += 1
        scriptedTask?.cancel()
        replyGeneration += 1
        let generation = replyGeneration
        let pairing = app?.pairing
        scriptedTask = Task {
            do { try await Task.sleep(nanoseconds: 900_000_000) } catch { return }
            guard generation == replyGeneration, app?.pairing == pairing else { return }
            scripted.append(Line(id: UUID(), text: T(key), me: false))
            scriptedThinking = false
        }
    }

    // MARK: device tools (the model requests, the device decides)

    private func deviceTool(_ name: String, _ args: [String: JSONValue]) async -> JSONValue {
        guard let app else { return .object(["ok": .bool(false)]) }
        switch name {
        case "express":
            let f = args["feeling"]?.string ?? "happy"
            expression = ["sleepy": .sleepy, "cozy": .cozy, "curious": .listening, "proud": .cheering][f] ?? .happy
        case "record_dial":
            if let item = args["item"]?.string.flatMap(DialItem.init(rawValue:)), let v = args["value"]?.int ?? lastSpokenDial {
                return .object(["ok": .bool(await app.recordDial(item: item, value: v))])
            }
            return .object(["ok": .bool(false), "error": .string("a valid item and value are required")])
        case "start_phq9":
            guard app.isPaired else { return .object(["ok": .bool(false)]) }
            app.phq9Requested = true
        case "start_activity":
            // Only on the person's word: a model that opens a fresh Talk by launching a game would pull them out
            // of the conversation before they said anything (seen live 2026-11-14).
            guard conversation.lines.contains(where: \.me) else {
                return .object(["ok": .bool(false), "error": .string("ask the person first; they haven't asked for an activity")])
            }
            let kind = args["kind"]?.string ?? ""
            guard let r = ["breathe": KaikuRoute.breathe, "firefly": .firefly, "pebbles": .pebbles, "tell": .tell, "walk": .walk, "light_hunt": .walk][kind] else {
                return .object(["ok": .bool(false), "error": .string("not on this device")])
            }
            app.deepLink = r
            app.selectedTab = r.tab
        default:
            return .object(["ok": .bool(false), "error": .string("not on this device")])
        }
        return .object(["ok": .bool(true)])
    }
}

extension TalkModel {
    static func greetingKey(_ d: Date = Date()) -> String {
        let h = Calendar.current.component(.hour, from: d)
        return h < 5 ? "greet.night" : h < 12 ? "greet.morning" : h < 18 ? "greet.afternoon" : h < 23 ? "greet.evening" : "greet.night"
    }

    /// Phone call / Siri / alarm → pause (mascot sleepy, "listening paused"); afterwards resume politely.
    /// Glasses or AirPods connecting / leaving → keep going on the new route, tell the person once.
    func audioEvent(_ ev: TalkAudio.Event) {
        switch ev {
        case .interrupted:
            VoiceLines.shared.stop()
            conversation.pause()
        case .resumed(let shouldResume):
            guard shouldResume, conversation.phase == .paused else { return }
            conversation.resume()
            conversation.context("[back after an interruption, e.g. a phone call]")
        case .routeChanged(let name):
            guard !routeAnnounced, !name.isEmpty else { return }
            routeAnnounced = true
            app?.showToast(T("talk.route", ["name": name]))
        }
    }

    /// Backgrounded during Talk: end the session cleanly after 30 s.
    func backgrounded() async {
        try? await Task.sleep(nanoseconds: 30_000_000_000)
        if !Task.isCancelled { stop() }
    }
}

public struct TalkView: View {
    @Environment(AppModel.self) private var app
    @State private var model = TalkModel()
    @State private var text = ""
    @State private var bgTask: Task<Void, Never>?
    @State private var columnWidth: CGFloat = 0
    @Environment(\.scenePhase) private var phase
    @Environment(\.openURL) private var openURL
    @State private var showPairing = false
    @State private var followLatest = true
    @Environment(\.dynamicTypeSize) private var dts
    @Environment(\.kaikuStaticLayout) private var staticLayout

    public init() {}

    /// Header-sized Kaiku: the chat gets the room (no panel, no halo; the mascot draws on a clear background).
    var mascotSize: CGFloat { KaikuTokens.Size.mascotS }

    var mascotState: MascotState {
        switch model.mode {
        case .listening: return .listening
        case .thinking, .connecting: return .thinking
        case .speaking: return .speaking
        case .paused, .muted: return .sleepy
        default: return model.expression ?? app.ambientState
        }
    }

    public var body: some View {
        KScreen(T("tab.talk"), scrolls: false, maxWidth: KaikuTokens.Size.contentMax, spacing: KaikuTokens.Space.s3) {
            header
            voiceButton
            transcript
            Composer(text: $text, placeholder: T("talk.type"), mic: voiceAction,
                     micOn: model.micOn, micLabel: voiceControlTitle, micDisabled: model.mode == .connecting) {
                followLatest = true
                model.send(text)
                text = ""
            }
            .disabled(model.mode == .connecting)
        }
        .sheet(isPresented: $showPairing) {
            PairStep(back: { showPairing = false }, next: { showPairing = false; model.toggleListening() })
                .environment(app)
        }
        .task { if !staticLayout { await model.start(app: app) } }
        .onDisappear { model.stop() }
        .onChange(of: app.pairing) { _, _ in model.stop(); text = "" }
        .onChange(of: phase) { _, p in
            bgTask?.cancel()
            if p == .background { bgTask = Task { await model.backgrounded() } }
            if p == .active { Task { await model.start(app: app) } }
        }
    }

    // MARK: header — compact Kaiku (tap = talk / stop) + one status line

    private var header: some View {
        HStack(spacing: KaikuTokens.Space.s3) {
            ZStack {
                if model.micOn { ListeningRing(size: mascotSize + KaikuTokens.Space.s2, active: model.mode == .listening) }
                MascotView(state: mascotState, size: mascotSize, tappable: false)
            }
            .frame(width: mascotSize + KaikuTokens.Space.s3, height: mascotSize + KaikuTokens.Space.s3)
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                Text(statusLine).kText(.callout, weight: .medium).foregroundStyle(KaikuTokens.Colors.ink)
                    .wraps()
                if model.hasLive, !TalkAudio.outputName.isEmpty {
                    Text(T("talk.voice.route", ["name": TalkAudio.outputName])).kText(.footnote)
                        .foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                }
                if let sub = subLine {
                    Text(sub).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast), value: model.mode)
        }
        .accessibilityElement(children: .combine)
    }

    /// The one voice control: a full-width labelled button whenever the microphone is not open. While it is
    /// open, the same action lives on the microphone button beside the composer ("Mute microphone").
    @ViewBuilder private var voiceButton: some View {
        if !model.micOn && model.mode != .connecting {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                Button(action: voiceAction) {
                    Label(voiceControlTitle, systemImage: model.mode == .denied ? "gearshape.fill" : "mic.fill")
                }
                .buttonStyle(.kPrimary)
                if app.isPaired && model.mode != .denied {
                    Text(T("talk.voice.cta.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
            }
        }
    }

    private func voiceAction() {
        if !app.isPaired || model.conversation.unavailableReason == .pairing { showPairing = true }
        else if model.mode == .denied {
            #if os(iOS)
            if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
            #else
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") { openURL(url) }
            #endif
        } else { model.toggleListening() }
    }

    /// Voice stopped for a reason that trying again can fix (not pairing, permission or the privacy pause).
    private var canRetry: Bool {
        guard model.mode == .scripted, app.isPaired else { return false }
        switch model.conversation.unavailableReason {
        case .connection, .voice, .audio: return true
        default: return false
        }
    }

    private var voiceControlTitle: String {
        if !app.isPaired || model.conversation.unavailableReason == .pairing { return T("talk.voice.connect") }
        if model.mode == .denied { return T("talk.voice.settings") }
        if model.mode == .connecting { return T("talk.connecting") }
        if model.micOn { return T("talk.voice.mute") }
        return model.hasLive ? T("talk.voice.resume") : T("talk.voice.start")
    }

    private var unavailableText: String {
        switch model.conversation.unavailableReason {
        case .pairing: return T("talk.unavailable.pairing")
        case .microphone: return T("talk.unavailable.microphone")
        case .connection: return T("talk.unavailable.connection")
        case .voice: return T("talk.unavailable.voice")
        case .audio: return T("talk.unavailable.audio")
        case .paused: return T("you.pauseall.d")
        case nil: return T("talk.offline.t")
        }
    }

    private var statusLine: String {
        switch model.mode {
        case .ended: return T("talk.ended")
        case .connecting: return T("talk.connecting")
        case .live: return T("talk.on")
        case .listening: return T("talk.listening")
        case .thinking: return T("talk.thinking")
        case .speaking: return T("talk.speaking.hint")
        case .muted: return T("talk.tap")
        case .scripted, .denied: return unavailableText
        case .paused: return T("talk.paused")
        }
    }

    private var subLine: String? {
        switch model.mode {
        case .scripted: return T("talk.offline.d")
        case .ended: return T("talk.ended.d")
        default: return nil
        }
    }

    // MARK: transcript — full-width column, bubbles up to 80 %, pinned to the newest line

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: KaikuTokens.Space.s2) {
                    if model.mode == .denied { MicPermissionCard {} }
                    if canRetry {
                        // A dropped or unavailable voice is never a dead end: say what happened, offer one action.
                        KCard(tone: .sky) {
                            Text(model.lines.isEmpty ? unavailableText : T("talk.unavailable.dropped")).kText(.body)
                                .foregroundStyle(KaikuTokens.Colors.ink).wraps()
                        }
                    }
                    if model.lines.isEmpty { TalkWelcome { model.send($0) } }
                    ForEach(model.lines) { l in
                        Bubble(l.text, from: l.me ? .me : .kaiku, maxWidth: bubbleMax, footnote: l.interrupted ? T("talk.interrupted.label") : nil)
                            .textSelection(.enabled)
                            .id(l.id)
                    }
                    if model.mode == .thinking { TypingDots().frame(maxWidth: .infinity, alignment: .leading) }
                    Color.clear.frame(height: 1).id(Self.bottom)
                        .onAppear { followLatest = true }
                        .onDisappear { followLatest = false }
                }
                .padding(.vertical, KaikuTokens.Space.s2)
            }
            .defaultScrollAnchor(.bottom)
            .scrollDismissesKeyboard(.interactively)
            .frame(maxHeight: .infinity)
            .overlay(alignment: .bottomTrailing) {
                if !followLatest {
                    Button(T("talk.latest")) {
                        followLatest = true
                        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { proxy.scrollTo(Self.bottom, anchor: .bottom) }
                    }.buttonStyle(KButtonStyle(.secondary, fullWidth: false)).padding(KaikuTokens.Space.s2)
                }
            }
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { columnWidth = $0 }
            .onChange(of: model.lines) { _, _ in toBottom(proxy) }
            .onChange(of: model.mode) { _, _ in toBottom(proxy) }
            #if os(iOS)
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardDidShowNotification)) { _ in
                toBottom(proxy, animated: false)
            }
            #endif
        }
    }

    private static let bottom = "talk.bottom"

    private var bubbleMax: CGFloat {
        let w = columnWidth > 0 ? columnWidth : 600
        return dts.isAccessibilitySize ? w * 0.92 : w * 0.8
    }

    private func toBottom(_ proxy: ScrollViewProxy, animated: Bool = true) {
        guard followLatest else { return }
        if animated {
            withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { proxy.scrollTo(Self.bottom, anchor: .bottom) }
        } else {
            proxy.scrollTo(Self.bottom, anchor: .bottom)
        }
    }
}

/// A thin breathing ring around the header Kaiku while the mic is open (no filled panel).
struct ListeningRing: View {
    let size: CGFloat
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: rm || !active)) { tl in
            let t = tl.date.timeIntervalSinceReferenceDate
            let pulse = rm || !active ? 0.5 : 0.5 + 0.5 * sin(t * 2.4)
            Circle()
                .strokeBorder(KaikuTokens.Colors.clay.opacity(0.35 + 0.4 * pulse), lineWidth: 2.5)
                .frame(width: size, height: size)
                .scaleEffect(1 + 0.04 * pulse)
        }
        .accessibilityHidden(true)
    }
}

/// Three soft dots while Kaiku thinks (the header Kaiku already shows it's thinking).
struct TypingDots: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20, paused: rm)) { tl in
            let t = tl.date.timeIntervalSinceReferenceDate
            HStack(spacing: KaikuTokens.Space.s1) {
                ForEach(0..<3, id: \.self) { i in
                    Circle().fill(KaikuTokens.Colors.muted)
                        .frame(width: KaikuTokens.Space.s2, height: KaikuTokens.Space.s2)
                        .opacity(rm ? 0.7 : 0.35 + 0.65 * (0.5 + 0.5 * sin(t * 4 - Double(i) * 0.8)))
                }
            }
            .padding(.horizontal, KaikuTokens.Space.s3)
            .padding(.vertical, KaikuTokens.Space.s3)
            .background(Capsule().fill(KaikuTokens.Colors.surface))
        }
        .accessibilityLabel(T("talk.thinking"))
    }
}


/// Empty Talk: a warm hello card + three conversation starters (tap = send). Nobody faces a blank chat.
struct TalkWelcome: View {
    let send: (String) -> Void
    @Environment(AppModel.self) private var app
    static let starters: [(String, String, KTone)] = [
        ("sun.max.fill", "talk.starter.good", .honey),
        ("figure.walk", "talk.starter.walk", .sage),
        ("moon.stars.fill", "talk.starter.wind", .sky),
    ]
    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            Text(T("talk.welcome.t")).kText(.title3).wraps()
            Text(T("talk.welcome.d")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            ForEach(Self.starters, id: \.1) { icon, key, _ in
                Button { send(T(key)) } label: {
                    Label(T(key), systemImage: icon).kText(.callout).wraps()
                        .frame(maxWidth: .infinity, alignment: .leading)
                }.buttonStyle(KButtonStyle(.secondary))
            }
        }.padding(.vertical, KaikuTokens.Space.s2)
    }
}

import SwiftUI

/// Talk: an open spoken conversation (Conversation: server VAD, barge-in, the mind's tools) + bubbles + composer.
/// Starts with POST /v1/companion/session {surface: iphone|mac, intent: talk}. Tap Kaiku to stop / start listening.
/// Without Live (offline, no key, no mic): "Kaiku can talk once it's online" + typed messages that run the local
/// safety gate and get short scripted replies (copy keys; no AI pretending).
@Observable @MainActor
final class TalkModel {
    struct Line: Identifiable, Equatable { let id: UUID; let text: String; let me: Bool }
    enum Mode: Equatable { case connecting, live, scripted, listening, thinking, speaking, denied, paused, muted }

    var expression: MascotState?
    private var scripted: [Line] = []
    private var scriptedThinking = false
    private var scriptedIndex = 0
    private(set) var conversation = Conversation(surface: KaikuPlatform.surface, intent: .talk)
    weak var app: AppModel?
    private var audioTokens: [NSObjectProtocol] = []
    private var routeAnnounced = false
    private var started = false
    private var denied = false

    var hasLive: Bool { conversation.isLive }
    var lastSpokenDial: Int? { conversation.lastSpokenDial }

    var lines: [Line] {
        conversation.lines.map { Line(id: $0.id, text: $0.text, me: $0.me) } + scripted
    }

    var mode: Mode {
        if denied { return .denied }
        if scriptedThinking { return .thinking }
        switch conversation.phase {
        case .idle, .connecting: return started ? .connecting : .connecting
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
        guard !started else { return }
        started = true
        if audioTokens.isEmpty {
            audioTokens = TalkAudio.observe { [weak self] ev in self?.audioEvent(ev) }
        }
        let c = conversation
        c.deviceTool = { [weak self] name, args in await self?.deviceTool(name, args) ?? .object(["ok": .bool(false)]) }
        c.onCrisis = { [weak self] in self?.app?.crisis(trigger: "phrase") }
        c.onReady = { [weak c] in c?.context("[the person just opened Talk]") }   // Kaiku greets in its live voice
        if AudioCapture.permission == .denied { denied = true }
        let ok = await c.start(app: app)
        if !ok {
            // No Live: Kaiku still says hello in its own Gemini voice (cached / fetched line; silent offline).
            VoiceLines.shared.play(Self.greetingKey(), lang: app.language)
        }
    }

    func stop() {
        conversation.stop()
        audioTokens.forEach(NotificationCenter.default.removeObserver)
        audioTokens = []
        VoiceLines.shared.stop()
        TalkAudio.deactivate()
        started = false
        conversation = Conversation(surface: KaikuPlatform.surface, intent: .talk)
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
        guard hasLive else { return }
        conversation.setMuted(mode != .muted)
    }

    /// The mic is open (Live, not muted / paused).
    var micOn: Bool { hasLive && mode != .muted && mode != .paused }

    private func scriptedReply() {
        scriptedThinking = true
        let keys = ["talk.scripted.1", "talk.scripted.2", "talk.scripted.3"]
        let key = keys[scriptedIndex % keys.count]
        scriptedIndex += 1
        Task {
            try? await Task.sleep(nanoseconds: 900_000_000)
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
                await app.emit("obs.self_report", SelfReport(item: item, value: v, channel: KaikuPlatform.channel, context: "adhoc"))
            }
        case "start_activity":
            // Only on the person's word: a model that opens a fresh Talk by launching a game would pull them out
            // of the conversation before they said anything (seen live 2026-11-14).
            guard conversation.lines.contains(where: \.me) else {
                return .object(["ok": .bool(false), "error": .string("ask the person first; they haven't asked for an activity")])
            }
            let kind = args["kind"]?.string ?? ""
            guard let r = ["breathe": KaikuRoute.breathe, "firefly": .firefly, "pebbles": .pebbles, "tell": .tell][kind] else {
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
        case .resumed:
            guard conversation.phase == .paused else { return }
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
    @Environment(\.dynamicTypeSize) private var dts

    public init() {}

    /// Header-sized Kaiku: the chat gets the room (no panel, no halo; the mascot draws on a clear background).
    var mascotSize: CGFloat { dts.isAccessibilitySize ? 48 : 60 }

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
        KScreen(T("tab.talk"), scrolls: false, maxWidth: KaikuPlatform.isPhone ? 760 : 900, spacing: KaikuTokens.Space.s3) {
            header
            transcript
            Composer(text: $text, placeholder: T("talk.type")) {
                model.send(text)
                text = ""
            }
            .disabled(model.mode == .connecting)
        }
        .task { await model.start(app: app) }
        .onDisappear { model.stop() }
        .onChange(of: phase) { _, p in
            bgTask?.cancel()
            if p == .background { bgTask = Task { await model.backgrounded() } }
        }
    }

    // MARK: header — compact Kaiku (tap = talk / stop) + one status line

    private var header: some View {
        HStack(spacing: KaikuTokens.Space.s3) {
            Button { model.toggleListening() } label: {
                ZStack {
                    if model.micOn {
                        ListeningRing(size: mascotSize + 10, active: model.mode == .listening)
                    }
                    MascotView(state: mascotState, size: mascotSize, tappable: false)
                }
                .frame(width: mascotSize + 12, height: mascotSize + 12)
                .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(model.micOn ? T("talk.a11y.stop") : T("talk.a11y.start"))
            .accessibilityAddTraits(.isButton)

            VStack(alignment: .leading, spacing: 2) {
                Text(statusLine).kText(.callout, weight: .medium).foregroundStyle(KaikuTokens.Colors.ink)
                    .lineLimit(2).minimumScaleFactor(0.85)
                if let sub = subLine {
                    Text(sub).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).lineLimit(2)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast), value: model.mode)

            if model.hasLive {
                IconButton(model.micOn ? "mic.fill" : "mic", label: model.micOn ? T("talk.a11y.stop") : T("talk.a11y.start"),
                           filled: model.micOn) { model.toggleListening() }
            }
        }
    }

    private var statusLine: String {
        switch model.mode {
        case .connecting: return T("talk.connecting")
        case .live: return T("talk.on")
        case .listening: return T("talk.listening")
        case .thinking: return T("talk.thinking")
        case .speaking: return T("talk.speaking.hint")
        case .muted: return T("talk.tap")
        case .scripted, .denied: return T("talk.offline.t")
        case .paused: return T("talk.paused")
        }
    }

    private var subLine: String? {
        switch model.mode {
        case .scripted: return T("talk.offline.d")
        default: return nil
        }
    }

    // MARK: transcript — full-width column, bubbles up to 80 %, pinned to the newest line

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: KaikuTokens.Space.s2) {
                    if model.mode == .denied { MicPermissionCard {} }
                    if model.lines.isEmpty { TalkWelcome { model.send($0) } }
                    ForEach(model.lines) { l in
                        TalkBubble(text: l.text, me: l.me, maxWidth: bubbleMax).id(l.id)
                    }
                    if model.mode == .thinking { TypingDots().frame(maxWidth: .infinity, alignment: .leading) }
                    Color.clear.frame(height: 1).id(Self.bottom)
                }
                .padding(.vertical, KaikuTokens.Space.s2)
            }
            .defaultScrollAnchor(.bottom)
            .scrollDismissesKeyboard(.interactively)
            .frame(maxHeight: .infinity)
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
        if animated {
            withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { proxy.scrollTo(Self.bottom, anchor: .bottom) }
        } else {
            proxy.scrollTo(Self.bottom, anchor: .bottom)
        }
    }
}

/// One chat bubble: up to `maxWidth` (80 % of the column), never squeezed vertically (the keyboard shrinks the
/// scroll view, not the text).
struct TalkBubble: View {
    let text: String
    let me: Bool
    let maxWidth: CGFloat

    private var shape: UnevenRoundedRectangle {
        me ? UnevenRoundedRectangle(topLeadingRadius: 20, bottomLeadingRadius: 20, bottomTrailingRadius: 6, topTrailingRadius: 20, style: .continuous)
           : UnevenRoundedRectangle(topLeadingRadius: 20, bottomLeadingRadius: 6, bottomTrailingRadius: 20, topTrailingRadius: 20, style: .continuous)
    }

    var body: some View {
        Text(text)
            .kText(.body)
            .foregroundStyle(KaikuTokens.Colors.ink)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, KaikuTokens.Space.s4)
            .padding(.vertical, KaikuTokens.Space.s3)
            .background(shape.fill(me ? KaikuTokens.Colors.claySoft : KaikuTokens.Colors.surface)
                .shadow(color: KaikuTokens.Colors.ink.opacity(me ? 0 : 0.05), radius: 8, y: 3))
            .overlay(shape.strokeBorder(me ? .clear : KaikuTokens.Colors.line, lineWidth: 1))
            .frame(maxWidth: maxWidth, alignment: me ? .trailing : .leading)
            .frame(maxWidth: .infinity, alignment: me ? .trailing : .leading)
            .textSelection(.enabled)
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
            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { i in
                    Circle().fill(KaikuTokens.Colors.muted)
                        .frame(width: 7, height: 7)
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
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s4) {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                Text(T("talk.welcome.t")).kText(.title3, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                Text(T("talk.welcome.d")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            }
            .padding(KaikuTokens.Space.s5 - 4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                .fill(LinearGradient(colors: [KaikuTokens.Colors.claySoft, KaikuTokens.Colors.honeySoft.opacity(0.6)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing)))
            Text(T("talk.starters")).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.muted)
                .padding(.horizontal, KaikuTokens.Space.s1)
            VStack(spacing: KaikuTokens.Space.s2) {
                ForEach(Self.starters, id: \.1) { icon, key, tone in
                    Button { send(T(key)) } label: {
                        HStack(spacing: KaikuTokens.Space.s3) {
                            RowIcon(symbol: icon, tint: tone.ink, side: 34)
                            Text(T(key)).kText(.body).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Image(systemName: "arrow.up.circle.fill").font(.system(size: 20)).foregroundStyle(tone.ink.opacity(0.8))
                        }
                        .padding(.horizontal, KaikuTokens.Space.s4).padding(.vertical, KaikuTokens.Space.s3)
                        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.surface))
                        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.kPress)
                }
            }
            Text(T("talk.hint")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                .padding(.horizontal, KaikuTokens.Space.s1)
        }
        .padding(.top, KaikuTokens.Space.s3)
    }
}

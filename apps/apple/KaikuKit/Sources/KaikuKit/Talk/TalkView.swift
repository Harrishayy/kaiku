import SwiftUI

/// Talk: bubbles + hold-to-talk Kaiku (30 s ring) + composer. Starts with POST /v1/companion/session
/// {surface: iphone|mac}. With a live_token: Gemini Live (LiveSession), device tools handled here, cloud tools
/// forwarded to /v1/companion/tool. Without one: "Kaiku can talk once it's online" + typed messages that run the
/// local safety gate and get short scripted replies (copy keys; no AI pretending).
@Observable @MainActor
final class TalkModel {
    struct Line: Identifiable, Equatable { let id = UUID(); let text: String; let me: Bool }
    enum Mode: Equatable { case connecting, live, scripted, listening, thinking, speaking, denied, paused }

    var lines: [Line] = []
    var mode: Mode = .connecting
    var holdStart: Date?
    var expression: MascotState?
    var session: CompanionSessionResponse?
    private var live: LiveSession?
    private var capture = AudioCapture()
    private var scriptedIndex = 0
    private var started = Date()
    private var toolsUsed: [String] = []
    weak var app: AppModel?
    // A2: on-device listening (safety gate + spoken dial), interruptions / routes, reconnects.
    private let listener = OnDeviceListener()
    private var audioTokens: [NSObjectProtocol] = []
    private var routeAnnounced = false
    private var userStopped = false
    private var reconnects = 0
    private(set) var lastSpokenDial: Int?

    var hasLive: Bool { live != nil }

    func start(app: AppModel) async {
        self.app = app
        guard session == nil else { return }
        started = Date()
        userStopped = false
        if audioTokens.isEmpty {
            audioTokens = TalkAudio.observe { [weak self] ev in self?.audioEvent(ev) }
            listener.onHit = { [weak self] hit in Task { @MainActor in self?.onDeviceHit(hit) } }
            // Kaiku says hello in its own voice (cached line; on-device synthesizer when not cached / offline).
            VoiceLines.shared.play(Self.greetingKey(), lang: app.language)
        }
        let req = CompanionSessionRequest(surface: KaikuPlatform.surface, home_id: app.pairing?.homeID ?? "",
                                          intent: .talk, language: app.language.rawValue)
        guard app.isPaired, let s = try? await app.api.companionSession(req) else {
            mode = .scripted
            return
        }
        session = s
        guard let token = s.live_token?.token else { mode = .scripted; return }
        let l = LiveSession { [weak self] ev in Task { @MainActor in self?.handle(ev) } }
        live = l
        l.connect(token: token, session: s, language: app.language.rawValue)
    }

    func stop() {
        userStopped = true
        live?.close()
        live = nil
        _ = capture.stop()
        listener.stop()
        audioTokens.forEach(NotificationCenter.default.removeObserver)
        audioTokens = []
        VoiceLines.shared.stop()
        guard let app, let s = session else { return }
        // Close the episode the session opened (no transcript is ever sent).
        let ep = EpisodeIn(id: s.session_id, home_id: app.pairing?.homeID ?? "", surface: KaikuPlatform.surface, intent: .talk,
                           start: KaikuTime.iso(started), end: KaikuTime.iso(Date()),
                           outcome: lines.contains(where: \.me) ? .completed : .skipped, tools_used: toolsUsed)
        Task { _ = try? await app.api.companionEpisode(ep) }
        session = nil
    }

    // MARK: input

    func send(_ raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        lines.append(Line(text: text, me: true))
        if SafetyGate.shared.check(text) != nil { crisis(); return }
        if let live, mode != .scripted {
            live.sendText(text)
            mode = .thinking
        } else {
            scriptedReply()
        }
    }

    func press() async {
        guard mode != .listening else { return }
        switch AudioCapture.permission {
        case .denied: mode = .denied; return
        case .undetermined:
            if !(await AudioCapture.request()) { mode = .denied }
            return
        case .granted: break
        }
        guard let live else { return }
        if !OnDeviceListener.authorized { _ = await OnDeviceListener.requestAuthorization() }
        capture.onPCM = { [weak live] d in live?.sendAudio(d) }
        let listener = listener
        capture.onBuffer = { b in listener.append(b) }
        listener.start(lang: app?.language ?? .en)
        do {
            try capture.start()
            live.activityStart()
            holdStart = Date()
            mode = .listening
        } catch { mode = .denied }
    }

    func release() {
        guard mode == .listening else { return }
        _ = capture.stop()
        capture.onPCM = nil
        capture.onBuffer = nil
        listener.stop()
        live?.activityEnd()
        holdStart = nil
        mode = .thinking
    }

    private func scriptedReply() {
        mode = .thinking
        let keys = ["talk.scripted.1", "talk.scripted.2", "talk.scripted.3"]
        let key = keys[scriptedIndex % keys.count]
        scriptedIndex += 1
        Task {
            try? await Task.sleep(nanoseconds: 900_000_000)
            lines.append(Line(text: T(key), me: false))
            mode = .speaking
            try? await Task.sleep(nanoseconds: 1_400_000_000)
            if mode == .speaking { mode = .scripted }
        }
    }

    private func crisis() {
        userStopped = true
        _ = capture.stop()
        listener.stop()
        VoiceLines.shared.stop()
        live?.close()
        live = nil
        mode = .scripted
        app?.crisis(trigger: "phrase")
    }

    // MARK: live events

    private func handle(_ ev: LiveSession.Event) {
        switch ev {
        case .ready: mode = .live
        case .userText(let t):
            if SafetyGate.shared.check(t) != nil { crisis(); return }
            appendOrExtend(t, me: true)
        case .kaikuText(let t): appendOrExtend(t, me: false); mode = .speaking
        case .speaking(let on): mode = on ? .speaking : (live == nil ? .scripted : .live)
        case .toolCall(let id, let name, let args): Task { await tool(id: id, name: name, args: args) }
        case .closed:
            if live != nil { live = nil; if mode != .scripted { mode = .scripted } }
            reconnect()
        }
    }

    private func appendOrExtend(_ t: String, me: Bool) {
        if let last = lines.last, last.me == me, Date().timeIntervalSince(started) > 0 {
            lines[lines.count - 1] = Line(text: last.text + t, me: me)
        } else {
            lines.append(Line(text: t, me: me))
        }
    }

    private func tool(id: String, name: String, args: [String: JSONValue]) async {
        toolsUsed.append(name)
        guard let app, let s = session else { return }
        if ToolExecutor.isDevice(name) {
            var result: JSONValue = .object(["ok": .bool(true)])
            switch name {
            case "express":
                let f = args["feeling"]?.string ?? "happy"
                expression = ["sleepy": .sleepy, "cozy": .cozy, "curious": .listening, "proud": .cheering][f] ?? .happy
            case "record_dial":
                if let item = args["item"]?.string.flatMap(DialItem.init(rawValue:)), let v = args["value"]?.int ?? lastSpokenDial {
                    await app.emit("obs.self_report", SelfReport(item: item, value: v, channel: KaikuPlatform.channel, context: "adhoc"))
                }
            case "start_activity":
                let kind = args["kind"]?.string ?? ""
                if let r = ["breathe": KaikuRoute.breathe, "firefly": .firefly, "pebbles": .pebbles, "tell": .tell][kind] {
                    app.deepLink = r
                    app.selectedTab = r.tab
                } else { result = .object(["ok": .bool(false), "error": .string("not on this device")]) }
            default:
                result = .object(["ok": .bool(false), "error": .string("not on this device")])
            }
            live?.respond(id: id, name: name, result: result)
            return
        }
        let call = CompanionToolCall(home_id: app.pairing?.homeID ?? "", surface: KaikuPlatform.surface, name: name,
                                     args: args, session_id: s.session_id)
        guard let r = try? await app.api.companionTool(call) else {
            live?.respond(id: id, name: name, result: .object(["ok": .bool(false), "error": .string("offline")]))
            return
        }
        if r.crisis == true { crisis(); return }
        live?.respond(id: id, name: name, result: r.result ?? .object(["ok": .bool(r.ok)]))
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
            if mode == .listening { release() }
            VoiceLines.shared.stop()
            mode = .paused
        case .resumed:
            guard mode == .paused else { return }
            mode = hasLive ? .live : .scripted
            try? TalkAudio.activate()
            let line = T("talk.resumed")
            lines.append(Line(text: line, me: false))
            VoiceLines.shared.say(line, lang: app?.language ?? .en)
        case .routeChanged(let name):
            guard !routeAnnounced, !name.isEmpty else { return }
            routeAnnounced = true
            app?.showToast(T("talk.route", ["name": name]))
        }
    }

    func onDeviceHit(_ hit: OnDeviceListener.Hit) {
        switch hit {
        case .crisis: crisis()
        case .dial(let n): lastSpokenDial = n
        }
    }

    /// Live sessions have time limits: reconnect (twice at most) and say "I'm still here".
    func reconnect() {
        guard !userStopped, reconnects < 2, let app else { return }
        reconnects += 1
        session = nil
        Task {
            await start(app: app)
            if hasLive { lines.append(Line(text: T("talk.still"), me: false)) }
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
    @State private var pressing = false
    @State private var bgTask: Task<Void, Never>?
    @Environment(\.scenePhase) private var phase
    @Environment(\.dynamicTypeSize) private var dts

    public init() {}

    var holdSize: CGFloat { dts.isAccessibilitySize ? 72 : 104 }

    var mascotState: MascotState {
        switch model.mode {
        case .listening: return .listening
        case .thinking, .connecting: return .thinking
        case .speaking: return .speaking
        case .paused: return .sleepy
        default: return model.expression ?? app.ambientState
        }
    }

    public var body: some View {
        KScreen(T("tab.talk"), scrolls: false) {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(spacing: KaikuTokens.Space.s3) {
                        if model.mode == .scripted || model.mode == .denied && !model.hasLive {
                            KCard(tint: KaikuTokens.Colors.skySoft) {
                                Text(T("talk.offline.t")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                                Text(T("talk.offline.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                            }
                        }
                        if model.mode == .denied { MicPermissionCard {} }
                        if model.lines.isEmpty {
                            Text(T("talk.hint")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted)
                                .multilineTextAlignment(.center).wraps().frame(maxWidth: .infinity)
                                .padding(.top, KaikuTokens.Space.s2)
                        }
                        ForEach(model.lines) { l in Bubble(l.text, from: l.me ? .me : .kaiku).id(l.id) }
                        if model.mode == .thinking { TypingIndicator().frame(maxWidth: .infinity, alignment: .leading) }
                    }
                    .padding(.vertical, KaikuTokens.Space.s2)
                }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: model.lines) { _, l in
                    if let last = l.last { withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { proxy.scrollTo(last.id, anchor: .bottom) } }
                }
            }
            .frame(maxHeight: .infinity)
            holdArea
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

    private var holdArea: some View {
        VStack(spacing: KaikuTokens.Space.s1) {
            TimelineView(.animation(minimumInterval: 1.0 / 30, paused: model.mode != .listening)) { tl in
                let p = model.holdStart.map { tl.date.timeIntervalSince($0) / 30 } ?? 0
                ZStack {
                    ProgressRing(progress: p, width: 5).frame(width: holdSize + 14, height: holdSize + 14).opacity(model.hasLive ? 1 : 0)
                    MascotView(state: mascotState, size: holdSize, tappable: !model.hasLive)
                }
                .onChange(of: p >= 1) { _, full in if full { model.release() } }
            }
            .frame(maxWidth: .infinity)
            .contentShape(Circle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard model.hasLive, !pressing else { return }
                        pressing = true
                        Task { await model.press() }
                    }
                    .onEnded { _ in pressing = false; model.release() }
            )
            .accessibilityElement()
            .accessibilityLabel(model.mode == .listening ? T("talk.listening") : T("talk.hold"))
            .accessibilityAddTraits(model.hasLive ? .isButton : [])
            if !statusLine.isEmpty {
                Text(statusLine).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).multilineTextAlignment(.center).wraps()
            }
        }
    }

    private var statusLine: String {
        switch model.mode {
        case .connecting: return T("talk.connecting")
        case .listening: return T("talk.listening")
        case .thinking: return T("talk.thinking")
        case .live, .speaking: return T("talk.hold")
        case .scripted, .denied: return ""   // the hint already sits above the bubbles
        case .paused: return T("talk.paused")
        }
    }
}

/// Mini thinking Kaiku + three soft dots.
struct TypingIndicator: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        HStack(spacing: KaikuTokens.Space.s2) {
            MascotView(state: .thinking, size: 40, tappable: false)
            TimelineView(.animation(minimumInterval: 1.0 / 20, paused: rm)) { tl in
                let t = tl.date.timeIntervalSinceReferenceDate
                HStack(spacing: 5) {
                    ForEach(0..<3, id: \.self) { i in
                        Circle().fill(KaikuTokens.Colors.muted)
                            .frame(width: 7, height: 7)
                            .opacity(rm ? 0.7 : 0.35 + 0.65 * (0.5 + 0.5 * sin(t * 4 - Double(i) * 0.8)))
                    }
                }
            }
            .padding(.horizontal, KaikuTokens.Space.s3)
            .padding(.vertical, KaikuTokens.Space.s3)
            .background(Capsule().fill(KaikuTokens.Colors.surface))
        }
        .accessibilityLabel(T("talk.thinking"))
    }
}

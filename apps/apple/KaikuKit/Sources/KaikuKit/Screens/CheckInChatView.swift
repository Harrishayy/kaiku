import SwiftUI

/// Today's first stop: a small passing chat with Kaiku, not a form. Kaiku says hello (its Live voice when there is
/// one, text always); the person answers out loud, by typing, or just turns the three dials underneath: all three
/// count, and the dials are never a gate. An ordinary day wraps itself up ("Good to see you"); a very good or a
/// very hard day simply goes on (`CheckInState`). While Kaiku is on the line it is a call like Talk: the call
/// bar (mute me, mute Kaiku, type, end) and at most one activity card. iPhone: one column, the dials under the
/// chat. Mac / wide: the chat beside the dials.
public struct CheckInChatView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Environment(\.kaikuStaticLayout) private var staticLayout
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var dts
    @State private var chat = CheckInChat()
    @State private var text = ""
    @State private var typing = false
    @State private var columnWidth: CGFloat = 0
    @State private var bgTask: Task<Void, Never>?

    public init() {}

    private static let bottom = "checkin.bottom"
    private static let top = "checkin.top"

    public var body: some View {
        KScreen(T("checkin.title"), back: { dismiss() }, scrolls: false, maxWidth: KaikuTokens.Size.paneMax,
                spacing: KaikuTokens.Space.s3) {
            WideAware { wide in
                if wide {
                    HStack(alignment: .top, spacing: KaikuTokens.Space.s6) {
                        chatColumn(dialsInside: false).frame(maxWidth: .infinity)
                        Group {
                            if staticLayout { dials(button: true) } else {
                                ScrollView { dials(button: true).padding(.vertical, KaikuTokens.Space.s2) }.scrollBounceBehavior(.basedOnSize)
                            }
                        }
                        .frame(maxWidth: 420)
                    }
                } else {
                    chatColumn(dialsInside: true)
                }
            }
        }
        // A check-in that was left is over. If its screen is still on a stack and comes back, it shows nothing
        // and goes at once (the tab shell also takes it off the stack when the tab is left).
        .opacity(chat.left ? 0 : 1)
        .task {
            guard !staticLayout, !chat.left else { return }
            chat.talk.screenAppeared()
            await chat.start(app: app)
        }
        .onDisappear { chat.leave() }
        // The camera beside the check-in: only while this screen is in front, and only with her choice on.
        .keepsCameraInFront(chat.camera)
        .onChange(of: app.cameraOn) { _, on in Task { await chat.cameraChoiceChanged(on: on) } }
        .onChange(of: chat.talk.hasLive, initial: true) { _, live in typing = live && !chat.talk.conversation.listens }
        .onChange(of: scenePhase) { _, p in
            bgTask?.cancel()
            if p == .background { bgTask = Task { await chat.talk.backgrounded() } }
        }
        .onAppear {
            KSound.warmUp([.tick])
            if chat.left {
                var now = Transaction()
                now.disablesAnimations = true
                withTransaction(now) { dismiss() }
            } else if !staticLayout {
                chat.talk.screenAppeared()
            }
        }
    }

    // MARK: the chat

    private func chatContent(dialsInside: Bool) -> some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            if chat.state.end == nil {
                // She can always see the camera and stop it; a choice made under the older wording is asked once more.
                TaskCameraChip(camera: chat.camera)
                CameraConfirmCard()
            }
            kaiku.id(Self.top)
            if chat.state.end == nil { thread } else { ending }
            Color.clear.frame(height: 1).id(Self.bottom)
            if dialsInside { dials(button: !pinsDialButton) }
        }
        .padding(.vertical, KaikuTokens.Space.s2)
    }

    /// No call on the line (no voice right now, not connected, paused): the dials are the way through this
    /// screen, so "That's it" stays in view under them instead of below the fold, and Kaiku takes less room.
    private var dialsOnly: Bool { chat.state.end == nil && !chat.state.dialsDone && !chat.hasLive && !chat.connecting }
    private var pinsDialButton: Bool { dialsOnly && !staticLayout }
    private var mascotSize: CGFloat { dialsOnly ? KaikuTokens.Size.mascotM * 2 / 3 : KaikuTokens.Size.mascotM }

    @ViewBuilder private func chatColumn(dialsInside: Bool) -> some View {
        if staticLayout {
            // Snapshots (ImageRenderer) cannot draw a ScrollView: the same content, laid out flat.
            VStack(spacing: KaikuTokens.Space.s3) {
                chatContent(dialsInside: dialsInside)
                    .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { w in
                        if abs(w - columnWidth) > 0.5 { columnWidth = w }
                    }
                Spacer(minLength: 0)
                composer
            }
        } else {
            scrollingChat(dialsInside: dialsInside)
        }
    }

    private func scrollingChat(dialsInside: Bool) -> some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            ScrollViewReader { proxy in
                ScrollView { chatContent(dialsInside: dialsInside) }
                .scrollBounceBehavior(.basedOnSize)
                .scrollDismissesKeyboard(.interactively)
                .frame(maxHeight: .infinity)
                .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { w in
                    if abs(w - columnWidth) > 0.5 { columnWidth = w }
                }
                .onChange(of: chat.lines) { _, _ in follow(proxy) }
                .onChange(of: chat.card) { _, _ in follow(proxy) }
                .onChange(of: chat.state.end) { _, end in
                    guard end != nil else { return }
                    withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { proxy.scrollTo(Self.top, anchor: .top) }
                }
                #if os(iOS)
                .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardDidShowNotification)) { _ in
                    proxy.scrollTo(Self.bottom, anchor: .bottom)
                }
                #endif
            }
            composer
            if dialsInside && pinsDialButton { dialButton }
        }
    }

    /// The call bar while Kaiku is on the line (typing stays folded away until wanted).
    @ViewBuilder private var composer: some View {
        if chat.state.end == nil && chat.hasLive {
            if typing {
                Composer(text: $text, placeholder: T("talk.type")) {
                    chat.send(text)
                    text = ""
                }
            }
            CallBar(since: chat.talk.conversation.liveSince, status: chat.talk.status, micOn: chat.micOn,
                    voiceMuted: chat.talk.voiceMuted, typing: typing,
                    level: { [conversation = chat.talk.conversation] in CallStatus.level(db: conversation.level) },
                    toggleMic: micAction,
                    toggleVoice: { chat.talk.toggleVoice() }, toggleTyping: { typing.toggle() }, end: { chat.enough() })
        }
    }

    /// Only while the conversation is short enough to matter: keep the newest line just above the composer.
    private func follow(_ proxy: ScrollViewProxy) {
        guard chat.state.end == nil, !chat.lines.isEmpty else { return }
        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { proxy.scrollTo(Self.bottom, anchor: .bottom) }
    }

    private var bubbleMax: CGFloat {
        let w = columnWidth > 0 ? columnWidth : 600
        return dts.isAccessibilitySize ? w * 0.92 : w * 0.8
    }

    private var mascotState: MascotState {
        if chat.activeDial != nil { return .listening }
        switch chat.state.end {
        case .chat?, .offer?: return .happy
        case .dials(let key)?: return key == "checkin.dials.low" || key == "checkin.dials.tired" ? .cozy : .happy
        case .quiet?: return .cozy
        case nil: break
        }
        switch chat.phase {
        case .connecting, .thinking: return .thinking
        case .hearing: return .listening
        case .speaking: return .speaking
        default: return chat.talk.expression ?? app.ambientState
        }
    }

    /// Kaiku, with one quiet status line (who is listening, or why not).
    private var kaiku: some View {
        VStack(spacing: KaikuTokens.Space.s2) {
            ZStack {
                if chat.micOn { ListeningRing(size: mascotSize + KaikuTokens.Space.s3, active: chat.phase == .hearing || chat.phase == .listening) }
                GlowingMascot(state: mascotState, size: mascotSize,
                              dial: chat.activeDial.map { Double(chat.values[$0] ?? 3) }, tappable: false)
            }
            .frame(height: mascotSize + KaikuTokens.Space.s4)
            .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base), value: mascotSize)
            .accessibilityHidden(true)
            if let status {
                Text(status).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted)
                    .multilineTextAlignment(.center).wraps()
            }
        }
        .frame(maxWidth: .infinity)
    }

    /// Only when Kaiku is not on the line: the one short reason (the call bar says the rest).
    private var status: String? {
        guard chat.state.end == nil, !chat.hasLive else { return nil }
        if chat.connecting { return T("talk.connecting") }
        switch chat.unavailable {
        case .pairing?: return T("call.line.unpaired")
        case .paused?: return T("call.line.paused")
        case nil: return nil
        default: return T("checkin.voiceless")
        }
    }

    /// Kaiku's hello, then the few lines of the chat; the one activity card sits under the latest line.
    @ViewBuilder private var thread: some View {
        let lines = chat.lines
        if lines.first?.me != false {
            Bubble(chat.greeting, maxWidth: bubbleMax)   // Live's own hello takes its place once it is said
        }
        ForEach(lines) { l in
            Bubble(l.text, from: l.me ? .me : .kaiku, maxWidth: bubbleMax,
                   footnote: l.interrupted ? T("talk.interrupted.label") : nil)
                .textSelection(.enabled)
        }
        if chat.talk.mode == .thinking { TypingDots().frame(maxWidth: .infinity, alignment: .leading) }
        if let card = chat.card {
            ActivityCardView(card: card, open: { chat.openCard() }, putAside: { chat.putCardAside() })
        }
    }

    /// The warm end: what Kaiku said last, what may be offered, and the way on. Never a score or a form tick.
    @ViewBuilder private var ending: some View {
        switch chat.state.end {
        case .chat?:
            Text(T("checkin.goodtosee")).kText(.title3, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                .multilineTextAlignment(.center).accessibilityAddTraits(.isHeader)
            if let last = chat.lines.last, !last.me { Bubble(last.text, centered: true) }   // Kaiku's goodbye
        case .dials?:
            if let reply = chat.dialReply { Bubble(reply, big: true, centered: true) }
        case .quiet?:
            Bubble(T("checkin.quiet"), big: true, centered: true)
        case .offer?, nil:
            EmptyView()
        }
        if let card = chat.card {
            ActivityCardView(card: card, open: { chat.openCard() }, putAside: { chat.putCardAside() })
        }
        if chat.state.end != .offer {
            VStack(spacing: KaikuTokens.Space.s1) {
                if chat.state.end != .quiet {
                    if let next = app.nextPathStep {
                        // On the way to the next stop the check-in leaves its stack: it is over, and must not be
                        // found again behind the tab it was on.
                        Button(T("path.upnext", ["name": T(next.titleKey)])) { dismiss(); app.go(next) }
                            .buttonStyle(.kPrimary).keyboardShortcut(.defaultAction)
                    } else {
                        Button(T("checkin.done")) { dismiss() }.buttonStyle(.kPrimary).keyboardShortcut(.defaultAction)
                    }
                }
                if app.isPaired && !app.isPaused {
                    Button(T(chat.state.end == .chat ? "checkin.keeptalking" : "checkin.staytalk")) {
                        Task { await chat.keepTalking() }
                    }
                    .buttonStyle(.kGhost)
                }
            }
            .padding(.top, KaikuTokens.Space.s2)
        }
    }

    private func micAction() {
        if chat.talk.conversation.listens { chat.talk.toggleMic() } else {
            #if os(iOS)
            if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
            #else
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") { openURL(url) }
            #endif
        }
    }

    // MARK: the dials — the quiet alternative, on the same screen

    @ViewBuilder private func dials(button: Bool) -> some View {
        if !chat.state.dialsDone {
            VStack(alignment: .leading, spacing: dialsOnly ? KaikuTokens.Space.s2 : KaikuTokens.Space.s3) {
                Text(T("checkin.dials.t")).kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                    .accessibilityAddTraits(.isHeader)
                ForEach(DialItem.allCases) { item in
                    WeatherDial(item: item, value: binding(item), active: chat.activeDial == item) { chat.activeDial = item }
                }
                if button { dialButton }
            }
            .padding(.top, dialsOnly ? 0 : KaikuTokens.Space.s3)
        }
    }

    /// "That's it": the dials count on their own.
    private var dialButton: some View {
        Button(T("wx.done")) {
            Haptics.finished()
            KSound.play(.done)
            Task { await chat.submitDials() }
        }
        .buttonStyle(KButtonStyle(dialsOnly ? .primary : .secondary))
        .accessibilityIdentifier("checkin.dials.done")
    }

    private func binding(_ item: DialItem) -> Binding<Int> {
        Binding(get: { chat.values[item] ?? 3 }, set: { chat.values[item] = $0; chat.activeDial = item })
    }
}

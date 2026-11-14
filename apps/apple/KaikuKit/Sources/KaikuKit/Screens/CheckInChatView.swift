import SwiftUI

/// Today's first stop: a small passing chat with Kaiku, not a form. Kaiku says hello (its Live voice when there is
/// one, text always); the person answers out loud, by typing, or just turns the three dials underneath: all three
/// count, and the dials are never a gate. An ordinary day wraps itself up ("Good to see you"); a very good or a
/// very hard day simply goes on (`CheckInState`). One soft chip under Kaiku's line when the plan may offer
/// something. iPhone: one column, the dials under the chat. Mac / wide: the chat beside the dials.
public struct CheckInChatView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Environment(\.kaikuStaticLayout) private var staticLayout
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var dts
    @State private var chat = CheckInChat()
    @State private var text = ""
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
                            if staticLayout { dials } else {
                                ScrollView { dials.padding(.vertical, KaikuTokens.Space.s2) }.scrollBounceBehavior(.basedOnSize)
                            }
                        }
                        .frame(maxWidth: 420)
                    }
                } else {
                    chatColumn(dialsInside: true)
                }
            }
        }
        .task { if !staticLayout { await chat.start(app: app) } }
        .onDisappear { chat.leave() }
        .onChange(of: scenePhase) { _, p in
            bgTask?.cancel()
            if p == .background { bgTask = Task { await chat.talk.backgrounded() } }
        }
        .onAppear { KSound.warmUp([.tick]) }
    }

    // MARK: the chat

    private func chatContent(dialsInside: Bool) -> some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            kaiku.id(Self.top)
            if chat.state.end == nil { thread } else { ending }
            Color.clear.frame(height: 1).id(Self.bottom)
            if dialsInside { dials }
        }
        .padding(.vertical, KaikuTokens.Space.s2)
    }

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
                .onChange(of: chat.state.offer) { _, _ in follow(proxy) }
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
        }
    }

    @ViewBuilder private var composer: some View {
        if chat.state.end == nil {
            Composer(text: $text, placeholder: T("talk.type"), mic: micAction, micOn: chat.micOn,
                     micLabel: T(chat.micOn ? "talk.voice.mute" : "talk.voice.start"), micDisabled: chat.connecting) {
                chat.send(text)
                text = ""
            }
            .disabled(chat.connecting)
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
        if chat.state.sittingQuietly && chat.phase != .speaking { return .breathing }
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
                if chat.micOn { ListeningRing(size: KaikuTokens.Size.mascotM + KaikuTokens.Space.s3, active: chat.phase == .hearing) }
                GlowingMascot(state: mascotState, size: KaikuTokens.Size.mascotM,
                              dial: chat.activeDial.map { Double(chat.values[$0] ?? 3) }, tappable: false)
            }
            .frame(height: KaikuTokens.Size.mascotM + KaikuTokens.Space.s4)
            .accessibilityHidden(true)
            if let status {
                Text(status).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted)
                    .multilineTextAlignment(.center).wraps()
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var status: String? {
        guard chat.state.end == nil else { return nil }
        if chat.connecting { return T("talk.connecting") }
        if chat.typedOnly { return T("checkin.typedonly") }
        if chat.micOn { return T("talk.on") }
        if chat.hasLive { return T("talk.tap") }
        switch chat.unavailable {
        case .pairing?: return T("talk.unavailable.pairing")
        case .paused?: return T("you.pauseall.d")
        case nil: return nil
        default: return T("checkin.voiceless")
        }
    }

    /// Kaiku's hello, then the few lines of the chat; the offer chip sits under Kaiku's latest line.
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
        if let offer = chat.state.offer { OfferChip(offer: offer) { chat.takeOffer() } }
        if chat.state.sittingQuietly {
            Text(T("checkin.sitting")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted)
                .frame(maxWidth: .infinity, alignment: .leading).wraps()
        } else if chat.state.staying {
            Text(T("checkin.stay")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted)
                .frame(maxWidth: .infinity, alignment: .leading).wraps()
        }
        if chat.state.personTurns > 0 && chat.hasLive {
            // A calm way out, never a push: it sits quietly under the chat, the same on a long day.
            Button(T("checkin.enough")) { chat.enough() }
                .buttonStyle(KButtonStyle(.ghost, fullWidth: false))
                .frame(maxWidth: .infinity, alignment: .trailing)
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
        if let offer = chat.state.offer { OfferChip(offer: offer, centered: true) { chat.takeOffer() } }
        if chat.state.end != .offer {
            VStack(spacing: KaikuTokens.Space.s1) {
                if chat.state.end != .quiet {
                    if let next = app.nextPathStep {
                        Button(T("path.upnext", ["name": T(next.titleKey)])) { app.go(next) }
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
        if chat.typedOnly || (!chat.hasLive && AudioCapture.permission == .denied) {
            #if os(iOS)
            if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
            #else
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") { openURL(url) }
            #endif
        } else { chat.toggleMic() }
    }

    // MARK: the dials — the quiet alternative, on the same screen

    @ViewBuilder private var dials: some View {
        if !chat.state.dialsDone {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                    Text(T("checkin.dials.t")).kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                        .accessibilityAddTraits(.isHeader)
                    Text(T("checkin.dials.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
                ForEach(DialItem.allCases) { item in
                    WeatherDial(item: item, value: binding(item), active: chat.activeDial == item) { chat.activeDial = item }
                }
                Button(T("wx.done")) {
                    Haptics.finished()
                    KSound.play(.done)
                    Task { await chat.submitDials() }
                }
                .buttonStyle(.kSecondary)
            }
            .padding(.top, KaikuTokens.Space.s3)
        }
    }

    private func binding(_ item: DialItem) -> Binding<Int> {
        Binding(get: { chat.values[item] ?? 3 }, set: { chat.values[item] = $0; chat.activeDial = item })
    }
}

/// One soft offer under Kaiku's line. Taking it starts the activity; leaving it alone is just as fine.
struct OfferChip: View {
    let offer: CheckInOffer
    var centered = false
    let take: () -> Void

    var body: some View {
        Button(action: take) {
            HStack(spacing: KaikuTokens.Space.s2) {
                Image(systemName: offer.icon).foregroundStyle(KTone.sage.ink).accessibilityHidden(true)
                Text(offer.label()).foregroundStyle(KaikuTokens.Colors.ink).multilineTextAlignment(.leading)
            }
            .kText(.callout, weight: .medium)
            .padding(.horizontal, KaikuTokens.Space.s4)
            .padding(.vertical, KaikuTokens.Space.s2)
            .frame(minHeight: KaikuTokens.Size.tapMin)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KTone.sage.soft))
            .contentShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous))
        }
        .buttonStyle(.kPress)
        .accessibilityHint(T("offer.hint"))
        .accessibilityIdentifier("offer.chip")
        .frame(maxWidth: .infinity, alignment: centered ? .center : .leading)
        .transition(.opacity)
    }
}

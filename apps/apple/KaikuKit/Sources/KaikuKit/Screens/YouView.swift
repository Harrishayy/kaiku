import SwiftUI
#if os(iOS)
import UIKit
#endif

/// You: grouped rows (remembers, saw today, voice & language, quiet hours, devices, help) + "Pause everything".
public struct YouView: View {
    @Environment(AppModel.self) private var app
    @State private var confirmUnpair = false
    @State private var showServices = false
    @State private var showSharing = false
    public init() {}

    public var body: some View {
        @Bindable var app = app
        KScreen(T("tab.you"), subtitle: T("you.sub"), maxWidth: KaikuTokens.Size.paneMax) {
            KAdaptiveColumns(minWidth: 600, leadingFraction: 0.5) {
                KSection(T("you.sec.privacy"), icon: "hand.raised.fill", tone: .honey) {
                    KToggleRow(icon: "pause.fill", tint: KaikuTokens.Colors.honey, title: T("you.pauseall"),
                               detail: T("you.pauseall.d"), isOn: $app.pausedAll)
                    KDivider()
                    Button {
                        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { showSharing.toggle() }
                    } label: {
                        KRow(icon: "person.2.fill", tint: KaikuTokens.Colors.honey,
                             title: T(showSharing ? "you.sharing.hide" : "you.sharing"), accessory: showSharing ? .none : .chevron)
                    }
                    .buttonStyle(.kPressRow())
                    if showSharing {
                        ForEach(Signal.forThisDevice, id: \.self) { signal in
                            KDivider()
                            KToggleRow(title: T("sig.\(signal.rawValue).t"), detail: T("sig.\(signal.rawValue).d"),
                                       isOn: Binding(get: { app.consents[signal] ?? false }, set: { app.consents[signal] = $0 }))
                        }
                    }
                }
                KSection(T("you.sec.kaiku"), subtitle: T("you.sec.kaiku.d"), icon: "sparkles", tone: .clay) {
                    link(.memories, "sparkles", KaikuTokens.Colors.clay, "you.remembers")
                    KDivider()
                    link(.saw, "list.bullet.rectangle", KaikuTokens.Colors.sage, "you.saw")
                    KDivider()
                    link(.help, "heart.fill", KaikuTokens.Colors.clay, "you.help")
                }
            } trailing: {
                KSection(T("you.sec.settings"), icon: "slider.horizontal.3", tone: .sky) {
                    link(.voice, "globe", KaikuTokens.Colors.sky, "voice.title")
                    KDivider()
                    link(.quiet, "moon.fill", KaikuTokens.Colors.sky, "you.quiet")
                    KDivider()
                    link(.devices, "dot.radiowaves.left.and.right", KaikuTokens.Colors.honey, "you.devices")
                    if KaikuPlatform.isPhone {
                        KDivider()
                        link(.glasses, "eyeglasses", KaikuTokens.Colors.sage, "gc.title")
                    }
                    KDivider()
                    KToggleRow(icon: "speaker.wave.2.fill", tint: KaikuTokens.Colors.sage, title: T("you.sounds"), isOn: $app.sounds)
                    if app.notificationsOn == false {
                        KDivider()
                        NotificationsOffRow()
                    }
                }
                KSection(T("you.sec.connection"), icon: "link", tone: .sage) {
                    HStack(spacing: 0) {
                        KRow(icon: "link", tint: KaikuTokens.Colors.sage, title: app.isPaired ? T("you.paired") : T("you.notpaired"),
                             detail: app.pairing?.baseURL.host, accessory: .none)
                        if app.isPaired {
                            Button(T("you.unpair.short")) { confirmUnpair = true }
                                .buttonStyle(KButtonStyle(.ghost, fullWidth: false))
                                .fixedSize()
                                .padding(.trailing, KaikuTokens.Space.s1)
                        }
                    }
                    Button(T("service.search")) { showServices = true }.buttonStyle(.kGhost)
                    KDivider()
                    Button { app.restartSetup() } label: {
                        KRow(icon: "arrow.counterclockwise", tint: KaikuTokens.Colors.sage, title: T("setup.again"),
                             detail: T("setup.again.d"))
                    }
                    .buttonStyle(.kPressRow())
                }
            }
        }
        .sheet(isPresented: $showServices) {
            PairStep(back: { showServices = false }, next: { showServices = false }).environment(app)
        }
        .confirmationDialog(T("you.unpair.confirm"), isPresented: $confirmUnpair, titleVisibility: .visible) {
            Button(T("you.unpair"), role: .destructive) {
                Task { await app.unpair(); app.onboarded = false }
            }
            Button(T("common.back"), role: .cancel) {}
        }
    }

    private func link(_ r: KaikuRoute, _ icon: String, _ tint: Color, _ key: String) -> some View {
        NavigationLink(value: r) { KRow(icon: icon, tint: tint, title: T(key)) }.buttonStyle(.kPressRow())
    }
}

/// What Kaiku remembers: list with Delete each, Forget everything, remember on/off. /v1/me/memories.
public struct MemoriesView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var confirmAll = false
    @State private var confirmConversations = false
    @State private var showConversations = false
    public init() {}

    public var body: some View {
        KScreen(T("you.remembers"), back: { dismiss() }) {
            Text(T("mem.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            KSection {
                KToggleRow(title: T("mem.remember.t"), detail: T("mem.remember.d"),
                           isOn: Binding(get: { app.remember }, set: { v in Task { await app.setRemember(v) } }))
            }
            if !app.memoriesLoaded {
                LoadingState()
            } else if app.memories.isEmpty {
                if app.offline { ErrorState { Task { await app.loadMemories() } } } else { EmptyState(T("mem.empty")) }
            } else {
                KSection {
                    ForEach(Array(app.memories.enumerated()), id: \.element.id) { i, m in
                        if i > 0 { KDivider() }
                        HStack(spacing: KaikuTokens.Space.s3) {
                            Text(m.text).kText(.body).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Button(T("mem.delete")) { Task { await app.deleteMemory(m) } }
                                .buttonStyle(KButtonStyle(.secondary, fullWidth: false))
                                .fixedSize()
                        }
                        .padding(.horizontal, KaikuTokens.Space.s4)
                        .padding(.vertical, KaikuTokens.Space.s3)
                    }
                }
                Button(T("mem.forgetall")) { confirmAll = true }.buttonStyle(.kSecondary)
            }
            // Opt-in conversation words (`transcripts` signal): the switch + how many are kept + delete them all.
            KSection {
                KToggleRow(title: T("sig.transcripts.t"), detail: T("sig.transcripts.d"),
                           isOn: Binding(get: { app.consents[.transcripts] ?? false }, set: { app.consents[.transcripts] = $0 }))
            }
            Button(T("conv.read")) { showConversations = true }.buttonStyle(.kSecondary)
            if let n = app.conversationsKept, n > 0 {
                Text(T("conv.kept", n: n)).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                Button(T("conv.forgetall")) { confirmConversations = true }.buttonStyle(.kSecondary)
            }
        }
        .sheet(isPresented: $showConversations) { SavedConversationsView().environment(app) }
        .task { await app.loadMemories(); await app.loadConversations() }
        .confirmationDialog(T("conv.forgetall.confirm"), isPresented: $confirmConversations, titleVisibility: .visible) {
            Button(T("conv.forgetall"), role: .destructive) { Task { await app.forgetConversations() } }
            Button(T("common.back"), role: .cancel) {}
        }
        .confirmationDialog(T("mem.forgetall.confirm"), isPresented: $confirmAll, titleVisibility: .visible) {
            Button(T("mem.forgetall"), role: .destructive) { Task { await app.forgetAll() } }
            Button(T("common.back"), role: .cancel) {}
        }
    }
}

/// What Kaiku saw today: a mono receipt built from today's events for this home (numbers only), one pause switch
/// per signal, "never kept" + "shared as" footers.
public struct SawTodayView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    public init() {}

    struct Line: Identifiable { let id: String; let text: String; let signal: Signal? }

    var lines: [Line] {
        let ev = app.todayEvents
        func of(_ t: String) -> [AnyEnvelope] { ev.filter { $0.type == t } }
        var out: [Line] = []
        let ritual = of("obs.ritual").compactMap { $0.payload["duration_s"]?.double }.reduce(0, +)
        if !of("obs.ritual").isEmpty { out.append(Line(id: "robot", text: T("saw.robot.n", n: max(1, Int((ritual / 60).rounded()))), signal: nil)) }
        let dials = of("obs.self_report").count
        out.append(Line(id: "dial", text: dials > 0 ? T("saw.dial.n", n: dials) : T("saw.dial.none"), signal: .checkins))
        let games = of("obs.play_session").count
        if games > 0 { out.append(Line(id: "games", text: T("saw.games.n", n: games), signal: .checkins)) }
        let walk = of("obs.outing").compactMap { $0.payload["minutes"]?.double }.reduce(0, +)
        out.append(Line(id: "walk", text: walk > 0 ? T("saw.walk.n", n: Int(walk.rounded())) : T("saw.walk.none"), signal: .walks))
        out.append(Line(id: "voice", text: T("saw.voice"), signal: .voice))
        #if os(macOS)
        // The same local aggregate the hourly usage-rhythm numbers come from (numbers + app types only).
        out.append(Line(id: "mac", text: MacUsageStore.shared.receiptLines().joined(separator: "\n"), signal: .mac))
        #else
        out.append(Line(id: "mac", text: T("saw.mac"), signal: .mac))
        #endif
        out.append(Line(id: "watch", text: T("saw.watch"), signal: .watch))
        out.append(Line(id: "transcripts", text: T("saw.transcripts"), signal: .transcripts))
        return out
    }

    public var body: some View {
        KScreen(T("you.saw"), back: { dismiss() }) {
            EvidenceSection()
            Text(T("saw.head")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            KSection {
                ForEach(Array(lines.enumerated()), id: \.element.id) { i, l in
                    if i > 0 { KDivider() }
                    if let sig = l.signal {
                        KToggleRow(title: l.text, detail: app.allowed(sig) ? nil : T("saw.paused"),
                                   isOn: Binding(get: { app.consents[sig] ?? false }, set: { app.consents[sig] = $0 }))
                    } else {
                        KRow(title: l.text, accessory: .none)
                    }
                }
            }
            Text(T("saw.never")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
            Text(T("saw.share")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
        }
        .task { await app.loadToday() }
    }
}

struct DashedLine: View {
    var body: some View {
        Rectangle().fill(.clear).frame(height: 1)
            .overlay(Line().stroke(KaikuTokens.Colors.line, style: StrokeStyle(lineWidth: 1, dash: [4, 4])))
    }
    struct Line: Shape {
        func path(in r: CGRect) -> Path { var p = Path(); p.move(to: CGPoint(x: 0, y: r.midY)); p.addLine(to: CGPoint(x: r.maxX, y: r.midY)); return p }
    }
}

/// Voice and language: language segmented (English · Suomi · Svenska), pace, sample (GET /v1/voice/{key}).
public struct VoiceLanguageView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var player = VoiceSample()
    public init() {}

    public var body: some View {
        @Bindable var app = app
        KScreen(T("voice.title"), back: { dismiss() }) {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                Text(T("voice.lang")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                Text("English").kText(.body)
            }
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                Text(T("voice.pace")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                KSegmented([(VoicePace.slow, T("voice.slow")), (.normal, T("voice.normal"))], selection: $app.pace)
            }
            Button {
                Task { await player.play(api: app.api, lang: app.language.rawValue) { app.showToast(T("voice.sample.none")) } }
            } label: { Label(T("voice.sample"), systemImage: "play.fill") }
            .buttonStyle(.kSecondary)
        }
    }
}

/// Plays one cached line in Kaiku's voice (GET /v1/voice/greet.morning); the cloud says 503 without TTS.
@MainActor
final class VoiceSample {
    private var player: AVAudioPlayerBox?
    func play(api: APIClient, lang: String, unavailable: @escaping () -> Void) async {
        guard let data = await api.voice("greet.morning", lang: lang) else { unavailable(); return }
        player = AVAudioPlayerBox(data)
        player?.play()
    }
}

/// Quiet hours: two time boxes, weekend switch, sleepy Kaiku.
public struct QuietHoursView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    public init() {}
    public var body: some View {
        @Bindable var app = app
        KScreen(T("you.quiet"), back: { dismiss() }) {
            MascotView(state: .sleepy, size: KaikuTokens.Size.mascotM).frame(maxWidth: .infinity)
            Text(T("quiet.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            KSection {
                timeRow(T("quiet.from"), $app.quietFrom)
                KDivider()
                timeRow(T("quiet.to"), $app.quietTo)
                KDivider()
                KToggleRow(title: T("quiet.weekend"), isOn: $app.quietWeekend)
            }
        }
    }

    private func timeRow(_ label: String, _ b: Binding<Date>) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack {
                Text(label).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                Spacer(minLength: KaikuTokens.Space.s3)
                DatePicker(label, selection: b, displayedComponents: .hourAndMinute).labelsHidden().fixedSize()
            }
            VStack(alignment: .leading) {
                Text(label).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                DatePicker(label, selection: b, displayedComponents: .hourAndMinute).labelsHidden().fixedSize()
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(minHeight: KaikuTokens.Size.rowMin)
    }
}

/// Devices: robot, glasses, watch, Mac — connected · connecting · not set up (Set up) · needs attention.
/// Glasses and watch adapters come in later workstreams: they show "Not set up" honestly.
public struct DevicesView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var setupInfo: String?
    public init() {}

    enum Status { case connected, connecting, off, attention, ready }

    var robotStatus: Status {
        // The robot is "connected" when the cloud has heard from this home today (any robot-source event).
        if app.offline { return .connecting }
        return app.todayEvents.contains(where: { ["head", "sensors", "hub"].contains($0.source) }) ? .connected : .off
    }

    public var body: some View {
        KScreen(T("you.devices"), back: { dismiss() }) {
            KSection {
                row("dev.robot", "circle.hexagongrid.fill", app.isPaired ? robotStatus : .off)
                KDivider()
                row("dev.glasses", "eyeglasses", glassesStatus, setup: {
                    // Registration does not open the microphone or begin a walk.
                    if let connect = app.connectGlasses {
                        Task {
                            app.glassesRegistered = await connect()
                            setupInfo = app.glassesRegistered ? T("dev.ready") : T("walk.glasses.setup")
                        }
                    } else { setupInfo = T("walk.glasses.motion.unavailable") }
                })
                KDivider()
                row("dev.watch", "applewatch", watchStatus, setup: { Task { await setUpWatch() } })
                KDivider()
                row("dev.mac", "laptopcomputer", KaikuPlatform.isPhone ? .off : .connected)
            }
            if let setupInfo { OfflineBanner(setupInfo) }
            #if DEBUG
            DebugTools()
            #endif
        }
    }

    var glassesStatus: Status {
        let w = WalkModel.shared
        if w.active {
            switch w.glasses {
            case .connected: return .connected
            case .searching: return .connecting
            case .batteryLow, .disconnected, .registrationRequired, .motionUnavailable: return .attention
            case .off: return .off
            }
        }
        return app.glassesRegistered ? .ready : .off
    }

    var watchStatus: Status {
        switch app.healthState {
        case .connected: return .connected
        case .denied: return .attention
        case .off, .unavailable: return app.allowed(.watch) ? .ready : .off
        }
    }

    private func setUpWatch() async {
        #if os(iOS)
        app.consents[.watch] = true
        if await HealthSync.shared.authorize() {
            await HealthSync.shared.sync(app: app)
            if app.healthState != .connected { setupInfo = T("dev.watch.nodata") }
        } else {
            app.healthState = .denied
        }
        #else
        setupInfo = T("dev.setup.later")
        #endif
    }

    private func row(_ key: String, _ icon: String, _ s: Status, setup: (() -> Void)? = nil) -> some View {
        HStack(spacing: KaikuTokens.Space.s3) {
            RowIcon(symbol: icon, tint: s == .connected ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted)
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                Text(T(key)).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                HStack(spacing: KaikuTokens.Space.s2) {
                    Circle().fill(color(s)).frame(width: KaikuTokens.Space.s2, height: KaikuTokens.Space.s2)
                    Text(label(s)).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if s == .off {
                Button(T("dev.setup")) { if let setup { setup() } else { setupInfo = T("dev.setup.later") } }
                    .buttonStyle(KButtonStyle(.secondary, fullWidth: false))
                    .fixedSize()
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(minHeight: KaikuTokens.Size.rowMin)
        .accessibilityElement(children: .combine)
    }

    private func label(_ s: Status) -> String {
        switch s {
        case .connected: return T("dev.connected")
        case .connecting: return T("dev.connecting")
        case .off: return T("dev.off")
        case .attention: return T("dev.attn")
        case .ready: return T("dev.ready")
        }
    }

    private func color(_ s: Status) -> Color {
        switch s {
        case .connected: return KaikuTokens.Colors.sage
        case .connecting: return KaikuTokens.Colors.honey
        case .off: return KaikuTokens.Colors.line
        case .attention: return KaikuTokens.Colors.honey
        case .ready: return KaikuTokens.Colors.sage
        }
    }
}

/// Help and crisis contacts: body + three call buttons.
public struct HelpView: View {
    @Environment(\.dismiss) private var dismiss
    public init() {}
    public var body: some View {
        KScreen(T("you.help"), back: { dismiss() }) {
            Text(T("help.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            CallButtons(style: .secondary)
        }
    }
}

/// MIELI, 112, care team. Phone numbers come from copy (help.*.d) — tel: links where the device can call.
struct CallButtons: View {
    let style: KButtonKind
    @Environment(\.openURL) private var openURL
    @Environment(AppModel.self) private var app
    var body: some View {
        VStack(spacing: KaikuTokens.Space.s3) {
            call(T("help.mieli"), T("help.mieli.d"), "tel:0925250111")
            call(T("help.112"), T("help.112.d"), "tel:112")
            Text(T("crisis.delivery.contact")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
        }
    }

    private func call(_ title: String, _ detail: String, _ url: String?) -> some View {
        Button {
            if let url, let u = URL(string: url) { openURL(u) } else { app.showToast(T("help.team.toast")) }
        } label: {
            VStack(spacing: KaikuTokens.Space.s1) {
                Text(title)
                Text(detail).kText(.footnote).opacity(0.85)
            }
        }
        .buttonStyle(KButtonStyle(style))
    }
}

/// "Notifications are off" + a link to Settings (the app works fully without them).
struct NotificationsOffRow: View {
    @Environment(\.openURL) private var openURL
    var body: some View {
        Button {
            #if os(iOS)
            if let u = URL(string: UIApplication.openNotificationSettingsURLString) { openURL(u) }
            #endif
        } label: {
            KRow(icon: "bell.slash", tint: KaikuTokens.Colors.muted, title: T("you.notif.off"), detail: T("you.notif.off.d"))
        }
        .buttonStyle(.plain)
    }
}

#if DEBUG
/// Debug builds only: make the A2 paths demo-able in the simulator.
struct DebugTools: View {
    @Environment(AppModel.self) private var app
    @State private var note: String?
    var body: some View {
        KSection(T("debug.title")) {
            #if os(iOS)
            Button {
                Task {
                    app.consents[.watch] = true
                    let ok = await HealthSync.shared.addSampleData()
                    if ok { await HealthSync.shared.sync(app: app) }
                    note = ok ? T("debug.done") : T("debug.failed")
                }
            } label: { KRow(icon: "heart.text.square", tint: KaikuTokens.Colors.clay, title: T("debug.health"), accessory: .none) }
            .buttonStyle(.plain)
            KDivider()
            #endif
            Button { Task { await Notifier.shared.fireTest(.checkin, app: app); note = T("debug.done") } } label: {
                KRow(icon: "bell", tint: KaikuTokens.Colors.honey, title: T("debug.notif.checkin"), accessory: .none)
            }
            .buttonStyle(.plain)
            KDivider()
            Button { Task { await Notifier.shared.fireTest(.invitation, app: app); note = T("debug.done") } } label: {
                KRow(icon: "bell.badge", tint: KaikuTokens.Colors.honey, title: T("debug.notif.invite"), accessory: .none)
            }
            .buttonStyle(.plain)
        }
        if let note { Text(note).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
    }
}
#endif

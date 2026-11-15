import SwiftUI
#if os(iOS)
import UIKit
#endif

/// Layout pictures of the You page with one of its parts open (DEBUG: `-kaikuYouOpen sharing|service|quicktalk`).
enum YouDebug {
    static func opens(_ part: String) -> Bool {
        #if DEBUG
        return UserDefaults.standard.string(forKey: "kaikuYouOpen") == part
        #else
        return false
        #endif
    }
}

extension Signal {
    /// The signal's symbol in a list of choices.
    var symbol: String {
        switch self {
        case .checkins: return "checklist"
        case .walks: return "figure.walk"
        case .voice: return "waveform"
        case .camera: return "camera"
        case .mac: return "laptopcomputer"
        case .watch: return "applewatch"
        case .transcripts: return "text.bubble"
        case .see: return "eyeglasses"
        }
    }
    /// One short line for a row: the signal's own line, or its short form where the full text is a paragraph
    /// (`sig.<x>.s`; the paragraph is then shown in full under the list, `SharingInFull`).
    var lineKey: String { hasShortForm ? "sig.\(rawValue).s" : "sig.\(rawValue).d" }
    var hasShortForm: Bool { L10n.shared.has("sig.\(rawValue).s", .en) }
    /// The whole text of the choice, as setup and "In full" show it: `sig.<x>.d`, or `sig.<x>.full` where this app
    /// has to say more than the shared line does (the Watch choice names every kind of Apple Health data it reads).
    var wholeKey: String { L10n.shared.has("sig.\(rawValue).full", .en) ? "sig.\(rawValue).full" : "sig.\(rawValue).d" }
}

/// You: four short sections of rows. A row is an icon, a short title, at most one short line and ONE control: a
/// switch, or a link to the screen (chevron) or sheet that holds the rest. Two columns on the Mac pane, where the
/// whole page fits the default window; one column on the phone.
public struct YouView: View {
    @Environment(AppModel.self) private var app
    @State private var showSharing = YouDebug.opens("sharing")
    @State private var showService = YouDebug.opens("service")
    public init() {}

    public var body: some View {
        @Bindable var app = app
        ScrollViewReader { proxy in
        KScreen(T("tab.you"), subtitle: T("you.sub"), maxWidth: KaikuTokens.Size.paneMax) {
            KAdaptiveColumns(minWidth: 600, leadingFraction: 0.5, stack: KaikuTokens.Space.s5) {
                KSection(T("you.sec.privacy"), icon: "hand.raised.fill", tone: .honey) {
                    KToggleRow(icon: "pause.fill", tint: KaikuTokens.Colors.honey, title: T("you.pauseall"),
                               detail: T("you.pauseall.s"), isOn: $app.pausedAll)
                    KDivider()
                    sharingRow
                    if showSharing && KaikuPlatform.isPhone {   // the phone opens the choices in place; the Mac in a sheet
                        KDivider()
                        SharingRows()
                        SharingInFull().padding(KaikuTokens.Space.s4)
                    }
                    KDivider()
                    link(.saw, "list.bullet.rectangle", KaikuTokens.Colors.sage, "you.saw")
                }
                KSection(T("you.sec.kaiku"), icon: "sparkles", tone: .clay) {
                    link(.memories, "sparkles", KaikuTokens.Colors.clay, "you.remembers")
                    KDivider()
                    link(.help, "heart.fill", KaikuTokens.Colors.clay, "you.help")
                    KDivider()
                    // "Your choices and connection stay as they are": a line on the phone; in the Mac's half-width
                    // column it wraps and pushes the page past the window, so there it is the row's tooltip.
                    Button { app.restartSetup() } label: {
                        KRow(icon: "arrow.counterclockwise", tint: KaikuTokens.Colors.clay, title: T("setup.again"),
                             detail: KaikuPlatform.isPhone ? T("setup.again.d") : nil)
                    }
                    .buttonStyle(.kPressRow())
                    #if os(macOS)
                    .help(T("setup.again.d"))
                    #endif
                }
            } trailing: {
                KSection(T("you.sec.settings"), icon: "slider.horizontal.3", tone: .sky) {
                    link(.voice, "globe", KaikuTokens.Colors.sky, "voice.title")
                    KDivider()
                    link(.quiet, "moon.fill", KaikuTokens.Colors.sky, "you.quiet")
                    if KaikuPlatform.isPhone {
                        KDivider()
                        link(.glasses, "eyeglasses", KaikuTokens.Colors.sage, "gc.title")
                        KDivider()
                        WalkStyleSetting()   // Calm · Playful · Chatty (Walk/WalkView.swift)
                    }
                    #if os(macOS)
                    KDivider()
                    QuickTalkSettingsRow()   // Mac only: talk from any app (KaikuKit/Mac/QuickTalkView.swift)
                    #endif
                    KDivider()
                    KToggleRow(icon: "speaker.wave.2.fill", tint: KaikuTokens.Colors.sage, title: T("you.sounds"), isOn: $app.sounds)
                    if app.notificationsOn == false {
                        KDivider()
                        NotificationsOffRow()
                    }
                }
                KSection(T("you.sec.devices"), icon: "link", tone: .sage) {
                    if KaikuPlatform.isPhone {   // (`.id("devices")`: `-kaikuYouScroll devices` in DEBUG pictures)   // on the Mac Kaiku bot is a tab of its own
                        NavigationLink(value: KaikuRoute.bot) {
                            KRow(icon: KaikuTab.bot.symbol, tint: KaikuTokens.Colors.honey, title: T("tab.bot"), detail: T("bot.row.d"))
                        }
                        .buttonStyle(.kPressRow())
                        .accessibilityIdentifier("you.bot")
                        KDivider()
                    }
                    link(.devices, "dot.radiowaves.left.and.right", KaikuTokens.Colors.honey, "you.devices")
                    KDivider()
                    Button { showService = true } label: {
                        KRow(icon: "link", tint: app.isPaired ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted, title: T("you.service"),
                             detail: app.isPaired ? T("you.service.host", ["host": app.pairing?.baseURL.host ?? ""]) : T("you.notpaired"))
                    }
                    .buttonStyle(.kPressRow())
                }
                .id("devices")
            }
        }
        #if DEBUG
        .task {   // `-kaikuYouScroll devices`: a picture of the end of You on a small iPhone
            guard let to = UserDefaults.standard.string(forKey: "kaikuYouScroll") else { return }
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            proxy.scrollTo(to, anchor: .top)
        }
        #endif
        }
        .sheet(isPresented: $showService) { ServiceSheet().environment(app) }
        #if os(macOS)
        .sheet(isPresented: $showSharing) { SharingSheet().environment(app) }
        #endif
    }

    /// "Sharing and permissions": how many are on, at a glance; the choices themselves one step away.
    private var sharingRow: some View {
        let open = showSharing && KaikuPlatform.isPhone
        let all = Signal.forThisDevice
        let count = T("share.count", ["n": "\(all.filter { app.consents[$0] ?? false }.count)", "m": "\(all.count)"])
        return Button {
            if KaikuPlatform.isPhone {
                withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { showSharing.toggle() }
                // Her choices are in front of her: if "Watch" is on and this build reads kinds of Apple Health
                // data that iOS has not asked her about yet, iOS asks now.
                if showSharing { Task { await HealthAccess.review(app: app) } }
            } else {
                showSharing = true
            }
        } label: {
            KRow(icon: "person.2.fill", tint: KaikuTokens.Colors.honey, title: T(open ? "you.sharing.hide" : "you.sharing"),
                 detail: count, accessory: open ? .none : .chevron)
        }
        .buttonStyle(.kPressRow())
        .accessibilityLabel(T(open ? "you.sharing.hide" : "you.sharing"))
        .accessibilityValue(count)
    }

    private func link(_ r: KaikuRoute, _ icon: String, _ tint: Color, _ key: String) -> some View {
        NavigationLink(value: r) { KRow(icon: icon, tint: tint, title: T(key)) }.buttonStyle(.kPressRow())
    }
}

/// The sharing choices as a list to take in at a glance: one row a signal, its tile green while it is on and
/// grey while it is off, the title, one short line on what it is, and its switch. Every signal of this device,
/// in the same order and with the same meaning as at setup; nothing is switched by showing them.
struct SharingRows: View {
    @Environment(AppModel.self) private var app
    var body: some View {
        ForEach(Array(Signal.forThisDevice.enumerated()), id: \.element) { i, signal in
            if i > 0 { KDivider() }
            let on = app.consents[signal] ?? false
            KToggleRow(icon: signal.symbol, tint: on ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted,
                       title: T("sig.\(signal.rawValue).t"), detail: T(signal.lineKey),
                       isOn: app.choiceBinding(signal))   // the whole text of each choice stands under this list
                // "Watch" switched on here: iOS asks for Apple Health now, with the choice's text on screen.
                .onChange(of: on) { _, now in if signal == .watch, now { Task { await HealthAccess.review(app: app) } } }
        }
    }
}

/// The whole text of every choice whose row shows a short form: consent text is never cut, it is here in full.
struct SharingInFull: View {
    var signals: [Signal] = Signal.forThisDevice
    var body: some View {
        let long = signals.filter(\.hasShortForm)
        if !long.isEmpty {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
                Text(T("share.full")).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink2)
                    .accessibilityAddTraits(.isHeader)
                ForEach(long, id: \.self) { signal in
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                        Text(T("sig.\(signal.rawValue).t")).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                        Text(T(signal.wholeKey)).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// Sharing and permissions on the Mac: the choices in a sheet (the two-column page has no room to open them in place).
struct SharingSheet: View {
    var body: some View {
        KSheet(T("you.sharing"), width: KaikuTokens.Size.contentMax) {
            Text(T("share.sub")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            KSection { SharingRows() }
            SharingInFull()
        }
    }
}

/// The Kaiku service this device talks to: where it is connected, looking for another one nearby, unpairing.
struct ServiceSheet: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var confirmUnpair = false
    @State private var showServices = false
    var body: some View {
        KSheet(T("you.sec.connection"), height: 300) {
            KSection {
                KRow(icon: "link", tint: app.isPaired ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted,
                     title: app.isPaired ? T("you.paired") : T("you.notpaired"), detail: app.pairing?.baseURL.host,
                     accessory: app.isPaired ? .check : .none)
                KDivider()
                Button { showServices = true } label: {
                    KRow(icon: "magnifyingglass", tint: KaikuTokens.Colors.sage, title: T("service.search"))
                }
                .buttonStyle(.kPressRow())
                if app.isPaired {
                    KDivider()
                    Button { confirmUnpair = true } label: {
                        KRow(icon: "xmark.circle", tint: KaikuTokens.Colors.clay, title: T("you.unpair"), accessory: .none)
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
                dismiss()
            }
            Button(T("common.back"), role: .cancel) {}
        }
    }
}

/// What Kaiku remembers: list with Delete each, Forget everything, remember on/off. /v1/me/memories.
public struct MemoriesView: View {
    /// Full width on the phone; as wide as its words on the Mac (a button across the whole pane is a phone layout).
    static var button: KButtonStyle { KButtonStyle(.secondary, fullWidth: KaikuPlatform.isPhone) }

    @ViewBuilder private var conversationButtons: some View {
        Button(T("conv.read")) { showConversations = true }.buttonStyle(Self.button)
        if let n = app.conversationsKept, n > 0 {
            Button(T("conv.forgetall")) { confirmConversations = true }.buttonStyle(Self.button)
        }
    }

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
                KToggleRow(icon: "sparkles", tint: app.remember ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted,
                           title: T("mem.remember.t"), detail: T("mem.remember.d"),
                           isOn: Binding(get: { app.remember }, set: { v in Task { await app.setRemember(v) } }))
            }
            if !app.memoriesLoaded {
                LoadingState()
            } else if app.memories.isEmpty {
                if app.offline { ErrorState { Task { await app.loadMemories() } } } else { EmptyState(T("mem.empty")) }
            } else {
                KSection {
                    ForEach(Array(app.memories.enumerated()), id: \.element.id) { i, m in
                        if i > 0 { KDivider(plain: true) }
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
                Button(T("mem.forgetall")) { confirmAll = true }.buttonStyle(Self.button)
            }
            // Opt-in conversation words (`transcripts` signal), one group: the switch (its line says how many are
            // kept), the whole consent text under the card, then the ways to read or delete them.
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
                KSection {
                    let on = app.consents[.transcripts] ?? false
                    let kept = app.conversationsKept ?? 0
                    KToggleRow(icon: Signal.transcripts.symbol, tint: on ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted,
                               title: T("sig.transcripts.t"), detail: kept > 0 ? T("conv.kept", n: kept) : nil,
                               isOn: Binding(get: { app.consents[.transcripts] ?? false }, set: { app.consents[.transcripts] = $0 }))
                }
                Text(T("sig.transcripts.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: KaikuTokens.Space.s3) { conversationButtons }
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) { conversationButtons }
                }
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

    /// One row a signal: what was noticed for it today, line by line (the robot's line has no switch of its own).
    struct Row: Identifiable { let id: String; let signal: Signal?; var texts: [String] }
    var rows: [Row] {
        var out: [Row] = []
        for l in lines {
            if let sig = l.signal, let i = out.firstIndex(where: { $0.signal == sig }) { out[i].texts.append(l.text) }
            else { out.append(Row(id: l.signal?.rawValue ?? l.id, signal: l.signal, texts: [l.text])) }
        }
        return out
    }

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
        // Face signs during games and the check-in: how many activities had the camera on (numbers, never pictures).
        let seen = DayEvidence.cameraTasks(events: ev, sent: app.cameraChoice.sentToday())
        out.append(Line(id: "camera", text: seen.map { T("saw.camera.n", n: $0.count) } ?? T("saw.camera.none"), signal: .camera))
        #if os(macOS)
        // The same local aggregate the hourly usage-rhythm numbers come from (numbers + app types only).
        out.append(Line(id: "mac", text: MacUsageStore.shared.receiptLines().joined(separator: "\n"), signal: .mac))
        #else
        out.append(Line(id: "mac", text: T("saw.mac"), signal: .mac))
        #endif
        // Which kinds of numbers today's Apple Health summary held (named here; the numbers are in History).
        let health = DayEvidence.healthNames(ev)
        out.append(Line(id: "watch", text: health.isEmpty ? T("saw.watch.none") : T("saw.watch.read", ["list": health.joined(separator: ", ")]),
                        signal: .watch))
        out.append(Line(id: "transcripts", text: T("saw.transcripts"), signal: .transcripts))
        return out
    }

    public var body: some View {
        KScreen(T("you.saw"), back: { dismiss() }) {
            EvidenceSection()
            Text(T("saw.head")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            KSection {
                ForEach(Array(rows.enumerated()), id: \.element.id) { i, row in
                    if i > 0 { KDivider() }
                    if let sig = row.signal {
                        let on = app.allowed(sig)
                        KToggleRow(icon: sig.symbol, tint: on ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted,
                                   title: T("sig.\(sig.rawValue).t"), detail: on ? row.texts.joined(separator: "\n") : T("saw.paused"),
                                   isOn: Binding(get: { app.consents[sig] ?? false }, set: { app.consents[sig] = $0 }))
                            .onChange(of: app.consents[sig] ?? false) { _, now in
                                if sig == .watch, now { Task { await HealthAccess.review(app: app) } }   // iOS asks for Apple Health now
                            }
                    } else {
                        KRow(icon: "circle.hexagongrid.fill", tint: KaikuTokens.Colors.sage, title: T("dev.robot"),
                             detail: row.texts.joined(separator: "\n"), accessory: .none)
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
    @State private var kaikuMuted = Conversation.voiceMutedSaved
    public init() {}

    /// One choice for every place Kaiku speaks: saved, and applied at once to a conversation that is open.
    private var muteKaiku: Binding<Bool> {
        Binding(get: { kaikuMuted }, set: { on in
            kaikuMuted = on
            UserDefaults.standard.set(on, forKey: Conversation.voiceMutedKey)
            TalkModel.active?.conversation.setVoiceMuted(on)
            WalkModel.shared.companion?.setVoiceMuted(on)
        })
    }

    public var body: some View {
        @Bindable var app = app
        KScreen(T("voice.title"), back: { dismiss() }) {
            KSection {
                KToggleRow(icon: "speaker.slash.fill", tint: KaikuTokens.Colors.sky, title: T("call.mute.kaiku"),
                           detail: T("voice.mute.d"), isOn: muteKaiku)
                    .accessibilityIdentifier("voice.mute")
                KDivider()
                KRow(icon: "globe", tint: KaikuTokens.Colors.sky, title: T("voice.lang"), accessory: .value("English"))
                KDivider()
                HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
                    RowIcon(symbol: "metronome", tint: KaikuTokens.Colors.sky)
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                        Text(T("voice.pace")).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                        KSegmented([(VoicePace.slow, T("voice.slow")), (.normal, T("voice.normal"))], selection: $app.pace)
                    }
                }
                .padding(.horizontal, KaikuTokens.Space.s4)
                .padding(.vertical, KaikuTokens.Space.s3)
            }
            Button {
                Task { await player.play(api: app.api, lang: app.language.rawValue) { app.showToast(T("voice.sample.none")) } }
            } label: { Label(T("voice.sample"), systemImage: "play.fill") }
            .buttonStyle(MemoriesView.button)
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
                KDivider(plain: true)
                timeRow(T("quiet.to"), $app.quietTo)
                KDivider(plain: true)
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

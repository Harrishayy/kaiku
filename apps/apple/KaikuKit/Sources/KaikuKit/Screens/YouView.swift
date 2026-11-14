import SwiftUI

/// You: grouped rows (remembers, saw today, voice & language, quiet hours, devices, help) + "Pause everything".
public struct YouView: View {
    @Environment(AppModel.self) private var app
    @State private var confirmUnpair = false
    public init() {}

    public var body: some View {
        @Bindable var app = app
        KScreen(T("tab.you")) {
            KSection {
                KToggleRow(icon: "pause.circle.fill", title: T("you.pauseall"), detail: T("you.pauseall.d"), isOn: $app.pausedAll)
            }
            KSection {
                link(.memories, "brain.head.profile", KaikuTokens.Colors.clay, "you.remembers")
                KDivider()
                link(.saw, "list.bullet.rectangle", KaikuTokens.Colors.sage, "you.saw")
            }
            KSection {
                link(.voice, "globe", KaikuTokens.Colors.sky, "you.voice")
                KDivider()
                link(.quiet, "moon.fill", KaikuTokens.Colors.sky, "you.quiet")
                KDivider()
                link(.devices, "dot.radiowaves.left.and.right", KaikuTokens.Colors.honey, "you.devices")
            }
            KSection {
                link(.help, "heart.fill", KaikuTokens.Colors.clay, "you.help")
            }
            KSection {
                KRow(icon: "link", tint: KaikuTokens.Colors.sage, title: app.isPaired ? T("you.paired") : T("you.notpaired"),
                     detail: app.queued > 0 ? T("you.queued", n: app.queued) : nil, accessory: .none)
                if app.isPaired {
                    KDivider()
                    Button { confirmUnpair = true } label: {
                        KRow(title: T("you.unpair"), accessory: .none)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .confirmationDialog(T("you.unpair.confirm"), isPresented: $confirmUnpair, titleVisibility: .visible) {
            Button(T("you.unpair"), role: .destructive) {
                Task { await app.unpair(); app.onboarded = false }
            }
            Button(T("common.back"), role: .cancel) {}
        }
    }

    private func link(_ r: KaikuRoute, _ icon: String, _ tint: Color, _ key: String) -> some View {
        NavigationLink(value: r) { KRow(icon: icon, tint: tint, title: T(key)) }.buttonStyle(.plain)
    }
}

/// What Kaiku remembers: list with Delete each, Forget everything, remember on/off. /v1/me/memories.
public struct MemoriesView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var confirmAll = false
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
        }
        .task { await app.loadMemories() }
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
        out.append(Line(id: "mac", text: T("saw.mac"), signal: .mac))
        out.append(Line(id: "watch", text: T("saw.watch"), signal: .watch))
        return out
    }

    public var body: some View {
        KScreen(T("you.saw"), back: { dismiss() }) {
            Text(T("saw.head")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(lines.enumerated()), id: \.element.id) { i, l in
                    if i > 0 { DashedLine() }
                    HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(l.text).kText(.footnote, mono: true).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                            if let s = l.signal, !app.allowed(s) {
                                Text(T("saw.paused")).kText(.caption, mono: true).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        if let s = l.signal {
                            Toggle(isOn: Binding(get: { app.consents[s] ?? false }, set: { app.consents[s] = $0 })) { EmptyView() }
                                .labelsHidden()
                                .toggleStyle(.switch)
                                .tint(KaikuTokens.Colors.sage)
                                .accessibilityLabel(T("sig.\(s.rawValue).t"))
                        }
                    }
                    .padding(.vertical, KaikuTokens.Space.s3)
                }
            }
            .padding(.horizontal, KaikuTokens.Space.s4)
            .padding(.vertical, KaikuTokens.Space.s2)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.surface))
            .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).strokeBorder(KaikuTokens.Colors.line))
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
        KScreen(T("you.voice"), back: { dismiss() }) {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                Text(T("voice.lang")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                KSegmented(KaikuLanguage.allCases.map { ($0, $0.endonym) }, selection: $app.language)
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
            MascotView(state: .sleepy, size: 140).frame(maxWidth: .infinity)
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
        .frame(minHeight: 56)
    }
}

/// Devices: robot, glasses, watch, Mac — connected · connecting · not set up (Set up) · needs attention.
/// Glasses and watch adapters come in later workstreams: they show "Not set up" honestly.
public struct DevicesView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var setupInfo: String?
    public init() {}

    enum Status { case connected, connecting, off, attention }

    var robotStatus: Status {
        // The robot is "connected" when the cloud has heard from this home today (any robot-source event).
        if app.offline { return .connecting }
        return app.todayEvents.contains(where: { ["head", "sensors", "hub"].contains($0.source) }) || app.me != nil ? .connected : .off
    }

    public var body: some View {
        KScreen(T("you.devices"), back: { dismiss() }) {
            KSection {
                row("dev.robot", "circle.hexagongrid.fill", app.isPaired ? robotStatus : .off)
                KDivider()
                row("dev.glasses", "eyeglasses", .off)
                KDivider()
                row("dev.watch", "applewatch", .off)
                KDivider()
                row("dev.mac", "laptopcomputer", KaikuPlatform.isPhone ? .off : .connected)
            }
            if let setupInfo { OfflineBanner(setupInfo) }
        }
    }

    private func row(_ key: String, _ icon: String, _ s: Status) -> some View {
        HStack(spacing: KaikuTokens.Space.s3) {
            RowIcon(symbol: icon, tint: s == .connected ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted)
            VStack(alignment: .leading, spacing: 2) {
                Text(T(key)).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                HStack(spacing: 6) {
                    Circle().fill(color(s)).frame(width: 8, height: 8)
                    Text(label(s)).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if s == .off {
                Button(T("dev.setup")) { setupInfo = T("dev.setup.later") }
                    .buttonStyle(KButtonStyle(.secondary, fullWidth: false))
                    .fixedSize()
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(minHeight: 64)
        .accessibilityElement(children: .combine)
    }

    private func label(_ s: Status) -> String {
        switch s {
        case .connected: return T("dev.connected")
        case .connecting: return T("dev.connecting")
        case .off: return T("dev.off")
        case .attention: return T("dev.attn")
        }
    }

    private func color(_ s: Status) -> Color {
        switch s {
        case .connected: return KaikuTokens.Colors.sage
        case .connecting: return KaikuTokens.Colors.honey
        case .off: return KaikuTokens.Colors.line
        case .attention: return KaikuTokens.Colors.honey
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
            call(T("help.team"), T("help.team.d"), nil)
        }
    }

    private func call(_ title: String, _ detail: String, _ url: String?) -> some View {
        Button {
            if let url, let u = URL(string: url) { openURL(u) } else { app.showToast(T("help.team.toast")) }
        } label: {
            VStack(spacing: 2) {
                Text(title)
                Text(detail).kText(.footnote).opacity(0.85)
            }
        }
        .buttonStyle(KButtonStyle(style))
    }
}

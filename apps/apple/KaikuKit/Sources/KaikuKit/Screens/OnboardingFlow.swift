import SwiftUI
import UserNotifications

/// First-run setup (`SetupStep`): welcome → what Kaiku is and isn't → connect → choices → permissions → first
/// hello in Kaiku's voice + one tiny task with a celebration → Today. No tab bar; Help is one tap away on every
/// step. The step is saved (`AppModel.setupStep`), so setup resumes where it was left; You → "Run setup again"
/// starts it over. Permissions are only requested from their own row, never on arrival.
struct OnboardingFlow: View {
    @Environment(AppModel.self) private var app
    @State private var help = false

    private var step: SetupStep { SetupStep(rawValue: app.setupStep) ?? .welcome }

    var body: some View {
        Group {
            switch step {
            case .welcome: WelcomeStep { go(.about) }
            case .about: AboutStep(back: { go(.welcome) }) { go(.connect) }
            case .connect: PairStep(back: { go(.about) }, step: .connect) { go(.choices) }
            case .choices: ConsentStep(back: { go(.connect) }) { go(.permissions) }
            case .permissions: PermissionsStep(back: { go(.choices) }) { go(.hello) }
            case .hello: HelloStep(back: { go(.permissions) }) { app.finishSetup() }
            }
        }
        .environment(\.onboardingHelp, OnboardingHelp { help = true })
        .sheet(isPresented: $help) {
            NavigationStack { HelpView() }
                #if os(macOS)
                .frame(minWidth: 480, minHeight: 520)
                #endif
        }
    }

    private func go(_ s: SetupStep) {
        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base)) { app.setupStep = s.rawValue }
    }
}

/// Shared onboarding page: content scrolls, the primary action sits at the bottom.
struct OnboardingHelp { let open: () -> Void }

private struct OnboardingHelpKey: EnvironmentKey { static let defaultValue: OnboardingHelp? = nil }
extension EnvironmentValues {
    var onboardingHelp: OnboardingHelp? {
        get { self[OnboardingHelpKey.self] }
        set { self[OnboardingHelpKey.self] = newValue }
    }
}

struct OnbPage<Content: View, Actions: View>: View {
    let back: (() -> Void)?
    /// Shown as "Step n of 6" under the top row (nil outside first-run setup, e.g. the service sheet in You).
    var step: SetupStep? = nil
    @ViewBuilder let content: Content
    @ViewBuilder let actions: Actions
    @Environment(\.onboardingHelp) private var help

    @ViewBuilder private var helpButton: some View {
        if let help {
            Button(action: help.open) {
                Label { Text(T("you.help")).kText(.footnote, weight: .semibold).wraps() } icon: { Image(systemName: "questionmark.circle") }
                    .foregroundStyle(KaikuTokens.Colors.clay)
                    .frame(minHeight: KaikuTokens.Size.tapMin)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s5) {
                    // The same round back button as every other screen; Help shares the row.
                    HStack(spacing: KaikuTokens.Space.s3) {
                        if let back { BackButton(action: back) }
                        Spacer(minLength: 0)
                        helpButton
                    }
                    .frame(minHeight: KaikuTokens.Size.tapMin)
                    if let step {
                        SetupProgress(step: step)
                    }
                    content
                }
                .padding(.horizontal, KaikuPlatform.sidePadding)
                .padding(.top, KaikuTokens.Space.s3)
                .frame(maxWidth: KaikuTokens.Size.contentMax, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            .scrollBounceBehavior(.basedOnSize)
            .kTopEdgeBackdrop()
            VStack(spacing: KaikuTokens.Space.s2) { actions }
                .padding(.horizontal, KaikuPlatform.sidePadding)
                .padding(.vertical, KaikuTokens.Space.s4)
                .frame(maxWidth: KaikuTokens.Size.contentMax)
                .frame(maxWidth: .infinity)
        }
        .background(KBackdrop())
    }
}

struct SetupProgress: View {
    let step: SetupStep
    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            Text(T("setup.progress", n: step.number)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted)
            ProgressBar(progress: Double(step.number) / Double(SetupStep.allCases.count))
        }
        .accessibilityElement(children: .combine)
    }
}

struct WelcomeStep: View {
    let next: () -> Void
    var body: some View {
        OnbPage(back: nil) {
            GlowingMascot(state: .happy, size: KaikuTokens.Size.mascotL).frame(maxWidth: .infinity).padding(.top, KaikuTokens.Space.s5)
            Text(T("onb.welcome.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("setup.welcome.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            Text(T("setup.welcome.time")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
        } actions: {
            Button(T("onb.welcome.cta"), action: next).buttonStyle(.kPrimary)
        }
    }
}

/// What Kaiku is and is not. Never skippable: the limits are part of the product, not small print.
struct AboutStep: View {
    let back: () -> Void
    let next: () -> Void
    var body: some View {
        OnbPage(back: back, step: .about) {
            Text(T("setup.about.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            KSection(T("setup.about.can"), icon: "checkmark.circle.fill", tone: .sage) {
                KRow(icon: "bubble.left.and.bubble.right.fill", tint: KaikuTokens.Colors.sage, title: T("setup.about.can.1"), accessory: .none)
                KDivider()
                KRow(icon: "leaf.fill", tint: KaikuTokens.Colors.sage, title: T("setup.about.can.2"), accessory: .none)
                KDivider()
                KRow(icon: "person.2.fill", tint: KaikuTokens.Colors.sage, title: T("setup.about.can.3"), accessory: .none)
            }
            KSection(T("setup.about.not"), icon: "hand.raised.fill", tone: .honey) {
                KRow(icon: "stethoscope", tint: KaikuTokens.Colors.honey, title: T("setup.about.not.1"), accessory: .none)
                KDivider()
                KRow(icon: "phone.fill", tint: KaikuTokens.Colors.honey, title: T("setup.about.not.2"), accessory: .none)
                KDivider()
                KRow(icon: "person.fill.questionmark", tint: KaikuTokens.Colors.honey, title: T("setup.about.not.3"), accessory: .none)
            }
        } actions: {
            Button(T("setup.about.cta"), action: next).buttonStyle(.kPrimary)
        }
    }
}

struct PairStep: View {
    let back: () -> Void
    var step: SetupStep? = nil
    let next: () -> Void
    @Environment(AppModel.self) private var app
    @State private var address = ""
    @State private var invalid = false
    @State private var connecting = false
    @State private var advanced = false

    var body: some View {
        OnbPage(back: back, step: step) {
            Text(T("service.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("service.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            if let pairing = app.pairing {
                KCard(tint: KaikuTokens.Colors.sageSoft) {
                    Label(T("service.connected"), systemImage: "checkmark.circle.fill").kText(.body)
                    Text(pairing.baseURL.host ?? "Kaiku").kText(.footnote)
                }
            }
            ForEach(app.serviceDiscovery.services) { service in
                KCard {
                    Text(service.name).kText(.title3)
                    Text(service.baseURL.absoluteString).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2)
                    if service.descriptor.permitsDemoConnection {
                        Button(T("service.connect")) {
                            connecting = true
                            Task {
                                invalid = !(await app.connectService(service))
                                connecting = false
                                if !invalid { await app.refresh(); next() }
                            }
                        }.buttonStyle(.kSecondary).disabled(connecting || app.pairing?.baseURL == service.baseURL)
                    } else {
                        Text(T("service.auth")).kText(.footnote).wraps()
                    }
                }
            }
            if app.serviceDiscovery.services.isEmpty {
                Text(T(app.serviceDiscovery.searching ? "service.searching" : "service.none")).kText(.body)
                    .foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                if step != nil, !app.isPaired {
                    Text(T("setup.connect.offline.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                }
            }
            if invalid || app.serviceDiscovery.failed {
                Text(T("service.failed")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            }
            Button {
                withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { advanced.toggle() }
            } label: {
                Text(T("service.advanced")).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.clay).wraps()
                    .frame(maxWidth: .infinity, minHeight: KaikuTokens.Size.tapMin, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if advanced {
                TextField(T("service.address"), text: $address)
                    .textFieldStyle(.roundedBorder).autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never).keyboardType(.URL)
                    #endif
                Button(T("service.find")) { inspectAddress() }.buttonStyle(.kSecondary).disabled(address.isEmpty || connecting)
            }
        } actions: {
            if app.isPaired {
                Button(T("common.continue"), action: next).buttonStyle(.kPrimary)
            } else if step != nil {
                // First run: nobody should have to type an address to get in. Going on without a service is the
                // main path; looking again is secondary; the address field stays under Advanced.
                Button(T("setup.connect.offline.cta"), action: next).buttonStyle(.kPrimary)
                Button(T("service.search")) { app.serviceDiscovery.start() }.buttonStyle(.kGhost)
            } else {
                Button(T("service.search")) { app.serviceDiscovery.start() }.buttonStyle(.kSecondary)
                Button(T("common.skip"), action: next).buttonStyle(.kGhost)
            }
        }
        .task {
            await app.ensureServiceConnection()
            app.serviceDiscovery.start()
        }
        .onDisappear { app.serviceDiscovery.stop() }
    }

    private func inspectAddress() {
        connecting = true; invalid = false
        Task {
            defer { connecting = false }
            // Explicitly supplied account provisioning remains supported for authenticated services.
            if Pairing.parse(address) != nil { invalid = !(await app.pair(link: address)); if !invalid { next() }; return }
            guard let url = ServiceDiscovery.origin(address) else { invalid = true; return }
            invalid = await app.serviceDiscovery.inspect(url) == nil
        }
    }
}

struct ConsentStep: View {
    let back: () -> Void
    let next: () -> Void
    @Environment(AppModel.self) private var app
    var body: some View {
        OnbPage(back: back, step: .choices) {
            Text(T("setup.choices.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("setup.choices.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            KSection {
                ForEach(Array(Signal.forThisDevice.enumerated()), id: \.element) { i, s in
                    if i > 0 { KDivider(plain: true) }   // these rows have no icon tile
                    KToggleRow(title: T("sig.\(s.rawValue).t"), detail: T(s.wholeKey),
                               isOn: app.choiceBinding(s))   // each row shows the choice's whole text
                }
            }
        } actions: {
            Button(T("common.continue"), action: next).buttonStyle(.kPrimary)
        }
    }
}

/// Permissions in context: one row each, asked only when its own button is pressed. Asking for the microphone
/// shows the system question; it does not open the microphone.
struct PermissionsStep: View {
    let back: () -> Void
    let next: () -> Void
    @Environment(AppModel.self) private var app
    @Environment(\.openURL) private var openURL
    @State private var mic: SetupPermissionState = .notAsked
    @State private var notifications: SetupPermissionState = .notAsked
    @State private var health: SetupPermissionState = .notAsked
    @State private var glassesTried = false

    var body: some View {
        OnbPage(back: back, step: .permissions) {
            Text(T("setup.perm.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("setup.perm.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            KSection {
                SetupPermissionRow(icon: "mic.fill", tint: KaikuTokens.Colors.clay, title: T("setup.perm.mic.t"),
                                   detail: T("setup.perm.mic.d"), state: mic, openSettings: openSettings) {
                    Task { mic = await AudioCapture.request() ? .allowed : .denied }
                }
                KDivider()
                SetupPermissionRow(icon: "bell.fill", tint: KaikuTokens.Colors.honey, title: T("setup.perm.notif.t"),
                                   detail: T("setup.perm.notif.d"), state: notifications, openSettings: openSettings) {
                    Task {
                        let ok = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])) ?? false
                        notifications = ok ? .allowed : .denied
                        app.notificationsOn = ok
                    }
                }
                #if os(iOS)
                if app.consents[.watch] == true {
                    KDivider()
                    SetupPermissionRow(icon: "heart.fill", tint: KaikuTokens.Colors.sage, title: T("setup.perm.health.t"),
                                       detail: T("setup.perm.health.d"), state: health, openSettings: openSettings) {
                        Task {
                            if await HealthSync.shared.authorize() { health = .allowed; await HealthSync.shared.sync(app: app) }
                            else { health = .denied; app.healthState = .denied }
                        }
                    }
                }
                if let connect = app.connectGlasses {
                    KDivider()
                    SetupPermissionRow(icon: "eyeglasses", tint: KaikuTokens.Colors.sky, title: T("setup.perm.glasses.t"),
                                       detail: T("setup.perm.glasses.d"),
                                       state: app.glassesRegistered ? .allowed : .notAsked,
                                       allowedLabel: T("setup.perm.glasses.ready"),
                                       note: glassesTried && !app.glassesRegistered ? T("setup.perm.glasses.none") : nil,
                                       actionLabel: T("setup.perm.setup"), openSettings: openSettings) {
                        // Registration opens the Meta AI app for approval; it does not open the microphone.
                        Task { app.glassesRegistered = await connect(); glassesTried = true }
                    }
                }
                #endif
            }
            Text(T("setup.perm.later")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
        } actions: {
            Button(T("common.continue"), action: next).buttonStyle(.kPrimary)
        }
        .task { await load() }
    }

    private func load() async {
        switch AudioCapture.permission {
        case .granted: mic = .allowed
        case .denied: mic = .denied
        case .undetermined: mic = .notAsked
        }
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        switch settings.authorizationStatus {
        case .notDetermined: notifications = .notAsked
        case .denied: notifications = .denied
        default: notifications = .allowed
        }
        if app.healthState == .connected { health = .allowed } else if app.healthState == .denied { health = .denied }
    }

    private func openSettings() {
        #if os(iOS)
        if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
        #else
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy") { openURL(url) }
        #endif
    }
}

struct SetupPermissionRow: View {
    let icon: String
    let tint: Color
    let title: String
    let detail: String
    let state: SetupPermissionState
    var allowedLabel: String = T("setup.perm.on")
    var note: String? = nil
    var actionLabel: String = T("setup.perm.allow")
    let openSettings: () -> Void
    let ask: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
                RowIcon(symbol: icon, tint: tint)
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                    Text(title).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    Text(detail).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    if state == .allowed {
                        Label(allowedLabel, systemImage: "checkmark.circle.fill").kText(.footnote, weight: .semibold)
                            .foregroundStyle(KaikuTokens.Colors.sage)
                    } else if state == .denied {
                        Text(T("setup.perm.off")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                    }
                    if let note { Text(note).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if state == .notAsked {
                Button(actionLabel, action: ask).buttonStyle(KButtonStyle(.secondary))
                    .accessibilityLabel("\(actionLabel): \(title)")
            } else if state == .denied {
                Button(T("setup.perm.settings"), action: openSettings).buttonStyle(KButtonStyle(.ghost))
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
    }
}

/// First hello in Kaiku's own voice (Gemini TTS from the service; silent with the words on screen when there is
/// none: never a synthesizer), then one tiny practice task taken to completion with a celebration.
struct HelloStep: View {
    let back: () -> Void
    let done: () -> Void
    @State private var value = 3
    @State private var finished = false
    @State private var heard = false
    /// nil = still trying; true = audio really started; false = no voice (say so, never claim it).
    @State private var voicePlayed: Bool?
    @State private var asked = false
    @Environment(AppModel.self) private var app

    /// `asked`: the person pressed "Hear Kaiku". Before that nothing is loading and nothing was heard.
    static func voiceNoteKey(paired: Bool, played: Bool?, asked: Bool = true) -> String {
        guard paired else { return "setup.hello.silent" }
        guard asked else { return "setup.hello.tap" }
        switch played {
        case nil: return "setup.hello.loading"
        case true?: return "setup.hello.voice"
        case false?: return "setup.hello.unavailable"
        }
    }

    var body: some View {
        OnbPage(back: finished ? nil : back, step: .hello) {
            GlowingMascot(state: finished ? .cheering : (heard ? .listening : .speaking), size: KaikuTokens.Size.mascotL * 0.8,
                          dial: finished ? nil : Double(value))
                .frame(maxWidth: .infinity)
            if finished {
                Text(T("setup.done.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                Text(T("setup.done.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            } else {
                Bubble(T("setup.hello.title"), big: true)
                HStack(spacing: KaikuTokens.Space.s3) {
                    Text(T(Self.voiceNoteKey(paired: app.isPaired, played: voicePlayed, asked: asked))).kText(.footnote)
                        .foregroundStyle(KaikuTokens.Colors.muted).wraps()
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if app.isPaired {
                        Button(T(voicePlayed == true ? "setup.hello.again" : "setup.hello.hear")) { hello() }.buttonStyle(KButtonStyle(.ghost, fullWidth: false)).fixedSize()
                    }
                }
                KCard(tone: .sky) {
                    Text(T("setup.task.title")).kText(.title3).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    Text(T("setup.task.body")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    WeatherDial(item: .mood, value: $value, active: true)
                }
            }
        } actions: {
            if finished {
                Button(T("setup.done.cta"), action: done).buttonStyle(.kPrimary)
            } else {
                Button(T("setup.task.cta")) {
                    VoiceLines.shared.stop()
                    Haptics.finished()
                    withAnimation(KaikuTokens.Spring.gentle) { finished = true }
                    app.celebrate()
                }
                .buttonStyle(.kPrimary)
                Button(T("common.skip"), action: done).buttonStyle(.kGhost)
            }
        }
        // Kaiku's hello is not said because the page appeared: "Hear Kaiku" plays it.
        .task { heard = true }
        .onDisappear { VoiceLines.shared.stop() }
    }

    private func hello() {
        guard app.isPaired else { return }
        asked = true
        Task { voicePlayed = await VoiceLines.shared.playReporting("welcome.hello", lang: app.language, fallback: T("setup.hello.title"), origin: .pressed) }
    }
}

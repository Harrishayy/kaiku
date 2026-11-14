import SwiftUI
import UserNotifications

/// First launch: welcome → pair → consent per signal → notifications → meet Kaiku. No tab bar; Help is one tap
/// away on every step.
struct OnboardingFlow: View {
    enum Step: Int { case welcome, pair, consent, notifications, meet }
    @Environment(AppModel.self) private var app
    @State private var step: Step = .welcome
    @State private var help = false

    var body: some View {
        Group {
            switch step {
            case .welcome: WelcomeStep { go(.pair) }
            case .pair: PairStep(back: { go(.welcome) }) { go(.consent) }
            case .consent: ConsentStep(back: { go(.pair) }) { go(.notifications) }
            case .notifications: NotificationsStep(back: { go(.consent) }) { go(.meet) }
            case .meet: MeetStep(back: { go(.notifications) }) { app.onboarded = true }
            }
        }
        .environment(\.onboardingHelp, OnboardingHelp { help = true })
        .sheet(isPresented: $help) {
            NavigationStack { HelpView() }
                #if os(macOS)
                .frame(minWidth: 480, minHeight: 520)
                #endif
        }
        .onAppear {
            if let s = UserDefaults.standard.string(forKey: "kaikuOnboardingStep"), let n = Int(s), let st = Step(rawValue: n) { step = st }
        }
    }

    private func go(_ s: Step) {
        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base)) { step = s }
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
    @ViewBuilder let content: Content
    @ViewBuilder let actions: Actions
    @Environment(\.onboardingHelp) private var help

    @ViewBuilder private func backButton(label: Bool) -> some View {
        if let back {
            Button(action: back) {
                HStack(spacing: 4) {
                    Image(systemName: "chevron.left").font(.system(size: 17, weight: .semibold))
                    if label { Text(T("common.back")).kText(.body, weight: .medium).lineLimit(1).fixedSize() }
                }
                .foregroundStyle(KaikuTokens.Colors.clay)
                .frame(minWidth: KaikuTokens.Size.tapMin, minHeight: KaikuTokens.Size.tapMin, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(T("common.back"))
        }
    }

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
                    // Back + Help share the top row; icon-only back, then stacked, when Finnish at large text needs room.
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: KaikuTokens.Space.s3) { backButton(label: true); Spacer(minLength: 0); helpButton }
                        HStack(spacing: KaikuTokens.Space.s3) { backButton(label: false); Spacer(minLength: 0); helpButton }
                        VStack(alignment: .leading, spacing: 0) { backButton(label: false); helpButton }
                    }
                    content
                }
                .padding(.horizontal, KaikuPlatform.sidePadding)
                .padding(.top, KaikuTokens.Space.s2)
                .frame(maxWidth: 560, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            VStack(spacing: KaikuTokens.Space.s2) { actions }
                .padding(.horizontal, KaikuPlatform.sidePadding)
                .padding(.vertical, KaikuTokens.Space.s4)
                .frame(maxWidth: 560)
                .frame(maxWidth: .infinity)
                .background(KaikuTokens.Colors.bg)
        }
        .background(KaikuTokens.Colors.bg.ignoresSafeArea())
    }
}

struct WelcomeStep: View {
    let next: () -> Void
    var body: some View {
        OnbPage(back: nil) {
            MascotView(state: .happy, size: 190).frame(maxWidth: .infinity).padding(.top, KaikuTokens.Space.s5)
            Text(T("onb.welcome.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("onb.welcome.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
        } actions: {
            Button(T("onb.welcome.cta"), action: next).buttonStyle(.kPrimary)
        }
    }
}

struct PairStep: View {
    let back: () -> Void
    let next: () -> Void
    @Environment(AppModel.self) private var app
    @State private var link = ""
    @State private var pasting = !KaikuPlatform.isPhone
    @State private var invalid = false
    @State private var found = false

    var cameraAvailable: Bool {
        #if os(iOS)
        return QRScannerView.available
        #else
        return false
        #endif
    }

    var body: some View {
        OnbPage(back: back) {
            Text(T("onb.pair.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("onb.pair.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            if invalid {
                HStack(alignment: .top, spacing: KaikuTokens.Space.s3) {
                    Image(systemName: "questionmark.circle").foregroundStyle(KaikuTokens.Colors.honey)
                    Text(T("onb.pair.invalid")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(KaikuTokens.Space.s4)
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.honeySoft))
            }
            if found {
                KCard(tint: KaikuTokens.Colors.sageSoft) {
                    Label { Text(T("onb.pair.ok")).kText(.body).wraps() } icon: { Image(systemName: "checkmark.circle.fill") }
                        .foregroundStyle(KaikuTokens.Colors.ink)
                }
            }
            #if os(iOS)
            if !pasting {
                ZStack {
                    if cameraAvailable {
                        QRScannerView { code in handle(code) }
                    } else {
                        RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg).fill(KaikuTokens.Colors.surface2)
                        VStack(spacing: KaikuTokens.Space.s2) {
                            Image(systemName: "qrcode.viewfinder").font(.system(size: 44)).foregroundStyle(KaikuTokens.Colors.muted)
                            Text(T("onb.pair.nocamera")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2)
                                .multilineTextAlignment(.center).wraps()
                        }
                        .padding()
                    }
                    RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg).strokeBorder(KaikuTokens.Colors.clay, style: StrokeStyle(lineWidth: 3, dash: [14, 10]))
                }
                .aspectRatio(1, contentMode: .fit)
                .frame(maxWidth: 300)
                .clipShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg))
                .frame(maxWidth: .infinity)
                .accessibilityLabel(T("onb.pair.title"))
            }
            #endif
            if pasting {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                    TextField(T("onb.pair.placeholder"), text: $link, axis: .vertical)
                        .kText(.body)
                        .lineLimit(1...3)
                        .textFieldStyle(.plain)
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        #endif
                        .padding(KaikuTokens.Space.s4)
                        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.surface))
                        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).strokeBorder(KaikuTokens.Colors.line))
                        .onSubmit { handle(link) }
                }
            }
        } actions: {
            if pasting {
                Button(T("common.continue")) { handle(link) }.buttonStyle(.kPrimary).disabled(link.isEmpty || found)
            } else {
                Button(T("onb.pair.link")) { pasting = true }.buttonStyle(.kSecondary)
            }
            Button(T("common.skip"), action: next).buttonStyle(.kGhost)
        }
    }

    private func handle(_ code: String) {
        guard !found else { return }
        guard Pairing.parse(code) != nil else {
            withAnimation { invalid = true }
            return
        }
        invalid = false
        Task {
            await app.pair(link: code)
            withAnimation { found = true }
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            next()
        }
    }
}

struct ConsentStep: View {
    let back: () -> Void
    let next: () -> Void
    @Environment(AppModel.self) private var app
    var body: some View {
        OnbPage(back: back) {
            Text(T("onb.consent.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("onb.consent.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            KSection {
                ForEach(Array(Signal.forThisDevice.enumerated()), id: \.element) { i, s in
                    if i > 0 { KDivider() }
                    KToggleRow(title: T("sig.\(s.rawValue).t"), detail: T("sig.\(s.rawValue).d"),
                               isOn: Binding(get: { app.consents[s] ?? false }, set: { app.consents[s] = $0 }))
                }
            }
        } actions: {
            Button(T("common.continue"), action: next).buttonStyle(.kPrimary)
        }
    }
}

struct NotificationsStep: View {
    let back: () -> Void
    let next: () -> Void
    var body: some View {
        OnbPage(back: back) {
            KCard(tint: KaikuTokens.Colors.honeySoft) {
                Image(systemName: "bell.fill").font(.system(size: 34)).foregroundStyle(KaikuTokens.Colors.honey).accessibilityHidden(true)
                Text(T("onb.notif.title")).kText(.title2).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                Text(T("onb.notif.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            }
            .padding(.top, KaikuTokens.Space.s5)
        } actions: {
            Button(T("onb.notif.allow")) {
                Task {
                    // Denied → continue silently.
                    _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
                    next()
                }
            }
            .buttonStyle(.kPrimary)
            Button(T("common.skip"), action: next).buttonStyle(.kGhost)
        }
    }
}

struct MeetStep: View {
    let back: () -> Void
    let done: () -> Void
    @State private var value = 3
    var body: some View {
        OnbPage(back: back) {
            MascotView(state: .listening, size: 170, dial: Double(value)).frame(maxWidth: .infinity)
            Text(T("onb.meet.title")).kText(.title1).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("onb.meet.body")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            // Practice dial: not recorded.
            KCard { WeatherDial(item: .mood, value: $value) }
        } actions: {
            Button(T("onb.meet.cta"), action: done).buttonStyle(.kPrimary)
        }
    }
}

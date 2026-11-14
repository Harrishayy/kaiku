import SwiftUI

/// The five tabs, same names and order on iPhone (tab bar) and Mac (sidebar) — design/ia.md → Navigation.
public enum KaikuTab: String, CaseIterable, Identifiable, Hashable, Sendable {
    case today, play, talk, days, you
    public var id: String { rawValue }
    public var title: String { T("tab.\(rawValue)") }
    public var symbol: String {
        switch self {
        case .today: return "sun.horizon"
        case .play: return "sparkles"
        case .talk: return "bubble.left.and.bubble.right"
        case .days: return "leaf"
        case .you: return "person.crop.circle"
        }
    }
}

/// Every pushed screen. Parity: both targets render exactly this list (plan 02 §4); `platformOnly` marks the
/// exceptions, mirrored in apps/apple/AGENTS.md → Parity.
public enum KaikuRoute: String, Hashable, CaseIterable, Sendable {
    case weather, firefly, pebbles, breathe, tell, walk
    case lantern, seeds, watering
    case memories, saw, voice, quiet, devices, help, glasses

    public var tab: KaikuTab {
        switch self {
        case .weather: return .today
        case .firefly, .pebbles, .breathe, .tell, .walk, .lantern, .seeds, .watering: return .play
        default: return .you
        }
    }
}

/// The parity list (one row per screen in design/ia.md). Used by the parity test and the AGENTS.md table.
public enum KaikuScreen: String, CaseIterable, Sendable {
    case onboardingWelcome, onboardingAbout, onboardingPair, onboardingConsent, onboardingPermissions, onboardingHello
    case today, weatherCheck
    case play, firefly, pebbles, tell, breathe, walk
    case lantern, seeds, watering
    case talk
    case days, markDay
    case you, memories, saw, voice, quiet, devices, help, glasses
    case crisis
    case menuBarPopover

    public enum Platform: Sendable { case both, iPhoneOnly, macOnly }
    public var platform: Platform {
        switch self {
        case .menuBarPopover: return .macOnly
        case .walk, .glasses: return .iPhoneOnly
        default: return .both
        }
    }
}

@ViewBuilder
func destination(_ r: KaikuRoute) -> some View {
    switch r {
    case .weather: CheckInChatView()
    case .firefly: FireflyGame()
    case .pebbles: PebbleGame()
    case .lantern: LanternGame()
    case .seeds: SeedGame()
    case .watering: WateringGame()
    case .breathe: BreatheView()
    case .tell: TellKaikuView()
    case .walk: WalkView()
    case .memories: MemoriesView()
    case .saw: SawTodayView()
    case .voice: VoiceLanguageView()
    case .quiet: QuietHoursView()
    case .devices: DevicesView()
    case .help: HelpView()
    case .glasses: GlassesCheckView()
    }
}

/// Root of both apps: onboarding until done, then tabs (iPhone) or sidebar (Mac). Crisis covers everything.
public struct KaikuRootView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.scenePhase) private var phase
    public init() {}

    public var body: some View {
        @Bindable var app = app
        Group {
            if !app.onboarded {
                OnboardingFlow()
            } else {
                #if os(iOS)
                PhoneTabs()
                #else
                MacSidebar()
                #endif
            }
        }
        .id(app.language)
        .environment(\.locale, Locale(identifier: app.language.rawValue))
        .tint(KaikuTokens.Colors.clay)
        .kToast($app.toast)
        .kCelebration(app.celebration, enabled: !app.showCrisis)
        #if os(iOS)
        .fullScreenCover(isPresented: $app.showCrisis) { CrisisView() }
        #else
        .sheet(isPresented: $app.showCrisis) { CrisisView().frame(minWidth: 520, minHeight: 560) }
        #endif
        .task { await app.refresh() }
        .onChange(of: phase) { _, p in if p == .active { Task { await app.refresh() } } }
    }
}

#if os(iOS)
struct PhoneTabs: View {
    @Environment(AppModel.self) private var app
    @State private var paths: [KaikuTab: [KaikuRoute]] = [:]

    var body: some View {
        @Bindable var app = app
        TabView(selection: $app.selectedTab) {
            ForEach(KaikuTab.allCases) { tab in
                NavigationStack(path: binding(tab)) {
                    tabRoot(tab).navigationDestination(for: KaikuRoute.self) { destination($0) }
                }
                .tabItem { Label(tab.title, systemImage: tab.symbol) }
                .tag(tab)
            }
        }
        .onAppear { follow(app.deepLink) }
        .onChange(of: app.deepLink) { _, r in follow(r) }
    }

    private func follow(_ r: KaikuRoute?) {
        guard let r else { return }
        app.selectedTab = r.tab
        paths[r.tab] = [r]
        app.deepLink = nil
    }

    private func binding(_ tab: KaikuTab) -> Binding<[KaikuRoute]> {
        Binding(get: { paths[tab] ?? [] }, set: { paths[tab] = $0 })
    }
}
#endif

@ViewBuilder
func tabRoot(_ tab: KaikuTab) -> some View {
    switch tab {
    case .today: TodayView()
    case .play: PlayView()
    case .talk: TalkView()
    case .days: DaysView()
    case .you: YouView()
    }
}

#if os(macOS)
/// Mac window: sidebar with the five tabs and "I'm not OK" at the bottom; the pane is the iPhone screen at
/// window width (text columns capped).
struct MacSidebar: View {
    @Environment(AppModel.self) private var app
    @State private var path: [KaikuRoute] = []

    var body: some View {
        @Bindable var app = app
        NavigationSplitView {
            List(selection: Binding(get: { Optional(app.selectedTab) }, set: { if let t = $0 { app.selectedTab = t; path = [] } })) {
                ForEach(KaikuTab.allCases) { tab in
                    Label { Text(tab.title).kText(.body, weight: .medium) } icon: { Image(systemName: tab.symbol) }
                        .tag(tab)
                        .padding(.vertical, KaikuTokens.Space.s1)
                }
            }
            .listStyle(.sidebar)
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                    MascotView(state: app.ambientState, size: KaikuTokens.Size.mascotS, tappable: true)
                    NotOKPill()
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(KaikuTokens.Space.s4)
            }
            .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 280)
        } detail: {
            NavigationStack(path: $path) {
                tabRoot(app.selectedTab).navigationDestination(for: KaikuRoute.self) { destination($0) }
            }
            .background(KaikuTokens.Colors.bg)
        }
        .onAppear { follow(app.deepLink) }
        .onChange(of: app.deepLink) { _, r in follow(r) }
    }

    private func follow(_ r: KaikuRoute?) {
        guard let r else { return }
        app.selectedTab = r.tab
        path = [r]
        app.deepLink = nil
    }
}
#endif

/// One pane (a tab root or a pushed route) without navigation chrome — for previews and layout snapshots.
public struct KaikuPanePreview: View {
    let tab: KaikuTab
    let route: KaikuRoute?
    public init(tab: KaikuTab, route: KaikuRoute? = nil) { self.tab = tab; self.route = route }
    public var body: some View {
        Group {
            if let route { destination(route) } else { tabRoot(tab) }
        }
        .background(KaikuTokens.Colors.bg)
    }
}

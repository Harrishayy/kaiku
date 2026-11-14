import SwiftUI

/// The tabs, same names and order on iPhone (tab bar) and Mac (sidebar) — design/ia.md → Navigation.
/// History took the place of Your days (2026-11-14; Your days is History's first block and a screen under it,
/// `KaikuRoute.days`). Kaiku bot (2026-11-14): what the robot at home hears and does, live. It is a tab in the Mac's
/// sidebar; an iPhone tab bar shows five (a sixth puts the fifth AND the sixth behind "More", You included), so on
/// iPhone it is a screen under You (`KaikuRoute.bot`) and the bar keeps its five (`phoneBar`).
public enum KaikuTab: String, CaseIterable, Identifiable, Hashable, Sendable {
    case today, play, talk, history, bot, you
    public var id: String { rawValue }
    public var title: String { T("tab.\(rawValue)") }
    /// The iPhone tab bar: every tab but Kaiku bot.
    public static var phoneBar: [KaikuTab] { allCases.filter { $0 != .bot } }
    public var symbol: String {
        switch self {
        case .today: return "sun.horizon"
        case .play: return "sparkles"
        case .talk: return "bubble.left.and.bubble.right"
        case .history: return "chart.bar"
        case .bot: return "antenna.radiowaves.left.and.right"
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
    case days
    /// Kaiku bot as a pushed screen (iPhone, under You); on the Mac it is a tab.
    case bot

    public var tab: KaikuTab {
        switch self {
        case .weather: return .today
        case .days: return .history
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
    case history, historyMeasure
    case bot
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
    case .days: DaysView()
    case .bot: BotView(pushed: true)
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
            ForEach(KaikuTab.phoneBar) { tab in
                NavigationStack(path: binding(tab)) {
                    tabRoot(tab).navigationDestination(for: KaikuRoute.self) { destination($0) }
                }
                .tabItem { Label(tab.title, systemImage: tab.symbol) }
                .tag(tab)
            }
        }
        .onAppear { follow(app.deepLink); botUnderYou() }
        .onChange(of: app.deepLink) { _, r in follow(r) }
        // A check-in ends when its screen is left. Left by switching tabs it would stay on its tab's stack and
        // come back later as if it were still there, so it is taken off as the tab is left.
        .onChange(of: app.selectedTab) { old, _ in
            if paths[old]?.contains(.weather) == true { paths[old]?.removeAll { $0 == .weather } }
            botUnderYou()
        }
    }

    /// `kaiku://bot`, `-kaikuTab bot`: on iPhone Kaiku bot is a screen under You.
    private func botUnderYou() {
        guard app.selectedTab == .bot else { return }
        app.selectedTab = .you
        paths[.you] = [.bot]
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

@MainActor @ViewBuilder
func tabRoot(_ tab: KaikuTab) -> some View {
    switch tab {
    case .today: TodayView()
    case .play: PlayView()
    case .talk: TalkView(model: .forTalkScreen())   // on the Mac: the conversation quick talk shares (QuickTalkModel)
    case .history: HistoryView()
    case .bot: BotView()
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

import AppKit
import KaikuKit
import SwiftUI

/// Mac shell: a window (sidebar + pane, min 720 × 480), a menu bar popover and the Mac extras (notch island,
/// usage-rhythm sampler, daily invitation — `MacCompanion`). All share one AppModel.
@main
struct KaikuMacApp: App {
    @State private var app = DebugSnapshot.isSnapshot ? DebugSnapshot.model() : AppModel()
    @Environment(\.openWindow) private var openWindow

    var body: some Scene {
        Window("Kaiku", id: "main") {
            KaikuRootView()
                .environment(app)
                .frame(minWidth: 720, minHeight: 480)
                // kaiku://play/firefly etc. switch screens (same links as iPhone); anything else is a pairing link
                .onOpenURL { url in if !app.open(url) { Task { await app.pair(link: url.absoluteString) } } }
                .onAppear { MacCompanion.shared.start(app: app); startQuickTalk() }
                .task(id: app.nudge?.arm) { DailyInvitation.schedule(app: app) }
                #if DEBUG
                .onAppear { DebugSnapshot.runIfAsked(app: app) }
                #endif
        }
        .defaultSize(width: 980, height: 720)
        .windowResizability(.contentMinSize)

        MenuBarExtra {
            VStack(spacing: 0) {
                talkNow
                MenuBarPopover { tab, route in
                    app.selectedTab = tab
                    app.deepLink = route
                    openWindow(id: "main")
                    NSApp.activate(ignoringOtherApps: true)
                }
                #if DEBUG
                // Demo: synthetic 00:00–01:10 fed through the real aggregator and rules → the 01:10 peek, any time.
                Button(T("mac.sim.late")) { MacCompanion.shared.simulateLateEvening() }
                    .buttonStyle(KButtonStyle(.ghost, fullWidth: true))
                    .padding(.horizontal, KaikuTokens.Space.s4)
                    .padding(.bottom, KaikuTokens.Space.s3)
                #endif
            }
            .background(KaikuTokens.Colors.bg)
            .environment(app)
            .tint(KaikuTokens.Colors.clay)
            .onAppear { MacCompanion.shared.start(app: app); startQuickTalk() }
        } label: {
            Image(systemName: "circle.hexagongrid.fill")
        }
        .menuBarExtraStyle(.window)
    }

    /// Quick talk (the bar at the left edge of the screen) needs a way to bring this window forward: for "open
    /// Kaiku", for
    /// "Continue in Kaiku", for an activity, and for the crisis screen, which lives here.
    private func startQuickTalk() {
        QuickTalkController.shared.start(app: app) { tab in
            if let tab { app.selectedTab = tab }
            openWindow(id: "main")
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    /// "Talk now": the same as the key combination, for the pointer; and the switch for the bar at the screen
    /// edge (the same setting as in You). Shown while quick talk is on.
    @ViewBuilder private var talkNow: some View {
        let quick = QuickTalkController.shared.model
        if quick.enabled, !quick.inert {
            VStack(spacing: KaikuTokens.Space.s2) {
                Button { QuickTalkController.shared.trigger() } label: {
                    HStack(spacing: KaikuTokens.Space.s2) {
                        Image(systemName: "waveform")
                        Text(T("quick.now"))
                        Spacer(minLength: KaikuTokens.Space.s2)
                        Text(T("quick.keys")).opacity(0.8)
                    }
                }
                .buttonStyle(KButtonStyle(.primary))
                Toggle(isOn: Binding(get: { quick.showBar }, set: { quick.showBar = $0 })) {
                    Text(T("quick.set.bar")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .toggleStyle(.switch)
                .controlSize(.mini)
                .tint(KaikuTokens.Colors.sage)
                .padding(.horizontal, KaikuTokens.Space.s1)
            }
            .padding(.horizontal, KaikuTokens.Space.s4)
            .padding(.top, KaikuTokens.Space.s4)
        }
    }
}

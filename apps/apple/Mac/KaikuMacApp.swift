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
                .onOpenURL { url in Task { await app.pair(link: url.absoluteString) } }
                .onAppear { MacCompanion.shared.start(app: app) }
                .task(id: app.nudge?.arm) { DailyInvitation.schedule(app: app) }
                #if DEBUG
                .onAppear { DebugSnapshot.runIfAsked(app: app) }
                #endif
        }
        .defaultSize(width: 980, height: 720)
        .windowResizability(.contentMinSize)

        MenuBarExtra {
            VStack(spacing: 0) {
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
            .onAppear { MacCompanion.shared.start(app: app) }
        } label: {
            Image(systemName: "circle.hexagongrid.fill")
        }
        .menuBarExtraStyle(.window)
    }
}

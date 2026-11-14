import AppKit
import KaikuKit
import SwiftUI

/// Mac shell: a window (sidebar + pane, min 720 × 480) and a menu bar popover. Both share one AppModel.
@main
struct KaikuMacApp: App {
    @State private var app = AppModel()
    @Environment(\.openWindow) private var openWindow

    var body: some Scene {
        Window("Kaiku", id: "main") {
            KaikuRootView()
                .environment(app)
                .frame(minWidth: 720, minHeight: 480)
                .onOpenURL { url in Task { await app.pair(link: url.absoluteString) } }
                #if DEBUG
                .onAppear { DebugSnapshot.runIfAsked(app: app) }
                #endif
        }
        .defaultSize(width: 980, height: 720)
        .windowResizability(.contentMinSize)

        MenuBarExtra {
            MenuBarPopover { tab, route in
                app.selectedTab = tab
                app.deepLink = route
                openWindow(id: "main")
                NSApp.activate(ignoringOtherApps: true)
            }
            .environment(app)
            .tint(KaikuTokens.Colors.clay)
        } label: {
            Image(systemName: "circle.hexagongrid.fill")
        }
        .menuBarExtraStyle(.window)
    }
}

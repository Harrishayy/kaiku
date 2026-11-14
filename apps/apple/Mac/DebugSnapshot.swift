#if DEBUG
import AppKit
import KaikuKit
import SwiftUI

/// Layout check without screen-recording permission: `-kaikuSnapshot /path.png` renders the Mac pane for the
/// selected tab/route at the minimum window's pane size (720 × 480 window − 220 pt sidebar) with ImageRenderer,
/// writes a PNG and quits. Debug builds only.
enum DebugSnapshot {
    @MainActor static func runIfAsked(app: AppModel) {
        guard let path = UserDefaults.standard.string(forKey: "kaikuSnapshot") else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
            let view = KaikuPanePreview(tab: app.selectedTab, route: UserDefaults.standard.string(forKey: "kaikuRoute").flatMap(KaikuRoute.init(rawValue:)))
                .environment(app)
                .environment(\.kaikuStaticLayout, true)
                .frame(width: 500, height: 480)
                .clipped()
            let r = ImageRenderer(content: view)
            r.scale = 2
            if let img = r.nsImage, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
                try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
            }
            NSApp.terminate(nil)
        }
    }
}
#endif

import KaikuKit
import SwiftUI

/// iPhone shell: everything lives in KaikuKit. Pairing links (`kaiku://pair?…` or a universal https link with
/// `?home=&t=`) open the app and pair it.
@main
struct KaikuApp: App {
    @State private var app = AppModel()

    var body: some Scene {
        WindowGroup {
            KaikuRootView()
                .environment(app)
                .onOpenURL { url in Task { await app.pair(link: url.absoluteString) } }
        }
    }
}

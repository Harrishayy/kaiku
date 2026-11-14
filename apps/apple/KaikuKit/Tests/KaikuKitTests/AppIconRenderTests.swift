#if os(macOS)
import AppKit
import SwiftUI
import XCTest
@testable import KaikuKit

/// App icon source (opt-in): `KAIKU_ICON_OUT=<dir> swift test --filter AppIconRenderTests` renders
/// icon-light-1024.png / icon-dark-1024.png with the app's own MascotView (= design/mascot.spec.json) on token
/// colours. scripts/make_app_icon.sh runs this and builds the iOS + Mac AppIcon sets. Full bleed, no text, opaque.
@MainActor
final class AppIconRenderTests: XCTestCase {
    struct KaikuIcon: View {
        let dark: Bool
        var body: some View {
            let top = dark ? KaikuTokens.Colors.nightA : KaikuTokens.Colors.honeySoft
            let bottom = dark ? KaikuTokens.Colors.nightB : KaikuTokens.Colors.mascotShade
            ZStack {
                LinearGradient(colors: [top, bottom], startPoint: .top, endPoint: .bottom)
                RadialGradient(colors: [Color(red: 1, green: 0.85, blue: 0.56).opacity(dark ? 0.35 : 0.75), .clear],
                               center: .init(x: 0.5, y: 0.56), startRadius: 0, endRadius: 470)
                MascotView(state: .happy, size: 860, tappable: false, cycleStart: .distantPast)
                    .offset(y: 36)
            }
            .frame(width: 1024, height: 1024)
            .clipped()
            .environment(\.colorScheme, .light)
        }
    }

    func testRenderAppIcon() throws {
        guard let dir = ProcessInfo.processInfo.environment["KAIKU_ICON_OUT"] else { throw XCTSkip("set KAIKU_ICON_OUT") }
        defer { GlowClock.fixedHour = nil }
        for dark in [false, true] {
            GlowClock.fixedHour = dark ? 19 : 13   // warm chest glow: day honey / dusk amber, never the night blue
            let r = ImageRenderer(content: KaikuIcon(dark: dark))
            r.scale = 1
            r.isOpaque = true
            let cg = try XCTUnwrap(r.cgImage)
            XCTAssertEqual(cg.width, 1024)
            let data = try XCTUnwrap(NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]))
            try data.write(to: URL(fileURLWithPath: dir).appendingPathComponent("icon-\(dark ? "dark" : "light")-1024.png"))
        }
    }
}
#endif

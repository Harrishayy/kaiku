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

/// `-kaikuIslandSnapshot /path.png` (with `-kaikuSimulateLate YES`): once the island has peeked, renders a slice
/// of the menu bar around the notch (grey bars = menu titles / status items outside notch ± wings) with the island
/// collapsed, mid-morph, peeking and expanded, at 2× (the path) and 1× (`<path>.1x.png`). For checking the look
/// without screen-recording permission.
enum IslandSnapshot {
    @MainActor static var taken = false

    @MainActor static func runIfAsked(model: IslandModel, geometry: MacIslandGeometry?) {
        guard let path = UserDefaults.standard.string(forKey: "kaikuIslandSnapshot"), !taken else { return }
        taken = true            // the first peek only
        let kind = model.kind   // what was shown (the person may click the notch meanwhile)
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            // Copies pinned mid-loop (sleepy: 1.5 s of 3 s), where the floating z's are fully in.
            @MainActor func copy(_ s: IslandModel.State) -> IslandModel {
                let m = IslandModel()
                m.kind = kind; m.hasNotch = model.hasNotch; m.notchWidth = model.notchWidth; m.wing = model.wing
                m.menuBar = model.menuBar; m.helloLine = model.helloLine; m.risen = true; m.state = s
                m.loopStart = Date().addingTimeInterval(-1.5)
                return m
            }
            let peek = copy(.peek)
            let a = peek.shape(.hidden), b = peek.shape(.peek)
            let mid = MacIslandShape(topWidth: (a.topWidth + b.topWidth) / 2, bodyWidth: (a.bodyWidth + b.bodyWidth) / 2,
                                     bodyHeight: b.bodyHeight / 2, menuBar: b.menuBar, pill: b.pill)
            let view = VStack(spacing: 12) {
                MenuBarSlice(model: copy(.hidden), shape: nil)
                MenuBarSlice(model: copy(.peek), shape: mid)
                MenuBarSlice(model: peek, shape: nil)
                MenuBarSlice(model: copy(.expanded), shape: nil)
            }
            .padding(12)
            .background(Color(white: 0.75))
            for (scale, out) in [(2.0, path), (1.0, path + ".1x.png")] {
                let r = ImageRenderer(content: view)
                r.scale = scale
                if let img = r.nsImage, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
                    try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: out))
                }
            }
        }
    }
}

/// 760 pt of menu bar centred on the notch: a light menu bar with grey bars outside notch ± wings, the hardware
/// notch, and the island window on top (same size and origin as the real one).
private struct MenuBarSlice: View {
    let model: IslandModel
    let shape: MacIslandShape?
    var body: some View {
        let w: CGFloat = 760
        let strip = model.hasNotch ? model.notchWidth + 2 * model.wing : 0
        let winW = MacIslandLayout.expanded.width + 2 * NotchIsland.shadowPad
        let winH = model.menuBar + MacIslandShape.pillGap + MacIslandLayout.bodyHeight(expanded: true) + NotchIsland.shadowPad
        ZStack(alignment: .top) {
            Color(white: 0.93).frame(width: w, height: winH)
            Color(white: 0.97).frame(width: w, height: model.menuBar)
            HStack(spacing: 0) {
                HStack(spacing: 10) { ForEach(0..<4, id: \.self) { _ in Capsule().fill(Color(white: 0.6)).frame(width: 44, height: 9) } }
                    .frame(maxWidth: .infinity, alignment: .trailing).padding(.trailing, 10)
                Color.clear.frame(width: max(strip, model.notchWidth))
                HStack(spacing: 10) { ForEach(0..<4, id: \.self) { _ in Circle().fill(Color(white: 0.6)).frame(width: 12, height: 12) } }
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 10)
            }
            .frame(width: w, height: model.menuBar)
            if model.hasNotch { Color.black.frame(width: model.notchWidth, height: model.menuBar) }   // hardware notch
            IslandView(model: model, act: { _ in }, shapeOverride: shape).frame(width: winW, height: winH)
        }
        .frame(width: w, height: winH)
        .clipped()
    }
}
#endif

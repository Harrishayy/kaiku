#if DEBUG
import KaikuKit
import SwiftUI
import UIKit

/// Debug only: `-kaikuSurfaceSnapshot <dir>` renders the Live Activity / Dynamic Island / widget content at the
/// sizes of a small (375 pt) and a large (440 pt) iPhone into PNGs, so overflow can be reviewed without having to
/// lock the simulator. The views are the same ones the widget extension draws (KaikuKit/Widgets/SurfaceViews).
@MainActor
enum SurfaceSnapshots {
    static func runIfAsked() {
        guard let dir = UserDefaults.standard.string(forKey: "kaikuSurfaceSnapshot") else { return }
        let url = URL(fileURLWithPath: dir, isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        for lang in [KaikuLanguage.en, .fi] {
            for (name, width, widget) in [("small", 375.0, 158.0), ("large", 440.0, 170.0)] {
                func save<V: View>(_ v: V, _ file: String, _ size: CGSize, dark: Bool = false) {
                    let r = ImageRenderer(content: v.frame(width: size.width, height: size.height)
                        .environment(\.colorScheme, dark ? .dark : .light))
                    r.scale = 3
                    if let d = r.uiImage?.pngData() { try? d.write(to: url.appendingPathComponent("\(file)-\(lang.rawValue)-\(name).png")) }
                }
                let lockW = width - 16
                save(lockCard(WalkLockContent(lang: lang, minutes: 12, found: 2)), "lock-walk", CGSize(width: lockW, height: 160))
                save(lockCard(BreatheLockContent(lang: lang, breath: 3)), "lock-breathe", CGSize(width: lockW, height: 160))
                save(expandedIsland(lang), "island-expanded", CGSize(width: width - 22, height: 190))
                save(compactIsland(lang, minutes: 12), "island-compact", CGSize(width: 250, height: 37))
                let snap = WidgetSnapshot(mood: MascotState.cozy.rawValue, suggestionKey: "today.suggest.daylight_walk", checkedIn: false, lang: lang.rawValue)
                save(widgetCard(HomeWidgetContent(snap: snap, date: Date(), family: .small)), "widget-small", CGSize(width: widget, height: widget))
                save(widgetCard(HomeWidgetContent(snap: snap, date: Date(), family: .medium)), "widget-medium", CGSize(width: widget * 2 + 22, height: widget))
                save(lockAccessory(HomeWidgetContent(snap: snap, date: Date(), family: .rectangular)), "widget-rect", CGSize(width: widget + 2, height: 72))
                save(lockAccessory(HomeWidgetContent(snap: snap, date: Date(), family: .circular)), "widget-circular", CGSize(width: 76, height: 76))
            }
        }
        // every glyph state at island size and accessory size
        let glyphs = HStack(spacing: 14) {
            ForEach([MascotState.walking, .breathing, .sleepy, .cozy, .idle], id: \.self) { s in
                VStack { KaikuGlyph(state: s, size: 26); KaikuGlyph(state: s, size: 44) }
            }
        }
        .padding(12).background(Color.black)
        let r = ImageRenderer(content: glyphs)
        r.scale = 3
        if let d = r.uiImage?.pngData() { try? d.write(to: url.appendingPathComponent("glyphs.png")) }
        NSLog("kaiku surface snapshots written to %@", dir)
    }

    static func demoButtons(_ lang: KaikuLanguage) -> some View {
        Group {
            Button {} label: { Text(TL("lh.found", lang)).frame(maxWidth: .infinity) }.tint(KaikuTokens.Colors.sage)
            Button {} label: { Text(TL("lh.end", lang)).frame(maxWidth: .infinity) }.tint(KaikuTokens.Colors.ink2)
        }
        .buttonStyle(.borderedProminent)
    }

    static func lockCard<V: View>(_ v: V) -> some View {
        v.frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(RoundedRectangle(cornerRadius: 22).fill(KaikuTokens.Colors.bg))
    }

    static func widgetCard<V: View>(_ v: V) -> some View {
        v.padding(14).frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(RoundedRectangle(cornerRadius: 22).fill(KaikuTokens.Colors.bg))
    }

    static func lockAccessory<V: View>(_ v: V) -> some View {
        v.foregroundStyle(.white).frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(RoundedRectangle(cornerRadius: 14).fill(Color.gray.opacity(0.6)))
    }

    /// The expanded island laid out like ActivityKit does (leading · centre · trailing, bottom row).
    static func expandedIsland(_ lang: KaikuLanguage) -> some View {
        VStack(spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                MascotView(state: .walking, size: SurfaceSize.islandMascot, tappable: false)
                    .frame(width: SurfaceSize.islandMascot, height: SurfaceSize.islandMascot)
                WalkIslandCenter(lang: lang, found: 2)
                IslandMinutes(lang: lang, minutes: 12)
            }
            HStack(spacing: 10) {
                Button {} label: { Text(TL("lh.found", lang)).frame(maxWidth: .infinity) }.tint(KaikuTokens.Colors.sage)
                Button {} label: { Text(TL("lh.end", lang)).frame(maxWidth: .infinity) }.tint(.white.opacity(0.25))
            }
            .font(.system(.subheadline, design: .rounded).weight(.semibold))
            .buttonStyle(.borderedProminent)
        }
        .padding(.horizontal, 18).padding(.vertical, 14)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(RoundedRectangle(cornerRadius: 44).fill(Color.black))
    }

    static func compactIsland(_ lang: KaikuLanguage, minutes: Int) -> some View {
        HStack {
            KaikuGlyph(state: .walking, size: SurfaceSize.glyph)
            Spacer()
            Text(TL("la.min", lang, ["n": "\(minutes)"]))
                .font(.system(.caption, design: .rounded).weight(.semibold)).foregroundStyle(KaikuTokens.Colors.sage)
        }
        .padding(.horizontal, 10)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Capsule().fill(Color.black))
    }
}
#endif

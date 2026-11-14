#if DEBUG
import AppKit
import KaikuKit
import SwiftUI

/// Layout check without screen-recording permission: `-kaikuSnapshot /path.png` renders the Mac window for the
/// selected tab/route with ImageRenderer (a drawn sidebar + the pane), writes a PNG and quits. Debug builds only.
/// `-kaikuSnapshotSize 980x720` picks the window size (default: the minimum, 720 × 480). The pane lays out
/// statically (no ScrollView), so anything that would need scrolling shows up clipped at the bottom edge.
enum DebugSnapshot {
    static var isSnapshot: Bool { UserDefaults.standard.string(forKey: "kaikuSnapshot") != nil }

    /// Snapshot runs never touch the Keychain: the pairing comes from `-kaikuSnapshotPair <link>`, in memory only.
    @MainActor static func model() -> AppModel {
        AppModel(pairing: UserDefaults.standard.string(forKey: "kaikuSnapshotPair").flatMap(Pairing.parse))
    }

    @MainActor static func runIfAsked(app: AppModel) {
        guard let path = UserDefaults.standard.string(forKey: "kaikuSnapshot") else { return }
        QuickTalkSnapshot.runIfAsked(app: app)
        let dims = (UserDefaults.standard.string(forKey: "kaikuSnapshotSize") ?? "720x480")
            .split(separator: "x").compactMap { Double($0) }
        let w = dims.count == 2 ? dims[0] : 720, h = (dims.count == 2 ? dims[1] : 480) - 28   // minus the title bar
        let delay = UserDefaults.standard.double(forKey: "kaikuSnapshotDelay")
        DispatchQueue.main.asyncAfter(deadline: .now() + (delay > 0 ? delay : 4)) {
            let route = UserDefaults.standard.string(forKey: "kaikuRoute").flatMap(KaikuRoute.init(rawValue:))
            let view = HStack(spacing: 0) {
                MacSidebarSnapshot(selected: route?.tab ?? app.selectedTab).frame(width: 220)
                NavigationStack { KaikuPanePreview(tab: app.selectedTab, route: route) }
                    .frame(width: w - 220, height: h)
                    .clipped()
            }
            .environment(app)
            .environment(\.kaikuStaticLayout, true)
            .frame(width: w, height: h)
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
    /// Only as tall as the small call island needs.
    var tight = false
    var body: some View {
        let w: CGFloat = 760
        let strip = model.hasNotch ? model.notchWidth + 2 * model.wing : 0
        let winW = MacIslandLayout.expanded.width + 2 * NotchIsland.shadowPad
        let full = model.menuBar + MacIslandShape.pillGap + MacIslandLayout.bodyHeight(expanded: true) + NotchIsland.shadowPad
        let winH = tight ? model.menuBar + QuickTalkLayout.islandCall.height + 2 * NotchIsland.shadowPad : full
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
/// `-kaikuQuickTalkSnapshot <dir>` (together with `-kaikuSnapshot`, so the run is a snapshot run: nothing is armed,
/// no window is made, no conversation starts, the app quits by itself): PNGs of the quick-talk surface, light and
/// dark, 2x. Each is the real `QuickTalkSurface` at the left edge of a desktop-grey ground (the screen edge):
/// the bar at rest, the pill under the pointer, the popup in each state, the bar and the pill while a
/// conversation is on; plus `sheet.png` of them all, `reactions.png` (the drawn glyphs, large) and
/// `island-call.png` (the notch island showing a call). They are drawn from seeded `QuickTalkDisplay` values
/// (layout stills: the person's line is the demo sentence, Kaiku's lines are the app's own scripted copy, not
/// model output). With `-kaikuTalkDemo <state>` as well, `demo-<state>*.png` and `demo-<state>.txt` are what the
/// real `QuickTalkModel` + `TalkModel` + `Conversation` show on the scripted stand-in Live (no network, no
/// microphone, no sound): the popup, then put away (the bar with its meter, the island following the model).
/// With `-kaikuQuickTalkProbe YES` instead, `window-probe.txt` and `window-*.png` are the real quick-talk window
/// (made, placed, hovered with handed-in pointer positions, opened inert, closed): what it is and what it drew.
enum QuickTalkSnapshot {
    struct Still { let name: String; let stage: QuickTalkStage; let display: QuickTalkDisplay; var live = false; var meter = QuickTalkMeter() }

    @MainActor static func runIfAsked(app: AppModel) {
        guard let dir = UserDefaults.standard.string(forKey: "kaikuQuickTalkSnapshot") else { return }
        let out = URL(fileURLWithPath: dir, isDirectory: true)
        try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        let said = "I'm not feeling too well"
        let reply = T("talk.scripted.1")
        let long = [T("talk.scripted.1"), T("talk.scripted.2"), T("talk.scripted.3")].joined(separator: " ")
        let card = ActivityCard(kind: "breathe")
        let rest = QuickTalkDisplay(state: .ended, lineKey: "call.line.ready")
        let on = QuickTalkDisplay(state: .listening, micLive: true, mascot: .listening)
        let stills: [Still] = [
            Still(name: "bar-rest", stage: .bar, display: rest),
            Still(name: "bar-hover", stage: .pill, display: rest),
            Still(name: "popup-waking", stage: .popup, display: QuickTalkDisplay(state: .connecting, mascot: .thinking)),
            Still(name: "popup-listening-hint", stage: .popup, display: on, live: true),
            Still(name: "popup-listening-caption", stage: .popup,
                  display: QuickTalkDisplay(state: .hearing, person: said, micLive: true, mascot: .listening), live: true),
            Still(name: "popup-thinking", stage: .popup,
                  display: QuickTalkDisplay(state: .thinking, person: said, micLive: true, mascot: .thinking), live: true),
            Still(name: "popup-speaking-reaction", stage: .popup,
                  display: QuickTalkDisplay(state: .speaking, person: "I went for a walk this morning", kaiku: reply, micLive: true,
                                            mascot: .happy, reaction: .sparkle), live: true),
            Still(name: "popup-speaking-gentle", stage: .popup,
                  display: QuickTalkDisplay(state: .speaking, person: said, kaiku: reply, micLive: true, mascot: .cozy, reaction: .heart), live: true),
            Still(name: "popup-listening-curious", stage: .popup,
                  display: QuickTalkDisplay(state: .listening, person: said, kaiku: reply, micLive: true, mascot: .listening, reaction: .curious), live: true),
            Still(name: "popup-speaking-long", stage: .popup,
                  display: QuickTalkDisplay(state: .speaking, person: said + ", and I did not sleep much either", kaiku: long,
                                            micLive: true, voiceMuted: true, mascot: .speaking), live: true),
            Still(name: "popup-muted", stage: .popup, display: QuickTalkDisplay(state: .muted, person: said, kaiku: reply, mascot: .sleepy), live: true),
            Still(name: "popup-activity", stage: .popup,
                  display: QuickTalkDisplay(state: .listening, person: said, kaiku: reply, micLive: true, mascot: .listening, activity: card), live: true),
            Still(name: "popup-captions-off", stage: .popup,
                  display: QuickTalkDisplay(state: .hearing, captions: false, person: said, micLive: true, mascot: .listening), live: true),
            Still(name: "popup-captions-off-muted", stage: .popup, display: QuickTalkDisplay(state: .muted, captions: false, mascot: .sleepy), live: true),
            Still(name: "popup-not-connected", stage: .popup, display: QuickTalkDisplay(state: .notConnected, lineKey: "call.line.unpaired")),
            Still(name: "popup-paused", stage: .popup, display: QuickTalkDisplay(state: .paused, captions: false, lineKey: "call.line.paused")),
            Still(name: "popup-microphone-off", stage: .popup, display: QuickTalkDisplay(state: .micDenied, lineKey: "talk.unavailable.microphone")),
            Still(name: "popup-voice-unavailable", stage: .popup, display: QuickTalkDisplay(state: .unavailable, lineKey: "call.line.voice")),
            Still(name: "popup-setup", stage: .popup, display: QuickTalkDisplay(state: .setup, lineKey: "quick.setup")),
            Still(name: "popup-ended", stage: .popup, display: QuickTalkDisplay(state: .ended, lineKey: "call.ended")),
            Still(name: "bar-live-person", stage: .bar, display: on, live: true, meter: QuickTalkMeter(micOpen: true, level: 0.8)),
            Still(name: "bar-live-kaiku", stage: .bar, display: on, live: true, meter: QuickTalkMeter(micOpen: true, level: 0, kaikuSpeaking: true)),
            Still(name: "bar-live-muted", stage: .bar, display: on, live: true, meter: QuickTalkMeter()),
            Still(name: "bar-live-hover", stage: .pill, display: on, live: true),
        ]
        let pinned = Date().addingTimeInterval(-1.5)
        for dark in [false, true] {
            let suffix = dark ? "-dark" : ""
            for still in stills {
                write(edge(still, pinned: pinned, dark: dark), to: out.appendingPathComponent("\(still.name)\(suffix).png"), dark: dark)
            }
            let sheet = VStack(alignment: .leading, spacing: 2) {
                ForEach(stills, id: \.name) { still in
                    HStack(alignment: .center, spacing: 16) {
                        edge(still, pinned: pinned, dark: dark, tight: true)
                        Text(still.name).font(.system(size: 13, weight: .medium, design: .monospaced))
                            .foregroundStyle(Color(white: dark ? 0.8 : 0.25))
                    }
                }
            }
            .padding(.trailing, 24)
            .background(Color(white: dark ? 0.16 : 0.78))
            write(sheet, to: out.appendingPathComponent("sheet\(suffix).png"), dark: dark)
            // The drawn reactions, large (they are 18 pt beside Kaiku).
            let glyphs = HStack(spacing: 28) {
                ForEach(QuickTalkReaction.allCases, id: \.self) { r in
                    VStack(spacing: 10) {
                        QuickTalkReactionGlyph(reaction: r).scaleEffect(4).frame(width: 80, height: 80)
                        Text(r.rawValue).font(.system(size: 12, design: .monospaced)).foregroundStyle(KaikuTokens.Colors.muted)
                    }
                }
            }
            .padding(24)
            .background(KaikuTokens.Colors.surface)
            write(glyphs, to: out.appendingPathComponent("reactions\(suffix).png"), dark: dark)
        }
        write(islandSheet(calls: [QuickTalkCall(status: .listening, since: Date().addingTimeInterval(-134), micOn: true),
                                  QuickTalkCall(status: .speaking, since: Date().addingTimeInterval(-41), micOn: true),
                                  QuickTalkCall(status: .muted, since: Date().addingTimeInterval(-605), micOn: false)], pinned: pinned),
              to: out.appendingPathComponent("island-call.png"))

        // The real model on the scripted stand-in Live (the Talk demo argument; no microphone, no network).
        guard let demo = UserDefaults.standard.string(forKey: "kaikuTalkDemo") else {
            // Without it, `-kaikuQuickTalkProbe YES` checks the real window (inert: nothing can start).
            if UserDefaults.standard.bool(forKey: "kaikuQuickTalkProbe") {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { QuickTalkController.shared.probe(app: app, into: out) }
            }
            return
        }
        let model = QuickTalkController.shared.model
        let island = MacCompanion.shared.island
        var log: [String] = []
        func note(_ what: String) {
            log.append("\(what): stage=\(model.stage.rawValue) open=\(model.isOpen) live=\(model.isLive) display=\(model.display.state.rawValue) "
                + "call=\(model.call.map { $0.status.rawValue + (($0.micOn) ? " mic-on" : " mic-off") } ?? "none") island=\(island.model.state)")
        }
        note("before")
        model.inert = false
        model.open(app: app)
        model.inert = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.2) {
            note("popup")
            write(edge(Still(name: "", stage: model.stage, display: model.display, live: model.isLive, meter: model.meter), pinned: pinned, dark: false),
                  to: out.appendingPathComponent("demo-\(demo).png"))
            model.collapse()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                note("put away")
                write(edge(Still(name: "", stage: model.stage, display: model.display, live: model.isLive, meter: model.meter), pinned: pinned, dark: false),
                      to: out.appendingPathComponent("demo-\(demo)-away.png"))
                // The app's own island, following the model (not a seeded copy).
                island.model.loopStart = pinned
                write(MenuBarSlice(model: island.model, shape: nil).padding(12).background(Color(white: 0.75)),
                      to: out.appendingPathComponent("demo-\(demo)-island.png"))
                model.perform(.microphone)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                    note("muted from the island")
                    model.end()
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                        note("ended")
                        try? log.joined(separator: "\n").write(to: out.appendingPathComponent("demo-\(demo).txt"), atomically: true, encoding: .utf8)
                    }
                }
            }
        }
    }

    /// The surface as it sits on screen: the left edge of this picture is the left edge of the screen.
    @MainActor static func edge(_ still: Still, pinned: Date, dark: Bool, tight: Bool = false) -> some View {
        let card = still.display.cardSize
        let w = QuickTalkLayout.margin + QuickTalkLayout.wide.width + QuickTalkLayout.shadowPad
        let h = still.stage == .popup ? card.height + (tight ? 20 : 2 * QuickTalkLayout.shadowPad) : QuickTalkLayout.pill.height + 28
        return QuickTalkSurface(stage: still.stage, display: still.display, live: still.live, meter: still.meter, loopStart: pinned) { _ in }
            .frame(width: w, height: h)
            .background(Color(white: dark ? 0.16 : 0.78))
    }

    /// The notch island showing a call, on this Mac's own notch (or a typical one) and on a Mac without a notch.
    @MainActor static func islandSheet(calls: [QuickTalkCall], pinned: Date) -> some View {
        let g = MacIslandGeometry.pick(NSScreen.screens.map(NotchIsland.screenInfo)).map { MacIslandGeometry.compute($0) }
        @MainActor func island(_ call: QuickTalkCall, notch: Bool) -> IslandModel {
            let m = IslandModel()
            m.hasNotch = notch
            m.notchWidth = notch ? (g?.notch?.width ?? 185) : 0
            m.wing = notch ? (g?.notch != nil ? g?.wing ?? 60 : 60) : 0
            m.menuBar = notch ? (g?.notch != nil ? g?.menuBar ?? 32 : 32) : 24
            m.call = call; m.state = .call; m.risen = true; m.loopStart = pinned
            return m
        }
        return VStack(spacing: 12) {
            ForEach(Array(calls.enumerated()), id: \.offset) { _, call in MenuBarSlice(model: island(call, notch: true), shape: nil, tight: true) }
            if let first = calls.first { MenuBarSlice(model: island(first, notch: false), shape: nil, tight: true) }
            if let last = calls.last { MenuBarSlice(model: island(last, notch: false), shape: nil, tight: true) }
        }
        .padding(12)
        .background(Color(white: 0.75))
    }

    /// The token colours follow the appearance they are drawn in: render under the one asked for.
    @MainActor static func write(_ view: some View, to url: URL, dark: Bool = false) {
        let r = ImageRenderer(content: view.environment(\.colorScheme, dark ? .dark : .light))
        r.scale = 2
        NSAppearance(named: dark ? .darkAqua : .aqua)?.performAsCurrentDrawingAppearance {
            if let img = r.nsImage, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
                try? rep.representation(using: .png, properties: [:])?.write(to: url)
            }
        }
    }
}

/// A drawn stand-in for the List sidebar (ImageRenderer can't draw NSTableView-backed lists).
private struct MacSidebarSnapshot: View {
    let selected: KaikuTab
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(KaikuTab.allCases) { tab in
                HStack(spacing: 10) {
                    Image(systemName: tab.symbol).frame(width: 20)
                    Text(tab.title).kText(.body, weight: .medium)
                }
                .foregroundStyle(KaikuTokens.Colors.ink)
                .padding(.horizontal, 10).padding(.vertical, 7)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8).fill(tab == selected ? KaikuTokens.Colors.clay.opacity(0.16) : .clear))
            }
            Spacer()
        }
        .padding(.top, 34).padding(.horizontal, 10)
        .background(KaikuTokens.Colors.surface2)
    }
}
#else
import KaikuKit
enum DebugSnapshot {
    static let isSnapshot = false
    @MainActor static func model() -> AppModel { AppModel() }
}
#endif

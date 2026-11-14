#if DEBUG
import AppKit
import KaikuKit
import SwiftUI

/// Layout check without screen-recording permission: `-kaikuSnapshot /path.png` renders the Mac window for the
/// selected tab/route with ImageRenderer (a drawn sidebar + the pane), writes a PNG and quits. Debug builds only.
/// `-kaikuSnapshotSize 980x720` picks the window size (default: the minimum, 720 × 480). The pane lays out
/// statically (no ScrollView), so anything that would need scrolling shows up clipped at the bottom edge.
enum DebugSnapshot {
    /// A picture-taking run: nothing is armed, nothing is sampled or scheduled, the app quits by itself.
    static var isSnapshot: Bool { UserDefaults.standard.string(forKey: "kaikuSnapshot") != nil || isQuiet }
    /// `-kaikuWindowShots`: the run also stays out of the person's way (no Dock icon, no focus, an unseen window).
    static var isQuiet: Bool { WindowShots.dir != nil }

    /// Snapshot runs never touch the Keychain: the pairing comes from `-kaikuSnapshotPair <link>`, in memory only.
    @MainActor static func model() -> AppModel {
        AppModel(pairing: UserDefaults.standard.string(forKey: "kaikuSnapshotPair").flatMap(Pairing.parse))
    }

    @MainActor static func runIfAsked(app: AppModel) {
        WindowShots.runIfAsked(app: app)
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

/// `-kaikuWindowShots <dir>`: pictures of the REAL main window, taken from inside the app (a view may draw itself
/// into a bitmap: `cacheDisplay`, no Screen Recording permission). Unlike `-kaikuSnapshot` this is the window the
/// person uses: real switches, real pickers, the real scroll view, the real sidebar. One run walks the screens,
/// each at every size and look, and where a pane is longer than the window it is scrolled a page at a time
/// (`-p2`, `-p3`); a sheet the screen has open is pictured too (`-sheet`). It writes
/// `<screen>-<w>x<h>-<look>[-pN].png` at 2x, `shots-<look>.txt` (what was taken, and each pane's content height
/// against what the window shows) and `sheet-<w>x<h>.png`, a contact sheet of every picture of that size in the folder.
///
/// What the pictures cannot show: the window is drawn part by part (the whole window comes out blank on macOS 26),
/// so the sidebar's and the title bar's glass are flat fills, and because the window is never the key window its
/// switches are drawn in the grey of an inactive window where the person sees them in sage.
///
/// The run is a snapshot run (inert quick talk, no usage sampling, no notification scheduling, in-memory pairing)
/// and a quiet one: no Dock icon, no menu bar item, never frontmost, the window at 1 % opacity and deaf to the mouse.
/// - `-kaikuShotScreens you,memories,…` (default: You and its screens). Every tab root but Talk, the You routes,
///   and the games that open no sensor (`breathe`, `lantern`, `seeds`, `watering`, `pebbles`, `firefly`; one game a
///   run, since a pushed screen is not popped). Talk, Tell and the walk are refused (they open a conversation or
///   a microphone); the check-in (`weather`) only together with `-kaikuTalkDemo <state>`, the scripted Live.
///   `window` is the window as it stands (a setup step with `-kaikuOnboardingStep 3`, without `-kaikuSkipOnboarding`).
/// - `-kaikuShotSizes 980x720,720x480` (the window's size; the smallest the window allows is 720 × 532, the
///   480 pt of content under its 52 pt title bar) · `-kaikuShotLook light|dark` (one look a run: the app is
///   launched in it; without it, the system's)
/// - `-kaikuShotsOnline YES` draws the pane as when the service answers (the "can't reach the cloud" banner off);
///   pair with `-kaikuSnapshotPair` to an address nothing listens on, never to a real service.
/// - `-kaikuShotName <text>` is added to every file name (a second run with `-kaikuYouOpen sharing`, say).
/// - `-kaikuShotCompare "<before dir>|<after dir>"` writes only `compare-<w>x<h>-<look>.png` into `<dir>`: every
///   picture of either folder beside the one of the same name in the other.
enum WindowShots {
    static var dir: String? { UserDefaults.standard.string(forKey: "kaikuWindowShots") }
    static let tabs: [KaikuTab] = KaikuTab.allCases.filter { $0 != .talk }   // Talk opens a conversation
    /// The You screens, and the games that open no sensor of their own (with `-kaikuAutostart YES` a game is
    /// pictured while it is played). A picture run never opens a camera: the task camera is closed in it
    /// (`TaskCamera.standard`), and `-kaikuFaceSource scripted` shows the indicator on the stand-in source. The
    /// check-in is opened only on the scripted Live (`-kaikuTalkDemo <state>`: no network, no microphone).
    static var routes: [KaikuRoute] {
        let games: [KaikuRoute] = [.breathe, .lantern, .seeds, .watering, .pebbles, .firefly]
        let scripted = UserDefaults.standard.string(forKey: "kaikuTalkDemo") != nil
        return [.memories, .saw, .voice, .quiet, .devices, .help] + games + (scripted ? [.weather] : [])
    }
    @MainActor static var started = false

    @MainActor static func runIfAsked(app: AppModel) {
        guard let dir, !started else { return }
        started = true
        let out = URL(fileURLWithPath: dir, isDirectory: true)
        try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        Task { @MainActor in
            if let pair = UserDefaults.standard.string(forKey: "kaikuShotCompare") {
                compare(pair, into: out)
            } else {
                await run(app: app, out: out)
            }
            exit(0)   // the pictures are written; an open sheet would hold an ordinary quit back
        }
    }

    static func pause(_ seconds: Double) async { try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) }

    @MainActor static func mainWindow() -> NSWindow? {
        NSApp.windows.first { !($0 is NSPanel) && ($0.identifier?.rawValue.contains("main") == true || $0.title == "Kaiku") }
    }

    @MainActor static func run(app: AppModel, out: URL) async {
        let d = UserDefaults.standard
        func list(_ key: String, _ fallback: String) -> [String] {
            (d.string(forKey: key) ?? fallback).split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        }
        let names = list("kaikuShotScreens", "you,memories,saw,voice,quiet,devices,help")
        let sizes: [CGSize] = list("kaikuShotSizes", "980x720,720x480").compactMap {
            let p = $0.split(separator: "x").compactMap { Double($0) }
            return p.count == 2 ? CGSize(width: p[0], height: p[1]) : nil
        }
        // One look a run: the whole app is launched in it (`KaikuMacApp.init`); switching a live window's
        // appearance left the pane drawn in the old one.
        let dark = NSApp.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        let looks = [dark ? "dark" : "light"]
        let online = d.bool(forKey: "kaikuShotsOnline")
        let tag = d.string(forKey: "kaikuShotName").map { "-" + $0 } ?? ""
        var log: [String] = []
        defer { try? log.joined(separator: "\n").write(to: out.appendingPathComponent("shots\(tag)-\(looks[0]).txt"), atomically: true, encoding: .utf8) }

        var found: NSWindow?
        for _ in 0..<60 where found == nil { found = mainWindow(); if found == nil { await pause(0.1) } }
        guard let window = found else { log.append("no main window"); return }
        // Almost, not fully, transparent: a window the system counts as unseen is redrawn late, and the pictures
        // then show the state before the last change. Every window of this run, a sheet too, as soon as it is there.
        let alpha = 0.01
        func ghost() { for w in NSApp.windows where w.alphaValue != alpha || !w.ignoresMouseEvents { w.alphaValue = alpha; w.ignoresMouseEvents = true } }
        for _ in 0..<15 { ghost(); await pause(0.1) }
        if online, app.isPaired {   // the first load has to have failed before its banner can be taken away for good
            for _ in 0..<50 where !app.offline { await pause(0.15) }
            app.offline = false
            await pause(0.4)
        }
        log.append("window: policy=\(NSApp.activationPolicy().rawValue) (accessory=\(NSApplication.ActivationPolicy.accessory.rawValue)) "
            + "appActive=\(NSApp.isActive) key=\(window.isKeyWindow) alpha=\(window.alphaValue) paired=\(app.isPaired) offline=\(app.offline) online-look=\(online)")

        // Tab roots first: a pushed screen cannot be popped from here.
        var screens: [(name: String, go: () -> Void)] = []
        for n in names { if let t = tabs.first(where: { $0.rawValue == n }) { screens.append((n, { app.selectedTab = t })) } }
        for n in names { if let r = routes.first(where: { $0.rawValue == n }) { screens.append((n, { app.deepLink = r })) } }
        if names.contains("window") { screens.append(("window", {})) }   // the window as it stands (setup, say)
        let refused = names.filter { n in !screens.contains { $0.name == n } }
        if !refused.isEmpty { log.append("refused (not a screen this tool opens): \(refused.joined(separator: ", "))") }

        for screen in screens {
            screen.go()
            await pause(0.9)
            for look in looks {
                for size in sizes {
                    window.setContentSize(size)
                    await pause(0.6)
                    if online { app.offline = false; await pause(0.3) }
                    let base = "\(screen.name)\(tag)-\(Int(size.width))x\(Int(size.height))-\(look)"
                    ghost()
                    let note = await shoot(window, base: base, out: out)
                    log.append("\(base): window \(Int(window.frame.width))x\(Int(window.frame.height)), \(note)")
                    if let sheet = window.attachedSheet {   // a sheet is a window of its own: its own picture
                        let n = await shoot(sheet, base: base + "-sheet", out: out)
                        log.append("\(base)-sheet: \(Int(sheet.frame.width))x\(Int(sheet.frame.height)), \(n)")
                    }
                }
            }
        }
        // One sheet a size, of every picture of that size in the folder (so a second run in the other look adds to it).
        let files = inOrder(((try? FileManager.default.contentsOfDirectory(atPath: out.path)) ?? []).filter { $0.hasSuffix(".png") })
        for size in sizes {
            let key = "\(Int(size.width))x\(Int(size.height))"
            let items = files.filter { $0.contains("-\(key)-") && !$0.hasPrefix("sheet") && !$0.hasPrefix("compare") }
                .map { (String($0.dropLast(4)), Optional(out.appendingPathComponent($0))) }
            sheet(items, columns: 4, cell: CGSize(width: size.width / 2, height: size.height / 2), to: out.appendingPathComponent("sheet-\(key).png"))
        }
    }

    /// One window's pictures: as it stands, and a page at a time where its pane is longer than what shows.
    @MainActor static func shoot(_ window: NSWindow, base: String, out: URL) async -> String {
        let scroll = pane(in: window)
        var offsets: [CGFloat] = [0]
        var note = "fits"
        if let scroll, let doc = scroll.documentView {
            // The pane rests with its top under the title bar's inset; a page is what shows below it.
            let inset = scroll.contentInsets.top
            let visible = scroll.contentView.bounds.height, total = doc.frame.height
            let last = total - visible, page = max(80, visible - inset - 56)
            offsets = [-inset]
            var y = -inset + page
            while y < last && offsets.count < 6 { offsets.append(y); y += page }
            offsets.append(last)
            note = "scrolls: content \(Int(total)) pt, \(Int(visible - inset)) pt show (\(offsets.count) pages)"
        }
        for (i, y) in offsets.enumerated() {
            if let scroll, let doc = scroll.documentView {
                let top = doc.isFlipped ? y : doc.frame.height - scroll.contentView.bounds.height - y
                scroll.contentView.scroll(to: NSPoint(x: 0, y: top))
                scroll.reflectScrolledClipView(scroll.contentView)
                await pause(0.25)
            }
            _ = capture(window, to: out.appendingPathComponent(i == 0 ? "\(base).png" : "\(base)-p\(i + 1).png"))
        }
        if let scroll, let doc = scroll.documentView {   // back to the top for the next size
            scroll.contentView.scroll(to: NSPoint(x: 0, y: doc.isFlipped ? -scroll.contentInsets.top : doc.frame.height - scroll.contentView.bounds.height))
            scroll.reflectScrolledClipView(scroll.contentView)
        }
        return note
    }

    /// The pane's scroll view when its content is taller than what shows (the widest one: not the sidebar).
    @MainActor static func pane(in window: NSWindow) -> NSScrollView? {
        var best: NSScrollView?
        func walk(_ v: NSView) {
            if let s = v as? NSScrollView, let doc = s.documentView, s.frame.width > 300,
               doc.frame.height > s.contentView.bounds.height - s.contentInsets.top + 1, s.frame.width > (best?.frame.width ?? 0) { best = s }
            v.subviews.forEach(walk)
        }
        if let root = window.contentView { walk(root) }
        return best
    }

    /// The window's content as its own views draw it. The window as a whole cannot draw itself into a bitmap (the
    /// glass of the sidebar and the title bar are the window server's, and a `cacheDisplay` of the whole comes out
    /// blank), but its parts can: each column's SwiftUI view (the page backdrop, anything that does not scroll),
    /// then every scrolled area on top of it at its real place and scroll position. So everything in the pane is
    /// the real drawing (switches, pickers, text, the scroll position); only the sidebar's and the title bar's
    /// materials are a flat fill.
    @MainActor static func capture(_ window: NSWindow, to url: URL) -> Bool {
        guard let root = window.contentView else { return false }
        let size = root.bounds.size, scale = window.backingScaleFactor
        guard size.width > 0, size.height > 0,
              let canvas = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * scale), pixelsHigh: Int(size.height * scale),
                                            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return false }
        canvas.size = size
        guard let context = NSGraphicsContext(bitmapImageRep: canvas) else { return false }

        func place(_ v: NSView) -> NSRect {   // the view's rectangle on the canvas (origin bottom-left)
            let r = v.convert(v.bounds, to: root)
            return NSRect(x: r.minX, y: root.isFlipped ? size.height - r.maxY : r.minY, width: r.width, height: r.height)
        }
        func draw(_ v: NSView) {
            guard v.bounds.width > 0, v.bounds.height > 0, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { return }
            v.cacheDisplay(in: v.bounds, to: rep)
            rep.draw(in: place(v), from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: false, hints: nil)
        }
        func all<T: NSView>(_ type: T.Type, in v: NSView, into found: inout [T]) {
            if let t = v as? T { found.append(t) }
            v.subviews.forEach { all(type, in: $0, into: &found) }
        }
        func named(_ prefix: String, in v: NSView, into found: inout [NSView]) {
            if String(describing: Swift.type(of: v)).hasPrefix(prefix) { found.append(v); return }
            v.subviews.forEach { named(prefix, in: $0, into: &found) }
        }

        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = context
        let dark = NSApp.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        NSApp.effectiveAppearance.performAsCurrentDrawingAppearance {
            // The page backdrop is drawn afresh (it is a gradient the window's own view does not hand over).
            let backdrop = ImageRenderer(content: KBackdrop().frame(width: size.width, height: size.height)
                .environment(\.colorScheme, dark ? .dark : .light))
            backdrop.scale = scale
            if let image = backdrop.nsImage {
                image.draw(in: NSRect(origin: .zero, size: size), from: .zero, operation: .sourceOver, fraction: 1)
            } else {
                NSColor(KaikuTokens.Colors.bg).setFill()
                NSRect(origin: .zero, size: size).fill()
            }
            // The columns, widest first (the pane lies under the sidebar).
            var columns: [NSView] = []
            named("_NSSplitViewItemViewWrapper", in: root, into: &columns)
            if columns.isEmpty { columns = [root] }
            for (i, column) in columns.sorted(by: { $0.frame.width > $1.frame.width }).enumerated() {
                if i > 0 {   // a sidebar: its glass, as a flat fill
                    NSColor(KaikuTokens.Colors.surface2).withAlphaComponent(0.94).setFill()
                    place(column).fill()
                    NSColor(KaikuTokens.Colors.line).setFill()
                    NSRect(x: place(column).maxX, y: 0, width: 1, height: size.height).fill()
                }
                var hosts: [NSView] = []
                named("NSHostingView", in: column, into: &hosts)
                (hosts.isEmpty ? [column] : hosts).forEach(draw)
                var clips: [NSClipView] = []
                all(NSClipView.self, in: column, into: &clips)
                clips.forEach(draw)
            }
        }
        NSGraphicsContext.restoreGraphicsState()
        return (try? canvas.representation(using: .png, properties: [:])?.write(to: url)) != nil
    }

    /// File names in reading order: a screen's first page before its `-p2` (plain sorting puts "-p2.png" first).
    static func inOrder(_ names: [String]) -> [String] { names.sorted { $0.dropLast(4) < $1.dropLast(4) } }

    /// Before | after: every picture of either folder beside the one of the same name in the other (a page
    /// only one of them has stands beside an empty cell).
    @MainActor static func compare(_ pair: String, into out: URL) {
        let dirs = pair.split(separator: "|").map { URL(fileURLWithPath: String($0), isDirectory: true) }
        guard dirs.count == 2 else { return }
        func pictures(_ dir: URL) -> [String] {
            ((try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? [])
                .filter { $0.hasSuffix(".png") && !$0.hasPrefix("sheet") && !$0.hasPrefix("compare") }
        }
        let names = inOrder(Array(Set(pictures(dirs[0])).union(pictures(dirs[1]))))
        func there(_ u: URL) -> URL? { FileManager.default.fileExists(atPath: u.path) ? u : nil }
        var groups: [String: [(String, URL?)]] = [:]
        var cells: [String: CGSize] = [:]
        for name in names {
            // <screen>…-<w>x<h>-<look>[-pN].png
            guard let m = name.range(of: #"-(\d+)x(\d+)-(light|dark)"#, options: .regularExpression) else { continue }
            let key = String(name[m]).dropFirst()
            let dims = key.split(separator: "-")[0].split(separator: "x").compactMap { Double($0) }
            cells[String(key)] = CGSize(width: dims[0] * 0.75, height: dims[1] * 0.75)   // large enough to read
            let label = String(name.dropLast(4))
            groups[String(key), default: []].append(("before  " + label, there(dirs[0].appendingPathComponent(name))))
            groups[String(key), default: []].append(("after   " + label, there(dirs[1].appendingPathComponent(name))))
        }
        for (key, items) in groups {
            sheet(items, columns: 2, cell: cells[key] ?? CGSize(width: 490, height: 360), to: out.appendingPathComponent("compare-\(key).png"))
        }
    }

    /// A contact sheet: labelled thumbnails in a grid (a missing picture is a grey cell).
    static func sheet(_ items: [(String, URL?)], columns: Int, cell: CGSize, to url: URL) {
        guard !items.isEmpty else { return }
        let pad: CGFloat = 16, label: CGFloat = 26
        let rows = (items.count + columns - 1) / columns
        let w = Int(CGFloat(columns) * (cell.width + pad) + pad), h = Int(CGFloat(rows) * (cell.height + label + pad) + pad)
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8, samplesPerPixel: 4,
                                         hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
              let context = NSGraphicsContext(bitmapImageRep: rep) else { return }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = context
        NSColor(white: 0.8, alpha: 1).setFill()
        NSRect(x: 0, y: 0, width: w, height: h).fill()
        let text: [NSAttributedString.Key: Any] = [.font: NSFont.monospacedSystemFont(ofSize: 12, weight: .medium),
                                                   .foregroundColor: NSColor(white: 0.12, alpha: 1)]
        for (i, item) in items.enumerated() {
            let x = pad + CGFloat(i % columns) * (cell.width + pad)
            let top = CGFloat(h) - pad - CGFloat(i / columns) * (cell.height + label + pad)
            (item.0 as NSString).draw(at: NSPoint(x: x, y: top - label + 7), withAttributes: text)
            let r = NSRect(x: x, y: top - label - cell.height, width: cell.width, height: cell.height)
            NSColor(white: 0.7, alpha: 1).setFill()
            r.fill()
            if let u = item.1, let image = NSImage(contentsOf: u), image.size.width > 0, image.size.height > 0 {
                let s = min(cell.width / image.size.width, cell.height / image.size.height)
                let size = NSSize(width: image.size.width * s, height: image.size.height * s)
                image.draw(in: NSRect(x: r.minX, y: r.maxY - size.height, width: size.width, height: size.height),
                           from: .zero, operation: .sourceOver, fraction: 1)
            }
        }
        NSGraphicsContext.restoreGraphicsState()
        try? rep.representation(using: .png, properties: [:])?.write(to: url)
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
    static let isQuiet = false
    @MainActor static func model() -> AppModel { AppModel() }
}
#endif

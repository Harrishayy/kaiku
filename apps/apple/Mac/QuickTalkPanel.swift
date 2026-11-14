import AppKit
import Carbon.HIToolbox
import KaikuKit
import SwiftUI

/// Quick talk (Mac): a thin Kaiku-coloured bar at the left edge of the screen, always there while quick talk is on.
/// Under the pointer it grows into a pill with two buttons (start speaking, open Kaiku). ⌥⇧Space in any app (or a
/// double tap of a modifier key, when the person turned that on) grows it into the popup with Kaiku already
/// listening. This file is the AppKit side only: the window, the system hot key, the modifier monitor, the
/// pointer. What the surface shows and the conversation behind it are `QuickTalkModel` (KaikuKit/Mac), the same
/// `TalkModel` the Talk screen uses.
///
/// ONE window holds the bar, the pill and the popup (they are one shape that grows, `QuickTalkSurface`). It is a
/// borderless non-activating panel: it never takes keyboard focus from the app the person is in, floats above
/// normal windows, is on every Space and beside full-screen apps, and lets the mouse through everywhere except
/// the pill and the popup card (the resting bar takes no clicks at all). At rest it lives on the screen the
/// pointer is on. With the bar turned off the window is ordered out until the trigger.
///
/// Permissions (checked on macOS 26.5 with an app that has neither Accessibility nor Input Monitoring):
/// - the key combination and Esc are Carbon hot keys (`RegisterEventHotKey`): none needed;
/// - the double tap reads modifier changes from a global `flagsChanged` monitor, which macOS delivers without a
///   permission (key presses are not delivered, and are not asked for): "nothing else was pressed in between"
///   comes from the system's running count of key and mouse presses, never from which keys they were;
/// - the pointer's position (`NSEvent.mouseLocation`) needs none.
@MainActor
final class QuickTalkController {
    static let shared = QuickTalkController()

    let model = QuickTalkModel.shared
    private weak var app: AppModel?
    private var panel: NSPanel?
    private(set) var geometry: QuickTalkGeometry?
    private var hotKey: HotKey?
    private var escape: HotKey?
    private var monitors: [Any] = []
    private var detector: QuickTalkDoubleTap?
    private var pointerTimer: Timer?
    private var hideWork: DispatchWorkItem?
    private var lastTrigger = Date.distantPast
    private var started = false

    /// Called from both scenes' `onAppear` (like `MacCompanion.start`). `openMain` brings the main window forward.
    func start(app: AppModel, openMain: @escaping @MainActor (KaikuTab?) -> Void) {
        guard !started else { return }
        started = true
        self.app = app
        // Layout snapshots and inspection runs look at the app without ever starting a conversation: no window,
        // no hot key, no monitor.
        model.inert = DebugSnapshot.isSnapshot || UserDefaults.standard.bool(forKey: "kaikuInspectOnly")
        model.attach(app: app)
        model.openMain = openMain
        model.mainShowsTalk = { [weak app] in
            guard let app, app.onboarded, app.selectedTab == .talk, let w = Self.mainWindow() else { return false }
            return w.isVisible || w.isMiniaturized
        }
        model.openMicrophoneSettings = {
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
                NSWorkspace.shared.open(url)
            }
        }
        model.settingsChanged = { [weak self] in self?.arm() }
        arm()
        follow()
    }

    static func mainWindow() -> NSWindow? {
        NSApp.windows.first { !($0 is NSPanel) && ($0.identifier?.rawValue.contains("main") == true || $0.title == "Kaiku") }
    }

    // MARK: triggers

    /// (Re)arms what the settings ask for. Nothing is armed in an inert run.
    private func arm() {
        hotKey = nil
        monitors.forEach(NSEvent.removeMonitor)
        monitors = []
        detector = nil
        guard model.enabled, !model.inert else {
            // Turned off: nothing of quick talk's keeps listening.
            if model.isOpen { model.close() } else if model.isLive, !model.mainShowsTalk() { model.end() }
            return
        }
        hotKey = HotKey(keyCode: QuickTalkHotKey.keyCode, modifiers: QuickTalkHotKey.carbonModifiers) { [weak self] in self?.trigger() }
        guard let key = model.doubleTap.mods else { return }
        detector = QuickTalkDoubleTap(key: key)
        // Other apps in front: modifier changes only (macOS hands a global monitor nothing else without a permission).
        if let m = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged, handler: { [weak self] e in
            MainActor.assumeIsolated { self?.modifiersChanged(e) }
        }) { monitors.append(m) }
        // Kaiku in front: the same, from its own event stream.
        if let m = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged, handler: { [weak self] e in
            MainActor.assumeIsolated { self?.modifiersChanged(e) }
            return e
        }) { monitors.append(m) }
    }

    private func modifiersChanged(_ e: NSEvent) {
        var mods: QuickTalkMods = []
        let f = e.modifierFlags
        if f.contains(.shift) { mods.insert(.shift) }
        if f.contains(.control) { mods.insert(.control) }
        if f.contains(.option) { mods.insert(.option) }
        if f.contains(.command) { mods.insert(.command) }
        if f.contains(.function) { mods.insert(.function) }
        if detector?.modifiersChanged(mods, at: e.timestamp, input: Self.inputCount()) == true { trigger() }
    }

    /// How many keys and mouse buttons have been pressed in this login session (the system's own counters, the
    /// same family as the idle time the usage sampler reads). A count: never which key.
    static func inputCount() -> UInt64 {
        let s = CGEventSourceStateID.combinedSessionState
        return [CGEventType.keyDown, .leftMouseDown, .rightMouseDown, .otherMouseDown]
            .reduce(UInt64(0)) { $0 + UInt64(CGEventSource.counterForEventType(s, eventType: $1)) }
    }

    /// The key combination, the double tap or "Talk now": the popup grows out of the bar (a conversation put away
    /// earlier is shown as it is); pressed again while the popup is open, it closes.
    func trigger() {
        guard model.enabled, !model.inert, Date().timeIntervalSince(lastTrigger) > 0.3 else { return }
        lastTrigger = Date()
        if model.isOpen { model.close() } else { open() }
    }

    func open() {
        guard let app, !model.inert, !model.isOpen else { return }
        place()
        // Next turn of the run loop: the window is on screen, so the shape is seen growing.
        DispatchQueue.main.async { self.model.open(app: app) }
    }

    // MARK: the window

    private func makePanel() -> NSPanel {
        let p = NSPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = false   // the shape draws its own soft shadow
        p.level = .floating
        p.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        p.isMovable = false
        p.hidesOnDeactivate = false
        p.becomesKeyOnlyIfNeeded = true
        p.ignoresMouseEvents = true
        p.animationBehavior = .none
        p.allowsToolTipsWhenApplicationIsInactive = true   // the pill's two buttons are icons: their names on hover
        p.contentView = FirstMouseHostingView(rootView: QuickTalkPanelHost(model: model))
        return p
    }

    /// On the screen where the pointer is, at the left edge of its usable area, vertically centred. The bar, the
    /// pill and the popup all sit at that one place.
    private func place() {
        let screens = NSScreen.screens.map(NotchIsland.screenInfo)
        guard let screen = QuickTalkGeometry.pick(screens, pointer: NSEvent.mouseLocation) else { return }
        let g = QuickTalkGeometry.compute(screen)
        hideWork?.cancel()
        let p = panel ?? makePanel()
        panel = p
        if g != geometry || p.frame != g.window {
            geometry = g
            p.setFrame(g.window, display: true)
        }
        if !p.isVisible { p.orderFrontRegardless() }
    }

    /// The model says what the shape is (bar, pill, popup, or nothing): the window, the pointer tracking and the
    /// Esc key follow.
    private func follow() {
        let (stage, open) = withObservationTracking { (model.stage, model.isOpen) } onChange: { [weak self] in
            Task { @MainActor in self?.follow() }
        }
        guard !model.inert else { return }
        if stage != .hidden {
            if panel?.isVisible != true { place() }
            hideWork?.cancel()
            if pointerTimer == nil {
                let t = Timer(timeInterval: 0.08, repeats: true) { [weak self] _ in
                    MainActor.assumeIsolated { self?.trackPointer() }
                }
                t.tolerance = 0.02
                RunLoop.main.add(t, forMode: .common)
                pointerTimer = t
            }
        } else if panel?.isVisible == true, hideWork == nil || hideWork?.isCancelled == true {
            panel?.ignoresMouseEvents = true
            // The shape has shrunk into the edge (or faded) by then.
            let work = DispatchWorkItem { [weak self] in
                guard let self, self.model.stage == .hidden else { return }
                self.pointerTimer?.invalidate(); self.pointerTimer = nil
                self.panel?.orderOut(nil)
            }
            hideWork = work
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.7, execute: work)
        }
        if open {
            if escape == nil {
                escape = HotKey(keyCode: QuickTalkHotKey.escapeKeyCode, modifiers: 0) { [weak self] in self?.model.close() }
            }
        } else {
            escape = nil
        }
    }

    /// Twelve times a second: the bar follows the pointer's screen at rest, grows into the pill when the pointer
    /// comes to it, and the window takes the mouse only on the pill and on the popup card.
    private func trackPointer(at pointer: CGPoint = NSEvent.mouseLocation) {
        guard let panel, panel.isVisible else { return }
        var stage = model.stage
        if stage == .bar { place() }
        guard let g = geometry else { return }
        let hovering = (stage == .bar || stage == .pill)
            && QuickTalkLayout.hovering(was: model.hovering, pointer: pointer, bar: g.frame(.bar, live: model.isLive),
                                        pill: g.frame(.pill), edge: g.window.minX)
        if hovering != model.hovering {
            model.hovering = hovering
            stage = model.stage
        }
        let taking: CGRect?
        switch stage {
        case .popup: taking = g.frame(.popup, card: model.display.cardSize)
        case .pill: taking = g.frame(.pill)
        case .bar, .hidden: taking = nil
        }
        let ignore = !(taking?.contains(pointer) ?? false)
        if panel.ignoresMouseEvents != ignore { panel.ignoresMouseEvents = ignore }
    }
}

#if DEBUG
extension QuickTalkController {
    /// Snapshot runs only (`-kaikuQuickTalkProbe YES`, see `QuickTalkSnapshot`): the REAL window, checked without
    /// the person's pointer or keys. The run is inert (no conversation can start); the pointer positions are
    /// handed in instead of read. Writes what the window is and does to `window-probe.txt`, and the window's own
    /// content (bar, pill, popup, as drawn in it) to `window-*.png`.
    func probe(app: AppModel, into dir: URL) {
        guard model.inert else { return }
        var log: [String] = []
        func capture(_ name: String) {
            guard let v = panel?.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { return }
            v.cacheDisplay(in: v.bounds, to: rep)
            try? rep.representation(using: .png, properties: [:])?.write(to: dir.appendingPathComponent(name))
        }
        func state(_ what: String) {
            log.append("\(what): stage=\(model.stage.rawValue) hovering=\(model.hovering) open=\(model.isOpen) "
                + "takesMouse=\(panel.map { !$0.ignoresMouseEvents } ?? false) key=\(panel?.isKeyWindow ?? false) appActive=\(NSApp.isActive)")
        }
        // The trigger in an inert run: nothing opens, nothing starts.
        lastTrigger = .distantPast
        trigger()
        log.append("trigger in a snapshot run: open=\(model.isOpen) startAttempts=\(model.startAttempts) window=\(panel != nil)")
        let free = HotKey(keyCode: QuickTalkHotKey.keyCode, modifiers: QuickTalkHotKey.carbonModifiers) {}
        log.append("⌥⇧Space registers in this app: \(free.registered)")
        place()
        guard let panel, let g = geometry else { return }
        let far = CGPoint(x: g.visible.midX, y: g.visible.midY)
        log.append("window=\(panel.frame) visibleScreen=\(g.visible) level=\(panel.level.rawValue) (floating=\(NSWindow.Level.floating.rawValue)) "
            + "visible=\(panel.isVisible) canBecomeKey=\(panel.canBecomeKey) everySpace=\(panel.collectionBehavior.contains(.canJoinAllSpaces)) "
            + "besideFullScreen=\(panel.collectionBehavior.contains(.fullScreenAuxiliary)) shadow=\(panel.hasShadow) opaque=\(panel.isOpaque)")
        log.append("bar=\(g.frame(.bar)) pill=\(g.frame(.pill)) popup=\(g.frame(.popup))")
        trackPointer(at: far)
        state("pointer far away")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [self] in
            capture("window-bar.png")
            trackPointer(at: CGPoint(x: g.frame(.bar).midX, y: g.frame(.bar).midY))
            state("pointer on the bar")
            trackPointer(at: CGPoint(x: g.frame(.pill).maxX - 6, y: g.frame(.pill).midY))
            state("pointer on the pill")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [self] in
                capture("window-pill.png")
                trackPointer(at: CGPoint(x: g.frame(.pill).maxX + 40, y: g.frame(.pill).midY))
                state("pointer left the pill")
                model.hovering = true
                model.perform(.start)   // the pill's first button (inert: the popup opens, no conversation)
                trackPointer(at: CGPoint(x: g.frame(.popup).midX, y: g.frame(.popup).midY))
                state("popup, pointer on the card")
                trackPointer(at: CGPoint(x: g.frame(.popup).midX, y: g.frame(.popup).maxY + 20))
                state("popup, pointer above the card")
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [self] in
                    capture("window-popup.png")
                    log.append("popup shows: \(model.display.state.rawValue) micLive=\(model.display.micLive) startAttempts=\(model.startAttempts)")
                    model.close()
                    trackPointer(at: far)
                    state("closed")
                    try? log.joined(separator: "\n").write(to: dir.appendingPathComponent("window-probe.txt"), atomically: true, encoding: .utf8)
                }
            }
        }
    }
}
#endif

/// A click on the pill or the popup acts at once, though the window is never the key window.
private final class FirstMouseHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// One system-wide hot key (Carbon `RegisterEventHotKey`; needs no permission). Released when the object goes.
@MainActor
final class HotKey {
    private static var actions: [UInt32: () -> Void] = [:]
    private static var nextID: UInt32 = 1
    private static var handlerInstalled = false

    private var ref: EventHotKeyRef?
    private let id: UInt32
    /// False when the system refused the registration (the combination is not available).
    private(set) var registered = false

    init(keyCode: UInt32, modifiers: UInt32, action: @escaping () -> Void) {
        id = Self.nextID
        Self.nextID += 1
        Self.installHandler()
        let hotKeyID = EventHotKeyID(signature: 0x4B41_494B /* "KAIK" */, id: id)
        let status = RegisterEventHotKey(keyCode, modifiers, hotKeyID, GetEventDispatcherTarget(), 0, &ref)
        registered = status == noErr && ref != nil
        if registered { Self.actions[id] = action }
    }

    deinit {
        if let ref { UnregisterEventHotKey(ref) }
        let id = id
        Task { @MainActor in HotKey.actions[id] = nil }
    }

    private static func installHandler() {
        guard !handlerInstalled else { return }
        handlerInstalled = true
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetEventDispatcherTarget(), { _, event, _ in
            var hotKeyID = EventHotKeyID()
            let status = GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                                           MemoryLayout<EventHotKeyID>.size, nil, &hotKeyID)
            guard status == noErr else { return status }
            let id = hotKeyID.id
            DispatchQueue.main.async { MainActor.assumeIsolated { HotKey.actions[id]?() } }
            return noErr
        }, 1, &spec, nil, nil)
    }
}

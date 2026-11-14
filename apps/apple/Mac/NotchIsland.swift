import AppKit
import KaikuKit
import Observation
import SwiftUI

/// The notch island (design/ia.md → Mac extras, plan 02 §8): ONE window at level statusBar + 1 (26) whose top edge
/// is the top of the screen, drawing ONE black `MacIslandShape` that grows out of the notch. In the menu bar band
/// the shape is never wider than the notch + wings (`MacIslandGeometry`), so it never covers menu titles or status
/// items; below the menu bar it flares out (concave shoulders) into the body that holds Kaiku, the line and the
/// buttons. Collapsed ↔ peek ↔ expanded is one spring on the shape's width/height. Mouse-through everywhere except
/// inside the drawn shape (and the notch itself while collapsed, a hover/click zone → "hello"). On a Mac without a
/// notch the body is a pill just below the menu bar.
///
/// While a quick-talk conversation is on and its popup is put away (the person keeps working), the island shows
/// the call the way the iPhone's Dynamic Island does (`.call`): Kaiku, the call's one state word, the elapsed
/// time, mute me, end. A click anywhere else on it brings the popup back. It stays as long as the call does (no
/// timer folds it away) and folds back into the notch when the call ends.
@Observable @MainActor
final class IslandModel {
    enum State: Equatable { case hidden, peek, expanded, call }
    var state: State = .hidden
    /// The call showing in `.call`.
    var call: QuickTalkCall?
    /// What is showing: a peek rule's kind, or nil = "hello" (the person clicked the notch).
    var kind: MacPeekKind? = .lateNight
    var reply: String?
    var helloLine = ""
    var helloMascot: MascotState = .idle
    /// Kaiku has come down (it drops after the shape has started to grow).
    var risen = false
    var hasNotch = false
    var notchWidth: CGFloat = 0
    var wing: CGFloat = 0
    var menuBar: CGFloat = 24
    /// Mascot loop anchor (snapshots pin the sleepy loop mid-cycle, where the z's are showing).
    var loopStart: Date?

    /// The shape for a state (collapsed idle = the notch only; out = notch + wings in the band + the body).
    func shape(_ s: State) -> MacIslandShape {
        let band = hasNotch ? notchWidth + 2 * wing : 0
        switch s {
        case .hidden:
            return MacIslandShape(topWidth: notchWidth, bodyWidth: notchWidth, bodyHeight: 0, menuBar: menuBar, pill: !hasNotch)
        case .peek, .expanded:
            let e = s == .expanded
            return MacIslandShape(topWidth: band, bodyWidth: MacIslandLayout.size(expanded: e).width,
                                  bodyHeight: MacIslandLayout.bodyHeight(expanded: e), menuBar: menuBar, pill: !hasNotch)
        case .call:
            // A small body right under the notch: no wider than it has to be, like the Dynamic Island around its cutout.
            let size = QuickTalkLayout.islandCall
            return MacIslandShape(topWidth: band, bodyWidth: size.width, bodyHeight: size.height + (hasNotch ? MacIslandShape.shoulder : 0),
                                  menuBar: menuBar, pill: !hasNotch)
        }
    }

    var mascotState: MascotState {
        guard let kind else { return helloMascot }
        return reply != nil && kind == .stretch ? .happy : kind.mascot
    }
}

enum IslandAction { case yes, later, notToday, talk, open, expand, hello, callMute, callEnd, callShow }

@MainActor
final class NotchIsland {
    let model = IslandModel()
    private(set) var geometry: MacIslandGeometry?
    private let panel: NSPanel
    private weak var companion: MacCompanion?
    private var hideWork: DispatchWorkItem?
    private var hoverTimer: Timer?
    /// Room around the shape inside the window for the soft bottom shadow.
    static let shadowPad: CGFloat = 28

    init(companion: MacCompanion) {
        self.companion = companion
        panel = NSPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false   // the shape draws its own soft shadow, under the bottom edge only
        panel.level = NSWindow.Level(rawValue: NSWindow.Level.statusBar.rawValue + 1)
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        panel.isMovable = false
        panel.hidesOnDeactivate = false
        panel.ignoresMouseEvents = true
        panel.contentView = NSHostingView(rootView: IslandView(model: model) { [weak self] a in self?.handle(a) })
        reposition()
        panel.orderFrontRegardless()
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.reposition() }
        }
        let ws = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.activeSpaceDidChangeNotification, NSWorkspace.didWakeNotification] {
            ws.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.reposition() }
            }
        }
        hoverTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.trackMouse() }
        }
        // Kaiku coming to the front or leaving it decides whether its own Talk screen is showing the call.
        for name in [NSApplication.didBecomeActiveNotification, NSApplication.didResignActiveNotification] {
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.refreshCall() }
            }
        }
        followCall()
    }

    // MARK: the call (quick talk put away)

    private var quick: QuickTalkModel { QuickTalkController.shared.model }

    /// The call to show: a conversation is on, the popup is not showing it, and neither is Kaiku's own Talk
    /// screen in front.
    private var wantedCall: QuickTalkCall? {
        guard let call = quick.call, !quick.isOpen, !(NSApp.isActive && quick.mainShowsTalk()) else { return nil }
        return call
    }

    /// Follows the conversation: its state word, the microphone, its beginning and its end.
    private func followCall() {
        withObservationTracking {
            _ = (quick.call, quick.isOpen, companion?.app?.selectedTab)
        } onChange: { [weak self] in
            Task { @MainActor in self?.followCall() }
        }
        refreshCall()
    }

    private func refreshCall() {
        if let call = wantedCall {
            model.call = call
            guard model.state != .call else { return }
            // A call comes before a peek: whatever was out makes way.
            reposition()
            hideWork?.cancel()
            model.reply = nil
            model.risen = false
            panel.orderFrontRegardless()
            model.state = .call
        } else if model.state == .call {
            hide()
        }
    }

    static func screenInfo(_ s: NSScreen) -> MacScreenInfo {
        MacScreenInfo(frame: s.frame, visibleFrame: s.visibleFrame, safeTop: s.safeAreaInsets.top,
                      auxLeft: s.auxiliaryTopLeftArea, auxRight: s.auxiliaryTopRightArea, isMain: s == NSScreen.main)
    }

    /// Window: top edge = screen top, centred on the notch (or the screen), big enough for the expanded shape.
    func reposition() {
        guard let info = MacIslandGeometry.pick(NSScreen.screens.map(Self.screenInfo)) else { return }
        let g = MacIslandGeometry.compute(info)
        geometry = g
        model.hasNotch = g.notch != nil
        model.notchWidth = g.notch?.width ?? 0
        model.wing = g.wing
        model.menuBar = g.menuBar
        let e = MacIslandLayout.expanded
        let w = e.width + 2 * Self.shadowPad
        let h = g.menuBar + MacIslandShape.pillGap + MacIslandLayout.bodyHeight(expanded: true) + Self.shadowPad
        panel.setFrame(NSRect(x: (g.centerX - w / 2).rounded(), y: g.screenTop - h, width: w, height: h), display: true)
    }

    /// Mouse-through except inside the drawn shape; while collapsed only the notch takes the mouse (click → hello).
    private func trackMouse() {
        let m = NSEvent.mouseLocation, f = panel.frame
        guard NSMouseInRect(m, f, false) else { panel.ignoresMouseEvents = true; return }
        let local = CGPoint(x: m.x - f.minX, y: f.maxY - m.y)
        let path = model.shape(model.state).path(in: CGRect(origin: .zero, size: f.size))
        panel.ignoresMouseEvents = !path.contains(local)
    }

    func show(_ kind: MacPeekKind?) {
        reposition()
        hideWork?.cancel()
        model.kind = kind
        if kind == nil, let app = companion?.app {
            model.helloLine = app.greeting
            model.helloMascot = app.ambientState
        }
        model.reply = nil
        model.risen = false
        panel.orderFrontRegardless()
        model.state = kind == nil ? .expanded : .peek
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.model.risen = true }
        scheduleHide(after: 20)
        #if DEBUG
        IslandSnapshot.runIfAsked(model: model, geometry: geometry)
        #endif
    }

    func hide(animated: Bool = true) {
        hideWork?.cancel()
        model.risen = false
        model.reply = nil
        // A call that is still on comes back when a peek or a hello folds away.
        if model.state != .call, let call = wantedCall {
            model.call = call
            model.state = .call
        } else {
            model.state = .hidden
        }
    }

    func hover(_ inside: Bool) {
        guard model.state != .hidden, model.state != .call else { return }   // a call stays as long as it is on
        if inside { hideWork?.cancel() } else { scheduleHide(after: 8) }
    }

    private func scheduleHide(after s: Double) {
        hideWork?.cancel()
        let w = DispatchWorkItem { [weak self] in self?.hide() }
        hideWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + s, execute: w)
    }

    fileprivate func handle(_ a: IslandAction) {
        switch a {
        case .hello:
            if model.state == .hidden { show(nil) } else { hide() }
        case .expand:
            model.state = .expanded
            scheduleHide(after: 30)
        case .yes:
            // Goodnight needs no snooze (one late peek a night); a stretch taken quiets the next hour.
            if model.kind == .stretch { companion?.snooze(.hour) }
            model.reply = T(model.kind == .stretch ? "mac.stretch.go" : "mac.goodnight.reply")
            model.state = .expanded
            scheduleHide(after: model.kind == .stretch ? 8 : 5)
        case .later:
            companion?.snooze(.hour)
            hide()
        case .notToday:
            companion?.snooze(.today)
            hide()
        case .callMute:
            quick.toggleMicrophone()
        case .callEnd:
            quick.end()
        case .callShow:
            QuickTalkController.shared.open()
        case .talk, .open:
            hide()
            if a == .talk { companion?.app?.selectedTab = .talk }
            NSApp.activate(ignoringOtherApps: true)
            for w in NSApp.windows where w.identifier?.rawValue.contains("main") == true || w.title == "Kaiku" { w.makeKeyAndOrderFront(nil) }
        }
    }
}

/// design/motion.md → Mac notch island.
enum IslandMotion {
    static let morph = Animation.spring(response: 0.8, dampingFraction: 0.82)
    static let drop = Animation.spring(response: 1.1, dampingFraction: 0.78).delay(0.15)
    static let fade = Animation.easeInOut(duration: KaikuTokens.Duration.crossfade)
}

/// The whole island: one shape (pure black, no stroke, a soft shadow under the bottom edge only), tiny glyphs in
/// the wings while Kaiku is out, and the content in the body below the menu bar, clipped to the shape.
struct IslandView: View {
    let model: IslandModel
    let act: (IslandAction) -> Void
    /// Snapshots draw an explicit in-between shape (mid-morph); nil = the model's state.
    var shapeOverride: MacIslandShape?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let shape = shapeOverride ?? model.shape(model.state)
        let out = model.state != .hidden
        ZStack(alignment: .top) {
            shape
                .fill(Color.black)
                .shadow(color: .black.opacity(out ? 0.28 : 0), radius: 14, x: 0, y: 10)
            if out {
                wings.frame(maxWidth: .infinity, alignment: .top).clipShape(shape).transition(.opacity)
                content
                    .padding(.top, model.menuBar + (model.hasNotch ? MacIslandShape.shoulder : MacIslandShape.pillGap))
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                    .clipShape(shape)
                    .transition(.opacity)
            }
        }
        .padding(.horizontal, NotchIsland.shadowPad)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .contentShape(shape)
        .onTapGesture { if !out { act(.hello) } else if inCall { act(.callShow) } }   // the wings beside the notch too
        .onHover { inside in hoverChanged(inside) }
        .animation(reduceMotion ? IslandMotion.fade : IslandMotion.morph, value: model.state)
        .animation(reduceMotion ? IslandMotion.fade : IslandMotion.drop, value: model.risen)
        .environment(\.colorScheme, .dark)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(T("a11y.mascot"))
    }

    private func hoverChanged(_ inside: Bool) {
        if shapeOverride == nil { MacCompanion.shared.island.hover(inside) }
    }

    private var expanded: Bool { model.state == .expanded }
    private var inCall: Bool { model.state == .call && model.call != nil }

    /// Wing glyphs in the menu bar band (only inside notch ± wings): Kaiku left, the time right.
    @ViewBuilder private var wings: some View {
        if model.hasNotch {
            HStack(spacing: 0) {
                MascotView(state: inCall ? (model.call?.mascot ?? .listening) : model.mascotState,
                           size: min(24, model.menuBar - 6), tappable: false, cycleStart: model.loopStart)
                    .environment(\.kaikuMascotOnDark, true)
                    .frame(width: model.wing)
                Spacer(minLength: model.notchWidth)
                Group {
                    // In a call the wing is the call's clock (the Dynamic Island's trailing side); else the time.
                    if inCall, let since = model.call?.since {
                        Text(since, style: .timer).foregroundStyle(KaikuTokens.Colors.sage)
                    } else {
                        Text(Date(), format: .dateTime.hour().minute()).foregroundStyle(KaikuTokens.Colors.mascotBody)
                    }
                }
                .font(.system(size: 12, weight: .semibold, design: .rounded).monospacedDigit())
                .lineLimit(1)
                .minimumScaleFactor(0.7)
                .frame(width: model.wing)
            }
            .frame(width: model.notchWidth + 2 * model.wing, height: model.menuBar)
        }
    }

    /// Two columns inside the body (`MacIslandLayout`): Kaiku vertically centred left, text + buttons right.
    /// In a call: the small call row instead.
    @ViewBuilder private var content: some View {
        if model.state == .call, let call = model.call {
            callRow(call)
        } else {
            let size = MacIslandLayout.size(expanded: expanded)
            HStack(alignment: .center, spacing: MacIslandLayout.gap) {
                mascot
                textColumn
            }
            .padding(MacIslandLayout.padding)
            .frame(width: size.width, height: size.height, alignment: .leading)
        }
    }

    /// The call, small: the call's one state word, mute me, end; Kaiku and the elapsed time are in the wings beside
    /// the notch (on a Mac without a notch, in the row). A click anywhere else brings the popup back.
    private func callRow(_ call: QuickTalkCall) -> some View {
        let size = QuickTalkLayout.islandCall
        return HStack(spacing: KaikuTokens.Space.s3) {
            if !model.hasNotch {
                MascotView(state: call.mascot, size: 30, tappable: false, cycleStart: model.loopStart)
                    .environment(\.kaikuMascotOnDark, true)
                    .frame(width: 30, height: 30)
                    .accessibilityHidden(true)
            } else {
                Circle().fill(call.micOn ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted).frame(width: 8, height: 8)
                    .accessibilityHidden(true)
            }
            HStack(spacing: KaikuTokens.Space.s2) {
                Text(T(call.status.key)).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                    .lineLimit(1).minimumScaleFactor(0.8)
                if !model.hasNotch, let since = call.since {   // with a notch the elapsed time is in the wing
                    Text(since, style: .timer).kText(.footnote).monospacedDigit().foregroundStyle(KaikuTokens.Colors.muted)
                        .lineLimit(1).fixedSize()
                        .accessibilityLabel(T("call.a11y.time"))
                }
            }
            .accessibilityElement(children: .combine)
            Spacer(minLength: KaikuTokens.Space.s1)
            callButton(call.micOn ? "mic.fill" : "mic.slash.fill", T(call.micOn ? "call.mute.me" : "call.unmute.me"),
                       ink: call.micOn ? KaikuTokens.Colors.ink : KaikuTokens.Colors.clayInk,
                       fill: call.micOn ? KaikuTokens.Colors.surface2 : KaikuTokens.Colors.clay) { act(.callMute) }
            callButton("phone.down.fill", T("call.end"), ink: KaikuTokens.Colors.bg, fill: KaikuTokens.Colors.ink) { act(.callEnd) }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .frame(width: size.width, height: size.height)
        .contentShape(Rectangle())
        .onTapGesture { act(.callShow) }
        .help(T("quick.show"))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(T("quick.live"))
    }

    private func callButton(_ symbol: String, _ label: String, ink: Color, fill: Color, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).kText(.caption, weight: .semibold).foregroundStyle(ink)
                .frame(width: 30, height: 30)
                .background(Circle().fill(fill))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .help(label)
        .accessibilityLabel(label)
    }

    /// Before it has come down Kaiku waits above the body (clipped away), so it drops out of the notch.
    private var mascot: some View {
        let m = MacIslandLayout.mascotSize(expanded: expanded)
        return MascotView(state: model.mascotState, size: m, tappable: false, cycleStart: model.loopStart)
            .environment(\.kaikuMascotOnDark, true)
            .frame(width: m, height: m)
            .offset(y: reduceMotion || model.risen ? 0 : -MacIslandLayout.expanded.height)
            .opacity(reduceMotion && !model.risen ? 0 : 1)
            .allowsHitTesting(false)
    }

    private var line: String {
        if let r = model.reply { return r }
        guard let k = model.kind else { return model.helloLine }
        return T(k.lineKey)
    }

    private var textColumn: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            Text(line)
                .kText(.body, weight: .semibold)
                .foregroundStyle(KaikuTokens.Colors.ink)
                .wraps()
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
                .onTapGesture { act(.expand) }
            if model.reply == nil {
                FlowRow {
                    if let k = model.kind {
                        pill(T(k.yesKey), primary: true) { act(.yes) }
                        pill(T(k.laterKey), primary: false) { act(.later) }
                        if expanded {
                            pill(T("common.nottoday"), primary: false) { act(.notToday) }
                            pill(T("tab.talk"), primary: false) { act(.talk) }
                        }
                    } else {
                        pill(T("tab.talk"), primary: true) { act(.talk) }
                        pill(T("mac.open"), primary: false) { act(.open) }
                    }
                }
            }
        }
    }

    private func pill(_ text: String, primary: Bool, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(text).kText(.footnote, weight: .semibold)
                .fixedSize()
                .foregroundStyle(primary ? KaikuTokens.Colors.clayInk : KaikuTokens.Colors.ink)
                .padding(.horizontal, KaikuTokens.Space.s4)
                .frame(minHeight: 34)
                .background(Capsule().fill(primary ? KaikuTokens.Colors.clay : KaikuTokens.Colors.surface2))
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}

/// Buttons wrap to the next row instead of truncating (Finnish labels are long).
struct FlowRow: Layout {
    var spacing: CGFloat = KaikuTokens.Space.s2

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews)
        return CGSize(width: rows.map(\.width).max() ?? 0, height: rows.map(\.height).reduce(0, +) + spacing * CGFloat(max(0, rows.count - 1)))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews) {
            var x = bounds.minX
            for i in row.items {
                let s = subviews[i].sizeThatFits(.unspecified)
                subviews[i].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
                x += s.width + spacing
            }
            y += row.height + spacing
        }
    }

    private func arrange(width: CGFloat, _ subviews: Subviews) -> [(items: [Int], width: CGFloat, height: CGFloat)] {
        var rows: [(items: [Int], width: CGFloat, height: CGFloat)] = []
        var cur: (items: [Int], width: CGFloat, height: CGFloat) = ([], 0, 0)
        for i in subviews.indices {
            let s = subviews[i].sizeThatFits(.unspecified)
            let w = cur.items.isEmpty ? s.width : cur.width + spacing + s.width
            if !cur.items.isEmpty && w > width {
                rows.append(cur)
                cur = ([i], s.width, s.height)
            } else {
                cur = (cur.items + [i], w, max(cur.height, s.height))
            }
        }
        if !cur.items.isEmpty { rows.append(cur) }
        return rows
    }
}

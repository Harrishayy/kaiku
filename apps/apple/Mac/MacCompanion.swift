import AppKit
import CoreGraphics
import KaikuKit
import UserNotifications

/// Mac extras (A3), started once at launch: the usage-rhythm sampler (D26, opt-in), the notch peek rules and the
/// one daily invitation. Pure logic lives in KaikuKit/Mac (unit-tested); this file only touches AppKit.
@MainActor
final class MacCompanion {
    static let shared = MacCompanion()

    private(set) var app: AppModel?
    let store = MacUsageStore.shared
    lazy var island = NotchIsland(companion: self)
    private var timer: Timer?
    private var switches = 0
    private var observers: [NSObjectProtocol] = []
    private var ledger: MacPeekLedger {
        get {
            guard let d = UserDefaults.standard.data(forKey: "kaiku.mac.peeks"),
                  let l = try? JSONDecoder().decode(MacPeekLedger.self, from: d) else { return MacPeekLedger() }
            return l
        }
        set { UserDefaults.standard.set(try? JSONEncoder().encode(newValue), forKey: "kaiku.mac.peeks") }
    }

    func start(app: AppModel) {
        guard self.app == nil else { return }
        self.app = app
        let ws = NSWorkspace.shared.notificationCenter
        // Only a count of switches is kept; which app was activated is never looked at here.
        observers.append(ws.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.switches += 1 }
        })
        // After wake the next tick sees the gap (idle time, a break) and the snooze dates are wall-clock: nothing to reset.
        observers.append(ws.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        })
        timer = Timer.scheduledTimer(withTimeInterval: MacUsageAggregator.sampleSeconds, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        _ = island
        tick()
        DailyInvitation.schedule(app: app)
        if UserDefaults.standard.bool(forKey: "kaikuSimulateLate") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.simulateLateEvening() }
        }
    }

    /// Seconds since the last keyboard/mouse/trackpad input (the system idle counter; no event content).
    static func idleSeconds() -> Double {
        CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: CGEventType(rawValue: ~0)!)
    }

    func tick(now: Date = Date()) {
        guard let app else { return }
        let idle = Self.idleSeconds()
        if app.consents[.mac] == true {
            // The bundle id is reduced to a broad category on this line and never stored or sent.
            let category = app.isPaused ? .other : MacAppCategory.of(bundleID: NSWorkspace.shared.frontmostApplication?.bundleIdentifier)
            let sample = MacUsageSample(at: now, category: category, idleSeconds: idle, switches: app.isPaused ? 0 : switches, paused: app.isPaused)
            let closed = store.aggregator.ingest(sample)
            store.save()
            for c in closed {
                let end = min(now, c.start.addingTimeInterval(3600))
                Task { await app.recordScreenActivity(c.payload, at: end) }
            }
        }
        switches = 0
        let stretch = app.consents[.mac] == true ? store.aggregator.currentStretchMin : 0
        evaluatePeek(now: now, active: idle < MacUsageAggregator.activeIdleLimit, stretchMin: stretch)
    }

    func evaluatePeek(now: Date, active: Bool, stretchMin: Double, ledger override: MacPeekLedger? = nil) {
        guard let app, island.model.state == .hidden else { return }
        let ctx = MacPeekContext(now: now, active: active, stretchMin: stretchMin, paused: app.isPaused,
                                 blocked: override == nil && FrontmostCheck.blocked(),   // the demo (override ledger) always shows
                                 quietHours: MacInvitationTime.inQuiet(now, from: app.quietFrom, to: app.quietTo))
        var l = override ?? ledger
        guard let kind = MacPeekRules.decide(ctx, l) else { return }
        l.record(kind, at: now)
        if override == nil { ledger = l }
        island.show(kind)
    }

    func snooze(_ s: MacSnooze) {
        var l = ledger
        l.snooze(s, at: Date())
        ledger = l
    }

    /// Debug/demo: a synthetic 00:00–01:10 of evening use (video + messages, few breaks) fed through the same
    /// aggregator and rules, so the 01:10 peek can be shown at any time. The closed hour goes out as a `sim` obs;
    /// the real local aggregate and the real peek ledger are untouched.
    func simulateLateEvening() {
        guard let app else { return }
        let cal = Calendar.current
        let night = cal.startOfDay(for: Date())
        var a = MacUsageAggregator()
        var closed: [(start: Date, payload: ScreenActivity)] = []
        for i in 0..<(70 * 2) {
            let t = night.addingTimeInterval(Double(i) * 30)
            let cat: MacAppCategory = i % 7 < 4 ? .video : (i % 7 < 6 ? .communication : .social)
            closed += a.ingest(MacUsageSample(at: t, category: cat, idleSeconds: 3, switches: i % 6 == 0 ? 1 : 0))
        }
        for c in closed { Task { await app.recordScreenActivity(c.payload, at: Date(), sim: true) } }
        island.hide(animated: false)
        evaluatePeek(now: night.addingTimeInterval(70 * 60), active: true, stretchMin: a.currentStretchMin, ledger: MacPeekLedger())
    }
}

/// Best effort "don't interrupt": the frontmost app has a window covering a whole screen (full-screen video,
/// a presentation), or it is a call app (it may be sharing the screen). Window bounds need no screen-recording
/// permission; titles are never read.
enum FrontmostCheck {
    static let callApps: Set<String> = ["us.zoom.xos", "com.microsoft.teams2", "com.microsoft.teams", "com.apple.FaceTime",
                                        "com.cisco.webexmeetingsapp", "com.apple.ScreenSharing", "com.apple.screensharing.agent"]

    @MainActor static func blocked() -> Bool {
        guard let front = NSWorkspace.shared.frontmostApplication else { return false }
        if front.processIdentifier == ProcessInfo.processInfo.processIdentifier { return false }
        if callApps.contains(front.bundleIdentifier ?? "") { return true }
        let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
        let screens = NSScreen.screens.map(\.frame.size)
        for w in info {
            guard (w[kCGWindowOwnerPID as String] as? Int32) == front.processIdentifier,
                  (w[kCGWindowLayer as String] as? Int) == 0,
                  let b = w[kCGWindowBounds as String] as? NSDictionary,
                  let r = CGRect(dictionaryRepresentation: b) else { continue }
            if screens.contains(where: { abs($0.width - r.width) < 1 && abs($0.height - r.height) < 1 }) { return true }
        }
        return false
    }
}

/// The one daily invitation as a Mac notification. Interface kept tiny so A2's scheduler can replace it: schedule
/// (re)plans the next one, outside quiet hours, with today's suggestion line; nothing while paused or unpaired.
@MainActor
enum DailyInvitation {
    static let id = "kaiku.daily.invitation"

    static func schedule(app: AppModel, now: Date = Date()) {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [id])
        guard app.isPaired, !app.isPaused else { return }
        let at = MacInvitationTime.next(after: now, quietFrom: app.quietFrom, quietTo: app.quietTo)
        let content = UNMutableNotificationContent()
        content.title = T("a11y.mascot")
        content.body = T("today.suggest.\(app.nudge?.arm.rawValue ?? "none")")
        let comps = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: at)
        let req = UNNotificationRequest(identifier: id, content: content,
                                        trigger: UNCalendarNotificationTrigger(dateMatching: comps, repeats: false))
        center.getNotificationSettings { s in
            guard s.authorizationStatus == .authorized || s.authorizationStatus == .provisional else { return }
            center.add(req) { _ in }
        }
    }
}

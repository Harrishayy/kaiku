import Foundation
import Observation
@preconcurrency import UserNotifications
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

// What happens at home reaches this screen as it happens. `HomeUpdates` decides when the home stream
// (`HomeStreamClient`) runs and what each event refreshes:
//
//   agreed      an activity was agreed in a conversation somewhere, or changed: read the invitation again
//               (the card on Today, the notification rules in `Notifier.agreed`)
//   day         new observations were stored: read Today again (the path, "Today, so far", the garden)
//   invitation  today's invitation was answered on some device: its card leaves
//   hello       a connection that cannot go on from the last id: read everything again
//
// The stream runs while the app is paired, not paused and running: on the Mac always (the app lives in the menu
// bar); on iPhone while the app is in the foreground, or in the background while a call or a walk keeps it
// running. There is no Apple push in this app: a phone whose app is suspended hears nothing until it is opened
// again (or the system gives it a background refresh, which reads the list once: `catchUp`).

// MARK: where the app is

/// Whether the person can see the app right now. The notification rule and the stream's gate both ask here.
@MainActor
public enum AppPresence {
    /// Tests and picture runs answer for themselves.
    public static var probe: (inFront: Bool, foreground: Bool)?

    /// In front of the person: iPhone, the app is active; Mac, the main window is the key window (not the menu
    /// bar popover, the notch island or quick talk, which are panels).
    public static var inFront: Bool {
        if let probe { return probe.inFront }
        #if os(iOS)
        return UIApplication.shared.applicationState == .active
        #elseif os(macOS)
        guard let app = NSApp, app.isActive, let key = app.keyWindow else { return false }
        return isMain(key)
        #else
        return true
        #endif
    }

    /// iPhone: not in the background. The Mac app is always running where it can be seen (window or menu bar).
    public static var foreground: Bool {
        if let probe { return probe.foreground }
        #if os(iOS)
        return UIApplication.shared.applicationState != .background
        #else
        return true
        #endif
    }

    #if os(macOS)
    static func isMain(_ window: NSWindow) -> Bool { !(window is NSPanel) && window.styleMask.contains(.titled) }
    #endif

    /// A picture-taking run of the Mac app (`-kaikuWindowShots`, `-kaikuSnapshot`: Mac/DebugSnapshot.swift) only
    /// looks: it posts nothing to the person's notification centre and keeps no record of what it showed.
    public static var pictureRun: Bool {
        #if DEBUG && os(macOS)
        let d = UserDefaults.standard
        return d.string(forKey: "kaikuWindowShots") != nil || d.string(forKey: "kaikuSnapshot") != nil
        #else
        return false
        #endif
    }
}

// MARK: when the stream runs (pure)

public struct StreamGate: Equatable, Sendable {
    public var paired: Bool
    public var paused: Bool
    public var isPhone: Bool
    /// iPhone: the app is not in the background.
    public var foreground: Bool
    /// iPhone: a call or a walk keeps the app running in the background (their audio does; the stream never does).
    public var keptAlive: Bool

    public init(paired: Bool, paused: Bool, isPhone: Bool = KaikuPlatform.isPhone, foreground: Bool, keptAlive: Bool) {
        self.paired = paired; self.paused = paused; self.isPhone = isPhone
        self.foreground = foreground; self.keptAlive = keptAlive
    }

    public var runs: Bool { paired && !paused && (!isPhone || foreground || keptAlive) }
}

extension APIClient {
    /// `GET /v1/me/stream?home_id=&surface=` with the home's token, for exactly this pairing: nil once the
    /// device is paired to something else (the stream of a previous home is never asked for again).
    func streamRequest(for expected: Pairing, surface: CompanionSurface) -> URLRequest? {
        guard pairing == expected else { return nil }
        return try? request("GET", "/v1/me/stream", query: ["home_id": expected.homeID, "surface": surface.rawValue])
    }
}

// MARK: the runner

@MainActor
public final class HomeUpdates {
    public static let shared = HomeUpdates()

    /// Everything a test replaces: the list to refresh, the connection, where the app is.
    struct Parts {
        var offers: InvitationModel
        var transport: HomeStreamTransport
        var timing = HomeStreamClient.Timing()
        var isPhone = KaikuPlatform.isPhone
        var foreground: @MainActor () -> Bool = { AppPresence.foreground }
        /// A call or a walk is on (iPhone: what keeps the app running in the background).
        var keptAlive: @MainActor () -> Bool = { KaikuCall.isOpen || WalkModel.shared.active }
        /// How long to wait before one more try when the list could not be read after an event.
        var retryAfter: TimeInterval = 2
        /// History's own reload (its numbers change with the day too).
        var history: @MainActor (AppModel) async -> Void = { await HistoryModel.shared.load(app: $0) }
    }

    private let parts: Parts
    private weak var app: AppModel?
    private var observers: [NSObjectProtocol] = []
    private var wake: Task<Void, Never>?

    /// The open stream and the pairing it belongs to. `generation` tells its events from a previous one's.
    private struct Running {
        var task: Task<Void, Never>
        var pairing: Pairing
        var revision: Int
        var generation: Int
        var hellos = 0
        var continued: Bool          // it started with an id to go on from
    }
    private var running: Running?
    private var generation = 0
    /// The last id seen, per pairing: a stream that stops (background, pause) and starts again goes on from it.
    private var cursor: (pairing: Pairing, cursor: StreamCursor)?
    private var refreshing = false
    private var refreshAgain = false

    /// The stream is open and has said hello (for a status line and for tests).
    public private(set) var connected = false
    /// Events taken since the start, by name (tests, the debug trace). Never their content.
    private(set) var taken: [String] = []

    public init() { parts = Parts(offers: .shared, transport: URLSessionStreamTransport()) }
    init(parts: Parts) { self.parts = parts }

    // MARK: start, stop

    /// Called once by the app shell. From then on the stream follows the pairing, "pause everything" and (on
    /// iPhone) the foreground by itself.
    public func start(app: AppModel) {
        guard self.app == nil else { return }
        self.app = app
        let center = NotificationCenter.default
        #if os(iOS)
        for name in [UIApplication.didEnterBackgroundNotification, UIApplication.willEnterForegroundNotification,
                     UIApplication.didBecomeActiveNotification] {
            observers.append(center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.evaluate() }
            })
        }
        #elseif os(macOS)
        // After sleep the connection is dead; the heartbeat rule notices, this only makes it sooner.
        observers.append(NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.restart() }
        })
        MacNotificationAnswers.shared.attach(app: app)
        #endif
        _ = center
        follow(app)
        evaluate()
    }

    /// Pairing, "pause everything" and the timed pause are read here: any change is looked at again.
    private func follow(_ app: AppModel) {
        withObservationTracking {
            _ = app.pairing; _ = app.pairingRevision; _ = app.pausedAll; _ = app.pausedUntil
        } onChange: { [weak self, weak app] in
            Task { @MainActor in
                guard let self, let app else { return }
                self.follow(app)
                self.evaluate()
            }
        }
    }

    var gate: StreamGate {
        StreamGate(paired: app?.pairing != nil, paused: app?.isPaused ?? true, isPhone: parts.isPhone,
                   foreground: parts.foreground(), keptAlive: parts.keptAlive())
    }

    /// Opens, keeps or closes the stream as the gate says. Cheap: called on every lifecycle change, every
    /// change of pairing or pause, and every ping.
    func evaluate() {
        guard let app else { return }
        wake?.cancel(); wake = nil
        guard gate.runs, let pairing = app.pairing else {
            stop()
            // "Pause for 1 hour" ends by the clock, which nothing observes: look again when it does.
            if let until = app.pausedUntil, until > Date(), !app.pausedAll, app.pairing != nil {
                wake = Task { [weak self] in
                    try? await Task.sleep(nanoseconds: UInt64(max(1, until.timeIntervalSinceNow + 1) * 1_000_000_000))
                    guard !Task.isCancelled else { return }
                    self?.evaluate()
                }
            }
            return
        }
        if let running, running.pairing == pairing, running.revision == app.pairingRevision { return }
        open(pairing, app: app)
    }

    private func open(_ pairing: Pairing, app: AppModel) {
        stop()
        generation += 1
        let mine = generation
        if cursor?.pairing != pairing { cursor = (pairing, StreamCursor()) }     // another home starts from nothing
        let cursor = cursor!.cursor
        let api = app.api
        let surface: CompanionSurface = parts.isPhone ? .iphone : .mac
        let client = HomeStreamClient(
            homeID: pairing.homeID, cursor: cursor, transport: parts.transport, timing: parts.timing,
            request: { _ in await api.streamRequest(for: pairing, surface: surface) },
            onNote: { note in StreamTrace.write(note) },
            onEvent: { [weak self] event in await self?.take(event, generation: mine) })
        let continued = cursor.lastEventID != nil
        let task = Task { await client.run() }
        running = Running(task: task, pairing: pairing, revision: app.pairingRevision, generation: mine, continued: continued)
        StreamTrace.write("open continued=\(continued)")
    }

    public func stop() {
        guard let running else { return }
        running.task.cancel()
        self.running = nil
        connected = false
        StreamTrace.write("stop")
    }

    private func restart() {
        guard running != nil else { evaluate(); return }
        stop()
        evaluate()
    }

    // MARK: events

    /// One event from the stream. Dropped unless it comes from the stream that is open now, for the pairing the
    /// app has now: a late event from a previous home changes nothing. Returns at once; what it sets off (reads)
    /// runs on its own.
    func take(_ event: HomeStreamEvent, generation from: Int) {
        guard let app, let running, running.generation == from,
              app.pairing == running.pairing, app.pairingRevision == running.revision else { return }
        switch event {
        case .hello(let hello):
            guard hello.home_id == running.pairing.homeID else { stop(); return }
            let first = running.hellos == 0
            self.running?.hellos += 1
            connected = true
            note("hello")
            StreamTrace.write("hello resync=\(hello.resync == true) replayed=\(hello.replayed ?? 0)")
            guard hello.resync == true else { return }
            // Nothing to go on from: read again. The first hello after a start comes with the app's own read of
            // /v1/me (launch, foreground), so only the list is read here.
            if !(first && !running.continued) { refreshDay() }
            readOffers()
        case .agreed(let e):
            note("agreed")
            StreamTrace.write("agreed \(e.state)")
            readOffers(dropping: e.state == "removed" ? e.id : nil)
        case .day:
            note("day")
            refreshDay()
        case .invitation(let i):
            note("invitation")
            parts.offers.drop(invitation: i.id)
            readOffers()
        case .ping:
            evaluate()       // iPhone: a call that ended in the background no longer keeps the stream
        }
    }

    private func note(_ name: String) { taken.append(name); if taken.count > 200 { taken.removeFirst(100) } }

    /// The invitation and the agreed list, read again (one more try a little later when the service did not
    /// answer). Reads queue up in the model, so every event gets a read that started after it.
    private func readOffers(dropping removed: String? = nil) {
        guard let app else { return }
        let scope = app.pairingRevision
        let offers = parts.offers, retryAfter = parts.retryAfter
        Task { [weak app] in
            guard let app else { return }
            if let removed { await offers.drop(agreed: removed, app: app) }
            if await offers.load(app: app) {
                StreamTrace.write("offers agreed=\(offers.agreed.count)")
                return
            }
            try? await Task.sleep(nanoseconds: UInt64(retryAfter * 1_000_000_000))
            guard app.pairingRevision == scope else { return }
            await offers.load(app: app)
        }
    }

    /// What Today shows, read again without a visible reload (`AppModel.refresh` shows its loading state only
    /// before the first answer), and History's numbers when that tab is the one open. Events that arrive during
    /// a read are answered by one more read after it.
    private func refreshDay() {
        guard let app else { return }
        if refreshing { refreshAgain = true; return }
        refreshing = true
        let history = parts.history
        Task { [weak self, weak app] in
            repeat {
                self?.refreshAgain = false
                await app?.refresh()
                if let app, app.selectedTab == .history { await history(app) }
                StreamTrace.write("day read")
            } while self?.refreshAgain == true
            self?.refreshing = false
        }
    }

    // MARK: a phone that was away

    /// A background refresh (iPhone, when the system allows one): the list is read once, so an activity agreed
    /// while the app was suspended gets its notification late instead of never.
    public func catchUp(app: AppModel) async {
        await parts.offers.load(app: app)
    }
}

// MARK: Mac: answers to the notification

#if os(macOS)
/// The Mac shell has no notification delegate of its own: this one shows a notification also while the app is
/// active (the main window is not key then, or nothing would have been posted) and follows the agreed item's
/// Start and Not now. Other notifications (the daily invitation) keep their plain behaviour.
@MainActor
final class MacNotificationAnswers: NSObject, UNUserNotificationCenterDelegate {
    static let shared = MacNotificationAnswers()
    private weak var app: AppModel?

    func attach(app: AppModel) {
        guard let center = Notifier.systemCenter, center.delegate == nil else { return }
        self.app = app
        center.delegate = self
        Notifier.shared.registerCategories()
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent n: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound, .list]
    }

    /// The completion-handler form, told "done" on the main thread (the `async` form finishes wherever it last
    /// ran; on iPhone that stopped the app when an action opened it).
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let action = response.actionIdentifier
        let info = response.notification.request.content.userInfo
        let sendable = info.reduce(into: [String: String]()) { if let k = $1.key as? String, let v = $1.value as? String { $0[k] = v } }
        nonisolated(unsafe) let done = completionHandler
        Task { @MainActor in
            await self.answer(action: action, info: sendable)
            done()
        }
    }

    private func answer(action: String, info: [String: String]) async {
        guard let app, info["kind"] == NudgeScheduler.agreedKind else { return }
        guard let link = await Notifier.shared.handle(action: action, userInfo: info, app: app) else { return }
        app.open(link)
        NSApp.activate(ignoringOtherApps: true)
        if let window = NSApp.windows.first(where: { AppPresence.isMain($0) && $0.canBecomeKey }) {
            window.makeKeyAndOrderFront(nil)
        } else {
            NSWorkspace.shared.open(link)     // the main window was closed: the app's own link opens it there
        }
    }
}
#endif

// MARK: debug trace

/// `-kaikuStreamTrace <file>` (Debug builds): one line per connection step and per event name with the time, so
/// a run can show how long a card took. Never an id, a sentence or a value.
enum StreamTrace {
    #if DEBUG
    private static let lock = NSLock()
    private static let url: URL? = UserDefaults.standard.string(forKey: "kaikuStreamTrace").map { URL(fileURLWithPath: $0) }
    #endif

    static func write(_ note: HomeStreamClient.Note) {
        #if DEBUG
        switch note {
        case .connecting(let last): write("connecting last_id=\(last == nil ? "none" : "sent")")
        case .ended(let end): write("ended \(end)")
        case .waiting(let seconds): write(String(format: "waiting %.1fs", seconds))
        }
        #endif
    }

    static func write(_ line: String) {
        #if DEBUG
        guard let url else { return }
        let text = "\(KaikuTime.iso(Date())) \(line)\n"
        lock.lock(); defer { lock.unlock() }
        if let handle = try? FileHandle(forWritingTo: url) {
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: Data(text.utf8))
        } else {
            try? Data(text.utf8).write(to: url)
        }
        #endif
    }
}

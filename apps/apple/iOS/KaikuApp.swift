import BackgroundTasks
import KaikuKit
import SwiftUI
import UIKit
import UserNotifications
import WidgetKit
#if canImport(MWDATCore)
import MWDATCore
#endif

/// iPhone shell: everything lives in KaikuKit. Links: `kaiku://today|checkin|walk|play/<game>` (notifications,
/// widgets, Live Activities, Siri), the DAT registration callback, and pairing links (`?home=&t=`).
@main
struct KaikuApp: App {
    @UIApplicationDelegateAdaptor(KaikuAppDelegate.self) private var delegate
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            KaikuRootView()
                .environment(delegate.app)
                .onOpenURL { url in Task { await delegate.route(url) } }
                .task { await delegate.launched() }
                .onChange(of: phase) { _, p in if p == .active { Task { await delegate.foreground() } } }
        }
        .backgroundTask(.appRefresh(KaikuAppDelegate.refreshID)) { await KaikuAppDelegate.backgroundRefresh() }
    }
}

@MainActor
final class KaikuAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    static let refreshID = "fi.kaiku.app.refresh"
    let app = AppModel()
    private static weak var current: KaikuAppDelegate?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions opts: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        Self.current = self
        KaikuCall.clearLeftovers()
        UNUserNotificationCenter.current().delegate = self
        Notifier.shared.registerCategories()
        #if DEBUG
        SurfaceSnapshots.runIfAsked()
        #endif
        app.makeGlasses = { GlassesChoice.make() }
        #if canImport(MWDATCore) && canImport(MWDATMotion) && canImport(MWDATCamera)
        app.glassesControl = GlassesChoice.control()
        if (try? DATGlasses.configureSDK()) != nil {
            app.glassesRegistered = Wearables.shared.registrationState == .registered
        }
        app.connectGlasses = { await DATGlasses.register() }
        #endif
        IntentRouter.open = { [weak self] u in Task { await self?.route(u) } }
        if let u = IntentRouter.pending { IntentRouter.pending = nil; Task { await route(u) } }
        return true
    }

    func launched() async {
        HomeUpdates.shared.start(app: app)   // the home stream: what is agreed or done elsewhere shows here at once
        await WalkModel.recover(app: app)
        await foreground()
        #if DEBUG
        if UserDefaults.standard.bool(forKey: "kaikuHealthSample") {   // simulator demo: You → Devices → Try it out
            app.consents[.watch] = true
            if await HealthSync.shared.addSampleData() { await HealthSync.shared.sync(app: app) }
        }
        if let kind = UserDefaults.standard.string(forKey: "kaikuNotifyTest") {   // DEBUG builds only
            await Notifier.shared.fireTest(kind == "checkin" ? .checkin : .invitation, app: app,
                                           in: max(3, UserDefaults.standard.double(forKey: "kaikuNotifyDelay")))
        }
        #endif
    }

    /// On every foreground (and after pairing via refresh): notifications, voice cache, Health, widgets.
    func foreground() async {
        await app.refresh()
        app.notificationsOn = await Notifier.shared.authorized()
        await Notifier.shared.refresh(app: app)
        WidgetShared.write(app.widgetSnapshot)
        WidgetCenter.shared.reloadAllTimelines()
        await HealthSync.shared.sync(app: app)
        Self.scheduleRefresh()
        if app.isPaired { await VoiceLines.shared.prefetch(api: app.api, lang: app.language) }
    }

    func route(_ url: URL) async {
        if app.open(url) { return }
        #if canImport(MWDATCore)
        if (try? await Wearables.shared.handleUrl(url)) == true {
            app.glassesRegistered = Wearables.shared.registrationState == .registered
            return
        }
        #endif
        if await app.pair(link: url.absoluteString) { await foreground() }
    }

    static func scheduleRefresh() {
        let r = BGAppRefreshTaskRequest(identifier: refreshID)
        r.earliestBeginDate = Date().addingTimeInterval(3 * 3600)
        try? BGTaskScheduler.shared.submit(r)
    }

    /// Best effort: fetch /v1/nudge + /v1/me, re-plan notifications, sync Health.
    nonisolated static func backgroundRefresh() async {
        await MainActor.run { scheduleRefresh() }
        guard let d = await current else { return }
        await d.app.refresh()
        await Notifier.shared.refresh(app: d.app)
        await HomeUpdates.shared.catchUp(app: d.app)   // an activity agreed while the app was suspended: its notification, late
        await HealthSync.shared.sync(app: d.app)
    }

    // MARK: notifications

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent n: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound, .list]
    }

    /// The completion-handler form on purpose: UIKit must be told "done" on the main thread. The `async` form
    /// finishes wherever it last ran, and an action that opens the app (Let's go, Start) then stopped the app
    /// with "call must be made on main thread" (seen on iOS 26.2, 2026-11-14).
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let action = response.actionIdentifier
        let info = response.notification.request.content.userInfo
        let sendable = info.reduce(into: [String: String]()) { if let k = $1.key as? String, let v = $1.value as? String { $0[k] = v } }
        nonisolated(unsafe) let done = completionHandler
        Task { @MainActor in
            await self.handle(action: action, info: sendable)
            done()
        }
    }

    private func handle(action: String, info: [String: String]) async {
        let link = await Notifier.shared.handle(action: action, userInfo: info, app: app)
        if let link { await route(link) }
        await app.flush()
    }
}

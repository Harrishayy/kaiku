import Foundation
import SwiftUI
@preconcurrency import UserNotifications

/// Local notifications (plan 05 §1): turns `NudgeScheduler.plan` into UNNotificationRequests, registers the
/// categories (Let's go · Later · Not today; Good · Okay · Low), handles the answers without opening the app
/// (quick mood → `obs.self_report`, invitation answers → `obs.nudge_outcome`), and counts an invitation nobody
/// answered within 4 h as not accepted. No APNs. Everything goes through the app's offline queue.
@MainActor
public final class Notifier {
    public static let shared = Notifier()
    public static let ignoredAfter: TimeInterval = 4 * 3600

    public enum Action {
        public static let go = "kaiku.go", later = "kaiku.later", notToday = "kaiku.nottoday"
        public static let good = "kaiku.mood.4", okay = "kaiku.mood.3", low = "kaiku.mood.2"
    }

    private let center: UNUserNotificationCenter?
    private let defaults: UserDefaults

    /// Persisted bookkeeping (small; UserDefaults).
    struct Book: Codable {
        var delivered: [String: Date] = [:]
        var offered: [String: String] = [:]        // invitation id → arm
        var resolved: Set<String> = []
        var declinedDay: String?
        var laterUntil: Date?
        var checkinMinutes: [String: Int] = [:]    // day → local minute of that day's weather check
    }
    private var book: Book

    public init(defaults: UserDefaults = .standard, center: UNUserNotificationCenter? = Notifier.systemCenter) {
        self.defaults = defaults
        self.center = center
        if let d = defaults.data(forKey: "kaiku.notify"), let b = try? JSONDecoder().decode(Book.self, from: d) { book = b } else { book = Book() }
    }

    /// nil inside `swift test` (no app bundle → UNUserNotificationCenter would crash).
    public nonisolated static var systemCenter: UNUserNotificationCenter? {
        Bundle.main.bundleURL.pathExtension == "app" ? UNUserNotificationCenter.current() : nil
    }

    private func save() { if let d = try? JSONEncoder().encode(book) { defaults.set(d, forKey: "kaiku.notify") } }

    // MARK: permission

    public func authorized() async -> Bool? {
        guard let center else { return nil }
        let s = await center.notificationSettings()
        switch s.authorizationStatus {
        case .authorized, .provisional, .ephemeral: return true
        case .denied: return false
        default: return nil
        }
    }

    public func requestPermission() async -> Bool {
        guard let center else { return false }
        return (try? await center.requestAuthorization(options: [.alert, .sound])) ?? false
    }

    // MARK: categories

    public func registerCategories() {
        let go = UNNotificationAction(identifier: Action.go, title: T("notif.go"), options: [.foreground])
        let later = UNNotificationAction(identifier: Action.later, title: T("notif.later"), options: [])
        let no = UNNotificationAction(identifier: Action.notToday, title: T("common.nottoday"), options: [])
        let good = UNNotificationAction(identifier: Action.good, title: T("notif.good"), options: [])
        let okay = UNNotificationAction(identifier: Action.okay, title: T("notif.okay"), options: [])
        let low = UNNotificationAction(identifier: Action.low, title: T("notif.low"), options: [])
        center?.setNotificationCategories([
            UNNotificationCategory(identifier: NudgeScheduler.Category.invitation, actions: [go, later, no], intentIdentifiers: []),
            UNNotificationCategory(identifier: NudgeScheduler.Category.invitationNoLater, actions: [go, no], intentIdentifiers: []),
            UNNotificationCategory(identifier: NudgeScheduler.Category.checkin, actions: [good, okay, low], intentIdentifiers: []),
            UNNotificationCategory(identifier: NudgeScheduler.Category.phq9, actions: [], intentIdentifiers: []),
        ])
    }

    // MARK: scheduling

    func input(for app: AppModel, now: Date = Date()) -> NudgeScheduler.Input {
        let cal = Calendar.current
        func minute(_ d: Date) -> Int { cal.component(.hour, from: d) * 60 + cal.component(.minute, from: d) }
        let today = NudgeScheduler.dayKey(now, cal)
        var done = NudgeScheduler.doneToday(events: app.todayEvents)
        if app.weatherDoneToday { done.insert(.checkin) }
        if WalkModel.shared.active { done.insert(.walk) }
        var i = NudgeScheduler.Input(now: now, calendar: cal,
                                     quiet: .init(from: minute(app.quietFrom), to: minute(app.quietTo), sleepInWeekends: app.quietWeekend),
                                     done: done, arm: app.nudge?.arm)
        i.declinedToday = book.declinedDay == today
        i.laterUntil = book.laterUntil.flatMap { cal.isDate($0, inSameDayAs: now) ? $0 : nil }
        i.delivered = Set(book.delivered.keys).union(book.resolved)
        i.phq9Due = app.me?.phq9_due ?? false
        i.paused = app.isPaused
        // Learned usual check-in time: median of the last 14 days' first weather check (default 10:00).
        let mins = book.checkinMinutes.sorted { $0.key > $1.key }.prefix(14).map(\.value).sorted()
        if mins.count >= 3 { i.checkinUsualMinute = mins[mins.count / 2] }
        return i
    }

    /// Foreground / after pairing / background refresh: learn, sweep ignored invitations, then replace every
    /// pending Kaiku request with the current plan (same ids → no duplicates across timezone / DST changes).
    public func refresh(app: AppModel) async {
        guard let center, app.isPaired else { return }
        registerCategories()
        let now = Date()
        let cal = Calendar.current
        // learn the usual check-in time from today's events (any surface)
        if let first = app.todayEvents.filter({ $0.type == "obs.self_report" }).compactMap({ KaikuTime.parse($0.ts) }).min() {
            book.checkinMinutes[NudgeScheduler.dayKey(first, cal)] = cal.component(.hour, from: first) * 60 + cal.component(.minute, from: first)
        }
        for n in await center.deliveredNotifications() where n.request.identifier.hasPrefix("kaiku.") {
            markDelivered(n.request.identifier, at: n.date, arm: n.request.content.userInfo["arm"] as? String)
        }
        await sweepIgnored(app: app, now: now)
        guard await authorized() == true else { save(); return }
        let plan = NudgeScheduler.plan(input(for: app, now: now))
        let pending = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix("kaiku.") && !$0.hasSuffix(".test") }
        let keep = Set(plan.map(\.id))
        center.removePendingNotificationRequests(withIdentifiers: pending.filter { !keep.contains($0) })
        for p in plan { try? await center.add(request(p)) }
        // track invitations so an unanswered one counts as "not accepted" after 4 h
        for p in plan where p.kind == .invitation { if let a = p.arm { book.offered[p.id] = a.rawValue } }
        save()
        kaikuLog.notice("notify_plan \(plan.count)")
    }

    func markDelivered(_ id: String, at: Date, arm: String?) {
        if book.delivered[id] == nil { book.delivered[id] = at }
        if let arm { book.offered[id] = arm }
        // keep the book small: forget things older than 3 days
        let cutoff = Date().addingTimeInterval(-3 * 86400)
        book.delivered = book.delivered.filter { $0.value > cutoff || $0.key == "kaiku.phq9" }
        save()
    }

    func request(_ p: NudgeScheduler.Planned, trigger: UNNotificationTrigger? = nil) -> UNNotificationRequest {
        let c = UNMutableNotificationContent()
        let lang = L10n.shared.language
        c.title = lineKey(p).flatMap { VoiceLines.shared.text($0, lang: lang) } ?? T(p.titleKey)
        c.body = T(p.bodyKey)
        c.categoryIdentifier = p.category
        c.threadIdentifier = "kaiku"
        c.userInfo = ["link": p.deepLink, "kind": p.kind.rawValue, "arm": p.arm?.rawValue ?? "", "id": p.id]
        c.interruptionLevel = p.passive ? .passive : .active
        #if os(iOS)
        c.sound = UNNotificationSound(named: UNNotificationSoundName("kaiku-chime.caf"))
        if let a = Self.mascotAttachment(at: p.fireDate) { c.attachments = [a] }
        #else
        c.sound = .default
        #endif
        let t = trigger ?? UNCalendarNotificationTrigger(
            dateMatching: Calendar.current.dateComponents([.year, .month, .day, .hour, .minute, .second], from: p.fireDate), repeats: false)
        return UNNotificationRequest(identifier: p.id, content: c, trigger: t)
    }

    /// The voice line with the same words Kaiku says aloud (config/voice_lines.toml via GET /v1/voice).
    func lineKey(_ p: NudgeScheduler.Planned) -> String? {
        switch p.kind {
        case .checkin: return "checkin.ask"
        case .phq9: return nil
        case .invitation:
            switch p.arm {
            case .daylight_walk?: return "walk.start"
            case .breathe?: return "breathe.intro"
            case .icbt_exercise?: return "tell.prompt"
            default: return nil
            }
        }
    }

    #if os(iOS)
    /// A small mascot matching the time of day (sleepy late, happy by day), rendered once per state.
    static func mascotAttachment(at d: Date) -> UNNotificationAttachment? {
        let h = Calendar.current.component(.hour, from: d)
        let state: MascotState = h >= 21 || h < 7 ? .sleepy : h < 12 ? .happy : .idle
        let src = VoiceLines.dir.appendingPathComponent("mascot.\(state.rawValue).png")
        if !FileManager.default.fileExists(atPath: src.path) {
            let r = ImageRenderer(content: MascotView(state: state, size: 120, tappable: false).frame(width: 140, height: 140)
                .background(KaikuTokens.Colors.bg))
            r.scale = 3
            guard let png = r.uiImage?.pngData() else { return nil }
            try? png.write(to: src)
        }
        // attachments are moved into the notification store: hand over a copy
        let copy = FileManager.default.temporaryDirectory.appendingPathComponent("kaiku-\(UUID().uuidString).png")
        guard (try? FileManager.default.copyItem(at: src, to: copy)) != nil else { return nil }
        return try? UNNotificationAttachment(identifier: "mascot", url: copy)
    }
    #endif

    // MARK: answers

    /// A notification answer (button or tap). Returns the deep link to open, if any.
    @discardableResult
    public func handle(action: String, userInfo: [AnyHashable: Any], app: AppModel, now: Date = Date()) async -> URL? {
        let id = userInfo["id"] as? String ?? ""
        let arm = (userInfo["arm"] as? String).flatMap(NudgeArm.init(rawValue:))
        let link = (userInfo["link"] as? String).flatMap(URL.init(string:))
        markDelivered(id, at: now, arm: arm?.rawValue)
        switch action {
        case Action.good, Action.okay, Action.low:
            let v = Int(action.split(separator: ".").last ?? "3") ?? 3
            book.resolved.insert(id); save()
            await app.recordQuickMood(v)
            return nil
        case Action.later:
            book.laterUntil = now.addingTimeInterval(NudgeScheduler.laterSeconds)
            save()
            await refresh(app: app)
            return nil
        case Action.notToday:
            book.declinedDay = NudgeScheduler.dayKey(now, .current)
            await resolve(id, arm: arm, accepted: false, app: app)
            await refresh(app: app)
            return nil
        case UNNotificationDismissActionIdentifier:
            return nil
        default:   // Let's go, or a tap on the notification body
            if (userInfo["kind"] as? String) == NudgeScheduler.Kind.invitation.rawValue {
                await resolve(id, arm: arm, accepted: true, app: app)
            } else {
                book.resolved.insert(id); save()
            }
            return link
        }
    }

    private func resolve(_ id: String, arm: NudgeArm?, accepted: Bool, app: AppModel) async {
        guard !book.resolved.contains(id) else { return }
        book.resolved.insert(id)
        // The snoozed copy and the original are one offer: answering one answers both.
        let base = id.replacingOccurrences(of: ".later", with: "")
        book.resolved.insert(base); book.resolved.insert(base + ".later")
        save()
        if let arm { await app.emit("obs.nudge_outcome", NudgeOutcome(arm: arm, accepted: accepted)) }
    }

    /// Invitations delivered more than 4 h ago with no answer → not accepted.
    func sweepIgnored(app: AppModel, now: Date) async {
        for (id, armRaw) in book.offered where !book.resolved.contains(id) {
            guard let at = book.delivered[id], now.timeIntervalSince(at) >= Self.ignoredAfter,
                  book.laterUntil.map({ now > $0.addingTimeInterval(Self.ignoredAfter) }) ?? true else { continue }
            await resolve(id, arm: NudgeArm(rawValue: armRaw), accepted: false, app: app)
        }
        book.offered = book.offered.filter { !book.resolved.contains($0.key) || book.delivered[$0.key] == nil }
        save()
    }

    // MARK: debug (screenshots, demo): the real request, firing in a few seconds

    public func fireTest(_ kind: NudgeScheduler.Kind, app: AppModel, in seconds: TimeInterval = 5) async {
        guard let center else { return }
        registerCategories()
        center.removeAllDeliveredNotifications()   // a clean list for the demo / UI test
        if await authorized() != true { _ = await requestPermission() }
        let day = NudgeScheduler.dayKey(Date(), .current)
        let arm = app.nudge?.arm ?? .daylight_walk
        let p: NudgeScheduler.Planned
        switch kind {
        case .checkin:
            p = .init(id: "kaiku.checkin.\(day).test", kind: .checkin, fireDate: Date().addingTimeInterval(seconds), arm: nil,
                      category: NudgeScheduler.Category.checkin, deepLink: "kaiku://checkin", passive: false,   // banner, for the demo
                      titleKey: "notif.checkin.t", bodyKey: "notif.checkin.d")
        default:
            p = .init(id: "kaiku.invitation.\(day).test", kind: .invitation, fireDate: Date().addingTimeInterval(seconds), arm: arm,
                      category: NudgeScheduler.Category.invitation, deepLink: NudgeScheduler.deepLink(arm), passive: false,
                      titleKey: "notif.invite.\(arm.rawValue)", bodyKey: "notif.invite.d")
            book.offered[p.id] = arm.rawValue; save()
        }
        try? await center.add(request(p, trigger: UNTimeIntervalNotificationTrigger(timeInterval: seconds, repeats: false)))
    }
}

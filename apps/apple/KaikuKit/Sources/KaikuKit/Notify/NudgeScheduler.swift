import Foundation

/// What Kaiku may put on the lock screen, decided by a pure function so every rule is unit-tested
/// (plan 05 §1, §7). At most: one invitation a day (the `/v1/nudge` arm), one check-in reminder when the weather
/// check is not done by the person's usual time, and the PHQ-9 card once. Never a crisis message, never in quiet
/// hours, never something the person already did today on any surface. All times are local wall-clock minutes,
/// so a timezone or DST change just recomputes the same ids (no duplicates).
/// Besides the plan: one notification for each activity the person said yes to in a conversation (`agreed`),
/// posted at once when the app is not in front, with the same quiet hours and pause.
public enum NudgeScheduler {
    /// Things the person can already have done today, on any surface (robot, phone, Mac, glasses, web).
    public enum Activity: String, Sendable, CaseIterable { case checkin, walk, breathe, play, drum, friend }

    public enum Kind: String, Sendable { case invitation, checkin, phq9 }

    public struct Window: Sendable, Equatable {
        public var start: Int   // minutes from local midnight
        public var end: Int     // exclusive
        public init(_ start: Int, _ end: Int) { self.start = start; self.end = end }
    }

    public struct Quiet: Sendable, Equatable {
        public var from: Int    // minutes from midnight, e.g. 22:00 = 1320
        public var to: Int      // e.g. 08:00 = 480 (wraps midnight when from > to)
        public var sleepInWeekends: Bool
        public static let weekendExtra = 120
        public init(from: Int = 22 * 60, to: Int = 8 * 60, sleepInWeekends: Bool = true) {
            self.from = from; self.to = to; self.sleepInWeekends = sleepInWeekends
        }

        public func contains(minute m: Int, weekend: Bool) -> Bool {
            let end = to + (weekend && sleepInWeekends ? Self.weekendExtra : 0)
            if from == end { return false }
            return from < end ? (m >= from && m < end) : (m >= from || m < end)
        }
    }

    public struct Input: Sendable {
        public var now: Date
        public var calendar: Calendar
        public var windows: [Window]
        public var quiet: Quiet
        public var done: Set<Activity>
        public var arm: NudgeArm?
        /// "Not today" pressed on today's invitation.
        public var declinedToday = false
        /// "Later" pressed today: the invitation comes back at this time and cannot be snoozed again.
        public var laterUntil: Date?
        public var checkinUsualMinute = 10 * 60
        public var phq9Due = false
        /// Ids that already reached the person (delivered or answered): never schedule them again.
        public var delivered: Set<String> = []
        public var paused = false

        public init(now: Date, calendar: Calendar = .current, windows: [Window] = NudgeScheduler.defaultWindows,
                    quiet: Quiet = Quiet(), done: Set<Activity> = [], arm: NudgeArm? = nil) {
            self.now = now; self.calendar = calendar; self.windows = windows; self.quiet = quiet; self.done = done
            self.arm = arm
        }
    }

    public struct Planned: Sendable, Equatable, Identifiable {
        public var id: String
        public var kind: Kind
        public var fireDate: Date
        public var arm: NudgeArm?
        public var category: String
        public var deepLink: String
        /// `.active` for the invitation, `.passive` for reminders; never time-sensitive.
        public var passive: Bool
        public var titleKey: String
        public var bodyKey: String
    }

    public static let defaultWindows = [Window(10 * 60, 12 * 60 + 30), Window(14 * 60, 20 * 60)]
    public static let laterSeconds: TimeInterval = 2 * 3600

    public enum Category {
        public static let invitation = "kaiku.invite"
        public static let invitationNoLater = "kaiku.invite.nolater"
        public static let checkin = "kaiku.checkin"
        public static let phq9 = "kaiku.phq9"
        /// An activity agreed in a conversation: Start · Not now.
        public static let agreed = "kaiku.agreed"
        /// The same for an activity this device has no screen for: Not now only.
        public static let agreedElsewhere = "kaiku.agreed.elsewhere"
    }

    /// The activity an arm invites to (for "already did it today" and the deep link).
    public static func activity(_ arm: NudgeArm) -> Activity {
        switch arm {
        case .daylight_walk: return .walk
        case .breathe: return .breathe
        case .icbt_exercise: return .play
        case .drum: return .drum
        case .friend_ping: return .friend
        }
    }

    public static func deepLink(_ arm: NudgeArm) -> String {
        switch arm {
        case .daylight_walk: return "kaiku://walk"
        case .breathe: return "kaiku://play/breathe"
        case .icbt_exercise: return "kaiku://play/tell"
        case .drum, .friend_ping: return "kaiku://today"
        }
    }

    public static func id(_ kind: Kind, day: String) -> String { kind == .phq9 ? "kaiku.phq9" : "kaiku.\(kind.rawValue).\(day)" }

    /// The plan for today and tomorrow (so a reminder still fires if the app is not opened tomorrow morning).
    public static func plan(_ input: Input) -> [Planned] {
        guard !input.paused else { return [] }
        let cal = input.calendar
        var out: [Planned] = []
        let today = cal.startOfDay(for: input.now)
        for offset in 0..<2 {
            guard let day = cal.date(byAdding: .day, value: offset, to: today) else { continue }
            let key = dayKey(day, cal)
            let isToday = offset == 0
            let done: Set<Activity> = isToday ? input.done : []

            // Invitation (one a day).
            if let arm = input.arm, !(isToday && input.declinedToday), !done.contains(activity(arm)) {
                let snoozed = isToday ? input.laterUntil.flatMap { cal.isDate($0, inSameDayAs: day) ? $0 : nil } : nil
                // The snoozed invitation is a second notification of the same day with its own id.
                let id = id(.invitation, day: key) + (snoozed != nil ? ".later" : "")
                let candidate = snoozed.map { max($0, input.now) }
                    ?? max(isToday ? input.now.addingTimeInterval(60) : day, firstWindowStart(day, input))
                if !input.delivered.contains(id), let at = place(candidate, input), cal.isDate(at, inSameDayAs: day) {
                    out.append(Planned(id: id, kind: .invitation, fireDate: at, arm: arm,
                                       category: snoozed != nil ? Category.invitationNoLater : Category.invitation,
                                       deepLink: deepLink(arm), passive: false,
                                       titleKey: "notif.invite.\(arm.rawValue)", bodyKey: "notif.invite.d"))
                }
            }

            // Check-in reminder at the usual time (or soon, if the usual time has passed and it's still not done).
            let cid = id(.checkin, day: key)
            if !done.contains(.checkin), !input.delivered.contains(cid) {
                let usual = atMinute(day, input.checkinUsualMinute, cal)
                let candidate = isToday ? max(usual, input.now.addingTimeInterval(60)) : usual
                if let at = place(candidate, input), cal.isDate(at, inSameDayAs: day) {
                    out.append(Planned(id: cid, kind: .checkin, fireDate: at, arm: nil, category: Category.checkin,
                                       deepLink: "kaiku://checkin", passive: true,
                                       titleKey: "notif.checkin.t", bodyKey: "notif.checkin.d"))
                }
            }
        }
        // PHQ-9 card, once ever.
        if input.phq9Due, !input.delivered.contains(id(.phq9, day: "")),
           let at = place(input.now.addingTimeInterval(60), input) {
            out.append(Planned(id: id(.phq9, day: ""), kind: .phq9, fireDate: at, arm: nil, category: Category.phq9,
                               deepLink: "kaiku://phq9", passive: true, titleKey: "notif.phq9.t", bodyKey: "notif.phq9.d"))
        }
        // Two things never land in the same minute: the reminder yields to the invitation.
        out.sort { $0.fireDate < $1.fireDate }
        return out
    }

    /// The candidate time if it is inside a window and outside quiet hours, else the next moment that is
    /// (searching up to 3 days ahead). Nil when the person has no usable window at all.
    public static func place(_ candidate: Date, _ input: Input) -> Date? {
        let cal = input.calendar
        var day = cal.startOfDay(for: candidate)
        for _ in 0..<4 {
            let weekend = cal.isDateInWeekend(day)
            for w in input.windows.sorted(by: { $0.start < $1.start }) {
                var m = w.start
                let dayCandidate = cal.isDate(candidate, inSameDayAs: day) ? minute(candidate, cal) : 0
                m = max(m, dayCandidate)
                while m < w.end {
                    if !input.quiet.contains(minute: m, weekend: weekend) {
                        var at = atMinute(day, m, cal)
                        if cal.isDate(candidate, inSameDayAs: day), m == dayCandidate, at < candidate { at = candidate }
                        return at
                    }
                    m += 1
                }
            }
            day = cal.date(byAdding: .day, value: 1, to: day)!
        }
        return nil
    }

    static func firstWindowStart(_ day: Date, _ input: Input) -> Date {
        let first = input.windows.map(\.start).min() ?? 9 * 60
        return atMinute(day, first, input.calendar)
    }

    /// Wall-clock minute `m` of `day` (DST-safe: 10:00 stays 10:00 on the day the clocks change).
    static func atMinute(_ day: Date, _ m: Int, _ cal: Calendar) -> Date {
        cal.date(bySettingHour: m / 60, minute: m % 60, second: 0, of: day)
            ?? cal.date(byAdding: .minute, value: m, to: day)!
    }

    static func minute(_ d: Date, _ cal: Calendar) -> Int {
        let c = cal.dateComponents([.hour, .minute], from: d)
        return (c.hour ?? 0) * 60 + (c.minute ?? 0)
    }

    public static func dayKey(_ d: Date, _ cal: Calendar) -> String {
        let c = cal.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    // MARK: an activity agreed in a conversation (D50)

    /// One of today's agreed items as the rule sees it: its id and whether it is still open (not started, done
    /// or put aside).
    public struct AgreedItem: Sendable, Equatable {
        public var id: String
        public var open: Bool
        /// It was agreed in a conversation on this very device (not the glasses a walk speaks through): Kaiku
        /// has just said where it is, so this device does not ring about it.
        public var here: Bool
        public init(id: String, open: Bool, here: Bool = false) { self.id = id; self.open = open; self.here = here }
    }

    public struct AgreedInput: Sendable {
        public var now: Date
        public var calendar: Calendar
        public var quiet: Quiet
        public var paused: Bool
        /// The app is in front of the person right now (iPhone: active; Mac: the main window is key).
        public var inFront: Bool
        /// Today's agreed items as just read from the service.
        public var items: [AgreedItem]
        /// Items this device has already shown the person: the card arrived while the app was in front, or a
        /// notification went out.
        public var shown: Set<String>
        /// Items whose notification this device posted and has not taken away yet.
        public var posted: Set<String>

        public init(now: Date, calendar: Calendar = .current, quiet: Quiet = Quiet(), paused: Bool = false, inFront: Bool,
                    items: [AgreedItem], shown: Set<String> = [], posted: Set<String> = []) {
            self.now = now; self.calendar = calendar; self.quiet = quiet; self.paused = paused; self.inFront = inFront
            self.items = items; self.shown = shown; self.posted = posted
        }
    }

    public struct AgreedPlan: Sendable, Equatable {
        /// Items to post one notification for, now.
        public var post: [String] = []
        /// Items whose notification is taken away (removed, done, started or put aside, here or elsewhere).
        public var remove: [String] = []
        /// Items that now count as shown on this device (never notified about again).
        public var shown: [String] = []
    }

    public static let agreedKind = "agreed"
    public static func agreedID(_ item: String) -> String { "kaiku.agreed.\(item)" }

    /// What to do about agreed items after a read. An open item the person has not been shown here yet: in
    /// front, or agreed on this very device, the card arriving is the notice (nothing is posted, now or later);
    /// otherwise one notification, unless everything is paused or it is quiet hours (then the card waits on
    /// Today, and a later read outside quiet hours may still post it once). Whatever is no longer open loses
    /// its notification.
    public static func agreed(_ input: AgreedInput) -> AgreedPlan {
        var plan = AgreedPlan()
        let open = Set(input.items.filter(\.open).map(\.id))
        plan.remove = input.posted.subtracting(open).sorted()
        let quiet = input.quiet.contains(minute: minute(input.now, input.calendar), weekend: input.calendar.isDateInWeekend(input.now))
        for item in input.items where item.open && !input.shown.contains(item.id) {
            if input.inFront || item.here {
                plan.shown.append(item.id)
            } else if !input.paused && !quiet {
                plan.post.append(item.id)
                plan.shown.append(item.id)
            }
        }
        return plan
    }

    /// Which activities happened today, from the cloud's event list (any surface counts).
    public static func doneToday(events: [AnyEnvelope]) -> Set<Activity> {
        var s = Set<Activity>()
        for e in events {
            switch e.type {
            case "obs.self_report", "obs.checkin", "obs.mood_dial": s.insert(.checkin)
            case "obs.outing": s.insert(.walk)
            case "obs.drum_session": s.insert(.drum)
            case "obs.friend_link": s.insert(.friend)
            case "obs.play_session":
                if case .object(let o) = e.payload, case .string(let g)? = o["game"] {
                    s.insert(g == "breathe" ? .breathe : .play)
                } else { s.insert(.play) }
            case "obs.hrv_session": s.insert(.breathe)
            default: break
            }
        }
        return s
    }
}

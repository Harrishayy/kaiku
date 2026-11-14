import Foundation
#if os(iOS) && canImport(ActivityKit)
import ActivityKit

/// Live Activity for a walk (Dynamic Island + Lock Screen, design/ia.md → Walk surfaces). Updated locally by the
/// app while the walk runs; no push. `lang` keeps the widget extension in the person's language.
public struct WalkActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable, Sendable {
        public var minutes: Int
        public var found: Int
        public var steps: Int?
        public var glasses: Bool
        /// The spotting game that is on (`WalkGoal`): what to look for and how many. Nil = no game, and the
        /// surfaces say nothing about one.
        public var thing: String?
        public var target: Int?
        public init(minutes: Int, found: Int, steps: Int?, glasses: Bool, thing: String? = nil, target: Int? = nil) {
            self.minutes = minutes; self.found = found; self.steps = steps; self.glasses = glasses
            self.thing = thing; self.target = target
        }
    }
    public var startedAt: Date
    public var lang: String
    public init(startedAt: Date, lang: String) { self.startedAt = startedAt; self.lang = lang }
}

/// Live Activity for Breathe with Kaiku: Kaiku breathing, breath n of 6.
public struct BreatheActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable, Sendable {
        public var breath: Int
        public var total: Int
        public init(breath: Int, total: Int) { self.breath = breath; self.total = total }
    }
    public var startedAt: Date
    public var lang: String
    public init(startedAt: Date, lang: String) { self.startedAt = startedAt; self.lang = lang }
}

/// Starts / updates / ends the two activities. A walk activity goes stale after 4 h (the max walk), so an app that
/// was killed mid-walk never leaves it on the Lock Screen.
@MainActor
public enum KaikuLiveActivities {
    public static let maxWalk: TimeInterval = 4 * 3600

    public static var enabled: Bool { ActivityAuthorizationInfo().areActivitiesEnabled }

    public static func startWalk(at start: Date, lang: String, state: WalkActivityAttributes.ContentState) {
        guard enabled else { return }
        endAllWalks()
        let content = ActivityContent(state: state, staleDate: start.addingTimeInterval(maxWalk))
        _ = try? Activity.request(attributes: WalkActivityAttributes(startedAt: start, lang: lang), content: content, pushType: nil)
    }

    public static func updateWalk(_ state: WalkActivityAttributes.ContentState) {
        for a in Activity<WalkActivityAttributes>.activities {
            let content = ActivityContent(state: state, staleDate: a.attributes.startedAt.addingTimeInterval(maxWalk))
            Task { await a.update(content) }
        }
    }

    public static func endWalk(_ state: WalkActivityAttributes.ContentState?) {
        for a in Activity<WalkActivityAttributes>.activities {
            let final = state.map { ActivityContent(state: $0, staleDate: nil) }
            Task { await a.end(final, dismissalPolicy: .after(Date().addingTimeInterval(60))) }
        }
    }

    public static func endAllWalks() {
        for a in Activity<WalkActivityAttributes>.activities { Task { await a.end(nil, dismissalPolicy: .immediate) } }
    }

    public static func startBreathe(lang: String, total: Int) {
        guard enabled else { return }
        endBreathe()
        let content = ActivityContent(state: BreatheActivityAttributes.ContentState(breath: 1, total: total),
                                      staleDate: Date().addingTimeInterval(15 * 60))
        _ = try? Activity.request(attributes: BreatheActivityAttributes(startedAt: Date(), lang: lang), content: content, pushType: nil)
    }

    public static func updateBreathe(breath: Int, total: Int) {
        for a in Activity<BreatheActivityAttributes>.activities {
            let c = ActivityContent(state: BreatheActivityAttributes.ContentState(breath: breath, total: total),
                                    staleDate: Date().addingTimeInterval(15 * 60))
            Task { await a.update(c) }
        }
    }

    public static func endBreathe() {
        for a in Activity<BreatheActivityAttributes>.activities { Task { await a.end(nil, dismissalPolicy: .immediate) } }
    }
}
#endif

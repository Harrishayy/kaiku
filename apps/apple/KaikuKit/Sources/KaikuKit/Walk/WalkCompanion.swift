import Foundation

// The walk companion's device rules, all pure (tested in WalkCompanionTests): the style the person chose, the
// spotting goal's count, and when the walk nudges Kaiku. What Kaiku says is never decided here: the words of a
// style, the nudge lines and their intervals all come from the cloud (`CompanionSessionResponse.walk`).

// MARK: style

public extension WalkStyle {
    static let fallback: WalkStyle = .quiet
    static let defaultsKey = "kaiku.walkStyle"

    /// The person's choice on this device (default Calm).
    static func stored(_ defaults: UserDefaults = .standard) -> WalkStyle {
        defaults.string(forKey: defaultsKey).flatMap(WalkStyle.init(rawValue:)) ?? fallback
    }

    func store(_ defaults: UserDefaults = .standard) { defaults.set(rawValue, forKey: Self.defaultsKey) }

    var titleKey: String { "walk.style.\(rawValue).t" }
    /// One short line: what a walk in this style is like.
    var lineKey: String { "walk.style.\(rawValue).d" }
    var symbol: String {
        switch self {
        case .quiet: return "leaf"
        case .playful: return "sparkles"
        case .chatty: return "bubble.left.and.bubble.right"
        }
    }
}

// MARK: spotting goal

/// One small spotting game on a walk: `target` of `thing` to find (`set_walk_goal`). The device keeps the count,
/// so "two more to find" is true. The fixed light hunt is one instance of it. Only the word and a number live
/// here, for this walk: nothing about what was seen is stored or sent anywhere but the live conversation.
public struct WalkGoal: Equatable, Sendable {
    /// contracts: `set_walk_goal` (target 1...5, thing ≤ 30 characters).
    public static let targets = 1...5
    public static let thingMax = 30

    public let thing: String
    public let target: Int
    public private(set) var found = 0

    public var left: Int { target - found }
    public var done: Bool { found >= target }

    /// Nil when there is nothing to look for. A target outside 1...5 is brought inside it (the result tells Kaiku
    /// the number that counts).
    public init?(thing: String, target: Int) {
        let t = thing.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard !t.isEmpty else { return nil }
        self.thing = String(t.prefix(Self.thingMax))
        self.target = min(Self.targets.upperBound, max(Self.targets.lowerBound, target))
    }

    /// One find. False when the goal was already complete: nothing counts past the target.
    @discardableResult
    public mutating func find() -> Bool {
        guard !done else { return false }
        found += 1
        return true
    }

    /// The thing as a label ("Trees").
    public var title: String { thing.prefix(1).uppercased() + thing.dropFirst() }

    /// `set_walk_goal` → api.WalkGoalResult.
    public var goalResult: JSONValue {
        .object(["thing": .string(thing), "target": .number(Double(target)),
                 "found": .number(Double(found)), "left": .number(Double(left))])
    }

    /// `log_walk_moment` → api.WalkMomentResult.
    public var momentResult: JSONValue {
        .object(["ok": .bool(true), "thing": .string(thing), "found": .number(Double(found)),
                 "target": .number(Double(target)), "left": .number(Double(left))])
    }

    /// `log_walk_moment` without a goal: the moment is heard, there is nothing to count.
    /// `note` is for the model: in a real walk it proposed "three birds" and counted aloud by itself without ever
    /// setting the goal, so the spoken count and the screen disagreed (2026-11-14). The result tells it what to do.
    public static let momentWithoutGoal: JSONValue =
        .object(["ok": .bool(true), "thing": .null, "found": .null, "target": .null, "left": .null,
                 "note": .string("No spotting goal is set, so nothing was counted. If the two of you are playing, call "
                                 + "set_walk_goal with the thing and the target now, then log this find again. "
                                 + "Only say a count that a tool result gave you.")])

    /// The fixed light hunt (three bright things): the game when the person marks a find and none is on, and the
    /// one a walk without Kaiku's live voice has (its scripted lines count to three).
    public static var lightHunt: WalkGoal { WalkGoal(thing: T("walk.goal.lights"), target: 3) ?? WalkGoal(lights: 3) }
    private init(lights target: Int) { thing = "bright things"; self.target = target }
    public var isLightHunt: Bool { thing == Self.lightHunt.thing && target == Self.lightHunt.target }

    /// What Kaiku is told when the count changes outside its own tool call (the person tapped "Found one").
    public var contextLine: String {
        done ? "[spotting game · \(thing) · all \(target) found]"
             : "[spotting game · \(thing) · \(found) of \(target) found · \(left) left]"
    }
}

// MARK: nudges

/// When the walk nudges Kaiku. A Live session only answers input, so for Kaiku to speak when something worth it
/// comes into view (or after a quiet stretch) the device sends a short context line, and Kaiku answers it in words
/// only when it has something to say. Pure: the time is passed in. The lines and the seconds come from the cloud's
/// `WalkGuide`; a nil value means that nudge is not used. This type only decides when; holding back a wordless
/// answer is the conversation's job.
///
/// Rules:
/// - Nothing is sent unless the conversation is open and simply listening: not while the person is speaking, not
///   while Kaiku is speaking or a tool is running, not muted (quiet walk), not paused (a call, "Pause everything"),
///   not while connecting or after the conversation ended.
/// - Silence runs from the moment both sides went quiet, or from the newest words if those are later.
/// - `quiet_prompt`: once per silence, after the full `quiet_after_s`. Words from either side start a new silence.
/// - `look_prompt`: only while pictures are reaching the conversation, every `look_every_s` of silence, counted
///   from the later of the silence's start, the camera coming on, and the last nudge.
public struct WalkNudger: Equatable, Sendable {
    public enum Nudge: Equatable, Sendable {
        case look(String), quiet(String)
        public var text: String {
            switch self { case .look(let t), .quiet(let t): return t }
        }
        public var kind: String {
            switch self { case .look: return "look"; case .quiet: return "quiet" }
        }
    }

    /// What is true at one moment of the walk.
    public struct Moment: Equatable, Sendable {
        /// The conversation's phase; nil when there is none.
        public var phase: Conversation.Phase?
        /// Pictures are reaching the conversation right now ("Let Kaiku see" on, frames flowing).
        public var cameraOn: Bool
        /// "Pause everything" is on.
        public var paused: Bool
        /// The newest words from either side.
        public var lastWords: Date?
        public init(phase: Conversation.Phase?, cameraOn: Bool = false, paused: Bool = false, lastWords: Date? = nil) {
            self.phase = phase; self.cameraOn = cameraOn; self.paused = paused; self.lastWords = lastWords
        }
    }

    public var guide: WalkGuide?
    private var quietSince: Date?
    private var cameraSince: Date?
    private var lastNudge: Date?
    private var quietSent = false

    public init(guide: WalkGuide? = nil) { self.guide = guide }

    /// Call about once a second. Returns the line to send now, if one is due.
    public mutating func next(at now: Date, _ m: Moment) -> Nudge? {
        cameraSince = m.cameraOn ? (cameraSince ?? now) : nil
        guard m.phase == .listening, !m.paused else {
            quietSince = nil
            return nil
        }
        var since = quietSince ?? now
        if let words = m.lastWords, words > since, words <= now { since = words }
        if quietSince != since {
            quietSince = since
            quietSent = false
        }
        guard let guide else { return nil }
        if !quietSent, let after = guide.quiet_after_s, after > 0, let line = Self.line(guide.quiet_prompt),
           now.timeIntervalSince(since) >= Double(after) {
            quietSent = true
            lastNudge = now
            return .quiet(line)
        }
        if let cameraSince, let every = guide.look_every_s, every > 0, let line = Self.line(guide.look_prompt) {
            let from = [since, cameraSince, lastNudge ?? .distantPast].max() ?? since
            if now.timeIntervalSince(from) >= Double(every) {
                lastNudge = now
                return .look(line)
            }
        }
        return nil
    }

    private static func line(_ text: String?) -> String? {
        guard let t = text?.trimmingCharacters(in: .whitespacesAndNewlines), !t.isEmpty else { return nil }
        return t
    }
}

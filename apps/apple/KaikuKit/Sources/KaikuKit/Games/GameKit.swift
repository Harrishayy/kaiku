import Foundation

// Shared, pure pieces of the measured games (Lantern, Seed shelf, Watering, Pebble path): statistics, the input
// provenance, session counting (warm-up sessions), the validity → quality rule, the daily rotation and the local
// raw-trial log. Why these games and what they can and cannot say: docs/validation.md → Games.

/// A monotonic clock for reaction times (wall-clock `Date` can jump when the time syncs).
enum GameClock {
    static var now: TimeInterval { ProcessInfo.processInfo.systemUptime }
}

public enum GameStats {
    public static func mean(_ xs: [Double]) -> Double? { xs.isEmpty ? nil : xs.reduce(0, +) / Double(xs.count) }

    /// Sample standard deviation (n − 1).
    public static func sd(_ xs: [Double]) -> Double? {
        guard xs.count >= 2, let m = mean(xs) else { return nil }
        return (xs.reduce(0) { $0 + ($1 - m) * ($1 - m) } / Double(xs.count - 1)).squareRoot()
    }

    /// Coefficient of variation (SD / mean): reaction-time variability that does not grow just because someone is slower.
    public static func cv(_ xs: [Double]) -> Double? {
        guard let s = sd(xs), let m = mean(xs), m > 0 else { return nil }
        return s / m
    }

    public static func round(_ x: Double, _ places: Int) -> Double {
        let k = pow(10, Double(places))
        return (x * k).rounded() / k
    }
}

/// Tracks which inputs answered during one session (touch on iPhone, click or keys on Mac).
public struct InputTracker: Sendable, Equatable {
    public private(set) var seen: Set<PlayInput> = []
    public init() {}
    public mutating func note(_ i: PlayInput) { seen.insert(i) }
    public var value: PlayInput? { seen.count > 1 ? .mixed : seen.first }
    /// A tap or click on this platform.
    public static var pointing: PlayInput { KaikuPlatform.isPhone ? .touch : .pointer }
}

/// One trial as kept on the device (the full detail; the cloud gets `rt_ms` + `trial_codes`).
public struct GameTrial: Codable, Sendable, Equatable {
    public var code: String          // same letters as PlaySession.trial_codes
    public var rt_ms: Int            // 0 = no response
    public var practice: Bool
    public var detail: [String: Double]   // game-specific: foreperiod_s, symbol, digit, reward, effort_taps, …
    public init(code: String, rt_ms: Int, practice: Bool = false, detail: [String: Double] = [:]) {
        self.code = code; self.rt_ms = rt_ms; self.practice = practice; self.detail = detail
    }
}

/// Session counting and the validity → quality rule for the measured games.
public enum GameHistory {
    /// Games whose numbers feed criteria metrics.
    public static let measured: Set<PlayGame> = [.lantern, .seeds, .watering, .pebbles]
    /// The first sessions of a game on a device are learning the game, not a reading (practice effects).
    public static let warmupSessions = 3

    static func key(_ g: PlayGame) -> String { "kaiku.games.count.\(g.rawValue)" }

    public static func count(_ g: PlayGame, defaults: UserDefaults) -> Int { defaults.integer(forKey: key(g)) }

    /// Numbers the session (1 = first on this device) and marks the warm-up ones. A doubtful session
    /// (`valid == false`) keeps the count where it was: it does not use up a warm-up slot.
    public static func stamp(_ s: PlaySession, defaults: UserDefaults) -> PlaySession {
        var s = s
        let done = count(s.game, defaults: defaults)
        let n = done + 1
        if s.valid != false { defaults.set(n, forKey: key(s.game)) }
        s.session_index = n
        s.warmup = n <= warmupSessions
        return s
    }

    /// Envelope quality: a doubtful session is below every metric's `quality_min` (0.5); a fine one carries the
    /// share of usable trials (never below 0.6, so a few missed trials do not hide the session).
    public static func quality(_ s: PlaySession) -> Double {
        if s.valid == false { return 0.2 }
        guard let n = s.trials_n, n > 0, let v = s.valid_n else { return 1 }
        return GameStats.round(max(0.6, min(1, Double(v) / Double(n))), 2)
    }
}

/// Which measured games are in today's path. The lantern is the daily anchor (the shortest task with the best
/// repeat reliability); the second one rotates, so each comes round every third day and a day's games stay
/// around three minutes.
public enum GameRotation {
    public static let anchor: PlayGame = .lantern
    public static let cycle: [PlayGame] = [.seeds, .pebbles, .watering]

    public static func rotating(dayOfYear: Int) -> PlayGame { cycle[((dayOfYear % cycle.count) + cycle.count) % cycle.count] }

    public static func today(_ date: Date = Date(), calendar: Calendar = .current) -> [PlayGame] {
        let d = calendar.ordinality(of: .day, in: .year, for: date) ?? 1
        return [anchor, rotating(dayOfYear: d)]
    }

    /// Rough play time in seconds (intro and practice included), for the "about n min" labels and the budget test.
    public static func seconds(_ g: PlayGame) -> Int {
        switch g {
        case .lantern: return 95
        case .seeds: return 110
        case .watering: return 90
        case .pebbles: return 120
        default: return 60
        }
    }
}

/// The raw trials of the last sessions, kept on this device only (Application Support/Kaiku/game_trials.json).
/// Nothing reads it back into the UI; it is the record behind the summary numbers that were sent.
public actor GameTrialLog {
    public struct Entry: Codable, Sendable, Equatable {
        public var game: String
        public var at: String
        public var input: String?
        public var trials: [GameTrial]
    }

    public static let shared = GameTrialLog()
    public static let maxSessions = 120
    private let url: URL

    public init(url: URL = KaikuPaths.support.appendingPathComponent("game_trials.json")) { self.url = url }

    public func entries() -> [Entry] {
        guard let data = try? Data(contentsOf: url) else { return [] }
        return (try? JSONDecoder().decode([Entry].self, from: data)) ?? []
    }

    public func append(game: PlayGame, input: PlayInput?, trials: [GameTrial], at: Date = Date()) {
        var all = entries()
        all.append(Entry(game: game.rawValue, at: KaikuTime.iso(at), input: input?.rawValue, trials: trials))
        if all.count > Self.maxSessions { all.removeFirst(all.count - Self.maxSessions) }
        if let data = try? JSONEncoder().encode(all) { try? data.write(to: url, options: .atomic) }
    }
}

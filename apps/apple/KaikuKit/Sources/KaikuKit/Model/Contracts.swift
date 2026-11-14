import Foundation

// Swift mirrors of the contracts this app sends and reads. Ground truth: contracts/python/kaiku_contracts
// (payloads.py, api.py) → contracts/schemas/*.json. Field names are the JSON names (snake_case) on purpose, so a
// diff against the schema is a read-across. Optional fields are omitted when nil (the cloud models use
// extra="forbid", so only schema fields are ever sent). ContractTests checks every payload against its schema.

public let kaikuSchemaVersion = 1

// MARK: - Envelope

public enum EnvelopeSource: String, Codable, Sendable { case phone, laptop }

public struct Envelope<P: Codable & Sendable>: Codable, Sendable {
    public var v: Int = kaikuSchemaVersion
    public var id: String
    public var ts: String
    public var home_id: String
    public var source: EnvelopeSource
    public var type: String
    public var payload: P
    public var sim: Bool = false

    public init(id: String = UUID7.make(), ts: Date = Date(), home_id: String, source: EnvelopeSource,
                type: String, payload: P, sim: Bool = false) {
        self.id = id
        self.ts = KaikuTime.iso(ts)
        self.home_id = home_id
        self.source = source
        self.type = type
        self.payload = payload
        self.sim = sim
    }
}

/// A type-erased envelope, as stored in the offline queue and sent in `POST /v1/events` batches.
public struct AnyEnvelope: Codable, Sendable, Identifiable, Hashable {
    public var v: Int
    public var id: String
    public var ts: String
    public var home_id: String
    public var source: String
    public var type: String
    public var payload: JSONValue
    public var sim: Bool?

    public init<P>(_ e: Envelope<P>) throws {
        let data = try JSONEncoder().encode(e.payload)
        v = e.v; id = e.id; ts = e.ts; home_id = e.home_id; source = e.source.rawValue; type = e.type
        payload = try JSONDecoder().decode(JSONValue.self, from: data)
        sim = e.sim
    }
}

public enum KaikuTime {
    /// UTC with milliseconds and Z, as the envelope wants (`2026-11-14T08:05:00.123Z`).
    public static func iso(_ d: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        f.timeZone = TimeZone(identifier: "UTC")
        return f.string(from: d)
    }

    public static func parse(_ s: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: s) { return d }
        // Python isoformat without zone ("2026-11-14T08:05:00.123456") or with +00:00
        let p = DateFormatter()
        p.locale = Locale(identifier: "en_US_POSIX")
        p.timeZone = TimeZone(identifier: "UTC")
        for fmt in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXXXX", "yyyy-MM-dd'T'HH:mm:ssXXXXX", "yyyy-MM-dd'T'HH:mm:ss.SSSSSS",
                    "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd"] {
            p.dateFormat = fmt
            if let d = p.date(from: s) { return d }
        }
        return nil
    }
}

// MARK: - Payloads (obs.*)

public enum DialItem: String, Codable, CaseIterable, Sendable, Identifiable {
    case mood, energy, sleep
    public var id: String { rawValue }
}

public enum SelfReportChannel: String, Codable, Sendable { case robot, phone, mac, web, glasses_voice }

/// obs.self_report — one dial answer (1..5).
public struct SelfReport: Codable, Sendable, Equatable {
    public var item: DialItem
    public var value: Int
    public var channel: SelfReportChannel
    public var context: String = "adhoc"

    public init(item: DialItem, value: Int, channel: SelfReportChannel, context: String = "adhoc") {
        self.item = item
        self.value = min(5, max(1, value))
        self.channel = channel
        self.context = context
    }
}

public enum PlayGame: String, Codable, Sendable, CaseIterable, Identifiable {
    case firefly, pebbles, tell, breathe
    public var id: String { rawValue }
}

public enum PlayDevice: String, Codable, Sendable { case phone, mac, web }

/// obs.play_session — one short game. Fields a game doesn't produce stay nil (and are not sent).
public struct PlaySession: Codable, Sendable, Equatable {
    public var game: PlayGame
    public var device: PlayDevice
    public var duration_s: Double
    public var reaction_ms_median: Double?
    public var reaction_ms_iqr: Double?
    public var lapses: Int?
    public var false_taps: Int?
    public var speech_rate: Double?
    public var pause_ratio: Double?
    public var pitch_variability: Double?
    public var hr_before_bpm: Double?
    public var hr_after_bpm: Double?
    public var span_max: Int?
    public var accuracy: Double?

    public init(game: PlayGame, device: PlayDevice, duration_s: Double) {
        self.game = game
        self.device = device
        self.duration_s = min(3600, max(0, duration_s))
    }
}

// MARK: - API (cloud HTTP models, kaiku_contracts/api.py)

public enum MascotMood: String, Codable, Sendable { case idle, happy, cozy, crisis }

public struct MascotInfo: Codable, Sendable, Equatable {
    public var mood: MascotMood
    public var line_key: String?
}

public enum NudgeArm: String, Codable, Sendable, CaseIterable {
    case breathe, drum, daylight_walk, friend_ping, icbt_exercise
}

public struct NudgeResponse: Codable, Sendable, Equatable {
    public var arm: NudgeArm
    public var reason: String
    public var probs: [String: Double]?
}

public enum HighlightKind: String, Codable, Sendable { case good, hard }

public struct Highlight: Codable, Sendable, Equatable, Hashable {
    public var date: String
    public var kind: HighlightKind
    public var text: String
    public var source: String
}

public struct GardenDay: Codable, Sendable, Equatable, Hashable {
    public var date: String          // local day, yyyy-MM-dd
    public var count: Int
    public var kinds: [String]       // ritual, drum_session, play_session, outing, friend_link, weather_check
    public init(date: String, count: Int = 0, kinds: [String] = []) { self.date = date; self.count = count; self.kinds = kinds }
}

public struct Garden: Codable, Sendable, Equatable {
    public var plants: Int
    public var resting: Bool
    /// The last 14 local days, oldest first (one plot each). Absent from older clouds → [].
    public var days: [GardenDay]
    public init(plants: Int = 0, resting: Bool = false, days: [GardenDay] = []) {
        self.plants = plants; self.resting = resting; self.days = days
    }
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        plants = try c.decodeIfPresent(Int.self, forKey: .plants) ?? 0
        resting = try c.decodeIfPresent(Bool.self, forKey: .resting) ?? false
        days = try c.decodeIfPresent([GardenDay].self, forKey: .days) ?? []
    }
}

public struct HelpStat: Codable, Sendable, Equatable {
    public var activity: String
    public var label: String
    public var tries: Int
    public var mean_effect: Double?
}

public struct MeResponse: Codable, Sendable, Equatable {
    public var home_id: String
    public var summary: String
    public var last_week: [String]?
    public var what_helps: [HelpStat]?
    public var next_suggestion: NudgeResponse?
    public var phq9_due: Bool?
    public var mascot: MascotInfo?
    public var highlights: [Highlight]?
    public var garden: Garden?
    public var sim: Bool?
}

public enum MemoryCategory: String, Codable, Sendable, CaseIterable {
    case name, people, places, likes, what_helps, plans, preference
}

public struct Memory: Codable, Sendable, Equatable, Identifiable, Hashable {
    public var id: Int
    public var category: MemoryCategory
    public var text: String
    public var created: String
    public var last_used: String?
}

public struct MemoriesResponse: Codable, Sendable, Equatable {
    public var home_id: String
    public var remember: Bool
    public var memories: [Memory]
}

public struct MemorySettings: Codable, Sendable, Equatable { public var remember: Bool }
public struct DeletedResponse: Codable, Sendable, Equatable { public var deleted: Int }

public struct EventsBatch: Codable, Sendable { public var events: [AnyEnvelope] }

public struct EventsResult: Codable, Sendable, Equatable {
    public var accepted: Int
    public var duplicates: Int
    public var rejected: [JSONValue]?
}

public struct LiveEventsResponse: Codable, Sendable { public var events: [AnyEnvelope] }

public enum CompanionSurface: String, Codable, Sendable { case robot, glasses, iphone, mac, web }
public enum CompanionIntent: String, Codable, Sendable { case ritual, checkin, walk, breathe, talk, `break` }

public struct CompanionSessionRequest: Codable, Sendable {
    public var surface: CompanionSurface
    public var home_id: String
    public var intent: CompanionIntent
    public var language: String?
    public var others_present: Bool = false
}

public struct LiveToken: Codable, Sendable, Equatable {
    public var token: String
    public var expires_at: String
    public var new_session_expires_at: String
}

public struct CompanionTool: Codable, Sendable, Equatable {
    public var name: String
    public var description: String
    public var parameters: JSONValue
}

public struct ContextCard: Codable, Sendable, Equatable {
    public var time_of_day: String
    public var language: String?
    public var intent: String?
    public var first_name: String?
    public var suggestion: String?
    public var open_thread: String?
    public var tone: String?
}

public struct CompanionSessionResponse: Codable, Sendable, Equatable {
    public var session_id: String
    public var model: String
    public var voice: String
    public var system_instruction: String
    public var tools: [CompanionTool]
    public var context_card: ContextCard
    public var persona_version: String
    public var safety_phrases_version: String
    public var live_token: LiveToken?
    /// Kaiku's recommended Live setup (persona, voice, `[live]` VAD); the token locks only the model.
    public var live_setup: JSONValue?
}

public struct CompanionToolCall: Codable, Sendable {
    public var home_id: String
    public var surface: CompanionSurface
    public var name: String
    public var args: [String: JSONValue]
    public var session_id: String?
}

public struct CompanionToolResult: Codable, Sendable, Equatable {
    public var ok: Bool
    public var name: String
    public var executor: String?
    public var result: JSONValue?
    public var error: String?
    public var crisis: Bool?
}

public enum EpisodeOutcome: String, Codable, Sendable { case completed, skipped, ended_early, crisis, offline }

public enum TranscriptRole: String, Codable, Sendable { case person, kaiku }
public struct TranscriptTurn: Codable, Sendable, Equatable {
    public var role: TranscriptRole
    public var text: String
}

public struct EpisodeIn: Codable, Sendable {
    public var id: String?
    public var home_id: String
    public var surface: CompanionSurface
    public var intent: CompanionIntent
    public var start: String
    public var end: String?
    public var outcome: EpisodeOutcome
    public var tools_used: [String]
    /// Only with the `transcripts` consent on (contracts: api.EpisodeIn.transcript).
    public var transcript: [TranscriptTurn]? = nil
}

public struct StoredTranscript: Codable, Sendable, Equatable {
    public var episode_id: String
    public var surface: CompanionSurface
    public var intent: CompanionIntent
    public var start: String
    public var turns: [TranscriptTurn]
}

public struct TranscriptsResponse: Codable, Sendable, Equatable {
    public var home_id: String
    public var transcripts: [StoredTranscript]
}

public struct EpisodeResult: Codable, Sendable { public var ok: Bool; public var id: String; public var transcript_stored: Bool? }

/// Tool registry facts the device needs (contracts/schemas/companion_tools.json → `executor`). Device tools are
/// handled in the app; cloud tools are forwarded to POST /v1/companion/tool.
public enum ToolExecutor {
    public static let deviceTools: Set<String> = [
        "express", "log_walk_moment", "look_at_this", "record_dial", "send_friend_ping", "start_activity", "start_phq9",
    ]
    public static func isDevice(_ name: String) -> Bool { deviceTools.contains(name) }
}

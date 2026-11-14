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
    /// 0..1, optional: criteria metrics skip readings below their `quality_min` (a doubtful game session).
    public var quality: Double?

    public init(id: String = UUID7.make(), ts: Date = Date(), home_id: String, source: EnvelopeSource,
                type: String, payload: P, sim: Bool = false, quality: Double? = nil) {
        self.quality = quality.map { min(1, max(0, $0)) }
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
    public var quality: Double?

    public init<P>(_ e: Envelope<P>) throws {
        let data = try JSONEncoder().encode(e.payload)
        v = e.v; id = e.id; ts = e.ts; home_id = e.home_id; source = e.source.rawValue; type = e.type
        payload = try JSONDecoder().decode(JSONValue.self, from: data)
        sim = e.sim
        quality = e.quality
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
    case lantern, seeds, watering
    public var id: String { rawValue }
}

public enum PlayDevice: String, Codable, Sendable { case phone, mac, web }

/// How the person answered in a game (timing provenance: a touch, a click and a key have different latencies).
public enum PlayInput: String, Codable, Sendable { case touch, pointer, keyboard, mixed }

/// Why a game session is doubtful (it is still sent, with `valid: false` and a low envelope quality).
public enum PlayFlag: String, Codable, Sendable, CaseIterable {
    case few_trials, false_starts, low_accuracy, too_fast, interrupted
}

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
    public var expressivity_index: Double?
    public var face_movement: Double?
    public var camera_face_coverage: Double?
    public var camera_samples: Int?
    public var camera_method: String?
    public var hr_before_bpm: Double?
    public var hr_after_bpm: Double?
    public var span_max: Int?
    public var accuracy: Double?
    // research-inspired games (lantern, seeds, watering; docs/validation.md → Games)
    public var trials_n: Int?
    public var valid_n: Int?
    public var input: PlayInput?
    public var session_index: Int?
    public var warmup: Bool?
    public var valid: Bool?
    public var flags: [PlayFlag]?
    public var false_starts: Int?
    public var response_speed: Double?
    public var reaction_ms_cv: Double?
    public var throughput_per_min: Double?
    public var hard_choice_ratio: Double?
    public var tap_rate_hz: Double?
    public var rt_ms: [Int]?
    public var trial_codes: String?

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
/// Why this conversation was opened (contracts: api.CompanionSessionRequest.purpose). The cloud shapes the chat
/// with it: a check-in is a small passing chat that closes itself on an ordinary day.
public enum CompanionPurpose: String, Codable, Sendable { case talk, check_in, walk, ritual }

public struct CompanionSessionRequest: Codable, Sendable {
    public var surface: CompanionSurface
    public var home_id: String
    public var intent: CompanionIntent
    public var language: String?
    public var others_present: Bool = false
    public var resume_session_id: String? = nil
    /// Omitted when nil, so a cloud that does not know the field yet still accepts the request.
    public var purpose: CompanionPurpose? = nil
    /// Walk sessions: how Kaiku walks with the person (the person's choice on this device). Omitted when nil.
    public var walk_style: WalkStyle? = nil
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
    /// "NON_BLOCKING": Live asynchronous function calling; answer with the result's `scheduling`.
    public var behavior: String? = nil
}

public struct ContextCard: Codable, Sendable, Equatable {
    public var time_of_day: String
    public var language: String?
    public var intent: String?
    public var first_name: String?
    public var suggestion: String?
    public var open_thread: String?
    public var tone: String?
    /// Plain facts the person recorded themselves today, in everyday words ("a short night"); never a number.
    public var today_facts: [String]? = nil
    public var last_reflection: LastReflection? = nil
    /// Set when the device said why it opened the session (talk | check_in | walk | ritual).
    public var purpose: String? = nil
    /// Check-in sessions: how the chat should open (brief | stay).
    public var chat_depth: String? = nil
    /// Check-in sessions: dials not answered today (mood | energy | sleep).
    public var open_items: [String]? = nil
}

/// How the latest talk with Kaiku went: a level and themes, never the words (contracts: api.LastReflection).
public struct LastReflection: Codable, Sendable, Equatable {
    public var when: String?
    public var valence: String?
    public var themes: [String]?
    public var declined: Bool?
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
    public var max_session_seconds: Int? = nil
    /// The quiet limit after which the device ends the call by itself (talk and check-in 180, a walk 900).
    public var idle_end_s: Int? = nil
    public var context_refresh_seconds: Int? = nil
    /// Kaiku's recommended Live setup (persona, voice, `[live]` VAD); the token locks only the model.
    public var live_setup: JSONValue?
    /// How this conversation should run (contracts: api.ChatShape {purpose, depth, open_items}): the same guidance
    /// the model reads. Loosely typed on purpose: the device only reads it; absent when no purpose was sent.
    public var chat_shape: JSONValue? = nil
    /// Walk sessions only: the nudges the device sends so Kaiku can speak first (contracts: api.WalkGuide).
    public var walk: WalkGuide? = nil
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
    public var complete: Bool? = nil
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

/// `POST /v1/companion/close` (contracts: api.SessionClose): a conversation stopped and how long it ran, across
/// every token it used. The cloud settles its Live budget hold to that time.
public struct SessionClose: Codable, Sendable, Equatable {
    public var home_id: String
    public var session_id: String
    public var elapsed_s: Double
}
public struct SessionCloseResult: Codable, Sendable { public var ok: Bool; public var session_id: String }

/// Tool registry facts the device needs (contracts/schemas/companion_tools.json → `executor`). Device tools are
/// handled in the app; cloud tools are forwarded to POST /v1/companion/tool.
public enum ToolExecutor {
    public static let deviceTools: Set<String> = [
        "express", "log_walk_moment", "look_at_this", "record_dial", "send_friend_ping", "start_activity", "start_phq9",
        // In the registry since 2026-11-14: the walk's spotting game (`WalkModel.walkTool`) and the activity card
        // in a conversation (`TalkModel.deviceTool`). A surface that has no use for one answers "not on this
        // device" (the default of every `deviceTool`) instead of forwarding it to the cloud.
        "set_walk_goal", "suggest_activity",
    ]
    public static func isDevice(_ name: String) -> Bool { deviceTools.contains(name) }
}

/// What the cloud's `feel` tool hands back when the voice model noticed a feeling or news (contracts:
/// api.FeelPlan; chosen by code in the cloud from this person's own record). The device never decides any of it:
/// it shows the one thing that may be offered as a soft chip, lets a `stay` conversation run on, and plays the
/// completion sparkle once for good news. The hints for the model's own words (`reflect_hint`, `recall`,
/// `offer_note`) go back to the model untouched and are not read here.
public struct FeelPlan: Equatable, Sendable {
    public enum Depth: String, Sendable { case brief, stay }
    /// comfort | celebrate | steady | explore | give_space
    public var stance: String?
    public var depth: Depth
    /// One small thing Kaiku may offer once, as a phrase for the model ("sitting quietly together for a minute").
    public var mayOffer: String?
    /// The `start_activity` kind behind the offer, when it is an activity (breathe | drum | walk …).
    public var offerActivity: String?

    public init(stance: String? = nil, depth: Depth = .brief, mayOffer: String? = nil, offerActivity: String? = nil) {
        self.stance = stance; self.depth = depth; self.mayOffer = mayOffer; self.offerActivity = offerActivity
    }

    /// Reads a tool result. Nil when it is not a plan.
    public init?(result: JSONValue?) {
        guard let result, case .object(let o) = result["plan"] ?? result,
              o["depth"] != nil || o["stance"] != nil else { return nil }
        stance = o["stance"]?.string
        depth = o["depth"]?.string.flatMap(Depth.init(rawValue:)) ?? .brief
        mayOffer = o["may_offer"]?.string
        offerActivity = o["offer_activity"]?.string
    }

    /// Good news: the one case that gets the sparkle moment.
    public var isGoodNews: Bool { stance == "celebrate" }
}

public extension CompanionSessionResponse {
    /// How the cloud wants this conversation to open (`chat_shape.depth`): `stay` after a heavy few days.
    var openingDepth: FeelPlan.Depth? { chat_shape?["depth"]?.string.flatMap(FeelPlan.Depth.init(rawValue:)) }
    /// Check-in dials not answered today on any surface (`chat_shape.open_items`); nil on an older cloud.
    var openCheckInItems: [DialItem]? {
        guard case .array(let a)? = chat_shape?["open_items"] else { return nil }
        return a.compactMap { $0.string.flatMap(DialItem.init(rawValue:)) }
    }
}

// MARK: - Walking together (contracts: api.WalkGuide, api.WalkGoalResult, api.WalkMomentResult)

/// How Kaiku walks with the person (`CompanionSessionRequest.walk_style`; registry `walk_styles`). What each style
/// means for Kaiku's words lives in the cloud (config/persona.md "Walking together"); the device stores the
/// person's choice, sends it, and shows it.
public enum WalkStyle: String, Codable, Sendable, CaseIterable, Identifiable {
    case quiet, playful, chatty
    public var id: String { rawValue }
}

/// `CompanionSessionResponse.walk`: the nudges the device sends on a walk. A Live session only answers input, so
/// the device sends `look_prompt` every `look_every_s` (camera on, nobody speaking) and `quiet_prompt` once after
/// `quiet_after_s` without anyone speaking. Nil = that nudge is not used in this style. Timing rules: `WalkNudger`.
public struct WalkGuide: Codable, Sendable, Equatable {
    public var style: WalkStyle
    public var look_every_s: Int? = nil
    public var look_prompt: String? = nil
    public var quiet_after_s: Int? = nil
    public var quiet_prompt: String? = nil

    public init(style: WalkStyle, look_every_s: Int? = nil, look_prompt: String? = nil,
                quiet_after_s: Int? = nil, quiet_prompt: String? = nil) {
        self.style = style; self.look_every_s = look_every_s; self.look_prompt = look_prompt
        self.quiet_after_s = quiet_after_s; self.quiet_prompt = quiet_prompt
    }

    /// A style this build does not know must not stop the walk's conversation from opening.
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        style = (try? c.decode(WalkStyle.self, forKey: .style)) ?? .quiet
        look_every_s = try? c.decodeIfPresent(Int.self, forKey: .look_every_s)
        look_prompt = try? c.decodeIfPresent(String.self, forKey: .look_prompt)
        quiet_after_s = try? c.decodeIfPresent(Int.self, forKey: .quiet_after_s)
        quiet_prompt = try? c.decodeIfPresent(String.self, forKey: .quiet_prompt)
    }
}

// MARK: - Invitation (contracts: api.InvitationResponse, api.Invitation, api.InvitationAnswer)

/// One thing Kaiku would like to bring up or offer now (`GET /v1/me/invitation`). Chosen by code in the cloud;
/// the device shows the sentence and two answers and goes where a yes leads.
public struct Invitation: Codable, Sendable, Equatable, Identifiable {
    public enum Kind: String, Codable, Sendable { case talk_about, activity }
    public var id: String
    public var kind: Kind
    public var text: String
    /// Names the template the cloud used. Not an audio key: `text` is spoken with `POST /v1/voice/say`.
    public var voice_key: String
    public var topic: String? = nil
    /// One of the registry's `activities` (kept as the raw word: a kind this build has no screen for is not shown).
    public var activity: String? = nil
}

public struct InvitationResponse: Codable, Sendable, Equatable {
    public var home_id: String
    public var invitation: Invitation? = nil
}

/// `POST /v1/me/invitation/answer`. A not-now is final for that id.
public struct InvitationAnswer: Codable, Sendable, Equatable {
    public enum Answer: String, Codable, Sendable { case yes, not_now }
    public var id: String
    public var answer: Answer
    public init(id: String, answer: Answer) { self.id = id; self.answer = answer }
}

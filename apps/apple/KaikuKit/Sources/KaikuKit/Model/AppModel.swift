import Foundation
import Observation
import SwiftUI

/// The signals the person can allow (onboarding consent, "What Kaiku saw today" pauses). Ids match copy keys
/// `sig.<id>.{t,d}`. Check-ins + walks default on, the rest off (design/ia.md → Onboarding).
public enum Signal: String, CaseIterable, Identifiable, Sendable {
    case checkins, walks, voice, mac, watch
    public var id: String { rawValue }
    public var defaultOn: Bool { self == .checkins || self == .walks }
    /// Signals this platform can actually produce (others are shown but explained as another device's).
    public static var forThisDevice: [Signal] { KaikuPlatform.isPhone ? [.checkins, .walks, .voice, .watch] : [.checkins, .voice, .mac] }
}

public enum VoicePace: String, CaseIterable, Sendable { case slow, normal }

/// One observable model shared by every screen (iPhone + Mac). Network + persistence live in `APIClient` and
/// `OfflineQueue`; settings live in UserDefaults (no secrets there — the pairing is in the Keychain).
@Observable @MainActor
public final class AppModel {
    public private(set) var pairing: Pairing?
    @ObservationIgnored public let api: APIClient
    @ObservationIgnored let queue: OfflineQueue
    @ObservationIgnored private let defaults: UserDefaults

    // cloud state
    public var me: MeResponse?
    public var nudge: NudgeResponse?
    public var memories: [Memory] = []
    public var remember = true
    public var memoriesLoaded = false
    public var todayEvents: [AnyEnvelope] = []
    public var loading = false
    public var offline = false
    public var queued = 0

    // UI state
    public var showCrisis = false
    public var toast: String?
    public var celebrateUntil: Date?
    public var selectedTab: KaikuTab = .today
    public var deepLink: KaikuRoute?
    // A2 (iPhone extras)
    /// A notification / widget asked for the PHQ-9 (web page): the shell opens `phq9URL`.
    public var phq9Requested = false
    /// nil = not asked yet, false = turned off in Settings (You shows a calm "turned off" row).
    public var notificationsOn: Bool?
    public var healthState: HealthState = .off
    /// Which glasses adapter a walk uses (the iOS shell sets DAT or mock; nil = phone only).
    @ObservationIgnored public var makeGlasses: (() -> GlassesAdapter?)?

    // settings
    public var onboarded: Bool { didSet { defaults.set(onboarded, forKey: "kaiku.onboarded") } }
    public var language: KaikuLanguage {
        didSet { L10n.shared.language = language; defaults.set(language.rawValue, forKey: "kaiku.lang") }
    }
    public var consents: [Signal: Bool] { didSet { saveDict(consents.mapKeys(\.rawValue), "kaiku.consents") } }
    public var pausedAll: Bool { didSet { defaults.set(pausedAll, forKey: "kaiku.pausedAll") } }
    public var pausedUntil: Date? { didSet { defaults.set(pausedUntil, forKey: "kaiku.pausedUntil") } }
    public var pace: VoicePace { didSet { defaults.set(pace.rawValue, forKey: "kaiku.pace") } }
    public var quietFrom: Date { didSet { defaults.set(quietFrom, forKey: "kaiku.quietFrom") } }
    public var quietTo: Date { didSet { defaults.set(quietTo, forKey: "kaiku.quietTo") } }
    public var quietWeekend: Bool { didSet { defaults.set(quietWeekend, forKey: "kaiku.quietWeekend") } }
    public var weatherDoneDay: String? { didSet { defaults.set(weatherDoneDay, forKey: "kaiku.weatherDone") } }
    public var breathHaptics: Bool { didSet { defaults.set(breathHaptics, forKey: "kaiku.breathHaptics") } }
    /// Tiny UI sounds (games, dials). Respects the silent switch (iOS) and system mute. Default on.
    public var sounds: Bool { didSet { defaults.set(sounds, forKey: KSound.enabledKey) } }
    /// Days the person marked in Your days (local only: no contract carries day marks yet).
    public var marks: [String: HighlightKind] { didSet { saveDict(marks.mapValues(\.rawValue), "kaiku.marks") } }
    /// Name override for layout stress tests (`-kaikuName Annemarie-Kristiina`); otherwise from memories.
    @ObservationIgnored private let nameOverride: String?

    public init(defaults: UserDefaults = .standard, pairing: Pairing? = PairingStore.load()) {
        self.defaults = defaults
        // Dev/test launch arguments (UserDefaults argument domain): -kaikuPairLink <url>, -kaikuSkipOnboarding YES
        var p = pairing
        if let link = defaults.string(forKey: "kaikuPairLink"), let parsed = Pairing.parse(link) {
            p = parsed
            PairingStore.save(parsed)
        }
        self.pairing = p
        api = APIClient(pairing: p)
        queue = OfflineQueue()
        onboarded = defaults.bool(forKey: "kaiku.onboarded") || defaults.bool(forKey: "kaikuSkipOnboarding")
        let langRaw = defaults.string(forKey: "kaiku.lang") ?? KaikuLanguage.system.rawValue
        language = KaikuLanguage(rawValue: langRaw) ?? .en
        let saved = defaults.dictionary(forKey: "kaiku.consents") as? [String: Bool] ?? [:]
        consents = Dictionary(uniqueKeysWithValues: Signal.allCases.map { ($0, saved[$0.rawValue] ?? $0.defaultOn) })
        pausedAll = defaults.bool(forKey: "kaiku.pausedAll")
        pausedUntil = defaults.object(forKey: "kaiku.pausedUntil") as? Date
        pace = VoicePace(rawValue: defaults.string(forKey: "kaiku.pace") ?? "") ?? .normal
        let cal = Calendar.current
        quietFrom = defaults.object(forKey: "kaiku.quietFrom") as? Date ?? cal.date(bySettingHour: 22, minute: 0, second: 0, of: Date())!
        quietTo = defaults.object(forKey: "kaiku.quietTo") as? Date ?? cal.date(bySettingHour: 8, minute: 0, second: 0, of: Date())!
        quietWeekend = defaults.object(forKey: "kaiku.quietWeekend") as? Bool ?? true
        weatherDoneDay = defaults.string(forKey: "kaiku.weatherDone")
        breathHaptics = defaults.bool(forKey: "kaiku.breathHaptics")
        sounds = defaults.object(forKey: KSound.enabledKey) as? Bool ?? true
        let m = defaults.dictionary(forKey: "kaiku.marks") as? [String: String] ?? [:]
        marks = m.compactMapValues { HighlightKind(rawValue: $0) }
        nameOverride = defaults.string(forKey: "kaikuName")
        if let tab = defaults.string(forKey: "kaikuTab").flatMap(KaikuTab.init(rawValue:)) { selectedTab = tab }
        if let r = defaults.string(forKey: "kaikuRoute").flatMap(KaikuRoute.init(rawValue:)) { deepLink = r }
        L10n.shared.language = language
        // Screenshot hook: show the crisis screen without emitting a flag.
        if defaults.bool(forKey: "kaikuShowCrisis") { showCrisis = true }
    }

    private func saveDict(_ d: [String: Any], _ key: String) { defaults.set(d, forKey: key) }

    // MARK: derived

    public var isPaired: Bool { pairing != nil }

    public var firstName: String? {
        if let n = nameOverride { return n }
        guard let m = memories.first(where: { $0.category == .name }) else { return nil }
        return NameFromMemory.extract(m.text)
    }

    /// Everything paused (switch, or "pause for 1 hour" on the Mac).
    public var isPaused: Bool {
        if pausedAll { return true }
        if let u = pausedUntil, u > Date() { return true }
        return false
    }

    public func allowed(_ s: Signal) -> Bool { !isPaused && (consents[s] ?? false) }

    /// Time-of-day greeting with the person's first name when Kaiku knows it.
    public var greeting: String {
        let h = Calendar.current.component(.hour, from: Date())
        let part = h < 5 ? "late" : h < 12 ? "morning" : h < 18 ? "afternoon" : h < 23 ? "evening" : "late"
        if let n = firstName { return T("today.greet.\(part)", ["name": n]) }
        return T("today.greet.\(part).noname")
    }

    public var weatherDoneToday: Bool { weatherDoneDay == Self.dayKey(Date()) }

    /// Ambient mascot state: `GET /v1/me → mascot.mood`, `happy` for a moment after a finished interaction,
    /// `sleepy` after 23:00, `thinking` while the first load runs.
    public var ambientState: MascotState {
        if let u = celebrateUntil, u > Date() { return .happy }
        let hour = Calendar.current.component(.hour, from: Date())
        if me == nil && loading { return .thinking }
        if me?.mascot?.mood == .cozy { return .cozy }
        if hour >= 23 || hour < 5 { return .sleepy }
        return MascotState(mood: me?.mascot?.mood)
    }

    public static func dayKey(_ d: Date) -> String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: d)
    }

    // MARK: pairing

    @discardableResult
    public func pair(link: String) async -> Bool {
        guard let p = Pairing.parse(link) else { return false }
        PairingStore.save(p)
        pairing = p
        await api.setPairing(p)
        await refresh()
        return true
    }

    public func unpair() async {
        PairingStore.clear()
        pairing = nil
        await api.setPairing(nil)
        me = nil; nudge = nil; memories = []; todayEvents = []
    }

    // MARK: loading

    public func refresh() async {
        guard pairing != nil else { return }
        loading = true
        defer { loading = false }
        await flush()
        async let meR = try? api.me()
        async let nudgeR = try? api.nudge()
        async let memR = try? api.memories()
        let (m, n, mem) = await (meR, nudgeR, memR)
        if let m { me = m; offline = false } else { offline = true }
        // Cloud state `safety` → mood `crisis`: the scripted screen, once per launch (no new flag: the cloud knows).
        if m?.mascot?.mood == .crisis, !crisisShownForMood { crisisShownForMood = true; present(crisis: true) }
        nudge = n ?? m?.next_suggestion
        if let mem { memories = mem.memories; remember = mem.remember; memoriesLoaded = true }
        await loadToday()
    }

    public func loadToday() async {
        let start = Calendar.current.startOfDay(for: Date())
        if let r = try? await api.todaysEvents(since: start) { todayEvents = r.events.filter { $0.home_id == pairing?.homeID } }
    }

    public func loadMemories() async {
        do {
            let r = try await api.memories()
            memories = r.memories; remember = r.remember; memoriesLoaded = true; offline = false
        } catch { offline = true; memoriesLoaded = true }
    }

    public func deleteMemory(_ m: Memory) async {
        memories.removeAll { $0.id == m.id }
        if (try? await api.deleteMemory(m.id)) != nil { toast = T("toast.deleted") } else { offline = true; await loadMemories() }
    }

    public func forgetAll() async {
        let before = memories
        memories = []
        if (try? await api.deleteAllMemories()) != nil { toast = T("toast.deleted") } else { memories = before; offline = true }
    }

    public func setRemember(_ on: Bool) async {
        remember = on
        if let r = try? await api.setRemember(on) { remember = r.remember } else { offline = true }
    }

    // MARK: recording (everything goes through the offline queue)

    func emit<P: Codable & Sendable>(_ type: String, _ payload: P, id: String = UUID7.make(), ts: Date = Date()) async {
        guard let p = pairing else { return }
        let env = Envelope(id: id, ts: ts, home_id: p.homeID, source: KaikuPlatform.source, type: type, payload: payload)
        guard let any = try? AnyEnvelope(env) else { return }
        await queue.enqueue(any)
        await flush()
    }

    public func flush() async {
        let ok = await queue.flush(using: api)
        queued = await queue.count
        if !ok { offline = true }
    }

    /// The weather check: three obs.self_report (channel phone|mac). Sent only with the check-ins signal on.
    public func recordWeather(_ values: [DialItem: Int]) async {
        weatherDoneDay = Self.dayKey(Date())
        celebrate()
        guard allowed(.checkins) else { return }
        for item in DialItem.allCases {
            if let v = values[item] { await emit("obs.self_report", SelfReport(item: item, value: v, channel: KaikuPlatform.channel)) }
        }
        await loadToday()
    }

    /// Quick mood from a notification button (Good · Okay · Low → 4 · 3 · 2). Queued if offline.
    public func recordQuickMood(_ value: Int) async {
        guard allowed(.checkins) else { return }
        await emit("obs.self_report", SelfReport(item: .mood, value: value, channel: KaikuPlatform.channel, context: "adhoc"))
    }

    /// One finished game → obs.play_session. Speech features only with the voice signal on.
    public func recordPlay(_ session: PlaySession) async {
        celebrate()
        guard allowed(.checkins) else { return }
        var s = session
        if s.game == .tell && !allowed(.voice) { s.speech_rate = nil; s.pause_ratio = nil; s.pitch_variability = nil }
        await emit("obs.play_session", s)
        await loadToday()
    }

    /// Crisis: show the scripted screen first, then tell the care team (obs.safety_flag, sent before anything
    /// else in the queue would be nicer; the queue is FIFO and small, and flushes immediately).
    @ObservationIgnored private var crisisShownForMood = false

    private func present(crisis: Bool) {
        var t = Transaction()
        t.disablesAnimations = true   // crisis: no motion at all
        withTransaction(t) { showCrisis = crisis }
    }

    public func crisis(trigger: String) {
        present(crisis: true)
        Task { await emit("obs.safety_flag", SafetyFlag(trigger: trigger, handled_locally: true)) }
    }

    public func celebrate() { celebrateUntil = Date().addingTimeInterval(6) }

    public func showToast(_ text: String) { toast = text }
}

/// obs.safety_flag — emitted when the person opens the crisis screen or a crisis phrase hits on this device.
public struct SafetyFlag: Codable, Sendable {
    public var trigger: String       // phrase | manual
    public var handled_locally: Bool
    public var severity = "high"
}

/// Port of `cloud/kaiku_cloud/mind/memory.first_name` (the context card uses the same rule).
public enum NameFromMemory {
    static let re = try! NSRegularExpression(pattern: "(?:name is|call me|i'm|i am|nimeni on|olen|jag heter)\\s+(\\w+)",
                                             options: [.caseInsensitive])
    public static func extract(_ text: String) -> String? {
        let r = NSRange(text.startIndex..., in: text)
        if let m = re.firstMatch(in: text, range: r), let g = Range(m.range(at: 1), in: text) { return String(text[g]) }
        return text.split(separator: " ").count <= 2 ? text : nil
    }
}

extension Dictionary {
    func mapKeys<K: Hashable>(_ f: (Key) -> K) -> [K: Value] { Dictionary<K, Value>(uniqueKeysWithValues: map { (f($0.key), $0.value) }) }
}

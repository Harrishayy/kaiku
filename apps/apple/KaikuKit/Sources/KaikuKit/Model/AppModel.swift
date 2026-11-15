import Foundation
import Observation
import SwiftUI

/// The signals the person can allow (onboarding consent, "What Kaiku saw today" pauses). Ids match copy keys
/// `sig.<id>.{t,d}`. Check-ins + walks default on, the rest off (design/ia.md → Onboarding).
public enum Signal: String, CaseIterable, Identifiable, Sendable {
    case checkins, walks, voice, camera, mac, watch
    /// Keep the words of conversations with Kaiku (opt-in, off by default): the person can read and delete them;
    /// never shown to the care team; used de-identified to teach Kaiku's own model. Crisis talk is never kept.
    case transcripts
    /// "Let Kaiku see through the glasses during walks" (off by default): about one picture a second goes to the
    /// live conversation only, while it is open. Never saved, never sent to the Kaiku cloud.
    case see
    /// "Let Kaiku's model look" (off by default, D65): during a check-in with the camera on, a few small pictures
    /// go to the Kaiku service once, where Kaiku's own model (Gemma) looks at them. Pictures are not saved; only
    /// what it notes is kept.
    case look
    public var id: String { rawValue }
    public var defaultOn: Bool { self == .checkins || self == .walks }
    /// Signals this platform can actually produce (others are shown but explained as another device's).
    public static var forThisDevice: [Signal] {
        KaikuPlatform.isPhone ? [.checkins, .walks, .voice, .camera, .look, .watch, .transcripts, .see]
            : [.checkins, .voice, .camera, .look, .mac, .transcripts]
    }
}

public enum VoicePace: String, CaseIterable, Sendable { case slow, normal }

/// One observable model shared by every screen (iPhone + Mac). Network + persistence live in `APIClient` and
/// `OfflineQueue`; settings live in UserDefaults (no secrets there — the pairing is in the Keychain).
@Observable @MainActor
public final class AppModel {
    public private(set) var pairing: Pairing?
    private(set) var pairingRevision = 0
    @ObservationIgnored public let api: APIClient
    @ObservationIgnored let queue: OfflineQueue
    @ObservationIgnored let episodes: EpisodeOutbox
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored let serviceDiscovery: ServiceDiscovery
    @ObservationIgnored private var connectionTask: Task<Bool, Never>?
    @ObservationIgnored private let saveService: (Pairing) -> Bool

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
    /// Bumped by every finished task, game, walk or check-in: the root view plays one completion moment per bump.
    public private(set) var celebration = 0
    public var selectedTab: KaikuTab = .today
    /// The person just pressed something that means "talk with Kaiku now" (a yes on Today's talk card). Talk takes
    /// it once as it appears and opens the call; opening the Talk tab any other way only shows "Call Kaiku".
    public var talkAsked = false
    public var deepLink: KaikuRoute?
    // A2 (iPhone extras)
    /// A notification / widget asked for the PHQ-9 (web page): the shell opens `phq9URL`.
    public var phq9Requested = false
    /// nil = not asked yet, false = turned off in Settings (You shows a calm "turned off" row).
    public var notificationsOn: Bool?
    public var healthState: HealthState = .off
    /// Which glasses adapter a walk uses (the iOS shell sets DAT or mock; nil = phone only).
    @ObservationIgnored public var makeGlasses: (() -> GlassesAdapter?)?
    @ObservationIgnored public var connectGlasses: (() async -> Bool)?
    public var glassesRegistered = false
    /// The DAT SDK for the Glasses check screen (iOS shell); nil where the SDK is not linked.
    @ObservationIgnored public var glassesControl: (any GlassesControl)?

    // settings
    public var onboarded: Bool { didSet { defaults.set(onboarded, forKey: "kaiku.onboarded") } }
    /// Where first-run setup was left (`SetupStep` raw value): closing the app mid-setup resumes there.
    public var setupStep: Int { didSet { defaults.set(setupStep, forKey: "kaiku.setupStep") } }
    public var language: KaikuLanguage {
        get { .en }
        set { L10n.shared.language = .en; defaults.set("en", forKey: "kaiku.lang") }
    }
    public var consents: [Signal: Bool] { didSet {
        saveDict(consents.mapKeys(\.rawValue), "kaiku.consents")
        if consents[.transcripts] != true { episodes.removeTranscripts() }
    } }
    /// "Camera during activities": the wording agreed to, and what this device sent today.
    @ObservationIgnored let cameraChoice: CameraChoice
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
    /// Game (PlayGame raw value) → the local day it was last finished on this device. Drives Today's path ticks.
    public var playedDays: [String: String] { didSet { saveDict(playedDays, "kaiku.played") } }
    /// Local day → conversations finished on this device (the evidence list; episodes are not in /v1/events).
    public var talkDays: [String: Int] { didSet { saveDict(talkDays, "kaiku.talks") } }
    public var talksToday: Int { talkDays[Self.dayKey(Date())] ?? 0 }
    /// Name override for layout stress tests (`-kaikuName Annemarie-Kristiina`); otherwise from memories.
    @ObservationIgnored private let nameOverride: String?

    public convenience init(defaults: UserDefaults = .standard, pairing: Pairing? = PairingStore.load()) {
        self.init(defaults: defaults, pairing: pairing, api: nil, queue: OfflineQueue(), episodes: EpisodeOutbox())
    }

    init(defaults: UserDefaults, pairing: Pairing?, api injectedAPI: APIClient?, queue: OfflineQueue, episodes: EpisodeOutbox, discovery: ServiceDiscovery? = nil,
         saveService: @escaping (Pairing) -> Bool = PairingStore.save) {
        self.defaults = defaults
        cameraChoice = CameraChoice(defaults: defaults)
        self.serviceDiscovery = discovery ?? ServiceDiscovery()
        self.saveService = saveService
        // Dev/test launch arguments (UserDefaults argument domain): -kaikuPairLink <url>, -kaikuSkipOnboarding YES
        var p = pairing
        if let link = defaults.string(forKey: "kaikuPairLink"), let parsed = Pairing.parse(link) {
            if parsed.homeID != pairing?.homeID { cameraChoice.clearSent() }   // the day's camera receipt belongs to one home
            p = parsed
            PairingStore.save(parsed)
        }
        self.pairing = p
        if let p { ServiceIdentity.remember(p, defaults: defaults) }
        api = injectedAPI ?? APIClient(pairing: p)
        VoiceLines.shared.api = api   // lines not cached yet are fetched in Kaiku's real voice (never a synthesizer)
        self.queue = queue
        self.episodes = episodes
        onboarded = defaults.bool(forKey: "kaiku.onboarded") || defaults.bool(forKey: "kaikuSkipOnboarding")
        setupStep = SetupStep.resume(saved: defaults.object(forKey: "kaiku.setupStep") as? Int,
                                     launchArgument: defaults.string(forKey: "kaikuOnboardingStep")).rawValue
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
        playedDays = defaults.dictionary(forKey: "kaiku.played") as? [String: String] ?? [:]
        talkDays = (defaults.dictionary(forKey: "kaiku.talks") as? [String: Int] ?? [:]).filter { $0.key == Self.dayKey(Date()) }
        nameOverride = defaults.string(forKey: "kaikuName")
        if let tab = defaults.string(forKey: "kaikuTab").flatMap(KaikuTab.init(rawValue:)) { selectedTab = tab }
        if let r = defaults.string(forKey: "kaikuRoute").flatMap(KaikuRoute.init(rawValue:)) { deepLink = r }
        L10n.shared.language = language
        if consents[.transcripts] != true { episodes.removeTranscripts() }
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
    public func playedToday(_ game: String) -> Bool { playedDays[game] == Self.dayKey(Date()) }

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

    // MARK: companion service (independent of robot hardware)

    /// Automatic provisioning is restricted to a build-configured, explicitly demo service. Discovery on the
    /// LAN only lists candidates; it never moves an existing profile or sends credentials to those candidates.
    @discardableResult func ensureServiceConnection() async -> Bool {
        if pairing != nil { return true }
        guard !defaults.bool(forKey: "kaiku.serviceAutoDisabled") else { return false }
        if let connectionTask { return await connectionTask.value }
        let revision = pairingRevision
        let task = Task { [weak self] in
            guard let self, let candidate = await serviceDiscovery.configuredDemo(),
                  pairing == nil, revision == pairingRevision else { return self?.pairing != nil }
            return await connectService(candidate, expectedRevision: revision)
        }
        connectionTask = task
        let result = await task.value
        connectionTask = nil
        return result
    }

    /// Called for an explicit service selection, or the vetted configured-service bootstrap above.
    @discardableResult func connectService(_ candidate: DiscoveredService, expectedRevision: Int? = nil) async -> Bool {
        let revision = expectedRevision ?? pairingRevision
        guard let checked = await serviceDiscovery.inspect(candidate.baseURL),
              checked.descriptor.permitsDemoConnection, revision == pairingRevision else { return false }
        if let pairing, ServiceDiscovery.origin(pairing.baseURL.absoluteString) == checked.baseURL { return true }
        let next = Pairing(baseURL: checked.baseURL,
                           homeID: ServiceIdentity.home(for: checked.baseURL, defaults: defaults), token: nil)
        guard saveService(next) else { return false }
        defaults.set(false, forKey: "kaiku.serviceAutoDisabled")
        await updatePairing(next)
        serviceDiscovery.stop()
        return true
    }

    // MARK: pairing

    @discardableResult
    public func pair(link: String) async -> Bool {
        guard let p = Pairing.parse(link) else { return false }
        PairingStore.save(p)
        await updatePairing(p)
        await refresh()
        return true
    }

    public func unpair() async {
        defaults.set(true, forKey: "kaiku.serviceAutoDisabled")
        PairingStore.clear()
        await updatePairing(nil)
    }

    /// Invalidate in-flight reads before any suspension. Device preferences survive; person data does not.
    func updatePairing(_ next: Pairing?) async {
        guard pairing != next else { return }
        let changedHome = pairing?.baseURL != next?.baseURL || pairing?.homeID != next?.homeID
        pairingRevision += 1
        pairing = next
        if let next { ServiceIdentity.remember(next, defaults: defaults) }
        if changedHome {
            WalkModel.shared.clearForPairingChange()
            HistoryModel.shared.clearForPairingChange()   // the numbers on screen and the copy kept for offline
            InvitationModel.shared.clearForPairingChange()   // the invitation and what was agreed today (D50)
            me = nil; nudge = nil; memories = []; todayEvents = []
            remember = true; memoriesLoaded = false; conversationsKept = nil
            savedConversations = []; conversationsLoading = false; conversationsFailed = false
            healthState = .off; loading = false; offline = false; queued = 0
            toast = nil; celebrateUntil = nil; showCrisis = false; crisisShownForMood = false
            phq9Requested = false; deepLink = nil
            marks = [:]; playedDays = [:]; weatherDoneDay = nil; talkDays = [:]
            cameraChoice.clearSent()
        }
        await api.setPairing(next)
    }

    // MARK: loading

    public func refresh() async {
        guard await ensureServiceConnection() else { return }
        let revision = pairingRevision
        loading = true
        defer { if revision == pairingRevision { loading = false } }
        await flush()
        guard revision == pairingRevision else { return }
        async let meR = try? api.me()
        async let nudgeR = try? api.nudge()
        async let memR = try? api.memories()
        let (m, n, mem) = await (meR, nudgeR, memR)
        guard revision == pairingRevision else { return }
        if let m { me = m; offline = false } else { offline = true }
        // Cloud state `safety` → mood `crisis`: the scripted screen, once per launch (no new flag: the cloud knows).
        if m?.mascot?.mood == .crisis, !crisisShownForMood { crisisShownForMood = true; present(crisis: true) }
        nudge = n ?? m?.next_suggestion
        if let mem { memories = mem.memories; remember = mem.remember; memoriesLoaded = true }
        await loadToday()
    }

    public func loadToday() async {
        guard let paired = pairing else { return }
        let revision = pairingRevision
        let start = Calendar.current.startOfDay(for: Date())
        if let r = try? await api.todaysEvents(since: start), revision == pairingRevision {
            todayEvents = r.events.filter { $0.home_id == paired.homeID }
        }
    }

    public func loadMemories() async {
        guard pairing != nil else { return }
        let revision = pairingRevision
        do {
            let r = try await api.memories()
            guard revision == pairingRevision else { return }
            memories = r.memories; remember = r.remember; memoriesLoaded = true; offline = false
        } catch { if revision == pairingRevision { offline = true; memoriesLoaded = true } }
    }

    public func deleteMemory(_ m: Memory) async {
        let revision = pairingRevision
        memories.removeAll { $0.id == m.id }
        let result = try? await api.deleteMemory(m.id)
        guard revision == pairingRevision else { return }
        if result != nil { toast = T("toast.deleted") } else { offline = true; await loadMemories() }
    }

    public func forgetAll() async {
        let revision = pairingRevision
        let before = memories
        memories = []
        let result = try? await api.deleteAllMemories()
        guard revision == pairingRevision else { return }
        if result != nil { toast = T("toast.deleted") } else { memories = before; offline = true }
    }

    /// Stored conversations (opt-in `transcripts` signal); nil = not loaded / offline.
    public var conversationsKept: Int?
    public var savedConversations: [StoredTranscript] = []
    public var conversationsLoading = false
    public var conversationsFailed = false

    public func loadConversations() async {
        let revision = pairingRevision
        conversationsLoading = true; conversationsFailed = false
        let result = try? await api.transcripts()
        guard revision == pairingRevision else { return }
        conversationsLoading = false
        if let result, result.home_id == pairing?.homeID {
            savedConversations = result.transcripts
            conversationsKept = result.transcripts.count
        } else { conversationsFailed = true }
    }

    public func forgetConversations() async {
        let revision = pairingRevision
        episodes.removeTranscripts()
        let result = try? await api.deleteAllTranscripts()
        guard revision == pairingRevision else { return }
        if result != nil { conversationsKept = 0; savedConversations = []; conversationsFailed = false; toast = T("toast.deleted") } else { conversationsFailed = true; offline = true }
    }

    public func setRemember(_ on: Bool) async {
        let revision = pairingRevision
        remember = on
        let result = try? await api.setRemember(on)
        guard revision == pairingRevision else { return }
        if let result { remember = result.remember } else { offline = true }
    }

    // MARK: recording (everything goes through the offline queue)

    func emit<P: Codable & Sendable>(_ type: String, _ payload: P, id: String = UUID7.make(), ts: Date = Date(), sim: Bool = false,
                                    quality: Double? = nil, pairedTo expected: Pairing? = nil) async {
        guard let p = pairing, expected == nil || p == expected else { return }
        let env = Envelope(id: id, ts: ts, home_id: p.homeID, source: KaikuPlatform.source, type: type, payload: payload,
                           sim: sim, quality: quality)
        guard let any = try? AnyEnvelope(env) else { return }
        await queue.enqueue(any, server: p.baseURL)
        await flush()
    }

    public func flush() async {
        let revision = pairingRevision
        let ok = await queue.flush(using: api)
        let episodesOK = await episodes.flush(using: api)
        guard revision == pairingRevision else { return }
        queued = await queue.count + episodes.entries.count
        if !ok || !episodesOK { offline = true }
    }

    func finishEpisode(_ episode: EpisodeIn, pairing: Pairing) {
        if !episodes.enqueue(episode, pairing: pairing) { offline = true }
        // A conversation the person took part in counts as one of today's moments (never after a crisis).
        if episode.outcome == .completed || episode.outcome == .ended_early, self.pairing == pairing {
            talkDays = [Self.dayKey(Date()): talksToday + 1]
        }
        queued += 1
        Task { await flush() }
    }

    /// Device tools share the same consent gate as manual check-ins.
    func recordDial(item: DialItem, value: Int) async -> Bool {
        guard allowed(.checkins), (1...5).contains(value) else { return false }
        await emit("obs.self_report", SelfReport(item: item, value: value, channel: KaikuPlatform.channel, context: "adhoc"))
        return true
    }

    /// The weather check: three obs.self_report (channel phone|mac). Sent only with the check-ins signal on.
    public func recordWeather(_ values: [DialItem: Int], celebrates: Bool = true) async {
        weatherDoneDay = Self.dayKey(Date())
        if celebrates { celebrate() }
        guard allowed(.checkins) else { return }
        for item in DialItem.allCases {
            if let v = values[item] { await emit("obs.self_report", SelfReport(item: item, value: v, channel: KaikuPlatform.channel)) }
        }
        await loadToday()
    }

    /// Today's check-in happened (a chat the person took part in, or the dials): the first stop of the path is
    /// done and the completion moment plays, once a day.
    public func checkInDone() {
        guard !weatherDoneToday else { return }
        weatherDoneDay = Self.dayKey(Date())
        celebrate()
    }

    /// Quick mood from a notification button (Good · Okay · Low → 4 · 3 · 2). Queued if offline.
    public func recordQuickMood(_ value: Int) async {
        guard allowed(.checkins) else { return }
        await emit("obs.self_report", SelfReport(item: .mood, value: value, channel: KaikuPlatform.channel, context: "adhoc"))
    }

    /// One finished game → obs.play_session. Speech features only with the voice signal on.
    public func recordPlay(_ session: PlaySession, sim: Bool = false) async {
        await recordPlay(session, sim: sim, camera: nil)
    }

    /// The same, with what the task's camera measured (nil = it did not run): the two older numbers go into the
    /// game's own observation as before, and the face signs follow as one obs.face_signs that points at it.
    func recordPlay(_ session: PlaySession, sim: Bool = false, camera: TaskCameraResult?) async {
        playedDays[session.game.rawValue] = Self.dayKey(Date())
        celebrate()
        guard allowed(.checkins) else { return }
        var s = session
        if s.game == .tell && !allowed(.voice) { s.speech_rate = nil; s.pause_ratio = nil; s.pitch_variability = nil }
        // The camera choice may have been switched off while the game ran: then nothing of it is sent.
        let camera = cameraOn ? camera : nil
        let sim = sim || camera?.simulated == true
        if let geometry = camera?.geometry {
            s.expressivity_index = geometry.expressivity; s.face_movement = geometry.movement
            s.camera_face_coverage = geometry.coverage; s.camera_samples = geometry.samples
            s.camera_method = "vision_landmarks"
        }
        if !cameraOn {
            s.expressivity_index = nil; s.face_movement = nil; s.camera_face_coverage = nil
            s.camera_samples = nil; s.camera_method = nil
        }
        // Measured games: the nth session on this device (the first few are warm-up: practice effects), and a
        // doubtful session goes out with a low quality so no metric counts it.
        var quality: Double?
        if GameHistory.measured.contains(s.game) {
            s = GameHistory.stamp(s, defaults: defaults)
            quality = GameHistory.quality(s)
        }
        let id = UUID7.make()
        await emit("obs.play_session", s, id: id, sim: sim, quality: quality)
        if let camera { await recordFaceSigns(camera, task: s.game.rawValue, ref: id) }
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

    public func celebrate() { celebrateUntil = Date().addingTimeInterval(6); celebration += 1 }

    /// First-run setup finished (or skipped where that is safe): land on Today.
    public func finishSetup() {
        setupStep = SetupStep.welcome.rawValue
        selectedTab = .today
        onboarded = true
    }

    /// You → "Run setup again": the same flow from the start. Choices, pairing and data are untouched.
    public func restartSetup() {
        setupStep = SetupStep.welcome.rawValue
        deepLink = nil
        onboarded = false
    }

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

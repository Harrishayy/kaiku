import Foundation
import Observation
#if canImport(CoreMotion)
import CoreMotion
#endif

/// The walk companion (plan 05 §3, §6): Light hunt on a walk, with Meta glasses when they're there. Glasses IMU →
/// cadence, gait regularity, head-up ratio; sparse brightness → daylight minutes; at the end one
/// `obs.outing {method: dat_imu | steps}`. A disconnect mid-walk keeps the walk going on the phone (one spoken
/// notice). A draft is saved every 15 s, so a walk the app never finished (killed) is posted on the next launch.
///
/// Talking on the walk: `companion` is a live `Conversation` on the `glasses` surface (intent `walk`) — the mind
/// gives it the walking persona (very short turns, never "look at your screen") and the walk tools. With Meta
/// glasses paired over Bluetooth, the glasses' mics and speakers carry it (HFP); without them the phone does.
/// The walk tells Kaiku what happens as short context events (`[found one · 2 of 3]`, `[walk · 10 min]`); the
/// person can interrupt Kaiku at any time. Without Live (offline / no key) the scripted voice lines play instead.
@Observable @MainActor
public final class WalkModel {
    public static let shared = WalkModel()

    public private(set) var active = false
    public private(set) var start: Date?
    public private(set) var found = 0
    public private(set) var glasses: GlassesState = .off
    public private(set) var steps: Int?
    public private(set) var finished: Outing?
    public static let goal = 3
    /// The live companion for this walk (nil when off or unavailable).
    public private(set) var companion: Conversation?
    public var talking: Bool { companion?.isLive == true }

    @ObservationIgnored private var gait = GaitAnalyzer()
    @ObservationIgnored private var daylight = DaylightCounter()
    @ObservationIgnored private var adapter: GlassesAdapter?
    @ObservationIgnored private weak var app: AppModel?
    @ObservationIgnored private var envelopeID = UUID7.make()
    @ObservationIgnored private var ticker: Task<Void, Never>?
    @ObservationIgnored private var usedGlasses = false
    @ObservationIgnored private var announcedDrop = false
    @ObservationIgnored private var lastMinuteEvent = 0
    @ObservationIgnored private var audioTokens: [NSObjectProtocol] = []
    #if os(iOS)
    @ObservationIgnored private let pedometer = CMPedometer()
    @ObservationIgnored private var phoneSteps: Int?
    #endif

    public init() {}

    public var minutes: Int { start.map { Int(Date().timeIntervalSince($0) / 60) } ?? 0 }

    // MARK: lifecycle

    public func begin(app: AppModel, adapter: GlassesAdapter?) {
        guard !active else { return }
        self.app = app
        self.adapter = adapter
        active = true
        finished = nil
        found = 0
        steps = nil
        gait = GaitAnalyzer()
        daylight = DaylightCounter()
        usedGlasses = false
        announcedDrop = false
        envelopeID = UUID7.make()
        let now = Date()
        start = now
        glasses = adapter == nil ? .off : .searching
        #if os(iOS)
        KaikuLiveActivities.startWalk(at: now, lang: app.language.rawValue, state: contentState)
        if CMPedometer.isStepCountingAvailable() {
            pedometer.startUpdates(from: now) { [weak self] data, _ in
                let n = data?.numberOfSteps.intValue
                Task { @MainActor in self?.phoneSteps = n }
            }
        }
        #endif
        lastMinuteEvent = 0
        startCompanion(app: app)
        if let adapter {
            Task { await adapter.start { [weak self] ev in Task { @MainActor in self?.handle(ev) } } }
        }
        saveDraft()
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 15_000_000_000)
                guard let self, self.active else { return }
                self.tick()
            }
        }
    }

    func clearFinished() { finished = nil }

    /// `byKaiku`: the model's `log_walk_moment` already knows (it heard it), so no context event goes back.
    public func foundOne(byKaiku: Bool = false) {
        guard active, found < Self.goal else { return }
        found += 1
        Haptics.finished()
        if talking {
            if !byKaiku { companion?.context("[found one · \(found) of \(Self.goal)]") }
        } else if let app {
            VoiceLines.shared.play(found >= Self.goal ? "walk.light_hunt.found" : "walk.light_hunt.\(found + 1)", lang: app.language)
        }
        tick()
    }

    /// Quiet walk ↔ talk with Kaiku (button on the walk screen).
    public func setTalking(_ on: Bool) {
        guard active, let app else { return }
        if on {
            if let c = companion, c.isLive { c.setMuted(false) } else { startCompanion(app: app) }
        } else {
            companion?.setMuted(true)
        }
    }

    public var companionMuted: Bool { companion?.phase == .muted }

    /// Ends the walk and posts the outing (nothing is posted for a walk under one minute or without consent).
    public func end() async {
        guard active, let start else { return }
        active = false
        ticker?.cancel()
        stopCompanion()
        await adapter?.stop()
        adapter = nil
        #if os(iOS)
        pedometer.stopUpdates()
        #endif
        daylight.close()
        let outing = makeOuting(minutes: Date().timeIntervalSince(start) / 60)
        finished = outing
        #if os(iOS)
        KaikuLiveActivities.endWalk(contentState)
        #endif
        Self.clearDraft()
        glasses = .off
        guard let app else { return }
        VoiceLines.shared.play("walk.done", lang: app.language)
        if outing.minutes >= 1, app.allowed(.walks) {
            await app.emit("obs.outing", outing, id: envelopeID, ts: start)
            app.celebrate()
            await app.loadToday()
        }
    }

    // MARK: events

    private func handle(_ ev: GlassesEvent) {
        guard active else { return }
        switch ev {
        case .state(let s):
            if s == .connected { usedGlasses = true }
            if s == .disconnected, !announcedDrop, let app {
                announcedDrop = true
                if talking { companion?.context("[glasses disconnected · the walk goes on with the phone]") }
                else { app.showToast(T("walk.glasses.lost")) }   // no keyed voice line for this one: text, never a synthesizer
            }
            glasses = s
        case .imu(let samples):
            gait.add(samples)
            steps = gait.steps
        case .brightness(let b): daylight.add(b)
        case .tap: foundOne()
        }
    }

    private func tick() {
        let m = minutes
        if talking, m >= lastMinuteEvent + 10 {
            lastMinuteEvent = m - m % 10
            companion?.context("[walk · \(lastMinuteEvent) min]")
        }
        #if os(iOS)
        KaikuLiveActivities.updateWalk(contentState)
        #endif
        saveDraft()
    }

    #if os(iOS)
    private var contentState: WalkActivityAttributes.ContentState {
        .init(minutes: minutes, found: found, steps: steps ?? phoneSteps, glasses: glasses == .connected)
    }
    #endif

    func makeOuting(minutes: Double) -> Outing {
        var o = Outing(minutes: (minutes * 10).rounded() / 10, method: usedGlasses && gait.steps > 0 ? .dat_imu : .steps)
        if usedGlasses && gait.steps > 0 {
            o.steps = gait.steps
            o.cadence_spm = gait.cadence.map { ($0 * 10).rounded() / 10 }
            o.gait_regularity = gait.regularity.map { ($0 * 100).rounded() / 100 }
            o.head_up_ratio = gait.headUpRatio.map { ($0 * 100).rounded() / 100 }
            o.daylight_min = daylight.minutes.map { ($0 * 10).rounded() / 10 }
        } else {
            #if os(iOS)
            o.steps = phoneSteps
            #endif
        }
        return o
    }

    // MARK: companion (live conversation through the glasses)

    private func startCompanion(app: AppModel) {
        stopCompanion()
        let c = Conversation(surface: .glasses, intent: .walk)
        companion = c
        c.deviceTool = { [weak self] name, args in await self?.walkTool(name, args) ?? .object(["ok": .bool(false)]) }
        c.onCrisis = { [weak self, weak app] in
            Task { await self?.end() }
            app?.crisis(trigger: "phrase")
        }
        c.onReady = { [weak c] in c?.context("[walk started · light hunt: spot \(Self.goal) green or bright things]") }
        if audioTokens.isEmpty {
            audioTokens = TalkAudio.observe { [weak self] ev in
                switch ev {
                case .interrupted: self?.companion?.pause()
                case .resumed: self?.companion?.resume()
                case .routeChanged: break
                }
            }
        }
        Task {
            let ok = await c.start(app: app)
            guard self.active, self.companion === c else { c.stop(); return }
            if !ok {
                companion = nil
                VoiceLines.shared.play("walk.light_hunt.1", lang: app.language)
            }
        }
    }

    private func stopCompanion() {
        companion?.stop(outcome: found > 0 ? .completed : nil)
        companion = nil
        audioTokens.forEach(NotificationCenter.default.removeObserver)
        audioTokens = []
    }

    /// Device tools on a walk: the model asks, the walk decides.
    private func walkTool(_ name: String, _ args: [String: JSONValue]) async -> JSONValue {
        switch name {
        case "log_walk_moment":
            guard found < Self.goal else { return .object(["ok": .bool(true), "found": .number(Double(found)), "goal": .number(Double(Self.goal))]) }
            foundOne(byKaiku: true)
            return .object(["ok": .bool(true), "found": .number(Double(found)), "goal": .number(Double(Self.goal))])
        case "express":
            return .object(["ok": .bool(true)])
        case "record_dial":
            guard let app, let item = args["item"]?.string.flatMap(DialItem.init(rawValue:)),
                  let v = args["value"]?.int ?? companion?.lastSpokenDial else { return .object(["ok": .bool(false)]) }
            await app.emit("obs.self_report", SelfReport(item: item, value: v, channel: KaikuPlatform.channel, context: "adhoc"))
            return .object(["ok": .bool(true)])
        case "start_activity":
            let kind = args["kind"]?.string ?? ""
            return .object(["ok": .bool(kind == "walk" || kind == "light_hunt")])
        case "look_at_this":
            // Camera frames need the DAT camera stream (not wired yet): say so instead of pretending to see.
            return .object(["ok": .bool(false), "error": .string("the glasses camera is not connected; you cannot see")])
        default:
            return .object(["ok": .bool(false), "error": .string("not on this device")])
        }
    }

    // MARK: draft (app killed mid-walk → partial outing on next launch)

    struct Draft: Codable {
        var id: String
        var start: Date
        var lastSeen: Date
        var outing: Outing
    }

    static var draftURL: URL { KaikuPaths.support.appendingPathComponent("walk.json") }

    private func saveDraft() {
        guard let start else { return }
        let d = Draft(id: envelopeID, start: start, lastSeen: Date(), outing: makeOuting(minutes: Date().timeIntervalSince(start) / 60))
        if let data = try? JSONEncoder().encode(d) { try? data.write(to: Self.draftURL, options: .atomic) }
    }

    static func clearDraft() { try? FileManager.default.removeItem(at: draftURL) }

    /// On launch: a draft without a running walk means the app was killed mid-walk → post what we had.
    public static func recover(app: AppModel) async {
        guard !shared.active, let data = try? Data(contentsOf: draftURL),
              let d = try? JSONDecoder().decode(Draft.self, from: data) else { return }
        clearDraft()
        #if os(iOS)
        KaikuLiveActivities.endAllWalks()
        #endif
        guard d.outing.minutes >= 1, app.allowed(.walks) else { return }
        await app.emit("obs.outing", d.outing, id: d.id, ts: d.start)
    }
}

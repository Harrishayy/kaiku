import Foundation
import Observation
#if canImport(CoreMotion)
import CoreMotion
#endif

/// The walk companion (plan 05 §3, §6): Light hunt on a walk, with Meta glasses when they're there. Glasses IMU →
/// cadence, gait regularity, head-up ratio; sparse brightness → daylight minutes; at the end one
/// `obs.outing {method: dat_imu | steps}`. A disconnect mid-walk keeps the walk going on the phone (one spoken
/// notice). A draft is saved every 15 s, so a walk the app never finished (killed) is posted on the next launch.
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

    @ObservationIgnored private var gait = GaitAnalyzer()
    @ObservationIgnored private var daylight = DaylightCounter()
    @ObservationIgnored private var adapter: GlassesAdapter?
    @ObservationIgnored private weak var app: AppModel?
    @ObservationIgnored private var envelopeID = UUID7.make()
    @ObservationIgnored private var ticker: Task<Void, Never>?
    @ObservationIgnored private var usedGlasses = false
    @ObservationIgnored private var announcedDrop = false
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
        VoiceLines.shared.play("walk.light_hunt.1", lang: app.language)
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

    public func foundOne() {
        guard active, found < Self.goal else { return }
        found += 1
        Haptics.finished()
        if let app { VoiceLines.shared.play(found >= Self.goal ? "walk.light_hunt.found" : "walk.light_hunt.\(found + 1)", lang: app.language) }
        tick()
    }

    /// Ends the walk and posts the outing (nothing is posted for a walk under one minute or without consent).
    public func end() async {
        guard active, let start else { return }
        active = false
        ticker?.cancel()
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
                VoiceLines.shared.say(T("walk.glasses.lost"), lang: app.language)
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

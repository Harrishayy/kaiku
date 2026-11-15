import Foundation
import Observation
#if canImport(CoreMotion)
import CoreMotion
#endif

/// The walk companion (plan 05 §3, §6): a walk with Kaiku's voice, with Meta glasses when they're there. Glasses
/// IMU → cadence, gait regularity, head-up ratio; at the end one `obs.outing {method: dat_imu | steps}`. A
/// disconnect mid-walk keeps the walk going on the phone (one spoken notice). A draft is saved every 15 s, so a
/// walk the app never finished (killed) is posted on the next launch.
///
/// Talking on the walk: `companion` is a live `Conversation` (intent and purpose `walk`; surface `glasses` when the
/// voice is in the ear, `iphone` when the walk runs on the phone). The person's `style` (Calm · Playful · Chatty)
/// goes with it as `walk_style`; the mind answers with that style's persona, the walk tools and a `WalkGuide`.
/// A Live session only answers input, so the walk nudges Kaiku with the guide's lines (`WalkNudger`): a look
/// around while pictures flow, a word after a quiet stretch. Kaiku answers a nudge in words only when there is
/// something to say; every nudge leaves through `send(_:to:)`, so its answer can be held until it has a real word.
/// A spotting game (`set_walk_goal` / `log_walk_moment`) is counted here (`goal`), so "two more to find" is true;
/// the fixed light hunt is one instance of it. The walk tells Kaiku what happens as short context events
/// (`[spotting game · trees · 2 of 3 found · 1 left]`, `[walk · 10 min]`); the person can interrupt Kaiku at any
/// time. Without Live (offline / no key) the scripted voice lines play instead.
@Observable @MainActor
public final class WalkModel {
    public static let shared = WalkModel()

    public private(set) var active = false
    public private(set) var start: Date?
    /// The spotting game on this walk, if one is on (Kaiku sets it; the count is kept here).
    public private(set) var goal: WalkGoal?
    public var found: Int { goal?.found ?? 0 }
    /// How Kaiku walks with the person. Stored on this device; sent as `walk_style` when a conversation starts.
    public var style: WalkStyle { didSet { if style != oldValue { style.store(defaults) } } }
    /// The style of the conversation that is open now (what the cloud answered with); nil without one.
    public var liveStyle: WalkStyle? { companion?.session?.walk?.style }
    public private(set) var glasses: GlassesState = .off
    public private(set) var steps: Int?
    public private(set) var finished: Outing?
    /// The live companion for this walk (nil when off or unavailable).
    public private(set) var companion: Conversation?
    public var talking: Bool { companion?.isLive == true }
    /// Where the conversation's sound comes in and goes out (shown on the walk screen).
    public private(set) var route = TalkAudio.Route()
    /// The glasses camera on this walk (only ever on with the person's "Let Kaiku see" choice).
    public private(set) var camera: GlassesCameraState = .off
    public private(set) var cameraNote: String?
    public private(set) var visionPaused = false
    /// nil = the glasses do not report it.
    public private(set) var worn: Bool?
    /// Why Kaiku's voice is not there (nil = it is, or it was never tried).
    public private(set) var voiceProblem: Conversation.UnavailableReason?
    public private(set) var summary: Summary?

    public struct Summary: Equatable, Sendable {
        public enum Saved: Equatable, Sendable { case saved, tooShort, walksOff, notConnected }
        public var minutes: Double
        public var steps: Int?
        /// Times the person spoke (a count, never the words).
        public var turns: Int
        public var frames: Int
        public var inTheEar: Bool
        public var saved: Saved
    }

    public var seeAllowed: Bool { app?.allowed(.see) == true }
    /// Kaiku's voice stopped by itself (session length limit or a lost connection): offer "Talk again".
    public var companionEnded: Bool {
        guard active, let c = companion else { return false }
        return !c.isLive && c.phase != .connecting
    }

    @ObservationIgnored private var gait = GaitAnalyzer()
    @ObservationIgnored private var daylight = DaylightCounter()
    @ObservationIgnored private var adapter: GlassesAdapter?
    @ObservationIgnored private weak var app: AppModel?
    @ObservationIgnored private var envelopeID = UUID7.make()
    @ObservationIgnored private var adapterTask: Task<Void, Never>?
    @ObservationIgnored private var ticker: Task<Void, Never>?
    @ObservationIgnored private var usedGlasses = false
    @ObservationIgnored private var simulated = false
    @ObservationIgnored private var scope: WalkScope?
    @ObservationIgnored private var announcedDrop = false
    @ObservationIgnored private var lastMinuteEvent = 0
    @ObservationIgnored private var audioTokens: [NSObjectProtocol] = []
    @ObservationIgnored private var lastFrameSent = Date.distantPast
    /// The newest frame, in memory only, replaced about once a second and dropped when the walk ends.
    @ObservationIgnored private var latestFrame: (frame: GlassesFrame, at: Date)?
    @ObservationIgnored private var toldSeeing = false
    @ObservationIgnored private var heardInEar = false
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var nudger = WalkNudger()
    @ObservationIgnored private var nudgeTask: Task<Void, Never>?
    /// A conversation was opened on this walk before (a later one is told the walk goes on, not to greet again).
    @ObservationIgnored private var openedBefore = false
    /// Tests: the walk's conversation on a fake microphone and a fake Live socket; the draft in a scratch file.
    @ObservationIgnored var makeConversation: @MainActor (CompanionSurface) -> Conversation = { surface in
        #if DEBUG
        if WalkTyped.on { return WalkTyped.conversation(surface) }   // simulator: no microphone, typed lines
        #endif
        return Conversation(surface: surface, intent: .walk, purpose: .walk)
    }
    @ObservationIgnored var draftFile = WalkModel.draftURL
    #if os(iOS)
    /// Created and used only once a walk starts: touching Core Motion (even `stopUpdates`) outside a walk made
    /// the Motion & Fitness question appear during setup, when the service connected and walk state was cleared.
    @ObservationIgnored private var pedometer: CMPedometer?
    @ObservationIgnored private var phoneSteps: Int?
    #endif

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        style = WalkStyle.stored(defaults)
    }

    public var minutes: Int { start.map { Int(Date().timeIntervalSince($0) / 60) } ?? 0 }

    // MARK: lifecycle

    public func begin(app: AppModel, adapter: GlassesAdapter?) {
        guard !active else { return }
        self.app = app
        scope = app.pairing.map(WalkScope.init)
        self.adapter = adapter
        simulated = adapter?.kind == "mock" || adapter?.kind == "dat-mock"
        active = true
        finished = nil
        goal = nil
        openedBefore = false
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
            let p = CMPedometer()
            pedometer = p
            p.startUpdates(from: now) { [weak self] data, _ in
                let n = data?.numberOfSteps.intValue
                Task { @MainActor in self?.phoneSteps = n }
            }
        }
        #endif
        lastMinuteEvent = 0
        camera = .off; cameraNote = nil; visionPaused = false; worn = nil; summary = nil; voiceProblem = nil
        latestFrame = nil; lastFrameSent = .distantPast; toldSeeing = false; heardInEar = false
        GlassesStatus.shared.resetFrames(); GlassesStatus.shared.clearError()
        GlassesStatus.shared.camera = .off; GlassesStatus.shared.cameraNote = nil
        GlassesLog.shared.log("walk_begin", ["adapter": adapter?.kind ?? "phone only", "see": app.allowed(.see),
                                             "paired": app.isPaired, "headset_available": TalkAudio.headsetAvailable ?? ""])
        let voice = startCompanion(app: app)
        // Order matters (Meta DAT docs, "Microphones and speakers"): the hands-free audio route must be up and
        // settled before the device session and its camera stream start, or the audio route can fail silently.
        adapterTask = Task { [weak self] in
            _ = await voice.value
            let headset = await TalkAudio.settleHeadset()
            guard let self, self.active, !Task.isCancelled else { return }
            self.noteRoute("walk start", settled: headset)
            guard let adapter else { return }
            await adapter.start { [weak self] ev in Task { @MainActor in self?.handle(ev) } }
            await self.applyVision()
        }
        saveDraft()
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 15_000_000_000)
                guard let self, self.active else { return }
                self.tick()
            }
        }
        nudgeTask?.cancel()
        nudgeTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                guard let self, self.active else { return }
                self.nudge()
            }
        }
        #if DEBUG
        WalkTyped.endLater(self)
        #endif
    }

    func clearFinished() { finished = nil }

    /// A new paired home must not inherit a previous person's active walk or completion screen.
    func clearForPairingChange() {
        active = false
        ticker?.cancel(); ticker = nil
        nudgeTask?.cancel(); nudgeTask = nil
        adapterTask?.cancel(); adapterTask = nil
        stopCompanion()
        let previousAdapter = adapter
        adapter = nil
        Task { await previousAdapter?.stop() }
        #if os(iOS)
        pedometer?.stopUpdates(); pedometer = nil; phoneSteps = nil
        KaikuLiveActivities.endAllWalks()
        #endif
        start = nil; finished = nil; goal = nil; steps = nil; glasses = .off; scope = nil
        camera = .off; cameraNote = nil; latestFrame = nil; summary = nil; worn = nil; voiceProblem = nil
        gait = GaitAnalyzer(); daylight = DaylightCounter()
    }

    /// The person marked a find themselves (walk screen, Dynamic Island, a tap on the glasses). With no game on,
    /// this starts the fixed light hunt. Kaiku is told the new count.
    public func foundOne() {
        guard active else { return }
        var g = goal ?? .lightHunt
        guard g.find() else { return }
        goal = g
        counted(byKaiku: false)
    }

    /// After a find. `byKaiku`: the model's `log_walk_moment` gets the count as its result, so no context event
    /// goes back. A finished game gets the completion moment; without Kaiku's live voice the scripted lines play.
    private func counted(byKaiku: Bool) {
        guard let g = goal else { return }
        Haptics.finished()
        if g.done { app?.celebrate() }
        if talking {
            if !byKaiku { companion?.personDid(g.contextLine) }      // the person's own tap: Kaiku's answer is theirs
        } else if let app {
            if g.done { VoiceLines.shared.play("walk.light_hunt.found", lang: app.language, origin: .pressed) }
            else if g.isLightHunt { VoiceLines.shared.play("walk.light_hunt.\(g.found + 1)", lang: app.language, origin: .pressed) }
        }
        GlassesLog.shared.log("walk_goal_count", ["found": g.found, "target": g.target, "by_kaiku": byKaiku])
        tick()
    }

    /// The walk screen's style control. The choice is stored at once; an open conversation is started again in the
    /// new style (the walk, its count and its minutes go on), because a style is part of how a conversation opens.
    public func choose(_ s: WalkStyle) {
        guard s != style else { return }
        style = s
        // Not during a quiet walk (the microphone stays closed until the person asks): `setTalking` picks the
        // new style up when they do.
        let restart = active && !companionMuted && companion.map { ($0.isLive || $0.phase == .connecting) && $0.walkStyle != s } == true
        GlassesLog.shared.log("walk_style", ["style": s.rawValue, "restart": restart])
        if restart, let app { startCompanion(app: app) }
    }

    // MARK: nudges (the guide's lines → the live conversation)

    /// Once a second while the walk runs: sends the guide's look / quiet line when `WalkNudger` says one is due.
    /// The guide is kept for the whole conversation, so the timers go on through a token renewal or a reconnect
    /// (the conversation is `connecting` for a moment: nothing is sent, and the silence starts again after it).
    func nudge(now: Date = Date()) {
        guard active, let c = companion else { return }
        if let guide = c.session?.walk { nudger.guide = guide }
        let seeing = camera == .streaming && now.timeIntervalSince(lastFrameSent) < 3
        let words = [c.lastPersonAt, c.lastKaikuAt].compactMap { $0 }.max()
        guard let n = nudger.next(at: now, .init(phase: c.phase, cameraOn: seeing, paused: app?.isPaused == true,
                                                 lastWords: words)) else { return }
        send(n, to: c)
        GlassesLog.shared.log("walk_nudge", ["kind": n.kind])   // which nudge, never its words or an answer
    }

    /// The one place a nudge leaves the walk. A declined nudge is not always silent (real sessions: a second or
    /// two of non-speech sound), so the answering turn is held until its first real word: `Conversation.nudge(_:)`
    /// sends the context turn and gates the answer. Never `context(_:)` for a nudge.
    private func send(_ nudge: WalkNudger.Nudge, to c: Conversation) {
        c.nudge(nudge.text)
    }

    /// Quiet walk ↔ talk with Kaiku (button on the walk screen).
    public func setTalking(_ on: Bool) {
        guard active, let app else { return }
        if on {
            if let c = companion, c.isLive, c.walkStyle == style { c.setMuted(false) } else { startCompanion(app: app) }
        } else {
            companion?.setMuted(true)
        }
        GlassesLog.shared.log("walk_talking", ["on": on])
        Task { await applyVision() }
    }

    // MARK: seeing (glasses camera → the live conversation only)

    /// Pause / resume seeing without changing the person's choice.
    public func setVisionPaused(_ paused: Bool) {
        visionPaused = paused
        GlassesLog.shared.log("vision_paused", ["paused": paused])
        Task { await applyVision() }
    }

    /// Brings the camera in line with: the person's choice, the pause button, and an open, unmuted conversation.
    /// Call it after any of those change (the walk screen calls it when the choice is flipped mid-walk).
    public func applyVision() async {
        guard active, let adapter else { return }
        let want = seeAllowed && !visionPaused && talking && !companionMuted
        await adapter.setCamera(want)
        if !want {
            latestFrame = nil
            setCamera(seeAllowed && visionPaused ? .paused : .off, note: nil)
        }
    }

    private func setCamera(_ state: GlassesCameraState, note: String?) {
        if state != camera { GlassesLog.shared.log("camera_state", ["state": state.rawValue, "note": note ?? ""]) }
        camera = state; cameraNote = note
        GlassesStatus.shared.camera = state; GlassesStatus.shared.cameraNote = note
        if state != .streaming { tellSeeing(false) }
    }

    /// Kaiku is told when it starts and stops receiving pictures, so it never talks as if it could see when it can't.
    private func tellSeeing(_ on: Bool) {
        guard toldSeeing != on else { return }
        toldSeeing = on
        companion?.context(on
            ? "[glasses camera on · you now get about one still picture a second of what the person is looking at]"
            : "[glasses camera off · you cannot see now]")
    }

    private func take(_ f: GlassesFrame) {
        guard active, seeAllowed, !visionPaused else { return }
        let now = Date()
        guard now.timeIntervalSince(lastFrameSent) >= GlassesVision.minInterval * 0.9 else { return }
        latestFrame = (f, now)
        guard companion?.sendFrame(f.jpeg) == true else { return }
        lastFrameSent = now
        GlassesStatus.shared.frameSent(at: now)
        if camera != .streaming { setCamera(.streaming, note: nil) }
        tellSeeing(true)
        if GlassesStatus.shared.framesSent == 1 || GlassesStatus.shared.framesSent % 30 == 0 {
            GlassesLog.shared.log("frames_sent", ["n": GlassesStatus.shared.framesSent, "bytes": f.jpeg.count,
                                                  "w": f.width, "h": f.height, "brightness": f.luminance])
        }
    }

    private func noteRoute(_ why: String, settled: Bool? = nil) {
        let was = route
        route = TalkAudio.route
        GlassesStatus.shared.route = route
        if route.inTheEar { heardInEar = true }
        var f: [String: Any] = ["why": why, "in": route.input, "in_type": route.inputType,
                                "out": route.output, "out_type": route.outputType]
        if let settled { f["headset_settled"] = settled }
        GlassesLog.shared.log("audio_route", f)
        guard was.active, was.headsetMic != route.headsetMic else { return }
        if route.headsetMic {
            companion?.context("[glasses audio back]")
        } else {
            companion?.context("[glasses audio lost · the conversation continues on the phone]")
            app?.showToast(T("walk.route.lost"))
        }
    }

    public var companionMuted: Bool { companion?.phase == .muted }

    /// Ends the walk and posts the outing (nothing is posted for a walk under one minute or without consent).
    public func end() async {
        guard active, let start else { return }
        active = false
        ticker?.cancel()
        nudgeTask?.cancel(); nudgeTask = nil
        adapterTask?.cancel(); adapterTask = nil
        let turns = companion?.lines.filter(\.me).count ?? 0
        let frames = GlassesStatus.shared.framesSent
        stopCompanion()
        await adapter?.stop()
        adapter = nil
        latestFrame = nil
        setCamera(.off, note: nil)
        #if os(iOS)
        pedometer?.stopUpdates(); pedometer = nil
        #endif
        daylight.close()
        let outing = makeOuting(minutes: Date().timeIntervalSince(start) / 60)
        finished = outing
        #if os(iOS)
        KaikuLiveActivities.endWalk(contentState)
        #endif
        clearDraft()
        glasses = .off
        guard let app else { return }
        let saved: Summary.Saved = outing.minutes < 1 ? .tooShort : !app.allowed(.walks) ? .walksOff
            : scope?.matches(app.pairing) == true ? .saved : .notConnected
        summary = Summary(minutes: outing.minutes, steps: outing.steps, turns: turns, frames: frames,
                          inTheEar: heardInEar, saved: saved)
        GlassesLog.shared.log("walk_end", ["minutes": outing.minutes, "steps": outing.steps ?? -1, "turns": turns,
                                           "frames": frames, "in_ear": heardInEar, "method": outing.method.rawValue,
                                           "saved": String(describing: saved)])
        VoiceLines.shared.play("walk.done", lang: app.language, origin: .pressed)
        if await Self.emitOuting(outing, id: envelopeID, start: start, simulated: simulated, scope: scope, app: app) {
            // The path's walk stop is ticked at once and stays ticked today (the garden only shows the outing after
            // the next full refresh).
            app.playedDays["walk"] = AppModel.dayKey(Date())
            app.celebrate()
            await app.loadToday()
        }
    }

    // MARK: events

    private func handle(_ ev: GlassesEvent) {
        guard active else { return }
        switch ev {
        case .frame(let f): take(f)
        case .camera(let state, let note): setCamera(state, note: note)
        case .worn(let on):
            guard worn != on else { return }
            let first = worn == nil
            worn = on
            GlassesLog.shared.log("glasses_worn", ["on": on])
            if !first || !on {
                companion?.context(on ? "[glasses back on]" : "[glasses taken off · wait quietly until they are back on]")
            }
        case .problem(let text): GlassesStatus.shared.error(text, where: "glasses")
        case .state(let s):
            if s != glasses { GlassesLog.shared.log("glasses_state", ["state": s.rawValue]) }
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
        // The toolkit delivers pictures only while the app is on screen: say so instead of showing "can see".
        if camera == .streaming, Date().timeIntervalSince(lastFrameSent) > 8 {
            setCamera(.paused, note: T("walk.see.background"))
        }
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
        .init(minutes: minutes, found: found, steps: steps ?? phoneSteps, glasses: glasses == .connected,
              thing: goal?.title, target: goal?.target)
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

    @discardableResult
    private func startCompanion(app: AppModel) -> Task<Bool, Never> {
        stopCompanion()
        voiceProblem = nil
        nudger = WalkNudger()
        toldSeeing = false   // a new conversation has not been told whether pictures are arriving
        // In the ear (glasses, or any hands-free headset) it is the glasses surface; a walk that runs on the
        // phone's own speaker says so, and the mind gives the phone the same walk tools.
        let inEar = adapter != nil || TalkAudio.headsetAvailable != nil
        let c = makeConversation(inEar ? .glasses : .iphone)
        c.walkStyle = style
        companion = c
        c.deviceTool = { [weak self] name, args in await self?.walkTool(name, args) ?? .object(["ok": .bool(false)]) }
        c.onCrisis = { [weak self, weak app] in
            Task { await self?.end() }
            app?.crisis(trigger: "phrase")
        }
        c.onReady = { [weak self, weak c] in
            guard let self, let c else { return }
            c.context(self.openingLine())
            #if DEBUG
            WalkTyped.say(into: c)
            #endif
        }
        c.onReconnected = { [weak self] in self?.toldSeeing = false }
        if audioTokens.isEmpty {
            audioTokens = TalkAudio.observe { [weak self] ev in
                switch ev {
                case .interrupted: self?.companion?.pause()
                case .resumed(let shouldResume): if shouldResume { self?.companion?.resume() }
                case .routeChanged: self?.noteRoute("route change")
                }
            }
        }
        return Task {
            let ok = await c.start(app: app)
            guard self.active, self.companion === c else { c.stop(); return false }
            if !ok {
                voiceProblem = c.unavailableReason ?? .connection
                GlassesStatus.shared.error("Kaiku's voice could not start: \(String(describing: voiceProblem!))", where: "walk voice")
                companion = nil
            } else {
                noteRoute("voice started")
                await applyVision()
            }
            return ok
        }
    }

    private func stopCompanion() {
        companion?.stop(outcome: found > 0 ? .completed : nil)
        companion = nil
        audioTokens.forEach(NotificationCenter.default.removeObserver)
        audioTokens = []
    }

    /// What a conversation is told when it opens. The first one greets; a later one on the same walk (after the
    /// time limit, a lost connection or a new style) carries on, and is told the game that is still on.
    func openingLine() -> String {
        defer { openedBefore = true }
        guard openedBefore else { return "[walk started · the person chose to walk with you: greet them in a few warm words]" }
        var parts = ["walk goes on", "\(minutes) min", "your voice is back after a short break: no new greeting, carry on"]
        if let g = goal, !g.done { parts.append("spotting game still on: \(g.thing), \(g.found) of \(g.target) found") }
        return "[" + parts.joined(separator: " · ") + "]"
    }

    /// The person's line the latest find was counted for, and what the model was told.
    private var lastFind: (said: UUID, result: JSONValue)?

    /// Device tools on a walk: the model asks, the walk decides.
    func walkTool(_ name: String, _ args: [String: JSONValue]) async -> JSONValue {
        switch name {
        case "set_walk_goal":
            // One game at a time: a new goal replaces the old one. The result is the count Kaiku may speak from.
            guard let thing = args["thing"]?.string,
                  let target = args["target"]?.int ?? args["target"]?.string.flatMap(Int.init),
                  let g = WalkGoal(thing: thing, target: target) else {
                return .object(["ok": .bool(false), "error": .string("say what to find (thing) and how many (target, 1 to 5)")])
            }
            goal = g
            lastFind = nil
            GlassesLog.shared.log("walk_goal", ["target": g.target])   // the number only, never the thing
            tick()
            return g.goalResult
        case "log_walk_moment":
            // One find. Without a game there is nothing to count; a finished game does not count past its target.
            guard var g = goal else { return WalkGoal.momentWithoutGoal }
            // At most one counted find for one thing the person said: the model sometimes logs the same find twice
            // (seen on the real model), and the count must stay what Kaiku says. The second call gets the first's answer.
            let said = companion?.lines.last(where: \.me)?.id
            if let said, let last = lastFind, last.said == said { return last.result }
            if g.find() { goal = g; counted(byKaiku: true) }
            if let said { lastFind = (said, g.momentResult) }
            return g.momentResult
        case "express":
            return .object(["ok": .bool(true)])
        case "record_dial":
            guard let app, let item = args["item"]?.string.flatMap(DialItem.init(rawValue:)),
                  let v = args["value"]?.int ?? companion?.lastSpokenDial else { return .object(["ok": .bool(false)]) }
            return .object(["ok": .bool(await app.recordDial(item: item, value: v))])
        case "start_activity":
            let kind = args["kind"]?.string ?? ""
            // Already walking. The light hunt is the fixed spotting game: it starts unless a game is still on.
            if kind == "light_hunt", goal?.done != false {
                goal = .lightHunt
                tick()
                return goal?.momentResult ?? .object(["ok": .bool(true)])
            }
            return .object(["ok": .bool(kind == "walk" || kind == "light_hunt")])
        case "look_at_this":
            // Only true when a frame from the last three seconds really went to Live: never pretend to see.
            if camera == .streaming, let l = latestFrame, Date().timeIntervalSince(l.at) < 3, companion?.sendFrame(l.frame.jpeg) == true {
                return .object(["ok": .bool(true), "seeing": .bool(true),
                                "note": .string("a fresh picture of what the person is looking at was just sent to you")])
            }
            return .object(["ok": .bool(false), "seeing": .bool(false), "error": .string(seeAllowed
                ? "the glasses camera is not sending pictures right now; you cannot see"
                : "seeing is turned off; you cannot see. They can turn on Let Kaiku see in the Kaiku app if they want")])
        default:
            return .object(["ok": .bool(false), "error": .string("not on this device")])
        }
    }

    // MARK: draft (app killed mid-walk → partial outing on next launch)

    /// Persist only destination identity, never the pairing token.
    struct WalkScope: Codable, Equatable {
        var server: URL
        var home: String
        init(_ pairing: Pairing) { server = pairing.baseURL; home = pairing.homeID }
        func matches(_ pairing: Pairing?) -> Bool { pairing.map { WalkScope($0) == self } ?? false }
    }

    struct Draft: Codable {
        var id: String
        var start: Date
        var lastSeen: Date
        var outing: Outing
        var simulated: Bool? = nil
        var scope: WalkScope? = nil
    }

    static var draftURL: URL { KaikuPaths.support.appendingPathComponent("walk.json") }

    private func saveDraft() {
        guard let start else { return }
        let d = Draft(id: envelopeID, start: start, lastSeen: Date(), outing: makeOuting(minutes: Date().timeIntervalSince(start) / 60), simulated: simulated, scope: scope)
        if let data = try? JSONEncoder().encode(d) { try? data.write(to: draftFile, options: .atomic) }
    }

    private func clearDraft() { try? FileManager.default.removeItem(at: draftFile) }

    /// On launch: a draft without a running walk means the app was killed mid-walk → post what we had.
    public static func recover(app: AppModel) async { await recover(app: app, from: draftURL) }

    static func recover(app: AppModel, from url: URL) async {
        guard !shared.active, let data = try? Data(contentsOf: url),
              let d = try? JSONDecoder().decode(Draft.self, from: data) else { return }
        // Legacy unscoped drafts stay quarantined. A changed pairing cannot claim another home's walk.
        guard d.scope?.matches(app.pairing) == true else { return }
        #if os(iOS)
        KaikuLiveActivities.endAllWalks()
        #endif
        guard await emitOuting(d.outing, id: d.id, start: d.start, simulated: d.simulated ?? false, scope: d.scope, app: app) else { return }
        try? FileManager.default.removeItem(at: url)
    }

    @discardableResult static func emitOuting(_ outing: Outing, id: String, start: Date,
                                             simulated: Bool, scope: WalkScope?, app: AppModel) async -> Bool {
        guard outing.minutes >= 1, app.allowed(.walks), scope?.matches(app.pairing) == true else { return false }
        await app.emit("obs.outing", outing, id: id, ts: start, sim: simulated)
        return true
    }
}

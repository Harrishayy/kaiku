import Foundation
import Observation

/// The daily check-in as a small passing chat (pure state; `CheckInChat` feeds it). An ordinary day closes itself
/// after a few exchanges: the model wraps up and the stop is ticked. When the plan says `stay` (a very good or a
/// very hard day) the chat simply goes on: nothing here counts turns, sets a timer or pushes towards an end.
/// The dials are always there as a quiet alternative and count on their own.
public struct CheckInState: Equatable, Sendable {
    public enum End: Equatable, Sendable {
        case chat                 // "Good to see you": the chat wrapped up and the person took part
        case quiet                // it ended before the person said anything: nothing is ticked
        case dials(String)        // the dials were turned: Kaiku's one warm line (copy / voice-line key)
        case offer                // the person opened the activity card and is on their way to it
    }

    public enum Event: Equatable, Sendable {
        case personSpoke
        case plan(FeelPlan)
        /// The model wrapped up, the session reached its limit, or the person said "that's enough" / left.
        case closed
        case dials(mood: Int, energy: Int, sleep: Int)
        case allDialsSpoken
        /// The activity card was opened: the person goes to that screen.
        case cardOpened
        case keepTalking
        /// The cloud asked for this chat to open with time (`chat_shape.depth: stay`, e.g. after a heavy few days).
        case opened(FeelPlan.Depth)
    }

    public enum Effect: Equatable, Sendable {
        case tick                 // today's first stop is done + the completion moment
        case sparkle              // good news: the sparkle moment, once
    }

    public private(set) var personTurns = 0
    public private(set) var depth: FeelPlan.Depth = .brief
    public private(set) var end: End?
    public private(set) var ticked = false
    public private(set) var sparkled = false
    public private(set) var dialsDone = false

    public init() {}

    /// A very good or very hard day: the chat goes on for as long as the person likes.
    public var staying: Bool { depth == .stay && end == nil }

    public mutating func apply(_ event: Event) -> [Effect] {
        var effects: [Effect] = []
        func tick(_ s: inout CheckInState) { if !s.ticked { s.ticked = true; effects.append(.tick) } }
        switch event {
        case .personSpoke:
            personTurns += 1
        case .plan(let p):
            depth = p.depth                   // the latest plan decides; the model follows the same one
            if p.isGoodNews && !sparkled { sparkled = true; effects.append(.sparkle) }
        case .closed:
            guard end == nil else { break }
            if personTurns > 0 || ticked { end = .chat; tick(&self) } else { end = .quiet }
        case .dials(let mood, let energy, let sleep):
            dialsDone = true
            end = .dials(Self.dialLine(mood: mood, energy: energy, sleep: sleep))
            tick(&self)
        case .allDialsSpoken:
            dialsDone = true
            tick(&self)
        case .cardOpened:
            end = .offer
            tick(&self)
        case .keepTalking:
            end = nil
        case .opened(let d):
            if d == .stay { depth = .stay }
        }
        return effects
    }

    /// Kaiku's one warm line for what was dialled (never a number, never a judgement).
    public static func dialLine(mood: Int, energy: Int, sleep: Int) -> String {
        if mood <= 2 { return "checkin.dials.low" }
        if mood >= 4 && energy >= 3 { return "checkin.dials.bright" }
        if sleep <= 2 || energy <= 2 { return "checkin.dials.tired" }
        return "checkin.dials.mid"
    }
}

/// The check-in chat: Kaiku greets (its Live voice when there is one, text always), the person answers by voice,
/// by typing, or just turns the dials. Runs the shared conversation engine with `purpose: check_in`; the cloud's
/// `feel` plan decides how long it goes on and what may be offered. Crisis, pause, transcripts consent and the
/// "never a synthesizer voice" rule are the engine's (`Conversation`, `TalkModel`), unchanged.
@Observable @MainActor
final class CheckInChat {
    static let opening = "[the person stopped by for today's check-in]"
    static let reopening = "[the person wants to keep talking after today's check-in]"

    let talk: TalkModel
    /// The check-in's camera, for the choice "Camera during activities": beside the chat from its start to its
    /// end, only while this screen is in front. Face signs as numbers; nothing of it goes to the conversation.
    let camera: TaskCamera
    private(set) var state = CheckInState()
    var values: [DialItem: Int] = [.mood: 3, .energy: 3, .sleep: 3]
    /// The dial being turned (Kaiku's ear follows it); nil while chatting.
    var activeDial: DialItem?
    /// Dial answers the person said out loud and the model recorded.
    private(set) var spokenDials: Set<DialItem> = []

    @ObservationIgnored private weak var app: AppModel?
    @ObservationIgnored private var watched: ObjectIdentifier?
    @ObservationIgnored private var seenTurns = 0
    @ObservationIgnored private var seenPlans = 0
    @ObservationIgnored private var seenClose = false
    @ObservationIgnored private var seenShape = false
    @ObservationIgnored private var observing = false
    @ObservationIgnored private var kaikuLinesAtDials = 0
    /// The screen was left (another tab, back, the way on): this check-in is over and its screen goes with it.
    private(set) var left = false
    /// She turned the camera off for this check-in: "Keep talking" does not turn it back on.
    @ObservationIgnored private var cameraOffByHer = false

    init(talk: TalkModel? = nil, camera: TaskCamera? = nil) {
        self.talk = talk ?? TalkModel(opening: Self.opening) {
            TalkModel.liveConversation(intent: .checkin, purpose: .check_in, typedWithoutMic: true)
        }
        self.camera = camera ?? TaskCamera()
        self.camera.blocked = { [weak self] in TaskCamera.busyElsewhere(own: self?.talk) }
        self.talk.silentGreeting = "checkin.hello"
        self.talk.allowsQuestionnaire = false
        self.talk.scriptedKeys = ["checkin.typed.offline", "talk.scripted.2"]
    }

    // MARK: what the screen shows

    var lines: [TalkModel.Line] { talk.lines }
    var hasLive: Bool { talk.hasLive }
    /// Live is open but the microphone is not allowed: Kaiku answers typed messages in its voice.
    var typedOnly: Bool { talk.hasLive && !talk.conversation.listens }
    var micOn: Bool { talk.micOn }
    /// The one activity card of this chat (the same card and rules as in Talk).
    var card: ActivityCard? { talk.activityCard }
    var connecting: Bool { talk.conversation.phase == .connecting }
    var phase: Conversation.Phase { talk.conversation.phase }
    var unavailable: Conversation.UnavailableReason? { talk.conversation.unavailableReason }

    /// Kaiku's greeting as text (always shown; Live says its own hello over it when there is a voice).
    var greeting: String {
        guard let app else { return T("checkin.hello") }
        return VoiceLines.shared.text("checkin.hello", lang: app.language) ?? T("checkin.hello")
    }

    /// Kaiku's warm line after the dials: its own live words once it has answered, the scripted line until then.
    var dialReply: String? {
        guard case .dials(let key)? = state.end else { return nil }
        let kaiku = talk.conversation.lines.filter { !$0.me }
        if kaiku.count > kaikuLinesAtDials, let last = kaiku.last { return last.text }
        return T(key)
    }

    // MARK: lifecycle

    /// The screen is showing: the chat opens. An ended check-in never opens a conversation again, whatever brings
    /// its screen back (the tab reappearing, a tab switch, the app returning from the background): the end screen
    /// has no call bar, so a conversation behind it would be one nobody can see. Only the person's own "keep
    /// talking" starts a new one (`keepTalking`).
    func start(app: AppModel) async {
        self.app = app
        guard state.end == nil, !left else { return }
        talk.onDial = { [weak self] item, value in self?.spoken(item, value) }
        talk.onActivity = { [weak self] _ in self?.run(.closed) }
        if !observing { observing = true; observe() }
        await talk.start(app: app)
        sync()
        await beginCamera()
    }

    // MARK: the camera beside the check-in

    /// Opens the camera for this check-in if her choice is on, the check-in is still going and she has not turned
    /// it off here. The system's own permission question comes with the first task that has the choice on.
    func beginCamera() async {
        guard let app, state.end == nil, !left, !cameraOffByHer, camera.state == .off else { return }
        await camera.begin(allowed: app.cameraOn)
    }

    /// Her choice changed while the check-in is open (the switch, "pause everything", the one-time question).
    func cameraChoiceChanged(on: Bool) async {
        if on { await beginCamera() } else { camera.cancel() }
    }

    /// The check-in is over: the camera closes at once. What it measured is sent only for a check-in that counted
    /// (she took part); one she only opened and left sends nothing.
    private func endCamera() {
        if camera.state == .stopped { cameraOffByHer = true }
        guard camera.state != .off else { return }
        let seen = camera.finish()
        guard state.ticked, let seen, let app else { return }
        Task { await app.recordFaceSigns(seen, task: FaceSigns.checkIn) }
    }

    /// Leaving the screen: a chat the person took part in counts, even when it had not wrapped up yet.
    func leave() {
        sync()
        if state.end == nil { run(.closed) }
        camera.cancel()        // nothing stays open behind a screen that was left
        observing = false
        left = true
        talk.retire()
    }

    // MARK: the person's moves

    func send(_ text: String) {
        talk.send(text)
        sync()
    }

    func toggleMic() {
        guard state.end == nil else { return }        // an end screen never has an open microphone
        talk.toggleMic()
    }

    /// "That's it": the dials count on their own. Kaiku answers what was dialled in one warm line: in its Live
    /// voice when a conversation is open, otherwise the scripted line (Gemini voice line when the service has it).
    func submitDials() async {
        guard let app else { return }
        let v = values
        kaikuLinesAtDials = talk.conversation.lines.filter { !$0.me }.count
        activeDial = nil
        talk.planCardAtOnce = true            // nothing more is being said: an offer may show on the end screen
        run(.dials(mood: v[.mood] ?? 3, energy: v[.energy] ?? 3, sleep: v[.sleep] ?? 3))
        if talk.hasLive {
            // An end screen has no call bar, so no conversation stays open behind it: the microphone shuts now,
            // Kaiku says its one line, and the conversation closes itself.
            talk.conversation.closeAfterAnswer(to: Self.dialContext(v))
        } else if case .dials(let key)? = state.end {
            VoiceLines.shared.play(key, lang: app.language, fallback: T(key))
        }
        await app.recordWeather(v, celebrates: false)
    }

    /// The card's button: the person asked. It goes to the activity, and the check-in counts.
    func openCard() {
        guard talk.activityCard != nil else { return }
        talk.openCard()
        run(.cardOpened)
    }

    func putCardAside() { talk.putCardAside() }

    /// "That's enough for now": the person ends the chat; it closes at once, as warmly as a model close.
    func enough() {
        sync()
        talk.end()
        run(.closed)
    }

    /// The call was ended away from this screen (End on the Lock Screen or in the Dynamic Island, or a long quiet
    /// time in a pocket): the same warm end as "That's enough for now".
    private var endedElsewhere: Bool {
        let c = talk.conversation
        return c.wasLive && c.phase == .idle && !c.endedInCrisis      // a crisis is not a check-in that went well
    }

    /// From an end state: carry on talking (a new conversation, no second hello).
    func keepTalking() async {
        guard let app, !left else { return }
        talk.stop()
        talk.opening = Self.reopening
        run(.keepTalking)
        await talk.start(app: app)
        sync()
        await beginCamera()
    }

    // MARK: private

    /// What Live is told when the dials were used: the dial's own words, never the numbers.
    static func dialContext(_ v: [DialItem: Int]) -> String {
        func word(_ item: DialItem) -> String { L10n.shared.string("wx.\(item.rawValue).\(v[item] ?? 3)", lang: .en) }
        return "[the person turned the dials instead of talking: weather inside \"\(word(.mood))\", energy \"\(word(.energy))\", "
            + "last night's sleep \"\(word(.sleep))\". Answer in one warm line; no numbers.]"
    }

    private func spoken(_ item: DialItem, _ value: Int) {
        values[item] = value
        spokenDials.insert(item)
        if spokenDials.count == DialItem.allCases.count { run(.allDialsSpoken) }
    }

    /// Re-arms itself on every change of the conversation it follows (lines, plan, close, a new conversation).
    private func observe() {
        guard observing else { return }
        withObservationTracking {
            let c = talk.conversation
            _ = (c.lines.count, c.planCount, c.closedByModel, c.endedByLimit, c.session?.session_id, c.phase)
        } onChange: { [weak self] in
            Task { @MainActor in
                guard let self, self.observing else { return }
                self.sync()
                self.observe()
            }
        }
    }

    /// Turns what happened in the conversation into check-in events (idempotent; also called by tests).
    func sync() {
        let c = talk.conversation
        if watched != ObjectIdentifier(c) {
            watched = ObjectIdentifier(c)
            seenTurns = 0; seenPlans = 0; seenClose = false; seenShape = false
        }
        if !seenShape, let s = c.session {
            seenShape = true
            if let d = s.openingDepth { run(.opened(d)) }
        }
        let turns = c.lines.filter(\.me).count
        while seenTurns < turns { seenTurns += 1; run(.personSpoke) }
        if c.planCount > seenPlans, let p = c.plan { seenPlans = c.planCount; run(.plan(p)) }
        if (c.closedByModel || c.endedByLimit || endedElsewhere) && !seenClose { seenClose = true; run(.closed) }
    }

    private func run(_ event: CheckInState.Event) {
        for effect in state.apply(event) {
            switch effect {
            case .tick: app?.checkInDone()
            case .sparkle: app?.celebrate()
            }
        }
        if state.end != nil { endCamera() }
    }
}

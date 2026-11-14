import Foundation
import Observation

/// One soft offer under Kaiku's line (the cloud's `feel` plan). `may_offer` is what it says, `offer_activity` is
/// what it starts. The person can take it or carry on; taking it counts as the person asking. An activity this
/// device can start opens it; anything else starts nothing: Kaiku is told they said yes and stays with them
/// (sitting quietly together is the offer that is always there).
public struct CheckInOffer: Equatable, Sendable {
    /// walk | breathe: started here. quiet: sitting together in the chat. other: something this device cannot start.
    public let kind: String
    /// The cloud's own words for the offer ("a few slow breaths together").
    public let text: String
    public let route: KaikuRoute?

    public var icon: String {
        switch kind {
        case "walk": return "figure.walk"
        case "breathe": return "wind"
        case "quiet": return "moon.stars.fill"
        default: return "sparkles"
        }
    }

    /// The chip's words: the plan's own phrase as a small question; in another language, the app's wording.
    public func label(_ language: KaikuLanguage = L10n.shared.language) -> String {
        guard language == .en, !text.isEmpty else { return L10n.shared.string("offer.\(kind)", lang: language) }
        return text.prefix(1).uppercased() + text.dropFirst() + (text.hasSuffix("?") ? "" : "?")
    }

    /// What Live is told when the person takes an offer that starts nothing on this device.
    public var acceptance: String {
        kind == "quiet"
            ? "[the person chose to sit quietly together. Say one short warm line, then stay with them without talking until they speak.]"
            : "[the person said yes to your offer: \(text). It cannot be started on this device; say plainly where it happens, or stay with them.]"
    }

    /// Nil when the plan offers nothing (`may_offer` is null).
    public init?(_ plan: FeelPlan, phone: Bool = KaikuPlatform.isPhone) {
        guard let offered = plan.mayOffer?.trimmingCharacters(in: .whitespacesAndNewlines), !offered.isEmpty else { return nil }
        text = offered
        switch plan.offerActivity {
        case "walk"? where phone, "light_hunt"? where phone: kind = "walk"; route = .walk
        case "breathe"?: kind = "breathe"; route = .breathe
        case nil where offered.lowercased().contains("quiet"): kind = "quiet"; route = nil
        default: kind = "other"; route = nil      // e.g. the drum lives on the robot
        }
    }
}

/// The daily check-in as a small passing chat (pure state; `CheckInChat` feeds it). An ordinary day closes itself
/// after a few exchanges: the model wraps up and the stop is ticked. When the plan says `stay` (a very good or a
/// very hard day) the chat simply goes on: nothing here counts turns, sets a timer or pushes towards an end.
/// The dials are always there as a quiet alternative and count on their own.
public struct CheckInState: Equatable, Sendable {
    public enum End: Equatable, Sendable {
        case chat                 // "Good to see you": the chat wrapped up and the person took part
        case quiet                // it ended before the person said anything: nothing is ticked
        case dials(String)        // the dials were turned: Kaiku's one warm line (copy / voice-line key)
        case offer                // the person took the offer and is on their way to it
    }

    public enum Event: Equatable, Sendable {
        case personSpoke
        case plan(FeelPlan)
        /// The model wrapped up, the session reached its limit, or the person said "that's enough" / left.
        case closed
        case dials(mood: Int, energy: Int, sleep: Int)
        case allDialsSpoken
        case offerTaken
        case keepTalking
        /// The cloud asked for this chat to open with time (`chat_shape.depth: stay`, e.g. after a heavy few days).
        case opened(FeelPlan.Depth)
    }

    public enum Effect: Equatable, Sendable {
        case tick                 // today's first stop is done + the completion moment
        case sparkle              // good news: the sparkle moment, once
        case start(KaikuRoute)
        case accepted(CheckInOffer)   // an offer that starts nothing here was taken: Kaiku is told, and stays
    }

    public private(set) var personTurns = 0
    public private(set) var depth: FeelPlan.Depth = .brief
    /// What the latest plan may offer, and how many things the person had said when it arrived.
    public private(set) var planned: CheckInOffer?
    public private(set) var plannedAtTurn = 0
    public private(set) var end: End?
    public private(set) var ticked = false
    public private(set) var sparkled = false
    public private(set) var dialsDone = false
    /// The person chose to sit quietly together: Kaiku is simply there until they say something.
    public private(set) var sittingQuietly = false

    public init() {}

    /// The chip under Kaiku's line. It waits until the person has said one more thing after the feeling (Kaiku
    /// meets the feeling first and never offers in its first reply to it), then stays there, easy to ignore,
    /// until it is taken or the plan changes. After the dials it shows at once: nothing more is being said.
    public var offer: CheckInOffer? {
        guard let planned else { return nil }
        if case .dials? = end { return planned }
        return personTurns > plannedAtTurn ? planned : nil
    }

    /// A very good or very hard day: the chat goes on for as long as the person likes.
    public var staying: Bool { depth == .stay && end == nil }

    public mutating func apply(_ event: Event, phone: Bool = KaikuPlatform.isPhone) -> [Effect] {
        var effects: [Effect] = []
        func tick(_ s: inout CheckInState) { if !s.ticked { s.ticked = true; effects.append(.tick) } }
        switch event {
        case .personSpoke:
            personTurns += 1
            sittingQuietly = false
        case .plan(let p):
            depth = p.depth                   // the latest plan decides; the model follows the same one
            planned = CheckInOffer(p, phone: phone)
            plannedAtTurn = personTurns
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
        case .offerTaken:
            guard let o = offer else { break }
            planned = nil
            guard let route = o.route else {
                if o.kind == "quiet" { sittingQuietly = true }
                depth = .stay                 // they asked Kaiku to stay
                if end != nil { end = nil }
                effects.append(.accepted(o))
                break
            }
            end = .offer
            tick(&self)
            effects.append(.start(route))
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

    init(talk: TalkModel? = nil) {
        self.talk = talk ?? TalkModel(opening: Self.opening) {
            Conversation(surface: KaikuPlatform.surface, intent: .checkin, purpose: .check_in, typedWithoutMic: true)
        }
        self.talk.silentGreeting = "checkin.hello"
        self.talk.allowsQuestionnaire = false
        self.talk.scriptedKeys = ["checkin.typed.offline", "talk.scripted.2"]
    }

    // MARK: what the screen shows

    var lines: [TalkModel.Line] { talk.lines }
    var hasLive: Bool { talk.hasLive }
    /// Live is open but the microphone is not allowed: Kaiku answers typed messages in its voice.
    var typedOnly: Bool { talk.hasLive && !talk.conversation.listens }
    var micOn: Bool { talk.hasLive && talk.conversation.listens && ![.muted, .paused].contains(talk.conversation.phase) }
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

    func start(app: AppModel) async {
        self.app = app
        talk.onDial = { [weak self] item, value in self?.spoken(item, value) }
        talk.onActivity = { [weak self] _ in self?.run(.closed) }
        if !observing { observing = true; observe() }
        await talk.start(app: app)
        sync()
    }

    /// Leaving the screen: a chat the person took part in counts, even when it had not wrapped up yet.
    func leave() {
        sync()
        if state.end == nil { run(.closed) }
        observing = false
        talk.stop()
    }

    // MARK: the person's moves

    func send(_ text: String) {
        talk.send(text)
        sync()
    }

    func toggleMic() { talk.toggleListening() }

    /// "That's it": the dials count on their own. Kaiku answers what was dialled in one warm line: in its Live
    /// voice when a conversation is open, otherwise the scripted line (Gemini voice line when the service has it).
    func submitDials() async {
        guard let app else { return }
        let v = values
        kaikuLinesAtDials = talk.conversation.lines.filter { !$0.me }.count
        activeDial = nil
        run(.dials(mood: v[.mood] ?? 3, energy: v[.energy] ?? 3, sleep: v[.sleep] ?? 3))
        if talk.hasLive {
            talk.conversation.setMuted(true)      // an end screen never has an open microphone
            talk.conversation.context(Self.dialContext(v))
        } else if case .dials(let key)? = state.end {
            VoiceLines.shared.play(key, lang: app.language, fallback: T(key))
        }
        await app.recordWeather(v, celebrates: false)
    }

    func takeOffer() { run(.offerTaken) }

    /// "That's enough for now": the person ends the chat; it closes at once, as warmly as a model close.
    func enough() {
        sync()
        talk.conversation.stop(outcome: .completed)
        run(.closed)
    }

    /// From an end state: carry on talking (a new conversation, no second hello).
    func keepTalking() async {
        guard let app else { return }
        talk.stop()
        talk.opening = Self.reopening
        run(.keepTalking)
        await talk.start(app: app)
        sync()
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
            _ = (c.lines.count, c.planCount, c.closedByModel, c.endedByLimit, c.session?.session_id)
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
        if (c.closedByModel || c.endedByLimit) && !seenClose { seenClose = true; run(.closed) }
    }

    private func run(_ event: CheckInState.Event) {
        for effect in state.apply(event) {
            switch effect {
            case .tick: app?.checkInDone()
            case .sparkle: app?.celebrate()
            case .start(let route):
                app?.deepLink = route
                app?.selectedTab = route.tab
            case .accepted(let offer):
                talk.conversation.context(offer.acceptance)
            }
        }
    }
}

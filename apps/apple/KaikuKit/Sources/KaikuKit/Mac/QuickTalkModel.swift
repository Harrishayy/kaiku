import Foundation
import Observation

extension TalkModel {
    /// The model behind the Talk screen. On the Mac it is the one quick talk uses, so the side panel and the main
    /// window show the same conversation and "Continue in Kaiku" carries it on. Elsewhere: a model of its own.
    static func forTalkScreen() -> TalkModel {
        #if os(macOS)
        return QuickTalkModel.shared.talk
        #else
        return TalkModel()
        #endif
    }
}

/// What the quick-talk panel shows, as plain values (`make` is the rule; tested). The panel never pretends to
/// listen: every reason it cannot is its own state with one calm line and the one thing that helps. The words are
/// the call's own (`CallStatus`, `call.*` copy): the same on the Talk screen and here.
public struct QuickTalkDisplay: Equatable, Sendable {
    public enum State: String, Sendable, CaseIterable {
        /// First-run setup is not finished (what Kaiku is and is not, the choices): that comes first.
        case setup
        case notConnected, paused, micDenied
        /// The service, the voice or the audio did not start.
        case unavailable
        case connecting
        /// The call is open: waiting for the person, hearing them, thinking, speaking.
        case listening, hearing, thinking, speaking
        /// The call is open and the person muted their microphone.
        case muted
        /// No call is open (it ended, or has not begun): one can be started.
        case ended
    }

    /// The one thing that helps when Kaiku cannot listen.
    public enum Help: Equatable, Sendable { case openKaiku, microphoneSettings, tryAgain }

    public var state: State
    public var captions: Bool
    /// The person's words in the exchange going on (as transcribed), and Kaiku's answer to them.
    public var person: String?
    public var kaiku: String?
    /// The microphone is open right now.
    public var micLive: Bool
    public var voiceMuted: Bool
    /// Copy key of the line shown instead of captions (why Kaiku is not listening).
    public var lineKey: String?
    public var mascot: MascotState
    /// The one activity Kaiku suggests in this conversation, if any.
    public var activity: ActivityCard?
    /// A small reaction beside Kaiku, for a moment (from something that really happened in the conversation).
    public var reaction: QuickTalkReaction?

    public init(state: State, captions: Bool = true, person: String? = nil, kaiku: String? = nil, micLive: Bool = false,
                voiceMuted: Bool = false, lineKey: String? = nil, mascot: MascotState = .idle, activity: ActivityCard? = nil,
                reaction: QuickTalkReaction? = nil) {
        self.state = state; self.captions = captions; self.person = person; self.kaiku = kaiku
        self.micLive = micLive; self.voiceMuted = voiceMuted; self.lineKey = lineKey; self.mascot = mascot
        self.activity = activity; self.reaction = reaction
    }

    /// A call is open (whether or not the microphone is muted).
    public var conversational: Bool { [.listening, .hearing, .thinking, .speaking, .muted].contains(state) }

    public var help: Help? {
        switch state {
        case .setup, .notConnected, .paused: return .openKaiku
        case .micDenied: return .microphoneSettings
        case .unavailable, .ended: return .tryAgain
        default: return nil
        }
    }

    public var helpKey: String? {
        switch help {
        case .openKaiku: return "mac.open"
        case .microphoneSettings: return "talk.voice.settings"
        case .tryAgain: return state == .ended ? "call.start" : "call.retry"
        case nil: return nil
        }
    }

    /// The call's one short state, in the call's own words; "Not listening" whenever no call is open.
    public var statusKey: String {
        switch state {
        case .connecting: return CallStatus.connecting.key
        case .listening, .hearing: return CallStatus.listening.key
        case .thinking: return CallStatus.thinking.key
        case .speaking: return CallStatus.speaking.key
        case .muted: return CallStatus.muted.key
        default: return "quick.status.off"
        }
    }

    public var cardSize: CGSize {
        QuickTalkLayout.card(captions: captions, conversational: conversational, activity: activity != nil)
    }

    /// Every copy key a display can ask for (a renamed key fails a test, not a screen).
    static let copyKeys: [String] = State.allCases.flatMap { s -> [String] in
        let d = QuickTalkDisplay(state: s)
        return [d.statusKey] + [d.helpKey].compactMap { $0 }
    } + ["quick.setup", "call.line.unpaired", "call.line.paused", "talk.unavailable.microphone", "call.line.connection",
         "call.line.audio", "call.line.voice", "call.ended", "call.line.ready", "quick.hint", "quick.hint.muted", "quick.continue", "quick.close",
         "quick.mic.on", "quick.mic.off", "quick.a11y.you", "quick.a11y.kaiku", "quick.title", "quick.keys",
         "call.mute.me", "call.unmute.me", "call.mute.kaiku", "call.unmute.kaiku", "card.open", "card.aside",
         "call.end", "quick.collapse", "quick.start", "quick.show", "mac.open", "quick.live"]

    /// The rule. Order matters: the most basic thing missing is the one that is said.
    /// `live` = a Live conversation is open; `status` is then the call's state (`CallStatus`: Kaiku speaking comes
    /// before the person's own mute); `hearing` = the person is talking right now. Without one, the conversation's
    /// `phase` and `reason` say why, and `wasLive` tells an ended call from one that has not begun.
    static func make(onboarded: Bool, paired: Bool, paused: Bool, micDenied: Bool, starting: Bool, live: Bool,
                     phase: Conversation.Phase, wasLive: Bool = false, reason: Conversation.UnavailableReason?,
                     status: CallStatus, micOn: Bool, hearing: Bool = false, lines: [(text: String, me: Bool)] = [],
                     captions: Bool = true, voiceMuted: Bool = false, expression: MascotState? = nil,
                     activity: ActivityCard? = nil, moment: MascotState? = nil, reaction: QuickTalkReaction? = nil) -> QuickTalkDisplay {
        func off(_ s: State, _ key: String) -> QuickTalkDisplay { QuickTalkDisplay(state: s, captions: captions, lineKey: key) }
        let waking = QuickTalkDisplay(state: .connecting, captions: captions, mascot: .thinking)
        guard onboarded else { return off(.setup, "quick.setup") }
        if starting { return waking }
        if !paired || reason == .pairing { return off(.notConnected, "call.line.unpaired") }
        if paused || reason == .paused { return off(.paused, "call.line.paused") }
        if micDenied || reason == .microphone || (live && status == .micOff) {
            return off(.micDenied, "talk.unavailable.microphone")
        }
        guard live else {
            switch phase {
            case .connecting: return waking
            case .unavailable:
                switch reason {
                case .connection: return off(.unavailable, "call.line.connection")
                case .audio: return off(.unavailable, "call.line.audio")
                default: return off(.unavailable, "call.line.voice")
                }
            default: return off(.ended, wasLive ? "call.ended" : "call.line.ready")
            }
        }
        // Kaiku's face follows the call; for a moment after something happened (`moment`) it shows that instead.
        let state: State, mascot: MascotState
        switch status {
        case .connecting: return waking
        case .speaking: state = .speaking; mascot = moment ?? .speaking
        case .thinking: state = .thinking; mascot = .thinking
        case .muted, .micOff, .paused: state = .muted; mascot = .sleepy
        case .listening: state = hearing ? .hearing : .listening; mascot = moment ?? (hearing ? .listening : (expression ?? .listening))
        }
        let words = QuickTalkCaptions.current(lines)
        return QuickTalkDisplay(state: state, captions: captions, person: words.person, kaiku: words.kaiku,
                                micLive: micOn, voiceMuted: voiceMuted, mascot: mascot, activity: activity,
                                reaction: state == .muted ? nil : reaction)
    }
}

/// Captions are the exchange going on, not a history (pure, tested): the person's latest words, and Kaiku's line
/// only when it answers them. When the person speaks again, Kaiku's older line steps aside. The card shows the
/// newest words of each (`tail`); the whole line stays in the display (and is what VoiceOver reads).
enum QuickTalkCaptions {
    /// Roughly what fits the card: one line of the person's words above three of Kaiku's, or four of theirs alone.
    static let personWithReply = 34, personAlone = 112, kaikuLimit = 86

    static func current(_ lines: [(text: String, me: Bool)]) -> (person: String?, kaiku: String?) {
        let spoken = lines.filter { !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        guard let last = spoken.last else { return (nil, nil) }
        if last.me { return (last.text, nil) }
        return (spoken.last(where: \.me)?.text, last.text)
    }

    /// The newest words: a long line keeps its end (from a word boundary), led by an ellipsis.
    static func tail(_ text: String, limit: Int) -> String {
        let t = text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard t.count > limit else { return t }
        var end = String(t.suffix(limit))
        if let space = end.firstIndex(of: " "), end.distance(from: end.startIndex, to: space) < limit / 2 {
            end = String(end[end.index(after: space)...])
        }
        return "…" + end
    }
}

/// A small reaction that pops up beside Kaiku (drawn glyphs in the token colours, never emoji).
public enum QuickTalkReaction: String, Sendable, CaseIterable { case sparkle, heart, curious }

/// What Kaiku shows for a moment when something really happens in the conversation (pure, tested). Never random:
/// the model's `express` tool call, a new `feel` plan from the cloud, Kaiku finding something it remembers about
/// them (`recall` came back with a memory). (A yes to an activity opens it in the main window: nothing to show here.)
/// Gentle on a heavy moment: while the plan says the person is having a hard time (`comfort`, `give_space`) there
/// are no sparkles and no hops, Kaiku is `cozy` (design/motion.md: hard days get cozy; it never looks sad).
enum QuickTalkMoment {
    enum Event: Equatable {
        /// `express`: the feeling as `TalkModel` maps it to Kaiku's face.
        case expression(MascotState)
        /// The `feel` plan's stance: comfort | celebrate | steady | explore | give_space.
        case plan(stance: String?)
        /// `recall` found something Kaiku remembers.
        case found
    }

    static func heavy(_ stance: String?) -> Bool { stance == "comfort" || stance == "give_space" }

    static func react(to event: Event, heavy: Bool) -> (mascot: MascotState?, reaction: QuickTalkReaction?) {
        switch event {
        case .expression(.happy): return heavy ? (.cozy, .heart) : (.happy, .sparkle)
        case .expression(.cheering): return heavy ? (.cozy, .heart) : (.cheering, .sparkle)
        case .found: return (nil, heavy ? nil : .sparkle)          // a small "I remember"; Kaiku's face stays with the call
        case .expression(.cozy): return (.cozy, .heart)
        case .expression(.listening): return (.listening, .curious)
        case .expression(let other): return (other, nil)           // sleepy draws its own z
        case .plan(let stance):
            switch stance {
            case "celebrate": return (.happy, .sparkle)
            case "comfort": return (.cozy, .heart)
            case "give_space": return (.cozy, nil)
            case "explore": return (.listening, .curious)
            default: return (nil, nil)                             // steady: nothing to show
            }
        }
    }
}

/// What the bar's meter shows while a conversation is on.
public struct QuickTalkMeter: Equatable, Sendable {
    public var micOpen: Bool
    /// The person's voice, 0…1.
    public var level: Double
    public var kaikuSpeaking: Bool
    public init(micOpen: Bool = false, level: Double = 0, kaikuSpeaking: Bool = false) {
        self.micOpen = micOpen; self.level = level; self.kaikuSpeaking = kaikuSpeaking
    }
}

#if os(macOS)
/// Quick talk on the Mac: a thin Kaiku-coloured bar at the left edge of the screen. Under the pointer it grows into
/// a pill with two buttons (start speaking, open Kaiku); the key combination, a double tap or the button grows it
/// into the popup, and a conversation with Kaiku starts at once, microphone open, Kaiku listening. This is the
/// state behind it: the settings (UserDefaults) and the ONE `TalkModel` the popup and the Talk screen both show.
/// The AppKit side (window, hot key, double tap, pointer) lives in the Mac shell, `Mac/QuickTalkPanel.swift`.
///
/// Three ways the popup goes away:
/// - `collapse()`: back to the bar, the conversation goes on (the bar shows the voice, the notch island the call);
/// - `close()` (Esc, the trigger again): ends the conversation the way leaving Talk does, unless the main window
///   is showing Talk (then that screen has it);
/// - `end()` (End call): ends it wherever it shows.
/// "Continue in Kaiku" hands it to the Talk screen. A conversation left in the background with nobody talking
/// ends by itself after `quietLimit`.
@Observable @MainActor
public final class QuickTalkModel {
    public static let shared = QuickTalkModel()

    enum Keys {
        static let enabled = "kaiku.quicktalk.on"
        static let bar = "kaiku.quicktalk.bar"
        static let doubleTap = "kaiku.quicktalk.doubleTap"
        static let captions = "kaiku.quicktalk.captions"
    }

    // MARK: settings (You → Quick talk)

    /// The triggers are armed. On by default: the key combination opens nothing by accident.
    public var enabled: Bool { didSet { defaults.set(enabled, forKey: Keys.enabled); settingsChanged?() } }
    /// The bar at the screen edge. Off = nothing on screen at rest; the triggers still work.
    public var showBar: Bool { didSet { defaults.set(showBar, forKey: Keys.bar); settingsChanged?() } }
    /// A double tap of one modifier key also starts quick talk (it needs no permission, see the Mac shell). Control
    /// by default; Option or off are the person's choice.
    public var doubleTap: QuickTalkDoubleTapKey { didSet { defaults.set(doubleTap.rawValue, forKey: Keys.doubleTap); settingsChanged?() } }
    /// Words beside Kaiku. Off = Kaiku alone.
    public var captions: Bool { didSet { defaults.set(captions, forKey: Keys.captions) } }
    /// The shell re-arms its triggers.
    @ObservationIgnored public var settingsChanged: (() -> Void)?

    // MARK: the shell's side (set once by `QuickTalkController`)

    /// True in layout-snapshot and inspection runs: the surface can be looked at, a conversation never starts.
    @ObservationIgnored public var inert = false
    /// The main window is on screen and showing the Talk tab right now.
    @ObservationIgnored public var mainShowsTalk: @MainActor () -> Bool = { false }
    /// Bring the main window forward (on this tab, or where it is when nil).
    @ObservationIgnored public var openMain: @MainActor (KaikuTab?) -> Void = { _ in }
    @ObservationIgnored public var openMicrophoneSettings: @MainActor () -> Void = {}
    @ObservationIgnored var micPermission: () -> AudioCapture.Permission = { QuickTalkModel.systemMicPermission() }

    /// The system's answer, read without asking. Under `-kaikuTalkDemo <state>` (Debug: every conversation runs on
    /// a scripted stand-in with no microphone) the stand-in's own answer counts, as it does for the Talk screen.
    static func systemMicPermission() -> AudioCapture.Permission {
        #if DEBUG
        if let demo = UserDefaults.standard.string(forKey: "kaikuTalkDemo") { return demo == "denied" ? .denied : .granted }
        #endif
        return AudioCapture.permission
    }

    // MARK: state

    let talk: TalkModel
    /// The popup is showing.
    public private(set) var isOpen = false
    /// The pointer is at the bar (the shell says so): it grows into the pill.
    public var hovering = false
    private var starting = false
    /// The popup was put away with the conversation still on (it is quick talk's to look after).
    private var away = false
    private var moment: MascotState?
    private var reaction: QuickTalkReaction?
    @ObservationIgnored private weak var app: AppModel?
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var shown: ObjectIdentifier?
    @ObservationIgnored private var watching = 0
    @ObservationIgnored private var seenPlans = 0
    @ObservationIgnored private var momentRun = 0
    @ObservationIgnored private var hooked: ObjectIdentifier?
    @ObservationIgnored private var quietTask: Task<Void, Never>?
    /// How many conversations this model has started (the tests and the snapshot probe check it stays 0 when it must).
    @ObservationIgnored public private(set) var startAttempts = 0
    /// How long the Talk screen has to come up after "Continue in Kaiku" before the conversation is ended instead.
    static var handoverGrace: TimeInterval = 2
    /// A conversation put away in the background ends by itself after this long without the person saying
    /// anything: the same rule as a call left in the background on the Talk screen (`TalkModel.backgrounded`), the
    /// session's own `idle_end_s` when the cloud sends one.
    static var quietLimit: TimeInterval = TalkModel.backgroundQuietLimit
    /// How long Kaiku's face keeps a moment, and how long the small reaction beside it stays.
    static var momentHold: TimeInterval = 4
    static var reactionHold: TimeInterval = 2.4

    init(defaults: UserDefaults = .standard, talk: TalkModel? = nil) {
        self.defaults = defaults
        self.talk = talk ?? TalkModel()
        enabled = defaults.object(forKey: Keys.enabled) as? Bool ?? true
        showBar = defaults.object(forKey: Keys.bar) as? Bool ?? true
        doubleTap = defaults.string(forKey: Keys.doubleTap).flatMap(QuickTalkDoubleTapKey.init(rawValue:)) ?? .control
        captions = defaults.object(forKey: Keys.captions) as? Bool ?? true
    }

    /// The shell hands the app model over at launch (the bar is there before anything is opened).
    public func attach(app: AppModel) { if self.app == nil { self.app = app } }

    /// The pill's "start speaking" (and "show" while a conversation is on): `open` with the attached app.
    public func start() { if let app { open(app: app) } }

    public var display: QuickTalkDisplay {
        guard let app else { return QuickTalkDisplay(state: .connecting, captions: captions, mascot: .thinking) }
        let c = talk.conversation
        return .make(onboarded: app.onboarded, paired: app.isPaired, paused: app.isPaused, micDenied: micPermission() == .denied,
                     starting: starting, live: talk.hasLive, phase: c.phase, wasLive: c.wasLive, reason: c.unavailableReason,
                     status: talk.status, micOn: talk.micOn, hearing: c.phase == .hearing, lines: c.lines.map { ($0.text, $0.me) },
                     captions: captions, voiceMuted: talk.voiceMuted, expression: talk.expression, activity: talk.activityCard,
                     moment: moment, reaction: reaction)
    }

    /// A conversation is on (in the popup, on the Talk screen, or put away in the background).
    public var isLive: Bool { talk.hasLive }

    /// The one shape right now: the popup; else the bar, the pill under the pointer; nothing when the bar is
    /// turned off. A conversation put away from the popup always keeps the bar, whatever the setting: an open
    /// microphone is never out of sight.
    public var stage: QuickTalkStage {
        if isOpen { return .popup }
        guard enabled, showBar || (away && isLive) else { return .hidden }
        return hovering ? .pill : .bar
    }

    /// The voice, for the bar's meter.
    public var meter: QuickTalkMeter {
        let c = talk.conversation
        return QuickTalkMeter(micOpen: talk.micOn, level: talk.micOn ? QuickTalkLayout.level(db: c.level) : 0, kaikuSpeaking: c.kaikuSpeaking)
    }

    /// For the notch island while the popup is put away: the call's one short state, when it began, the microphone.
    public var call: QuickTalkCall? {
        guard talk.hasLive else { return nil }
        return QuickTalkCall(status: talk.status, since: talk.conversation.liveSince, micOn: talk.micOn)
    }

    // MARK: open, collapse, close, end

    /// The trigger: the popup grows out of the bar and, when nothing stands in the way, a conversation starts at
    /// once. A conversation already on (put away earlier, or the Talk screen's) is shown as it is.
    public func open(app: AppModel) {
        self.app = app
        guard !isOpen else { return }
        isOpen = true
        hovering = false
        away = false
        quietTask?.cancel(); quietTask = nil
        shown = ObjectIdentifier(talk.conversation)
        seenPlans = talk.conversation.planCount
        watching += 1
        watch(watching)
        watchMoments(watching)
        begin()
    }

    /// Back to the bar; the conversation goes on. With nothing live there is nothing to keep: the same as closing.
    public func collapse() {
        guard isOpen else { return }
        guard talk.hasLive else { close(); return }
        isOpen = false
        guard !mainShowsTalk() else { return }   // the Talk screen has it, and its own rules
        away = true
        // Out of sight, a microphone must not listen for long: with nobody talking it ends by itself.
        let since = Date(), run = generation
        quietTask?.cancel()
        quietTask = Task { [weak self] in
            while !Task.isCancelled {
                let limit = self?.talk.conversation.session?.idle_end_s.map(TimeInterval.init) ?? Self.quietLimit
                try? await Task.sleep(nanoseconds: UInt64(min(2, limit / 4) * 1_000_000_000))
                guard let self, !Task.isCancelled, self.generation == run, !self.isOpen, self.talk.hasLive else { return }
                if self.mainShowsTalk() { return }
                let heard = max(self.talk.conversation.lastPersonAt ?? .distantPast, since)
                if Date().timeIntervalSince(heard) >= limit { self.end(); return }
            }
        }
    }

    /// Esc or the trigger again. Ends the conversation unless the Talk screen has it.
    public func close() {
        guard isOpen else { return }
        let onTalkScreen = mainShowsTalk()
        release()
        if !onTalkScreen { talk.stop() }
    }

    /// End call: from the popup, the pill, or the notch island. Ends it wherever it shows.
    public func end() {
        let onTalkScreen = mainShowsTalk()
        release()
        if onTalkScreen { talk.end() } else { talk.stop() }   // the Talk screen keeps its words, as its own End does
    }

    /// The main window opens on Talk with this same conversation; the popup steps aside without ending it.
    public func continueInKaiku() {
        guard let app, isOpen || talk.hasLive else { return }
        release()
        app.selectedTab = .talk
        openMain(.talk)
        // If the Talk screen did not come up after all, nothing may keep listening out of sight.
        let handed = generation
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(Self.handoverGrace * 1_000_000_000))
            guard let self, self.generation == handed, !self.isOpen, !self.mainShowsTalk() else { return }
            self.talk.stop()
        }
    }

    /// The popup is gone and this model lets go of the conversation (whoever has it now, or nobody).
    private func release() {
        isOpen = false
        away = false
        generation += 1
        watching += 1
        starting = false
        quietTask?.cancel(); quietTask = nil
        talk.onActivity = nil
        moment = nil; reaction = nil
    }

    /// Mute / unmute me (the call's own control: the same as on the Talk screen).
    public func toggleMicrophone() { talk.toggleMic() }

    /// Kaiku's voice off or on; its words keep coming as captions.
    public func toggleVoice() { talk.toggleVoice() }

    /// The card's button counts as the person asking: the activity opens in the main window and the popup steps
    /// aside (`arm`).
    public func openActivity() { talk.openCard() }

    public func putActivityAside() { talk.putCardAside() }

    /// The one helping button of a state that cannot listen.
    public func help() {
        guard let app else { return }
        switch display.help {
        case .openKaiku:
            let state = display.state
            close()
            if state != .setup { app.selectedTab = .you }   // the service and the pause switch are both in You
            openMain(state == .setup ? nil : .you)
        case .microphoneSettings:
            close()
            openMicrophoneSettings()
        case .tryAgain:
            begin()
        case nil: break
        }
    }

    // MARK: private

    private func begin() {
        guard let app, isOpen, !inert, !starting else { return }
        // A conversation that is on (put away earlier, or the Talk screen's) carries on as it is.
        if talk.hasLive { arm(); return }
        let canListen = app.onboarded && !app.isPaused && micPermission() != .denied
        if mainShowsTalk() {
            // The Talk screen has this conversation (starting, or ended): the popup shows the same one and starts
            // nothing of its own. One that ended there starts again the way that screen's own button does.
            if canListen, talk.conversation.phase != .connecting { talk.restart() }
            arm()
            return
        }
        guard canListen else { return }
        generation += 1
        let run = generation
        starting = true
        startAttempts += 1
        Task { [weak self] in
            guard let self else { return }
            // Whatever was left over (an ended or unavailable conversation) makes way for a fresh one.
            self.talk.stop()
            self.shown = ObjectIdentifier(self.talk.conversation)
            self.seenPlans = 0
            await self.talk.start(app: app)
            // The person speaks first here: Talk's own "just opened" event (Kaiku greets) is not sent.
            self.talk.conversation.onReady = nil
            guard self.generation == run, self.isOpen else { return }
            self.starting = false
            // Ended from the main window while it was starting (the person left Talk there): nothing to show.
            guard ObjectIdentifier(self.talk.conversation) == self.shown else { self.close(); return }
            if self.talk.hasLive { self.arm() } else { VoiceLines.shared.stop() }   // no spoken hello from a popup that cannot talk
        }
    }

    /// An activity the person asked for opens in the main window; the popup steps aside. And Kaiku's finds are
    /// noticed: the conversation's tool answers are listened to (after whoever listened before).
    private func arm() {
        let c = talk.conversation
        if hooked != ObjectIdentifier(c) {
            hooked = ObjectIdentifier(c)
            let earlier = c.onToolResult
            c.onToolResult = { [weak self] name, result in
                earlier?(name, result)
                Task { @MainActor in self?.toolAnswered(name, result) }
            }
        }
        talk.onActivity = { [weak self] _ in
            Task { @MainActor in
                guard let self, self.isOpen || self.talk.hasLive else { return }
                self.end()
                self.openMain(nil)
            }
        }
    }

    /// From opening until this model lets go: the crisis screen lives in the main window, so a crisis brings that
    /// forward and puts the popup away; and a conversation stopped from the main window (the person left Talk
    /// there) puts it away too. It keeps watching while the popup is collapsed and the conversation goes on.
    private func watch(_ token: Int) {
        guard token == watching else { return }
        let seen = withObservationTracking {
            (ObjectIdentifier(talk.conversation), app?.showCrisis ?? false)
        } onChange: { [weak self] in
            Task { @MainActor in self?.watch(token) }
        }
        if seen.1 {
            end()
            openMain(nil)
        } else if !starting, let shown, shown != seen.0 {
            if isOpen { close() } else { release() }
        }
    }

    /// Kaiku's moments: the model's `express` call, a new `feel` plan.
    private func watchMoments(_ token: Int) {
        guard token == watching else { return }
        withObservationTracking {
            _ = (talk.conversation.planCount, talk.expression)
        } onChange: { [weak self] in
            Task { @MainActor in self?.momentsChanged(token) }
        }
    }

    private func momentsChanged(_ token: Int) {
        guard token == watching else { return }
        let c = talk.conversation
        if c.planCount > seenPlans {
            seenPlans = c.planCount
            show(.plan(stance: c.plan?.stance))
        } else if c.planCount == seenPlans, let face = talk.expression {
            show(.expression(face))
        } else {
            seenPlans = c.planCount   // a new conversation
        }
        watchMoments(token)
    }

    /// A find: `recall` came back with something Kaiku remembers about the person.
    private func toolAnswered(_ name: String, _ result: CompanionToolResult) {
        guard isOpen || away, name == "recall", result.ok, case .array(let found)? = result.result?["memories"], !found.isEmpty else { return }
        show(.found)
    }

    private func show(_ event: QuickTalkMoment.Event) {
        guard talk.hasLive else { return }
        let r = QuickTalkMoment.react(to: event, heavy: QuickTalkMoment.heavy(talk.conversation.plan?.stance))
        guard r.mascot != nil || r.reaction != nil else { return }
        moment = r.mascot
        reaction = r.reaction
        momentRun += 1
        let run = momentRun
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(Self.reactionHold * 1_000_000_000))
            guard let self, self.momentRun == run else { return }
            self.reaction = nil
            try? await Task.sleep(nanoseconds: UInt64(max(0, Self.momentHold - Self.reactionHold) * 1_000_000_000))
            guard self.momentRun == run else { return }
            self.moment = nil
        }
    }
}

/// A call as the notch island shows it.
public struct QuickTalkCall: Equatable, Sendable {
    public var status: CallStatus
    public var since: Date?
    public var micOn: Bool
    public init(status: CallStatus, since: Date?, micOn: Bool) { self.status = status; self.since = since; self.micOn = micOn }

    /// Kaiku's face for the call's state (sleepy while the person is muted, as in the popup).
    public var mascot: MascotState {
        switch status {
        case .listening: return .listening
        case .speaking: return .speaking
        case .thinking, .connecting: return .thinking
        case .muted, .micOff, .paused: return .sleepy
        }
    }
}
#endif

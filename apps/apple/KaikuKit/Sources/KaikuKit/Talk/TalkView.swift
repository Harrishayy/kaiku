import SwiftUI

/// Talk: an open spoken conversation (Conversation: server VAD, barge-in, the mind's tools) + bubbles + composer.
/// Starts with POST /v1/companion/session {surface: iphone|mac, intent: talk}. Tap Kaiku to stop / start listening.
/// Without Live (offline, no key, no mic): "Kaiku can talk once it's online" + typed messages that run the local
/// safety gate and get short scripted replies (copy keys; no AI pretending).
@Observable @MainActor
final class TalkModel {
    struct Line: Identifiable, Equatable { let id: UUID; let text: String; let me: Bool; var interrupted = false }
    /// `ready`: no call was asked for yet on this screen (the screen shows "Call Kaiku").
    enum Mode: Equatable { case connecting, live, scripted, listening, thinking, speaking, denied, paused, muted, ended, ready }

    var expression: MascotState?
    private var scripted: [Line] = []
    private var scriptedThinking = false
    private var scriptedIndex = 0
    private var scriptedTask: Task<Void, Never>?
    private var replyGeneration = 0
    private(set) var conversation: Conversation
    private let makeConversation: @MainActor () -> Conversation
    /// What Live is told when the conversation opens (a fixed bracketed context event; Kaiku then greets).
    var opening: String
    /// The Gemini voice line played when Live is not there (nil: the time-of-day greeting).
    var silentGreeting: String?
    /// Kaiku's typed-message lines when there is no model to answer (copy keys, in turn).
    var scriptedKeys = ["talk.scripted.1", "talk.scripted.2", "talk.scripted.3"]
    /// The model recorded a dial answer the person said out loud (after it was sent).
    var onDial: ((DialItem, Int) -> Void)?
    /// False in a passing chat: the two-weekly questionnaire is never opened in the middle of a check-in.
    var allowsQuestionnaire = true
    /// The person asked for an activity and the model starts it: called just before the app goes there.
    var onActivity: ((KaikuRoute) -> Void)?
    init(opening: String = "[the person just opened Talk]",
         makeConversation: @escaping @MainActor () -> Conversation = { TalkModel.liveConversation(intent: .talk, purpose: .talk, typedWithoutMic: true) }) {
        self.opening = opening
        self.makeConversation = makeConversation
        conversation = makeConversation()
    }
    weak var app: AppModel?
    /// Is the screen that shows this conversation's call bar in front of the person? The screen says so as it
    /// appears and disappears. While it is not, no conversation starts and no microphone opens: a tab that is
    /// not showing stays alive on the iPhone, and what it does there nobody would see (2026-11-14: a check-in
    /// left on its tab opened a new conversation with no call bar when the tab came back). nil: no screen has
    /// claimed this model (the Mac's quick talk panel owns its window and its own rules).
    private(set) var onScreen: Bool?
    private var retired = false

    func screenAppeared() { if !retired { onScreen = true } }

    /// The screen is gone (another tab, popped, closed): the conversation ends with it.
    func screenDisappeared() {
        onScreen = false
        stop()
    }

    /// The screen is gone for good (a check-in that was left): this model never opens a conversation again,
    /// whatever calls it later.
    func retire() {
        retired = true
        screenDisappeared()
    }

    private var audioTokens: [NSObjectProtocol] = []
    private var routeAnnounced = false
    private var started = false
    private var denied = false
    private var observingCall = false

    var hasLive: Bool { conversation.isLive }
    /// This conversation was really connected at some point (so "dropped" is a true word for it).
    var everLive: Bool { conversation.wasLive }
    var lastSpokenDial: Int? { conversation.lastSpokenDial }

    var lines: [Line] {
        conversation.lines.map { Line(id: $0.id, text: $0.text, me: $0.me, interrupted: $0.interrupted) } + scripted
    }

    var mode: Mode {
        // Without the microphone a call still opens (typed, Kaiku answers aloud); "denied" is only the state
        // of a conversation that could not start for that reason.
        if denied && !hasLive && conversation.unavailableReason == .microphone { return .denied }
        if scriptedThinking { return .thinking }
        switch conversation.phase {
        case .idle: return started ? .ended : .ready
        case .connecting: return .connecting
        case .listening: return .live
        case .hearing: return .listening
        case .thinking: return .thinking
        case .speaking: return .speaking
        case .muted: return .muted
        case .paused: return .paused
        case .unavailable: return .scripted
        }
    }

    func start(app: AppModel) async {
        self.app = app
        guard onScreen != false else { return }       // never behind a screen that is not showing
        #if DEBUG
        // Inspect a real window without opening capture or minting a provider session.
        if UserDefaults.standard.bool(forKey: "kaikuInspectOnly") { started = true; return }
        if let demo = TalkDemo.state {
            guard !started else { return }
            started = true
            if !observingCall { observingCall = true; observeCall() }
            let c = conversation
            c.deviceTool = { [weak self] name, args in await self?.deviceTool(name, args) ?? .object(["ok": .bool(false)]) }
            c.onCrisis = { [weak self] in self?.app?.crisis(trigger: "phrase") }
            await TalkDemo.run(demo, conversation: c, app: app, checkIn: c.purpose == .check_in)
            return
        }
        #endif
        if denied && AudioCapture.permission != .denied { started = false }
        guard !started else { return }
        started = true
        if !observingCall { observingCall = true; observeCall() }
        if audioTokens.isEmpty {
            audioTokens = TalkAudio.observe { [weak self] ev in self?.audioEvent(ev) }
        }
        let c = conversation
        c.deviceTool = { [weak self] name, args in await self?.deviceTool(name, args) ?? .object(["ok": .bool(false)]) }
        c.onCrisis = { [weak self] in self?.app?.crisis(trigger: "phrase") }
        c.onReady = { [weak c, opening] in c?.context(opening) }   // Kaiku greets in its live voice
        denied = AudioCapture.permission == .denied
        await app.ensureServiceConnection()
        guard started, onScreen != false, conversation === c else { return }
        let ok = await c.start(app: app)
        denied = AudioCapture.permission == .denied
        #if DEBUG
        if ok { typeFromLaunchArguments(into: c) }
        #endif
        if !ok {
            // No Live: Kaiku still says hello in its own Gemini voice (cached / fetched line; silent offline).
            let key = silentGreeting ?? Self.greetingKey()
            // Only for the conversation that is still the one on screen: the start above can take seconds, and a
            // hello that arrives after the person left would be Kaiku talking on some other screen.
            guard started, onScreen != false, conversation === c else { return }
            VoiceLines.shared.play(key, lang: app.language, fallback: silentGreeting == nil ? nil : T(key), origin: .chat)
        }
    }

    #if DEBUG
    /// `-kaikuTalkSay "text"` types one message once Kaiku is on the line; `-kaikuTalkSayLater "one|two|three"
    /// -kaikuTalkSayDelay 40` types each of those that many seconds after the one before, wherever the app is by
    /// then (the real Live path, without the microphone: for screenshots, and for checking that a call goes on
    /// in the background and across the end of a Live token).
    private func typeFromLaunchArguments(into c: Conversation) {
        let d = UserDefaults.standard
        let first = d.string(forKey: "kaikuTalkSay"), later = d.string(forKey: "kaikuTalkSayLater")
        guard first != nil || later != nil else { return }
        let delay = max(5, d.double(forKey: "kaikuTalkSayDelay"))
        Task { [weak self, weak c] in
            for _ in 0..<60 where c?.liveSince == nil { try? await Task.sleep(nanoseconds: 500_000_000) }
            try? await Task.sleep(nanoseconds: 7_000_000_000)          // Kaiku's hello first
            guard let self, let c, self.conversation === c, c.isLive else { return }
            if let first { self.send(first) }
            for text in (later ?? "").split(separator: "|") {
                try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                guard self.conversation === c, c.isLive else { return }
                self.send(String(text))
            }
        }
    }
    #endif

    func stop() {
        replyGeneration += 1
        scriptedTask?.cancel(); scriptedTask = nil
        scriptedThinking = false; scripted = []
        takenPlan = 0; sparkled = false; toolCard = nil; aside = []; planCardAtOnce = false
        conversation.stop()
        audioTokens.forEach(NotificationCenter.default.removeObserver)
        audioTokens = []
        VoiceLines.shared.stop()
        TalkAudio.deactivate()
        started = false
        conversation = makeConversation()
        callChanged()
    }

    // MARK: input

    func send(_ raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        if hasLive { conversation.send(text: text); return }
        scripted.append(Line(id: UUID(), text: text, me: true))
        if SafetyGate.shared.check(text) != nil { app?.crisis(trigger: "phrase"); return }
        scriptedReply()
    }

    // MARK: the call (mute me, mute Kaiku, end): the same controls on every surface

    /// The call with an open conversation, for controls outside the views (Lock Screen, Dynamic Island, intents).
    static weak var active: TalkModel?

    var status: CallStatus { CallStatus(conversation) }
    /// The microphone is open (Live, allowed, not muted / paused).
    var micOn: Bool {
        hasLive && conversation.listens && !conversation.micMuted && ![.paused, .connecting].contains(conversation.phase)
    }
    var voiceMuted: Bool { conversation.voiceMuted }

    /// Mute / unmute me. Kaiku goes on answering what is typed.
    func toggleMic() {
        guard hasLive, conversation.listens else { return }
        // Muting is always allowed; the microphone only opens while the call's own screen is the one showing
        // (or the app is out of sight with the call on the Lock Screen: the screen is still the call's).
        guard !conversation.micMuted || onScreen != false else { return }
        conversation.setMuted(!conversation.micMuted)
    }

    /// Mute / unmute Kaiku's voice. Its words keep coming as captions.
    func toggleVoice() { conversation.setVoiceMuted(!conversation.voiceMuted) }

    /// End the call (the words stay on screen until the next one starts).
    func end() {
        guard hasLive || conversation.phase == .connecting else { return }
        conversation.stop(outcome: conversation.lines.contains(where: \.me) ? .completed : .skipped)
        callChanged()
    }

    /// Start again after an end, a drop or a failed start.
    func restart() {
        guard let app, !hasLive, onScreen != false else { return }
        started = false
        Task { await start(app: app) }
    }

    // MARK: the activity card (the `suggest_activity` tool, or what the `feel` plan may offer)

    private var toolCard: ActivityCard?
    private var aside: Set<String> = []
    private var takenPlan = 0
    private var sparkled = false
    /// The plan's offer normally waits for the person's next words (Kaiku meets the feeling first). After the
    /// check-in dials nothing more is being said, so it may show at once.
    var planCardAtOnce = false

    /// The one card in the conversation: one at a time, never the same kind twice, and a card that was put
    /// aside does not come back in this conversation.
    var activityCard: ActivityCard? {
        if let t = toolCard, !aside.contains(t.kind) { return t }
        let c = conversation
        guard c.planCount > takenPlan, let p = c.plan, planCardAtOnce || c.lines.filter(\.me).count > c.planTurns,
              let card = ActivityCard(plan: p), !aside.contains(card.kind) else { return nil }
        return card
    }

    /// The button on the card: counts as the person asking, and goes to the activity.
    func openCard() {
        guard let card = activityCard, let app else { return }
        conversation.personDid(card.openedText)
        toolCard = nil
        takenPlan = conversation.planCount
        aside.insert(card.kind)
        onActivity?(card.route)
        app.deepLink = card.route
        app.selectedTab = card.route.tab
    }

    /// The small way out: final for this conversation.
    func putCardAside() {
        guard let card = activityCard else { return }
        aside.insert(card.kind)
        toolCard = nil
        conversation.personDid(card.asideText)
    }

    /// A new plan arrived: good news gets the sparkle moment, once per conversation.
    func planArrived() {
        guard conversation.plan?.isGoodNews == true, !sparkled else { return }
        sparkled = true
        app?.celebrate()
    }

    private func scriptedReply() {
        scriptedThinking = true
        let keys = scriptedKeys
        let key = keys[scriptedIndex % keys.count]
        scriptedIndex += 1
        scriptedTask?.cancel()
        replyGeneration += 1
        let generation = replyGeneration
        let pairing = app?.pairing
        scriptedTask = Task {
            do { try await Task.sleep(nanoseconds: 900_000_000) } catch { return }
            guard generation == replyGeneration, app?.pairing == pairing else { return }
            scripted.append(Line(id: UUID(), text: T(key), me: false))
            scriptedThinking = false
        }
    }

    // MARK: device tools (the model requests, the device decides)

    private func deviceTool(_ name: String, _ args: [String: JSONValue]) async -> JSONValue {
        guard let app else { return .object(["ok": .bool(false)]) }
        switch name {
        case "express":
            let f = args["feeling"]?.string ?? "happy"
            expression = ["sleepy": .sleepy, "cozy": .cozy, "curious": .listening, "proud": .cheering][f] ?? .happy
        case "record_dial":
            if let item = args["item"]?.string.flatMap(DialItem.init(rawValue:)), let v = args["value"]?.int ?? lastSpokenDial {
                let ok = await app.recordDial(item: item, value: v)
                if ok { onDial?(item, v) }
                return .object(["ok": .bool(ok)])
            }
            return .object(["ok": .bool(false), "error": .string("a valid item and value are required")])
        case "start_phq9":
            guard allowsQuestionnaire else {
                return .object(["ok": .bool(false), "error": .string("not in a passing chat; leave the questionnaire for another time and do not read its questions out")])
            }
            guard app.isPaired else { return .object(["ok": .bool(false)]) }
            app.phq9Requested = true
        case "suggest_activity":
            // A card in the conversation: the person opens it or puts it aside. Nothing starts by itself.
            guard let card = ActivityCard(kind: args["kind"]?.string ?? "", line: args["line"]?.string), !aside.contains(card.kind) else {
                return .object(["ok": .bool(true), "shown": .bool(false)])
            }
            toolCard = card
            return .object(["ok": .bool(true), "shown": .bool(true)])
        case "start_activity":
            // Only on the person's word: a model that opens a fresh Talk by launching a game would pull them out
            // of the conversation before they said anything (seen live 2026-11-14).
            guard conversation.lines.contains(where: \.me) else {
                return .object(["ok": .bool(false), "error": .string("ask the person first; they haven't asked for an activity")])
            }
            // Only on the person's word: they asked for it, or said a clear yes to Kaiku's offer. Seen live
            // 2026-11-14: the model opened "Tell Kaiku" on the first sad sentence, and breathing on a "maybe".
            guard Self.asked(for: args["kind"]?.string ?? "", in: conversation.lines.last(where: \.me)?.text) else {
                return .object(["ok": .bool(false), "error": .string("they have not asked for it or clearly said yes; start nothing. Stay with what they said; you may offer once, later, as a question")])
            }
            let kind = args["kind"]?.string ?? ""
            guard let r = ActivityCard.route(kind == "light_hunt" ? "walk" : kind) else {
                return .object(["ok": .bool(false), "error": .string("not on this device")])
            }
            onActivity?(r)
            app.deepLink = r
            app.selectedTab = r.tab
        default:
            return .object(["ok": .bool(false), "error": .string("not on this device")])
        }
        return .object(["ok": .bool(true)])
    }
}

extension TalkModel {
    /// The conversation Talk and the check-in chat run on (a scripted stand-in under `-kaikuTalkDemo`, Debug only).
    static func liveConversation(intent: CompanionIntent, purpose: CompanionPurpose, typedWithoutMic: Bool = false) -> Conversation {
        #if DEBUG
        if let demo = TalkDemo.conversation(intent: intent, purpose: purpose) { return demo }
        #endif
        return Conversation(surface: KaikuPlatform.surface, intent: intent, purpose: purpose, typedWithoutMic: typedWithoutMic)
    }

    /// The person's latest words ask for this activity or say a clear yes (en / fi / sv). A hedge or a no
    /// ("maybe", "not now", "I don't know") is never a yes. The device decides this, not the model: when it says
    /// no, the model may ask plainly and the person can answer, or take the offer chip.
    nonisolated static func asked(for kind: String, in said: String?) -> Bool {
        guard let said else { return false }
        let text = " " + said.lowercased().replacingOccurrences(of: "’", with: "'")
            .components(separatedBy: CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "'")).inverted)
            .filter { !$0.isEmpty }.joined(separator: " ") + " "
        let yes = [" yes ", " yeah ", " yep ", " yup ", " sure ", " ok ", " okay ", " alright ", " please ", " let's ", " lets ",
                   " go ahead ", " sounds good ", " sounds nice ", " would help ", " would be nice ", " would be good ",
                   " i'd like ", " i would like ", " i'd love ", " love to ", " can we ", " could we ", " shall we ", " why not ",
                   " joo ", " juu ", " kyllä ", " toki ", " okei ", " mennään ", " tehdään ", " aloitetaan ", " sopii ", " mielellään ",
                   " ja ", " japp ", " gärna ", " okej ", " visst ", " absolut ", " kan vi ", " vi gör det "]
        let words: [String]
        switch kind {
        case "breathe": words = [" breath", " hengit", " anda", " andning"]
        case "walk", "light_hunt": words = [" walk", " kävel", " promen"]
        case "firefly", "pebbles", "lantern", "seeds", "watering": words = [" game", " play ", " peli", " pela", " spel"]
        default: words = []
        }
        let hedges = [" maybe ", " perhaps ", " not now ", " not today ", " not sure ", " don't know ", " dont know ", " later ", " no ",
                      " nope ", " don't want ", " dont want ", " rather not ", " can't ", " cant ", " ehkä ", " en tiedä ", " ei nyt ",
                      " myöhemmin ", " ei ", " en halua ", " kanske ", " inte nu ", " vet inte ", " senare ", " nej ", " vill inte "]
        let saysYes = yes.contains(where: text.contains)
        if hedges.contains(where: text.contains) && !saysYes { return false }
        return saysYes || words.contains(where: text.contains)
    }

    static func greetingKey(_ d: Date = Date()) -> String {
        let h = Calendar.current.component(.hour, from: d)
        return h < 5 ? "greet.night" : h < 12 ? "greet.morning" : h < 18 ? "greet.afternoon" : h < 23 ? "greet.evening" : "greet.night"
    }

    /// Phone call / Siri / alarm → pause (mascot sleepy, "listening paused"); afterwards resume politely.
    /// Glasses or AirPods connecting / leaving → keep going on the new route, tell the person once.
    func audioEvent(_ ev: TalkAudio.Event) {
        switch ev {
        case .interrupted:
            VoiceLines.shared.stop()
            conversation.pause()
        case .resumed(let shouldResume):
            guard shouldResume, conversation.phase == .paused else { return }
            conversation.resume()
            conversation.context("[back after an interruption, e.g. a phone call]")
        case .routeChanged(let name):
            guard !routeAnnounced, !name.isEmpty else { return }
            routeAnnounced = true
            app?.showToast(T("talk.route", ["name": name]))
        }
    }

    /// Out of sight (another app, the Lock Screen) the call goes on. A pocket must not listen for long: after the
    /// session's `idle_end_s` (this many seconds when the cloud sends none) in the background without the person
    /// saying anything, the call ends by itself. The session's own length limit, `max_session_seconds`, still
    /// applies on top.
    static var backgroundQuietLimit: TimeInterval = 180

    func backgrounded() async {
        let since = Date()
        while !Task.isCancelled {
            let limit = conversation.session?.idle_end_s.map(TimeInterval.init) ?? Self.backgroundQuietLimit
            try? await Task.sleep(nanoseconds: UInt64(min(2, limit / 4) * 1_000_000_000))
            guard !Task.isCancelled else { return }
            // Still watching while a dropped call is coming back; done once it is over.
            guard hasLive || conversation.phase == .connecting else { return }
            let heard = max(conversation.lastPersonAt ?? .distantPast, since)
            if Date().timeIntervalSince(heard) >= limit { end(); return }
        }
    }

    /// Follows the open conversation and keeps the call's outside surfaces true: the active call for the Lock
    /// Screen / Dynamic Island buttons and the Live Activity (state, microphone, the last caption).
    func observeCall() {
        guard observingCall else { return }
        withObservationTracking {
            let c = conversation
            _ = (c.phase, c.micMuted, c.voiceMuted, c.kaikuSpeaking, c.listens, c.liveSince, c.lines.last?.text, c.awaitingAnswer)
        } onChange: { [weak self] in
            Task { @MainActor in
                guard let self, self.observingCall else { return }
                self.callChanged()
                self.observeCall()
            }
        }
    }

    func callChanged() {
        let c = conversation
        // A call that dropped and is coming back is still the call (its bar says "Waking Kaiku up…").
        guard hasLive || c.phase == .connecting, let since = c.liveSince else {
            if TalkModel.active === self { TalkModel.active = nil; CallSurface.end() }
            return
        }
        TalkModel.active = self
        let last = c.lines.last
        CallSurface.show(since: since, lang: app?.language.rawValue ?? "en",
                         state: .init(status: status, micOn: micOn, voiceMuted: c.voiceMuted,
                                      caption: last.map { CallSurface.tail($0.text) }, captionMine: last?.me ?? false),
                         limit: TimeInterval(c.session?.max_session_seconds ?? 900))
    }
}

/// Talk: a call with Kaiku. Kaiku in the centre (it follows the call), the words of the two of you as captions,
/// and the call bar: how long, the one short state, mute me, mute Kaiku, type, end. Voice first: nothing on this
/// screen explains itself in paragraphs; a state that needs explaining gets one short line and one action.
public struct TalkView: View {
    @Environment(AppModel.self) private var app
    @State private var model: TalkModel
    @State private var text = ""
    @State private var typing = false
    @State private var bgTask: Task<Void, Never>?
    @State private var columnWidth: CGFloat = 0
    @Environment(\.scenePhase) private var phase
    @Environment(\.openURL) private var openURL
    @State private var showPairing = false
    @State private var followLatest = true
    @State private var viewport: CGFloat = 0
    @State private var keyboardUp = false
    @Environment(\.dynamicTypeSize) private var dts
    @Environment(\.kaikuStaticLayout) private var staticLayout

    public init() { _model = State(initialValue: TalkModel()) }
    /// The same call on another surface (a panel beside the main window): hand the model in.
    init(model: TalkModel) { _model = State(initialValue: model) }

    /// Kaiku is the centre of the call; it makes room once there are words to read or a keyboard to type on.
    var mascotSize: CGFloat {
        if keyboardUp { return KaikuTokens.Size.mascotS }
        return model.lines.isEmpty ? KaikuTokens.Size.mascotL * 0.8 : KaikuTokens.Size.mascotM
    }

    var mascotState: MascotState {
        guard model.hasLive else { return model.mode == .connecting ? .thinking : (model.expression ?? app.ambientState) }
        switch model.status {
        case .connecting, .thinking: return .thinking
        case .speaking: return .speaking
        case .paused: return .sleepy
        case .listening: return model.mode == .listening ? .listening : (model.expression ?? app.ambientState)
        case .muted, .micOff: return model.expression ?? app.ambientState
        }
    }

    public var body: some View {
        KScreen(nil, scrolls: false, maxWidth: KaikuTokens.Size.contentMax, spacing: KaikuTokens.Space.s3) {
            kaiku
            transcript
            if let card = model.activityCard {
                ActivityCardView(card: card, open: { model.openCard() }, putAside: { model.putCardAside() })
            }
            footer
        }
        .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast), value: model.activityCard)
        .sheet(isPresented: $showPairing) {
            PairStep(back: { showPairing = false }, next: { showPairing = false; model.restart() })
                .environment(app)
        }
        .onAppear {
            VoiceLines.shared.chat("talk", showing: true)
            model.app = app   // "Call Kaiku" works before any call was opened here
            if governsCall { model.screenAppeared() }
        }
        // Opening this screen does not open a call (2026-11-15): Kaiku never starts talking because a tab was
        // shown. "Call Kaiku" starts it, or a press elsewhere that asked for exactly this (`app.talkAsked`).
        .task {
            let asked = app.talkAsked || Self.launchStarts
            app.talkAsked = false
            if !staticLayout, asked { await model.start(app: app) }
        }
        .onDisappear {
            VoiceLines.shared.chat("talk", showing: false)
            if governsCall { model.screenDisappeared() } else { model.stop() }
        }
        .onChange(of: app.pairing) { _, _ in model.stop(); text = "" }
        // No call: nothing to type into. A call without the microphone: typing is the way to talk, so it is open.
        .onChange(of: model.hasLive, initial: true) { _, live in typing = live && !model.conversation.listens }
        .onChange(of: phase) { _, p in
            bgTask?.cancel()
            if p == .background { bgTask = Task { await model.backgrounded() } }
            // Back in front: a call that ended while the app was away is not opened again by itself; the
            // screen shows "Call Kaiku".
        }
    }

    /// Test, demo and picture runs open the call as the screen appears (`-kaikuTalkStart YES`, a Talk demo, or
    /// lines to type): there is nobody to press "Call Kaiku". Never in a release build.
    static var launchStarts: Bool {
        #if DEBUG
        let d = UserDefaults.standard
        return d.bool(forKey: "kaikuTalkStart") || TalkDemo.state != nil || d.bool(forKey: "kaikuInspectOnly")
            || d.string(forKey: "kaikuTalkSay") != nil || d.string(forKey: "kaikuTalkSayLater") != nil
        #else
        return false
        #endif
    }

    /// On the iPhone and iPad this screen owns its call: it starts while the screen is showing and ends when it
    /// goes. On the Mac the model is the one quick talk shares, which runs without this window.
    private var governsCall: Bool {
        #if os(macOS)
        return false
        #else
        return true
        #endif
    }

    // MARK: Kaiku — the centre of the call

    private var kaiku: some View {
        ZStack {
            if model.micOn { ListeningRing(size: mascotSize + KaikuTokens.Space.s3, active: model.mode == .listening) }
            MascotView(state: mascotState, size: mascotSize, tappable: false)
        }
        .frame(height: mascotSize + KaikuTokens.Space.s4)
        .frame(maxWidth: .infinity)
        .accessibilityHidden(true)
        .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base), value: mascotSize)
    }

    // MARK: the call bar, or the one line and the one action a state needs

    @ViewBuilder private var footer: some View {
        if model.hasLive {
            if typing {
                Composer(text: $text, placeholder: T("talk.type")) {
                    followLatest = true
                    model.send(text)
                    text = ""
                }
            }
            CallBar(since: model.conversation.liveSince, status: model.status, micOn: model.micOn, voiceMuted: model.voiceMuted,
                    typing: typing, level: { [conversation = model.conversation] in CallStatus.level(db: conversation.level) },
                    toggleMic: micAction, toggleVoice: { model.toggleVoice() },
                    toggleTyping: { typing.toggle() }, end: { model.end() })
        } else {
            let s = Self.idleState(mode: model.mode, reason: model.conversation.unavailableReason, paired: app.isPaired,
                                   hasLines: !model.lines.isEmpty, everLive: model.everLive)
            VStack(spacing: KaikuTokens.Space.s3) {
                Text(T(s.line)).kText(.callout, weight: .medium).foregroundStyle(KaikuTokens.Colors.ink)
                    .multilineTextAlignment(.center).wraps().accessibilityIdentifier("call.line")
                if let action = s.action {
                    Button { idle(action) } label: { Label(T(action.title), systemImage: action.symbol) }
                        .buttonStyle(.kPrimary).accessibilityIdentifier("call.action")
                }
            }
            .frame(maxWidth: .infinity)
        }
    }

    enum IdleAction: Equatable {
        case call, retry, connect, settings
        var title: String { ["call.start", "call.retry", "talk.voice.connect", "talk.voice.settings"][[.call, .retry, .connect, .settings].firstIndex(of: self)!] }
        var symbol: String { self == .connect ? "antenna.radiowaves.left.and.right" : self == .settings ? "gearshape.fill" : "phone.fill" }
    }

    /// With no call open: the one short line and the one action for the state (pure; tested).
    static func idleState(mode: TalkModel.Mode, reason: Conversation.UnavailableReason?, paired: Bool, hasLines: Bool,
                          everLive: Bool) -> (line: String, action: IdleAction?) {
        if mode == .connecting { return ("talk.connecting", nil) }
        if !paired || reason == .pairing { return ("call.line.unpaired", .connect) }
        if mode == .denied || reason == .microphone { return ("talk.unavailable.microphone", .settings) }
        if reason == .paused { return ("call.line.paused", nil) }
        if let note = stateNote(reason: reason, scripted: mode == .scripted, paired: paired, hasLines: hasLines, everLive: everLive) {
            return (note, .retry)
        }
        switch reason {
        case .connection?: return ("call.line.connection", .retry)
        case .voice?: return ("call.line.voice", .retry)
        case .audio?: return ("call.line.audio", .retry)
        default: return (mode == .ended ? "call.ended" : "call.line.ready", .call)
        }
    }

    private func idle(_ action: IdleAction) {
        switch action {
        case .connect: showPairing = true
        case .settings: openMicSettings()
        case .call, .retry: model.restart()
        }
    }

    /// Mute me. Without microphone permission there is nothing to unmute: the button leads to Settings.
    private func micAction() {
        if model.conversation.listens { model.toggleMic() } else { openMicSettings() }
    }

    private func openMicSettings() {
        #if os(iOS)
        if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
        #else
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") { openURL(url) }
        #endif
    }

    // MARK: captions — the words of the two of you, pinned to the newest line

    @ViewBuilder private var transcript: some View {
        if staticLayout {
            // Snapshots (ImageRenderer) cannot draw a ScrollView: the newest lines, laid out flat.
            VStack(spacing: KaikuTokens.Space.s2) {
                ForEach(model.lines.suffix(4)) { l in Bubble(l.text, from: l.me ? .me : .kaiku, maxWidth: bubbleMax) }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
        } else {
            scrollingTranscript
        }
    }

    private var scrollingTranscript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                // A plain VStack on purpose (a conversation is a few dozen short lines). The earlier LazyVStack
                // with an onAppear/onDisappear sentinel made the app hang: each appear/disappear wrote view state,
                // which rebuilt the lazy stack, which toggled the sentinel again. Following is derived from
                // geometry with a dead band.
                VStack(spacing: KaikuTokens.Space.s2) {
                    ForEach(model.lines) { l in
                        Bubble(l.text, from: l.me ? .me : .kaiku, maxWidth: bubbleMax, footnote: l.interrupted ? T("talk.interrupted.label") : nil)
                            .textSelection(.enabled)
                            .id(l.id)
                    }
                    if model.mode == .thinking { TypingDots().frame(maxWidth: .infinity, alignment: .leading) }
                    Color.clear.frame(height: 1).id(Self.bottom)
                        .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named(Self.scrollSpace)).minY } action: { y in
                            let next = TalkFollow.next(current: followLatest, sentinelY: y, viewport: viewport,
                                                       hasLines: !model.lines.isEmpty)
                            if next != followLatest { followLatest = next }
                        }
                }
                .padding(.vertical, KaikuTokens.Space.s2)
            }
            .coordinateSpace(.named(Self.scrollSpace))
            .defaultScrollAnchor(.bottom)
            .scrollDismissesKeyboard(.interactively)
            .frame(maxHeight: .infinity)
            .overlay(alignment: .bottomTrailing) {
                if !followLatest {
                    Button(T("talk.latest")) {
                        followLatest = true
                        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { proxy.scrollTo(Self.bottom, anchor: .bottom) }
                    }.buttonStyle(KButtonStyle(.secondary, fullWidth: false)).padding(KaikuTokens.Space.s2)
                }
            }
            .onGeometryChange(for: CGSize.self) { $0.size } action: { size in
                if abs(size.width - columnWidth) > 0.5 { columnWidth = size.width }
                if abs(size.height - viewport) > 0.5 { viewport = size.height }
            }
            .onChange(of: model.lines) { _, _ in toBottom(proxy) }
            .onChange(of: model.mode) { _, _ in toBottom(proxy) }
            .onChange(of: model.conversation.planCount) { _, _ in model.planArrived(); toBottom(proxy) }
            #if os(iOS)
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in
                if !keyboardUp { keyboardUp = true }
            }
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
                if keyboardUp { keyboardUp = false }
            }
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardDidShowNotification)) { _ in
                followLatest = true
                toBottom(proxy, animated: false)
            }
            .onChange(of: viewport) { _, _ in toBottom(proxy, animated: false) }
            #endif
        }
    }

    private static let scrollSpace = "talk.scroll"

    /// "The connection dropped" is only said after a conversation really was live (pure; tested). nil = the
    /// state's own line says it.
    static func stateNote(reason: Conversation.UnavailableReason?, scripted: Bool, paired: Bool, hasLines: Bool,
                          everLive: Bool) -> String? {
        guard scripted, paired else { return nil }
        switch reason {
        case .connection?, .voice?, .audio?: return hasLines && everLive ? "talk.unavailable.dropped" : nil
        default: return nil
        }
    }

    private static let bottom = "talk.bottom"

    private var bubbleMax: CGFloat {
        let w = columnWidth > 0 ? columnWidth : 600
        return dts.isAccessibilitySize ? w * 0.92 : w * 0.8
    }

    private func toBottom(_ proxy: ScrollViewProxy, animated: Bool = true) {
        guard followLatest else { return }
        if animated {
            withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { proxy.scrollTo(Self.bottom, anchor: .bottom) }
        } else {
            proxy.scrollTo(Self.bottom, anchor: .bottom)
        }
    }
}

enum TalkFollow {
    static let near: CGFloat = 48
    static let far: CGFloat = 120
    static func next(current: Bool, sentinelY: CGFloat, viewport: CGFloat, hasLines: Bool) -> Bool {
        guard hasLines, viewport > 0 else { return true }
        let below = sentinelY - viewport          // how far the end of the conversation is below the visible area
        if below <= near { return true }
        if below >= far { return false }
        return current
    }
}

/// A thin breathing ring around the header Kaiku while the mic is open (no filled panel).
struct ListeningRing: View {
    let size: CGFloat
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: rm || !active)) { tl in
            let t = tl.date.timeIntervalSinceReferenceDate
            let pulse = rm || !active ? 0.5 : 0.5 + 0.5 * sin(t * 2.4)
            Circle()
                .strokeBorder(KaikuTokens.Colors.clay.opacity(0.35 + 0.4 * pulse), lineWidth: 2.5)
                .frame(width: size, height: size)
                .scaleEffect(1 + 0.04 * pulse)
        }
        .accessibilityHidden(true)
    }
}

/// Three soft dots while Kaiku thinks (the header Kaiku already shows it's thinking).
struct TypingDots: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20, paused: rm)) { tl in
            let t = tl.date.timeIntervalSinceReferenceDate
            HStack(spacing: KaikuTokens.Space.s1) {
                ForEach(0..<3, id: \.self) { i in
                    Circle().fill(KaikuTokens.Colors.muted)
                        .frame(width: KaikuTokens.Space.s2, height: KaikuTokens.Space.s2)
                        .opacity(rm ? 0.7 : 0.35 + 0.65 * (0.5 + 0.5 * sin(t * 4 - Double(i) * 0.8)))
                }
            }
            .padding(.horizontal, KaikuTokens.Space.s3)
            .padding(.vertical, KaikuTokens.Space.s3)
            .background(Capsule().fill(KaikuTokens.Colors.surface))
        }
        .accessibilityLabel(T("talk.thinking"))
    }
}


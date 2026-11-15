import SwiftUI
#if os(macOS)
import AppKit
#endif

// The "Kaiku bot" tab: what the robot at home hears and does, live, from its own message bus on the home network
// (`BotModel`, `BotBusClient`). Read-only, except the "Robot microphone" switch (D56). Listening starts
// when the tab is on screen and the app is in front, and stops when either ends. Nothing heard is stored.

public struct BotView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.scenePhase) private var phase
    @Environment(\.dismiss) private var dismiss
    @State private var model = BotModel.shared
    @State private var filter: BotKind? = nil
    /// "Where the robot is": nil = open only while there is something to fix (no address, nobody answers, refused).
    @State private var showSetup: Bool? = nil
    @State private var showAll = UserDefaults.standard.string(forKey: "kaikuBotScroll") != nil
    private var setupOpen: Bool {
        showSetup ?? (model.address == nil || model.link == .unreachable || model.link == .refused)
    }
    /// iPhone: a screen under You (back + title); Mac: a tab root (page header).
    let pushed: Bool
    public init(pushed: Bool = false) { self.pushed = pushed }

    public var body: some View {
        ScrollViewReader { proxy in
        TimelineView(.periodic(from: .now, by: 1)) { tick in
            KScreen(T("bot.title"), subtitle: T("bot.sub"), back: pushed ? { dismiss() } : nil, maxWidth: KaikuTokens.Size.paneMax) {
                if pushed { Text(T("bot.sub")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps() }
                // Three things on top, always: is the robot there, this device as its microphone, what it is doing.
                // Where the robot is and everything it sends are one tap away, closed until asked for.
                BotConnectionCard(model: model, now: tick.date, part: .status)
                BotRobotMicCard(model: model, now: tick.date).id("robotmic")
                if model.state.messages > 0 { BotNowCard(state: model.state, now: tick.date).id("now") }
                BotMore(title: T("bot.more.setup"), detail: T("bot.more.setup.d"), open: setupOpen, id: "bot.more.setup") { showSetup = !setupOpen }
                if setupOpen { BotConnectionCard(model: model, now: tick.date, part: .details).id("robot") }
                if model.state.messages > 0 {
                    BotMore(title: T("bot.more.all"), detail: T("bot.more.all.d"), open: showAll, id: "bot.more.all") { showAll.toggle() }
                    if showAll {
                        KAdaptiveColumns(minWidth: 640, spacing: KaikuTokens.Space.s5, leadingFraction: 0.5, stack: KaikuTokens.Space.s5) {
                            BotSensesCard(state: model.state, now: tick.date).id("senses")
                            BotRecordsCard(state: model.state, now: tick.date).id("records")
                        } trailing: {
                            BotVoiceCard(state: model.state, now: tick.date).id("voice")
                        }
                        BotFeedCard(model: model, filter: $filter, now: tick.date).id("feed")
                    }
                }
            }
        }
        #if DEBUG
        .task {   // `-kaikuBotScroll now|senses|voice|records|feed`: pictures of the rest of the page (iPhone)
            guard let to = UserDefaults.standard.string(forKey: "kaikuBotScroll") else { return }
            try? await Task.sleep(nanoseconds: 2_500_000_000)
            proxy.scrollTo(to, anchor: .top)
        }
        #endif
        }
        .onAppear {
            model.configure(serviceURL: app.pairing?.baseURL, home: app.pairing?.homeID)
            model.setInFront(Self.inFront(phase))
            model.setVisible(true)
            #if DEBUG
            // `-kaikuBotMic YES`: a bench run starts with "Robot microphone" on (the permission must already be given)
            if UserDefaults.standard.bool(forKey: "kaikuBotMic") { Task { await model.setMic(true) } }
            #endif
        }
        .onDisappear { model.setVisible(false) }
        .onChange(of: app.pairingRevision) { _, _ in model.configure(serviceURL: app.pairing?.baseURL, home: app.pairing?.homeID) }
        .onChange(of: phase) { _, p in model.setInFront(Self.inFront(p)) }
        #if os(macOS)
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didResignActiveNotification)) { _ in
            if !AppPresence.pictureRun { model.setInFront(false) }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in model.setInFront(true) }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.screensDidSleepNotification)) { _ in model.setInFront(false) }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.sessionDidResignActiveNotification)) { _ in model.setInFront(false) }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.screensDidWakeNotification)) { _ in
            if NSApp?.isActive == true { model.setInFront(true) }
        }
        #endif
    }

    /// iPhone: the scene is active. Mac: the app is active (a picture run is never active, and only looks).
    static func inFront(_ phase: ScenePhase) -> Bool {
        #if os(macOS)
        if AppPresence.pictureRun { return true }
        return phase == .active && (NSApp?.isActive ?? true)
        #else
        return phase == .active
        #endif
    }
}

// MARK: little shared pieces

/// "3 s ago", "2 min ago", or the time of day for anything older than an hour.
enum BotTime {
    static func ago(_ d: Date?, now: Date) -> String {
        guard let d else { return T("bot.never") }
        let s = max(0, Int(now.timeIntervalSince(d)))
        if s < 2 { return T("bot.now") }
        if s < 60 { return T("bot.ago.s", ["n": String(s)]) }
        if s < 3600 { return T("bot.ago.min", ["n": String(s / 60)]) }
        return clock(d)
    }

    static func clock(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.shared.language.rawValue)
        f.setLocalizedDateFormatFromTemplate("HHmmss")
        return f.string(from: d)
    }
}

/// A label + value line inside a card (the value wraps under the label at large text).
struct BotFact: View {
    let label: String
    let value: String
    var detail: String? = nil
    @Environment(\.dynamicTypeSize) private var dts
    var body: some View {
        let layout = dts.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: KaikuTokens.Space.s1))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: KaikuTokens.Space.s3))
        layout {
            Text(label).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
            if !dts.isAccessibilitySize { Spacer(minLength: KaikuTokens.Space.s2) }
            VStack(alignment: dts.isAccessibilitySize ? .leading : .trailing, spacing: 0) {
                Text(value).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                    .multilineTextAlignment(dts.isAccessibilitySize ? .leading : .trailing).wraps()
                if let detail { Text(detail).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: 1 · connection

struct BotConnectionCard: View {
    /// status = the connection line and the robot's parts; details = the address and the sign-in.
    enum Part { case status, details }
    let model: BotModel
    let now: Date
    let part: Part
    @State private var typed = ""
    @State private var bad = false
    @State private var signIn = false

    private var status: (icon: String, tone: KTone, title: String) {
        if model.replaying { return ("play.circle", .sky, T("bot.link.replay")) }
        switch model.link {
        case .listening:
            return model.state.parts.isEmpty && model.heardSinceConnect == 0
                ? ("dot.radiowaves.left.and.right", .sky, T("bot.link.quiet"))
                : ("dot.radiowaves.left.and.right", .sage, T("bot.link.listening"))
        case .connecting: return ("ellipsis.circle", .sky, T("bot.link.connecting"))
        case .unreachable: return ("wifi.slash", .ink, T("bot.link.notfound"))
        case .refused: return ("lock", .honey, T("bot.link.refused"))
        case .idle: return model.address == nil ? ("questionmark.circle", .ink, T("bot.link.noaddress")) : ("pause.circle", .ink, T("bot.link.idle"))
        }
    }

    var body: some View {
        if part == .status {
            KSection {
                statusRow
                if model.link == .unreachable && model.state.messages == 0 && !model.replaying {
                    Text(T("bot.empty")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                        .padding(.horizontal, KaikuTokens.Space.s4).padding(.bottom, KaikuTokens.Space.s3)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                ForEach(partKeys, id: \.self) { key in
                    if let part = model.state.parts[key] {
                        KDivider()
                        BotPartRow(name: key, part: part, now: now)
                    }
                }
            }
        } else {
            KSection {
                addressRow
                if signIn || model.link == .refused {
                    KDivider(plain: true)
                    BotSignIn(model: model)
                }
            }
        }
    }

    private var partKeys: [String] {
        let known = ["head", "sensors", "hub", "friendlink"]
        return known.filter { model.state.parts[$0] != nil } + model.state.parts.keys.sorted().filter { !known.contains($0) }
    }

    private var statusRow: some View {
        let s = status
        return KRow(icon: s.icon, tint: s.tone.ink, title: s.title,
                    detail: model.address.map { T(model.addressGuessed ? "bot.address.guess" : "bot.address", ["address": $0.text]) }
                        ?? T("bot.address.none"),
                    accessory: .none)
            .accessibilityIdentifier("bot.link")
    }

    @ViewBuilder private var addressRow: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            Text(T("bot.address.label")).kText(.caption, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink2)
            HStack(spacing: KaikuTokens.Space.s2) {
                TextField(T("bot.address.placeholder"), text: $typed)
                    .textFieldStyle(.plain)
                    .kText(.body)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    #endif
                    .padding(.horizontal, KaikuTokens.Space.s3)
                    .frame(minHeight: KaikuTokens.Size.tapMin)
                    .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.surface2))
                    .onSubmit(apply)
                    .accessibilityLabel(T("bot.address.label"))
                    .accessibilityIdentifier("bot.address")
                Button(T("bot.address.use"), action: apply)
                    .buttonStyle(KButtonStyle(.secondary, fullWidth: false))
                    .accessibilityIdentifier("bot.address.use")
            }
            if bad { Text(T("bot.address.bad")).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink2).wraps() }
            Button(signIn ? T("bot.signin.hide") : T("bot.signin.show")) { signIn.toggle() }
                .buttonStyle(.plain)
                .kText(.caption, weight: .semibold)
                .foregroundStyle(KaikuTokens.Colors.clay)
                .frame(minHeight: KaikuTokens.Size.tapMin, alignment: .leading)
                .kPointer()
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .onAppear { if typed.isEmpty { typed = model.addressGuessed ? "" : (model.address?.text ?? "") } }
    }

    private func apply() {
        bad = !model.setAddress(typed)
    }
}

struct BotPartRow: View {
    let name: String
    let part: BotState.Part
    let now: Date
    var body: some View {
        HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
            KRow(icon: Self.icon(name), tint: part.status == "down" ? KaikuTokens.Colors.muted : KaikuTokens.Colors.sage,
                 title: BotWords.part(name), detail: detail, accessory: .none)
            if part.sim { KChip(T("common.simulated"), tone: .ink).padding(.trailing, KaikuTokens.Space.s4) }
        }
        .accessibilityElement(children: .combine)
    }

    private var detail: String {
        var bits = [T("bot.part.seen", ["when": BotTime.ago(part.lastSeen, now: now)])]
        if part.status == "down" { bits.append(T("bot.part.down")) } else if part.status == "degraded" { bits.append(T("bot.part.degraded")) }
        if let v = part.version { bits.append(T("bot.part.version", ["v": v])) }
        if part.firmware == "standalone" { bits.append(T("bot.part.standalone")) }
        return bits.joined(separator: " · ")
    }

    static func icon(_ name: String) -> String {
        switch name {
        case "head": return "face.smiling"
        case "sensors": return "sensor"
        case "hub": return "cpu"
        case "friendlink": return "lamp.table"
        default: return "circle.dotted"
        }
    }
}

struct BotSignIn: View {
    let model: BotModel
    @State private var user = ""
    @State private var password = ""
    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            Text(T("bot.signin.d")).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            field(TextField(T("bot.signin.user"), text: $user))
            field(SecureField(model.hasPassword ? T("bot.signin.password.kept") : T("bot.signin.password"), text: $password))
            Button(T("bot.signin.save")) {
                model.setSignIn(user: user, password: password.isEmpty ? nil : password)
                password = ""
            }
            .buttonStyle(KButtonStyle(.secondary, fullWidth: false))
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .onAppear { user = model.user }
    }

    private func field(_ f: some View) -> some View {
        f.textFieldStyle(.plain)
            .kText(.body)
            .autocorrectionDisabled()
            #if os(iOS)
            .textInputAutocapitalization(.never)
            #endif
            .padding(.horizontal, KaikuTokens.Space.s3)
            .frame(minHeight: KaikuTokens.Size.tapMin)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.surface2))
    }
}

/// Connected, and nothing has come yet: one plain sentence.
struct BotQuietCard: View {
    var body: some View {
        KCard(tone: .sky) {
            Text(T("bot.quiet")).kText(.body).foregroundStyle(KaikuTokens.Colors.ink).wraps()
        }
    }
}

/// One line that opens or closes the cards under it.
struct BotMore: View {
    let title: String
    let detail: String
    let open: Bool
    let id: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink)
                    Text(detail).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                }
                Spacer(minLength: KaikuTokens.Space.s2)
                Image(systemName: open ? "chevron.up" : "chevron.down").foregroundStyle(KaikuTokens.Colors.muted)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, KaikuTokens.Space.s4)
            .frame(minHeight: KaikuTokens.Size.tapMin)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .kPointer()
        .accessibilityValue(T(open ? "bot.more.open" : "bot.more.closed"))
        .accessibilityIdentifier(id)
    }
}

// MARK: this device as the robot's microphone (D56)

/// The one switch on this page that sends something: this iPhone or Mac, put beside the robot, is its microphone.
struct BotRobotMicCard: View {
    let model: BotModel
    let now: Date

    var body: some View {
        KSection(T("bot.robotmic.sec"), subtitle: T("bot.robotmic.sec.d"), icon: "mic", tone: .sage) {
            KToggleRow(icon: model.micOn ? "mic.fill" : "mic", title: T("bot.robotmic.t"), detail: status,
                       isOn: Binding(get: { model.micOn }, set: { on in Task { await model.setMic(on) } }))
                .accessibilityIdentifier("bot.robotmic")
        }
    }

    private var status: String {
        if model.micFailed { return T("bot.robotmic.failed") }
        guard model.micOn else { return T("bot.robotmic.off") }
        if model.link != .listening { return T("bot.robotmic.nolink") }
        if let at = model.micSentAt, now.timeIntervalSince(at) < 2 { return T("bot.robotmic.sending") }
        return T(model.state.micHeld(now: now) ? "bot.robotmic.speaking" : "bot.robotmic.waiting")
    }
}

// MARK: 2 · now

struct BotNowCard: View {
    let state: BotState
    let now: Date

    var body: some View {
        KSection(T("bot.sec.now"), subtitle: T("bot.sec.now.d"), icon: "sparkles", tone: .clay) {
            BotMicRow(open: state.micOpen(now: now), held: state.micHeldAt.map { now.timeIntervalSince($0) < 10 } ?? false)
            if state.helpOn(now: now) {
                KDivider()
                KRow(icon: "phone.circle", tint: KaikuTokens.Colors.sky, title: T("bot.help.shown"), detail: T("bot.help.shown.d"), accessory: .none)
            }
            KDivider(plain: true)
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                BotFact(label: T("bot.now.step"), value: BotWords.step(state.step), detail: state.stepAt.map { BotTime.ago($0, now: now) })
                if let mode = state.headMode { BotFact(label: T("bot.now.mode"), value: T(mode == "follow" ? "bot.mode.follow" : "bot.mode.drive")) }
                BotFact(label: T("bot.now.eyes"), value: state.eyes.map(BotWords.eyes) ?? T("bot.unknown"))
                BotFact(label: T("bot.now.light"), value: state.chest.map(BotWords.chest) ?? T("bot.unknown"))
                BotFact(label: T("bot.now.move"), value: movement)
            }
            .padding(KaikuTokens.Space.s4)
        }
    }

    private var movement: String {
        var bits: [String] = []
        if let m = state.panMode { bits.append(BotWords.panMode(m)) }
        if let b = state.bpm, state.panMode == "sway" || state.chest == "pulse" || state.chest == "breathe" {
            bits.append(T("bot.feed.bpm", ["n": BotWords.whole(b)]))
        }
        if let d = state.panDeg { bits.append(T(state.moving == true ? "bot.feed.pan.moving" : "bot.feed.pan", ["n": BotWords.whole(d)])) }
        return bits.isEmpty ? T("bot.unknown") : bits.joined(separator: " · ")
    }
}

/// The robot's microphone, said plainly and first: open or closed, and who holds it.
struct BotMicRow: View {
    let open: Bool?
    let held: Bool
    var body: some View {
        HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
            Image(systemName: open == true ? "mic.fill" : "mic.slash")
                .kText(.title3, weight: .semibold)
                .foregroundStyle(open == true ? KaikuTokens.Colors.clay : KaikuTokens.Colors.muted)
                .frame(width: KaikuTokens.Size.iconTile + KaikuTokens.Space.s3, height: KaikuTokens.Size.iconTile + KaikuTokens.Space.s3)
                .background(Circle().fill(open == true ? KaikuTokens.Colors.claySoft : KaikuTokens.Colors.surface2))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                Text(T(open == true ? "bot.mic.open" : open == false ? "bot.mic.closed" : "bot.mic.unknown"))
                    .kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                Text(T(open == true ? (held ? "bot.mic.open.d" : "bot.mic.open.head") : open == false ? "bot.mic.closed.d" : "bot.mic.unknown.d"))
                    .kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(KaikuTokens.Space.s4)
        .background(open == true ? KaikuTokens.Colors.claySoft.opacity(0.35) : Color.clear)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("bot.mic")
    }
}

// MARK: 3 · senses

struct BotSensesCard: View {
    let state: BotState
    let now: Date

    var body: some View {
        KSection(T("bot.sec.senses"), subtitle: T("bot.sec.senses.d"), icon: "hand.tap", tone: .honey) {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s4) {
                HStack(alignment: .top, spacing: KaikuTokens.Space.s4) {
                    BotEar(state: state, now: now).frame(maxWidth: .infinity, alignment: .leading)
                    BotTaps(state: state, now: now).frame(maxWidth: .infinity, alignment: .leading)
                }
                KDivider(plain: true).padding(.leading, -KaikuTokens.Space.s4)
                BotCamera(state: state, now: now)
                KDivider(plain: true).padding(.leading, -KaikuTokens.Space.s4)
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                    BotFact(label: T("bot.pulse"), value: pulse, detail: pulseDetail)
                    BotFact(label: T("bot.button"), value: state.buttonAt == nil ? T("bot.never")
                            : T(state.buttonPressed == true ? "bot.button.pressed" : "bot.button.released"),
                            detail: state.buttonAt.map { BotTime.ago($0, now: now) })
                }
            }
            .padding(KaikuTokens.Space.s4)
        }
    }

    private var pulse: String {
        if let at = state.pulseSamplesAt, now.timeIntervalSince(at) < 3 { return T("bot.pulse.reading") }
        if state.pulseAsked == true { return T("bot.pulse.asked") }
        if let hr = state.hr { return T("bot.pulse.result", ["bpm": BotWords.whole(hr)]) }
        return T("bot.pulse.off")
    }

    private var pulseDetail: String? {
        guard let hr = state.hr, let at = state.hrvAt else { return nil }
        var bits = [T("bot.pulse.result", ["bpm": BotWords.whole(hr)])]
        if let r = state.rmssd { bits.append(T("bot.pulse.rmssd", ["n": BotWords.whole(r)])) }
        if let b = state.breath { bits.append(T("bot.pulse.breath", ["n": BotWords.whole(b)])) }
        return bits.joined(separator: " · ") + " · " + BotTime.ago(at, now: now)
    }
}

struct BotEar: View {
    let state: BotState
    let now: Date
    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
            Text(T("bot.ear")).kText(.caption, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink2)
            Text(state.ear.map(String.init) ?? "–").kText(.title1, weight: .bold).foregroundStyle(KaikuTokens.Colors.ink)
                .contentTransition(.numericText())
            Text(state.earPressedAt.map { T("bot.ear.pressed", ["when": BotTime.ago($0, now: now)]) }
                 ?? (state.earAt.map { T("bot.ear.turned", ["when": BotTime.ago($0, now: now)]) } ?? T("bot.ear.none")))
                .kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps()
        }
        .accessibilityElement(children: .combine)
    }
}

/// A dot that lights on every tap (Reduce Motion: it changes colour, it does not grow) and the tempo of the last few.
struct BotTaps: View {
    let state: BotState
    let now: Date
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        let recent = state.taps.last.map { now.timeIntervalSince($0) < 1 } ?? false
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
            Text(T("bot.taps")).kText(.caption, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink2)
            HStack(spacing: KaikuTokens.Space.s2) {
                Circle()
                    .fill(recent ? KaikuTokens.Colors.honey : KaikuTokens.Colors.surface2)
                    .frame(width: KaikuTokens.Space.s4, height: KaikuTokens.Space.s4)
                    .scaleEffect(recent && !reduce ? 1.25 : 1)
                    .animation(reduce ? nil : .easeOut(duration: KaikuTokens.Feedback.release), value: state.tapCount)
                    .accessibilityHidden(true)
                Text(state.tapTempo.map { T("bot.taps.tempo", ["n": BotWords.whole($0)]) } ?? (state.tapCount == 0 ? "–" : T("bot.taps.n", ["n": String(state.tapCount)])))
                    .kText(.title3, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            }
            Text(state.tapCount == 0 ? T("bot.taps.none") : T("bot.taps.count", ["n": String(state.tapCount), "when": BotTime.ago(state.taps.last, now: now)]))
                .kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps()
        }
        .accessibilityElement(children: .combine)
    }
}

/// The robot's camera as the numbers it sends: a frame with a dot where a face is, bigger when nearer.
struct BotCamera: View {
    let state: BotState
    let now: Date
    var body: some View {
        let inView = state.someoneInView(now: now)
        let face = inView == true ? state.face : nil
        HStack(alignment: .top, spacing: KaikuTokens.Space.s4) {
            GeometryReader { g in
                let w = g.size.width, h = g.size.height
                ZStack {
                    RoundedRectangle(cornerRadius: KaikuTokens.Radius.sm, style: .continuous).fill(KaikuTokens.Colors.surface2)
                    RoundedRectangle(cornerRadius: KaikuTokens.Radius.sm, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1)
                    if let face {
                        let d = max(KaikuTokens.Space.s3, min(h * 0.9, (KaikuTokens.Space.s3 + face.size * h)))
                        Circle()
                            .fill(KaikuTokens.Colors.honey.opacity(0.85))
                            .frame(width: d, height: d)
                            .position(x: w / 2 + face.x * (w / 2 - d / 2), y: h / 2 + face.y * (h / 2 - d / 2))
                    }
                }
            }
            .aspectRatio(4.0 / 3.0, contentMode: .fit)
            .frame(maxWidth: KaikuTokens.Size.mascotM + KaikuTokens.Space.s6)
            .accessibilityElement()
            .accessibilityLabel(T("bot.camera"))
            .accessibilityValue(face.map { BotWords.face($0) } ?? T("bot.camera.nobody"))
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                Text(T("bot.camera")).kText(.caption, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink2)
                Text(T(inView == true ? "bot.camera.someone" : inView == false ? "bot.camera.nobody" : "bot.camera.unknown"))
                    .kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                if let face { Text(BotWords.face(face)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
                if let cm = state.distanceCm, let at = state.distanceAt, now.timeIntervalSince(at) < 10 {
                    Text(BotWords.distance(cm)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
                if let lux = state.lux { Text(BotWords.light(lux)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        Text(T("bot.camera.note")).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
    }
}

// MARK: 4 · voice and mind

struct BotVoiceCard: View {
    let state: BotState
    let now: Date

    var body: some View {
        KSection(T("bot.sec.voice"), subtitle: T("bot.sec.voice.d"), icon: "bubble.left.and.text.bubble.right", tone: .sage) {
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
                BotFact(label: T("bot.voice.conversation"),
                        value: T(state.conversationOpen == true ? "bot.voice.open" : state.conversationOpen == false ? "bot.voice.closed" : "bot.voice.none"),
                        detail: state.conversationAt.map { BotTime.ago($0, now: now) })
                if state.said.isEmpty {
                    Text(T("bot.voice.nothing")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                } else {
                    ForEach(Array(state.said.prefix(3).enumerated()), id: \.offset) { _, s in
                        Bubble(s.text, footnote: [BotWords.by(s.by).map { T("bot.voice.how", ["how": $0]) }, BotTime.ago(s.at, now: now)]
                                .compactMap { $0 }.joined(separator: " · "))
                    }
                }
                BotFact(label: T("bot.voice.heard"), value: state.heard == 0 ? T("bot.never") : T("bot.voice.heard.n", ["n": String(state.heard)]),
                        detail: state.heardAt.map { BotTime.ago($0, now: now) })
                Text(T("bot.voice.heard.d")).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                if !state.tools.isEmpty {
                    Text(T("bot.voice.tools")).kText(.caption, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink2)
                    ForEach(Array(state.tools.prefix(4).enumerated()), id: \.offset) { _, t in
                        HStack(alignment: .firstTextBaseline, spacing: KaikuTokens.Space.s2) {
                            Text(BotWords.tool(t)).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Text(BotTime.ago(t.at, now: now)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
                if state.level != nil || state.songBpm != nil || state.band != nil {
                    KDivider(plain: true).padding(.leading, -KaikuTokens.Space.s4)
                    Text(T("bot.game")).kText(.caption, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink2)
                    BotFact(label: T("bot.game.song"), value: playing ? (state.songBpm.map { T("bot.feed.bpm", ["n": BotWords.whole($0)]) } ?? "–") : T("bot.game.quiet"),
                            detail: state.level.map { T("bot.game.level", ["n": String($0)]) })
                    BotFact(label: T("bot.game.turn"), value: turn)
                }
            }
            .padding(KaikuTokens.Space.s4)
        }
    }

    private var playing: Bool { state.music == "song" || state.music == "start" }

    private var turn: String {
        if let band = state.band, let at = state.bandAt, (state.yourTurnAt.map { at >= $0 } ?? true) {
            return T("bot.feed.band", ["band": BotWords.band(band)])
        }
        if let at = state.yourTurnAt, now.timeIntervalSince(at) < 30 { return T("bot.feed.yourturn") }
        return T("bot.game.listening")
    }
}

// MARK: 6 · records sent on

struct BotRecordsCard: View {
    let state: BotState
    let now: Date
    var body: some View {
        KSection(T("bot.sec.records"), subtitle: T("bot.sec.records.d"), icon: "arrow.up.doc", tone: .ink) {
            if state.records.isEmpty {
                Text(T("bot.records.none")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                    .padding(KaikuTokens.Space.s4).frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ForEach(Array(state.records.prefix(6).enumerated()), id: \.element.id) { i, r in
                    if i > 0 { KDivider(plain: true) }
                    BotLine(item: r, now: now)
                }
            }
        }
    }
}

// MARK: 5 · the feed

struct BotFeedCard: View {
    let model: BotModel
    @Binding var filter: BotKind?
    let now: Date

    private static let filters: [(BotKind?, String)] = [(nil, "bot.filter.all"), (.senses, "bot.filter.senses"), (.body, "bot.filter.body"),
                                                         (.voice, "bot.filter.voice"), (.records, "bot.filter.records")]

    var body: some View {
        let items = model.feed.filter { filter == nil || $0.kind == filter }
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                SectionHeader(T("bot.sec.feed"), subtitle: T("bot.sec.feed.d"), icon: "list.bullet", tone: .clay)
                    .frame(maxWidth: .infinity, alignment: .leading)
                IconButton(model.frozenFeed == nil ? "pause.fill" : "play.fill",
                           label: model.frozenFeed == nil ? T("bot.feed.pause") : T("bot.feed.resume")) {
                    model.pause(model.frozenFeed == nil)
                }
                .accessibilityIdentifier("bot.feed.pause")
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: KaikuTokens.Space.s2) {
                    ForEach(Self.filters, id: \.1) { kind, key in
                        let on = filter == kind
                        Button { filter = kind } label: {
                            Text(T(key)).kText(.footnote, weight: .semibold)
                                .foregroundStyle(on ? KaikuTokens.Colors.ink : KaikuTokens.Colors.ink2)
                                .padding(.horizontal, KaikuTokens.Space.s3)
                                .frame(minHeight: KaikuTokens.Size.tapMin)
                                .background(Capsule().fill(on ? KaikuTokens.Colors.surface : KaikuTokens.Colors.surface2))
                                .overlay(Capsule().strokeBorder(on ? KaikuTokens.Colors.clay : .clear, lineWidth: 1.5))
                                .contentShape(Capsule())
                        }
                        .buttonStyle(.plain)
                        .kPointer()
                        .accessibilityAddTraits(on ? .isSelected : [])
                    }
                }
            }
            if model.frozenFeed != nil {
                Text(T("bot.feed.paused", ["n": String(model.newWhilePaused)])).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            }
            VStack(spacing: 0) {
                if items.isEmpty {
                    Text(T("bot.feed.empty")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                        .padding(KaikuTokens.Space.s4).frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    LazyVStack(spacing: 0) {
                        ForEach(Array(items.prefix(80).enumerated()), id: \.element.id) { i, item in
                            if i > 0 { KDivider(plain: true) }
                            BotLine(item: item, now: now)
                        }
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous))
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
                .kaikuShadow(KaikuTokens.Elevation.card))
            .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
        }
    }
}

/// One feed line: time, which part, what happened, how many messages it stands for.
struct BotLine: View {
    let item: BotFeedItem
    let now: Date
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: KaikuTokens.Space.s3) {
            Text(BotTime.clock(item.at)).kText(.caption, mono: true).foregroundStyle(KaikuTokens.Colors.muted)
            VStack(alignment: .leading, spacing: 0) {
                Text(item.line).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                HStack(spacing: KaikuTokens.Space.s2) {
                    Text(BotWords.part(item.source)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted)
                    if item.count > 1 { Text(T("bot.feed.times", ["n": String(item.count)])).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted) }
                    if item.sim { Text(T("common.simulated")).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted) }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s2)
        .accessibilityElement(children: .combine)
    }
}

import SwiftUI

/// Walk with Kaiku (iPhone): one start with the way Kaiku walks with you (Calm · Playful · Chatty), Kaiku's voice
/// in the glasses (or the phone when they are not there), what both sides said, where the sound is going, whether
/// Kaiku can see, the spotting game while one is on, and a plain summary at the end. Every state that can go wrong
/// has words on this screen; the same states go to the glasses log (You → Glasses check).
public struct WalkView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    private var walk = WalkModel.shared
    public init() {}

    public var body: some View {
        KScreen(T("walk.title"), back: walk.active ? nil : { dismiss() }) {
            if walk.active {
                walking
            } else if walk.finished != nil {
                done
            } else {
                intro
            }
        }
        .onAppear {
            if app.defaultsAutostartWalk, !walk.active, walk.finished == nil { start() }
        }
    }

    private func start() { walk.begin(app: app, adapter: app.makeGlasses?()) }

    private var seeBinding: Binding<Bool> {
        Binding(get: { app.consents[.see] ?? false },
                set: { app.consents[.see] = $0; GlassesLog.shared.log("see_choice", ["on": $0]); Task { await walk.applyVision() } })
    }

    private var intro: some View {
        VStack(spacing: KaikuTokens.Space.s4) {
            MascotWithBubble(state: .walking, text: T("walk.intro"))
            WalkStylePicker()
            KSection {
                StatusLine(icon: "ear", ok: TalkAudio.headsetAvailable != nil,
                           text: TalkAudio.headsetAvailable.map { T("walk.ready.ear") + " " + $0 } ?? T("walk.ready.phone"))
                KDivider()
                StatusLine(icon: "eyeglasses", ok: app.glassesRegistered,
                           text: app.makeGlasses == nil ? T("walk.phone") : app.glassesRegistered ? T("walk.ready.glasses") : T("walk.glasses.setup"))
                KDivider()
                KToggleRow(icon: "eye", title: T("sig.see.t"), detail: T("sig.see.d"), isOn: seeBinding)
            }
            if !app.isPaired { OfflineBanner(T("walk.voice.pairing")) }
            Button(T("walk.start")) { start() }.buttonStyle(.kPrimary)
            NavigationLink(value: KaikuRoute.glasses) { Text(T("gc.title")) }.buttonStyle(.kGhost)
        }
    }

    private var walking: some View {
        VStack(spacing: KaikuTokens.Space.s4) {
            HStack(spacing: KaikuTokens.Space.s3) {
                MascotView(state: walk.goal?.done == true ? .happy : .walking, size: KaikuTokens.Size.mascotS, tappable: false)
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                    Text(voiceLabel).kText(.title2).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    TimelineView(.periodic(from: .now, by: 15)) { _ in
                        Text(T("walk.minutes", n: walk.minutes)).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            KSection {
                StatusLine(icon: walk.route.inTheEar ? "ear" : "speaker.wave.2", ok: walk.route.inTheEar, text: routeLabel)
                KDivider()
                GlassesLine(state: walk.glasses, idle: false, worn: walk.worn)
                if walk.seeAllowed {
                    KDivider()
                    HStack(spacing: KaikuTokens.Space.s2) {
                        StatusLine(icon: walk.camera == .streaming ? "eye.fill" : "eye.slash",
                                   ok: walk.camera == .streaming, text: cameraLabel)
                        if walk.camera == .streaming || walk.visionPaused {
                            Button(walk.visionPaused ? T("walk.see.resume") : T("walk.see.pause")) { walk.setVisionPaused(!walk.visionPaused) }
                                .buttonStyle(KButtonStyle(.secondary, fullWidth: false)).fixedSize()
                                .padding(.trailing, KaikuTokens.Space.s3)
                        }
                    }
                }
            }
            WalkStylePicker(showsLine: false)
            if let goal = walk.goal {
                WalkGoalCard(goal: goal) { walk.foundOne() }
                    .transition(.opacity.combined(with: .scale(scale: 0.97, anchor: .top)))
            }
            if let problem = voiceProblemText {
                OfflineBanner(problem)
                Button(T("walk.voice.again")) { walk.setTalking(true) }.buttonStyle(.kSecondary)
            }
            if let c = walk.companion, !c.lines.isEmpty { transcript(c) }
            if walk.talking {
                Button(walk.companionMuted ? T("walk.talk.unmute") : T("walk.talk.mute")) {
                    walk.setTalking(walk.companionMuted)
                }
                .buttonStyle(.kSecondary)
                .accessibilityHint(T("walk.talk.on"))
            } else if walk.goal == nil {
                // Without Kaiku's live voice the walk still has its small game: the fixed light hunt.
                Button(T("lh.found")) { walk.foundOne() }.buttonStyle(.kSecondary)
            }
            Button(T("lh.end")) { Task { await walk.end() } }.buttonStyle(.kPrimary)
        }
    }

    /// The last few things said, newest at the bottom. Words stay on this screen unless the person chose to keep them.
    private func transcript(_ c: Conversation) -> some View {
        VStack(spacing: KaikuTokens.Space.s2) {
            ForEach(c.lines.suffix(6)) { line in
                HStack {
                    if line.me { Spacer(minLength: KaikuTokens.Space.s5) }
                    Bubble(line.text, from: line.me ? .me : .kaiku)
                    if !line.me { Spacer(minLength: KaikuTokens.Space.s5) }
                }
            }
        }
        .accessibilityIdentifier("walk.transcript")
    }

    private var voiceLabel: String {
        guard let c = walk.companion else { return T("walk.voice.none") }
        switch c.phase {
        case .connecting: return T("walk.voice.connecting")
        case .listening: return T("walk.voice.listening")
        case .hearing: return T("walk.voice.hearing")
        case .thinking: return T("walk.voice.thinking")
        case .speaking: return T("walk.voice.speaking")
        case .muted: return T("walk.voice.muted")
        case .paused: return T("walk.voice.paused")
        case .idle, .unavailable: return T("walk.voice.none")
        }
    }

    private var voiceProblemText: String? {
        if let c = walk.companion, walk.companionEnded {
            return c.endedByLimit ? T("walk.voice.limit") : reason(c.unavailableReason)
        }
        if walk.companion == nil, let r = walk.voiceProblem { return reason(r) }
        return nil
    }

    private func reason(_ r: Conversation.UnavailableReason?) -> String {
        switch r {
        case .microphone: return T("walk.voice.mic")
        case .pairing: return T("walk.voice.pairing")
        case .voice: return T("walk.voice.novoice")
        case .audio: return T("walk.voice.audio")
        case .paused: return T("walk.voice.pausedall")
        case .connection, .none: return T("walk.voice.connection")
        }
    }

    private var routeLabel: String {
        let r = walk.route
        if !r.active { return T("walk.route.waiting") }
        if r.inTheEar { return T("walk.route.ear") + " " + r.output }
        if r.headsetOut { return T("walk.route.outonly") + " " + r.output }
        return T("walk.route.phone") + (r.output.isEmpty ? "" : " (" + r.output + ")")
    }

    private var cameraLabel: String {
        switch walk.camera {
        case .streaming: return T("walk.see.on", n: GlassesStatus.shared.framesSent)
        case .starting: return T("walk.see.starting")
        case .paused: return walk.visionPaused ? T("walk.see.paused") : (walk.cameraNote ?? T("walk.see.paused"))
        case .needsPermission: return T("walk.see.permission")
        case .failed: return T("walk.see.failed") + (walk.cameraNote.map { " " + $0 } ?? "")
        case .off: return walk.talking ? T("walk.see.waiting") : T("walk.see.off")
        }
    }

    private var done: some View {
        VStack(spacing: KaikuTokens.Space.s4) {
            MascotWithBubble(state: .happy, text: T("walk.thanks"))
            if let s = walk.summary {
                KSection {
                    StatusLine(icon: "figure.walk", ok: true,
                               text: T("walk.minutes", n: Int(s.minutes.rounded())) + (s.steps.map { " · " + T("walk.sum.steps", n: $0) } ?? ""))
                    KDivider()
                    StatusLine(icon: s.inTheEar ? "ear" : "speaker.wave.2", ok: s.turns > 0,
                               text: (s.turns > 0 ? T("walk.sum.talked", n: s.turns) : T("walk.sum.quiet")) + " " + (s.inTheEar ? T("walk.sum.ear") : T("walk.sum.phone")))
                    KDivider()
                    StatusLine(icon: s.frames > 0 ? "eye" : "eye.slash", ok: s.frames > 0,
                               text: s.frames > 0 ? T("walk.sum.saw", n: s.frames) : T("walk.sum.nosee"))
                    KDivider()
                    StatusLine(icon: s.saved == .saved ? "checkmark.circle" : "info.circle", ok: s.saved == .saved, text: savedText(s.saved))
                }
            }
            Button(T("common.done")) { dismiss() }.buttonStyle(.kPrimary)
        }
        .onDisappear { WalkModel.shared.reset() }
    }

    private func savedText(_ s: WalkModel.Summary.Saved) -> String {
        switch s {
        case .saved: return T("walk.sum.saved")
        case .tooShort: return T("walk.sum.short")
        case .walksOff: return T("walk.sum.off")
        case .notConnected: return T("walk.sum.unpaired")
        }
    }
}

/// One status row: icon (sage when fine, muted otherwise) + plain words.
struct StatusLine: View {
    let icon: String
    let ok: Bool
    let text: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: KaikuTokens.Space.s3) {
            Image(systemName: icon).foregroundStyle(ok ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted).frame(width: 24)
            Text(text).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            Spacer(minLength: 0)
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

/// Calm · Playful · Chatty, with the chosen style's one line. Where a walk starts, on the walk (the three words
/// only) and in You. The choice is stored on this device; on a walk an open conversation starts again in it.
struct WalkStylePicker: View {
    var showsLine = true
    private let walk = WalkModel.shared
    init(showsLine: Bool = true) { self.showsLine = showsLine }

    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            KSegmented(WalkStyle.allCases.map { ($0, T($0.titleKey)) },
                       selection: Binding(get: { walk.style }, set: { walk.choose($0) }))
            if showsLine {
                Text(T(walk.style.lineKey)).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, KaikuTokens.Space.s1)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(T("walk.style.title"))
    }
}

/// The style choice as a settings row (You → Settings, under Glasses check).
struct WalkStyleSetting: View {
    var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            HStack(spacing: KaikuTokens.Space.s3) {
                RowIcon(symbol: "figure.walk", tint: KaikuTokens.Colors.sage)
                Text(T("walk.style.title")).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            }
            WalkStylePicker()
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The spotting game, quietly: "Trees  1 of 3", its dots, and one way to say "found one" without speaking. Shown
/// only while a game is on. The count is the walk's own (`WalkModel.goal`); nothing here is stored.
struct WalkGoalCard: View {
    let goal: WalkGoal
    let found: () -> Void

    var body: some View {
        // Three layouts, the first that fits: "Trees  1 of 3" on one line beside the button; the count under the
        // thing; and for a long thing the button underneath, so its name never squeezes into a narrow column.
        ViewThatFits(in: .horizontal) {
            HStack(spacing: KaikuTokens.Space.s3) { summary(inline: true); trailing(wide: false) }
            HStack(spacing: KaikuTokens.Space.s3) { summary(inline: false); trailing(wide: false) }
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) { summary(inline: false); trailing(wide: true) }
        }
        .padding(KaikuTokens.Space.s4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.sageSoft))
        .animation(KaikuTokens.Spring.gentle, value: goal.found)
        .accessibilityIdentifier("walk.goal")
    }

    private func summary(inline: Bool) -> some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            if inline {
                HStack(alignment: .firstTextBaseline, spacing: KaikuTokens.Space.s3) { thing.fixedSize(); count }
            } else {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) { thing.lineLimit(2).wraps(); count }
            }
            GoalDots(found: goal.found, target: goal.target)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(goal.title + ", " + T("walk.goal.a11y", ["n": "\(goal.found)", "m": "\(goal.target)"]))
    }

    private var thing: some View {
        Text(goal.title).kText(.title2).foregroundStyle(KaikuTokens.Colors.ink)
    }

    private var count: some View {
        Text(T("walk.goal.count", ["n": "\(goal.found)", "m": "\(goal.target)"]))
            .kText(.title2, weight: .regular).foregroundStyle(KaikuTokens.Colors.ink2).fixedSize()
            .contentTransition(.numericText())
    }

    @ViewBuilder private func trailing(wide: Bool) -> some View {
        if goal.done {
            Image(systemName: "checkmark.circle.fill").kText(.title1).foregroundStyle(KaikuTokens.Colors.sage)
                .transition(.scale(scale: 0.6).combined(with: .opacity))
                .accessibilityHidden(true)
        } else if wide {
            Button(T("lh.found"), action: found).buttonStyle(.kSecondary)
        } else {
            Button(T("lh.found"), action: found).buttonStyle(KButtonStyle(.secondary, fullWidth: false)).fixedSize()
        }
    }
}

/// One soft dot per thing to find: found ones filled sage.
struct GoalDots: View {
    let found: Int
    let target: Int
    var body: some View {
        HStack(spacing: KaikuTokens.Space.s2) {
            ForEach(0..<max(target, 0), id: \.self) { i in
                Circle()
                    .fill(i < found ? KaikuTokens.Colors.sage : KaikuTokens.Colors.surface)
                    .overlay(Circle().strokeBorder(KaikuTokens.Colors.sage, lineWidth: 2))
                    .frame(width: KaikuTokens.Space.s4, height: KaikuTokens.Space.s4)
            }
        }
        .accessibilityHidden(true)
    }
}

/// "Glasses · Connected" (or searching / not set up / taken off / disconnected → the walk goes on on the phone).
struct GlassesLine: View {
    let state: GlassesState
    let idle: Bool
    var worn: Bool? = nil
    var body: some View { StatusLine(icon: "eyeglasses", ok: state == .connected && worn != false, text: label) }

    var label: String {
        if worn == false, state != .disconnected, state != .off { return T("walk.glasses.offface") }
        switch state {
        case .off: return T("walk.phone")
        case .searching: return T("dev.connecting")
        case .registrationRequired: return T("walk.glasses.setup")
        case .motionUnavailable: return T("walk.glasses.motion.unavailable")
        case .connected: return T("walk.glasses.on")
        case .batteryLow: return T("dev.attn")
        case .disconnected: return T("walk.glasses.lost")
        }
    }
}

extension AppModel {
    /// `-kaikuAutostart YES` also starts a walk straight away (screenshots, UI tests).
    var defaultsAutostartWalk: Bool { UserDefaults.standard.bool(forKey: "kaikuAutostart") }
}

extension WalkModel {
    /// Back to the intro (after the thank-you screen).
    public func reset() { if !active { clearFinished() } }
}

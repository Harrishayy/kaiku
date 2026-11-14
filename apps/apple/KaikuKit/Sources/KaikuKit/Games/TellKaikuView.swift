import SwiftUI

/// Tell Kaiku: one gentle prompt; talk for up to 30 s. Start/stop is obvious: tap Kaiku (or the button, or
/// Space on Mac) to start and again when you're done — holding Kaiku works too. While listening Kaiku's ear is up,
/// a soft halo breathes with your voice level and the 30 s ring fills. Then thinking → thanks. Only on-device
/// speech features are kept (rate, pause ratio); no audio, no transcript. "Type instead" opens a text field;
/// typed words go through the safety gate and are then dropped.
public struct TellKaikuView: View {
    public init() {}
    public var body: some View {
        GameShell(titleKey: "game.tell.t", scene: .warm, introText: T("tell.prompt"), introState: .listening, endText: T("tell.thanks"),
                  demo: { TellDemo() },
                  field: { finish in TellField(finish: finish) },
                  endArt: { EmptyView() })
    }
}

struct TellField: View {
    let finish: (PlaySession?) -> Void
    static let maxSeconds: Double = 30
    enum Mode { case ready, listening, thinking, denied }

    @Environment(AppModel.self) private var app
    @Environment(\.accessibilityReduceMotion) private var rm
    @Environment(\.scenePhase) private var scenePhase
    @State private var active = true
    @State private var mode: Mode = .ready
    @State private var holdStart: Date?
    @State private var typing = false
    @State private var text = ""
    @State private var capture = AudioCapture()
    @State private var opened = Date()
    @State private var pressing = false
    @State private var pressAt = Date()
    @State private var latched = false      // started with a tap: the next tap stops
    @State private var stopTap = false
    @State private var level: Double = 0    // 0..1, smoothed mic level
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: KaikuTokens.Space.s4) {
            KCard(tone: .honey) {
                Text(T("tell.prompt")).kText(.title3, weight: .medium).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            }
            if !app.allowed(.voice) {
                Toggle(isOn: Binding(get: { app.consents[.voice] == true }, set: { app.consents[.voice] = $0 })) {
                    Text(T("task.voice.optin")).kText(.footnote).wraps()
                }.disabled(app.isPaused)
            }
            if mode == .denied {
                MicPermissionCard { typing = true }
            }
            TimelineView(.animation(minimumInterval: 1.0 / 30, paused: mode != .listening)) { tl in
                let p = holdStart.map { tl.date.timeIntervalSince($0) / Self.maxSeconds } ?? 0
                RingStage(maxSide: 260, minSide: 120) { side in
                    ZStack {
                        // voice halo: grows with the level (fades only, under Reduce Motion)
                        Circle()
                            .fill(KaikuTokens.Colors.claySoft)
                            .scaleEffect(mode == .listening && !rm ? 0.78 + 0.22 * level : 0.78)
                            .opacity(mode == .listening ? (rm ? 0.4 + 0.6 * level : 1) : 0.5)
                            .animation(.easeOut(duration: 0.12), value: level)
                        ProgressRing(progress: p, color: KaikuTokens.Colors.clay, width: 7,
                                     track: KaikuTokens.Colors.clay.opacity(0.14))
                        MascotView(state: mode == .listening ? .listening : mode == .thinking ? .thinking : .idle,
                                   size: side * 0.66, tappable: false)
                    }
                    .scaleEffect(pressing && !rm ? 0.97 : 1)
                    .animation(.easeOut(duration: 0.12), value: pressing)
                }
                .onChange(of: p >= 1) { _, full in if full { release() } }
            }
            .frame(maxWidth: .infinity)
            .contentShape(Circle())
            .kPointer()
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard !pressing else { return }
                        pressing = true
                        pressAt = Date()
                        if mode == .listening && latched { latched = false; stopTap = true; release() } else { latched = false; Task { await press() } }
                    }
                    .onEnded { _ in
                        pressing = false
                        if stopTap { stopTap = false; return }
                        // A quick tap latches (keep listening until the next tap); a hold stops on release.
                        if Date().timeIntervalSince(pressAt) < 0.45 { latched = true } else { release() }
                    }
            )
            .accessibilityElement()
            .accessibilityLabel(mode == .listening ? T("tell.listening") : T("tell.hold"))
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { toggle() }

            Text(mode == .listening ? T("tell.listening") : mode == .thinking ? T("common.loading") : T("tell.tap"))
                .kText(.callout).foregroundStyle(KaikuTokens.Colors.ink2).multilineTextAlignment(.center).wraps()
                .contentTransition(.opacity)
                .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast), value: mode)
            if typing {
                Composer(text: $text, placeholder: T("talk.type")) { send() }
            } else {
                VStack(spacing: KaikuTokens.Space.s1) {
                    Button { toggle() } label: {
                        Label(mode == .listening ? T("tell.done") : T("tell.start"),
                              systemImage: mode == .listening ? "stop.fill" : "mic.fill")
                    }
                    .buttonStyle(KButtonStyle(mode == .listening ? .secondary : .primary))
                    .disabled(mode == .thinking)
                    Button(T("tell.type")) { typing = true }.buttonStyle(.kGhost)
                }
                .frame(maxWidth: 420)
            }
        }
        .focusable(!typing)
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(.space) { toggle(); return .handled }
        .onAppear { active = true; focused = true }
        .onDisappear { active = false; cancelCapture() }
        .onChange(of: app.allowed(.voice)) { _, allowed in if !allowed { cancelCapture() } }
        .onChange(of: app.allowed(.checkins)) { _, allowed in if !allowed { cancelCapture() } }
        .onChange(of: scenePhase) { _, state in if state != .active { cancelCapture() } }
    }

    private func toggle() {
        if mode == .listening { latched = false; release() } else { latched = true; Task { await press() } }
    }

    private func press() async {
        guard mode == .ready, active, app.allowed(.voice), app.allowed(.checkins), scenePhase == .active else { return }
        guard !WalkModel.shared.talking else { app.showToast(T("task.voice.busy")); return }
        switch AudioCapture.permission {
        case .denied: mode = .denied; return
        case .undetermined:
            if !(await AudioCapture.request()) { mode = .denied; return }
            return   // the permission sheet ate the press; next press records
        case .granted: break
        }
        guard active, app.allowed(.voice), app.allowed(.checkins), scenePhase == .active else { return }
        do {
            capture.onLevel = { db in
                let v = Double(max(0, min(1, (db + 55) / 45)))
                Task { @MainActor in level = level * 0.6 + v * 0.4 }
            }
            try capture.start()
            holdStart = Date()
            mode = .listening
            KSound.play(.start)
            Haptics.tapKaiku()
            if !pressing && !latched { release() }
        } catch {
            mode = .denied
        }
    }

    private func release() {
        guard mode == .listening, let start = holdStart else { return }
        capture.onLevel = nil
        let frames = capture.stop()
        let held = Date().timeIntervalSince(start)
        holdStart = nil
        level = 0
        mode = .thinking
        KSound.play(.stop)
        let f = SpeechFeatures.compute(frameDB: frames)
        var s = PlaySession(game: .tell, device: KaikuPlatform.device, duration_s: held)
        s.speech_rate = f.speechRate
        s.pause_ratio = f.pauseRatio
        Task {
            try? await Task.sleep(nanoseconds: 900_000_000)
            guard active, app.allowed(.voice), app.allowed(.checkins), scenePhase == .active else { return }
            if held < 1 { mode = .ready; return }   // too short to count
            finish(s)
        }
    }

    private func cancelCapture() {
        capture.onLevel = nil; _ = capture.stop()
        mode = .ready; holdStart = nil; level = 0; latched = false; pressing = false
    }

    private func send() {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        text = ""
        if SafetyGate.shared.check(t) != nil { app.crisis(trigger: "phrase"); return }
        finish(PlaySession(game: .tell, device: KaikuPlatform.device, duration_s: Date().timeIntervalSince(opened)))
    }
}

/// Intro demo: a tap lands on Kaiku, its ear lifts, the ring fills while a voice halo pulses.
struct TellDemo: View {
    @Environment(\.accessibilityReduceMotion) private var rm
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: rm)) { tl in
            let t = rm ? 2.0 : tl.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 4.5)
            let on = t > 0.8 && t < 4
            let p = on ? (t - 0.8) / 3.2 : 0
            ZStack {
                Circle().fill(KaikuTokens.Colors.claySoft)
                    .frame(width: 112, height: 112)
                    .scaleEffect(on ? 0.85 + 0.15 * abs(sin(t * 5)) : 0.8)
                ProgressRing(progress: p, color: KaikuTokens.Colors.clay, width: 5, track: KaikuTokens.Colors.clay.opacity(0.14))
                    .frame(width: 124, height: 124)
                MascotView(state: on ? .listening : .idle, size: 84, tappable: false)
                if t > 0.4 && t < 1.1 {
                    Image(systemName: KaikuPlatform.isPhone ? "hand.point.up.left.fill" : "cursorarrow")
                        .font(.system(size: 22)).foregroundStyle(KaikuTokens.Colors.ink)
                        .offset(x: 26, y: 36)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .accessibilityHidden(true)
    }
}

/// Mic denied → permission card, then the text field.
struct MicPermissionCard: View {
    let typeInstead: () -> Void
    var body: some View {
        KCard(tone: .sky) {
            Text(T("perm.mic.t")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("perm.mic.d")).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            Button(T("talk.type"), action: typeInstead).buttonStyle(KButtonStyle(.secondary))
        }
    }
}

/// Composer: the text field takes the width; actions are icon buttons with accessible labels.
struct Composer: View {
    @Binding var text: String
    let placeholder: String
    var mic: (() -> Void)?
    var micOn = false
    var micLabel: String? = nil
    var micDisabled = false
    let send: () -> Void
    @FocusState private var focused: Bool

    var body: some View {
        HStack(alignment: .bottom, spacing: KaikuTokens.Space.s2) {
            TextField(placeholder, text: $text, axis: .vertical)
                .kText(.body)
                .lineLimit(1...4)
                .textFieldStyle(.plain)
                .focused($focused)
                .padding(.horizontal, KaikuTokens.Space.s4)
                .padding(.vertical, KaikuTokens.Space.s3)
                .frame(minHeight: KaikuTokens.Size.tapMin)
                .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(KaikuTokens.Colors.surface))
                .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .strokeBorder(focused ? KaikuTokens.Colors.focus : KaikuTokens.Colors.line, lineWidth: 1.5))
                .focusEffectDisabled()
                .onSubmit(send)
                .submitLabel(.send)
                // A multi-line field turns Return into a newline (onSubmit never fires on iOS): Return sends.
                .onChange(of: text) { _, t in
                    guard t.hasSuffix("\n") else { return }
                    text = String(t.dropLast())
                    if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { send() }
                }
            if let mic {
                IconButton(micOn ? "mic.slash.fill" : "mic.fill", label: micLabel ?? T("talk.hold"),
                           filled: micOn, action: mic)
                    .disabled(micDisabled).accessibilityIdentifier("talk.voice.control")
            }
            IconButton("arrow.up", label: T("talk.send"), filled: true, action: send)
                .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }
}

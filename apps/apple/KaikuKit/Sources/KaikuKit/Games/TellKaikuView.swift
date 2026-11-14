import SwiftUI

/// Tell Kaiku: one gentle prompt; hold Kaiku up to 30 s and talk (ring fills, ear up); release → thinking →
/// thanks. Only on-device speech features are kept (rate, pause ratio); no audio, no transcript. "Type instead"
/// opens a text field; typed words go through the safety gate and are then dropped.
public struct TellKaikuView: View {
    public init() {}
    public var body: some View {
        GameShell(titleKey: "game.tell.t", introText: T("tell.prompt"), introState: .listening, endText: T("tell.thanks"),
                  field: { finish in TellField(finish: finish) },
                  endArt: { EmptyView() })
    }
}

struct TellField: View {
    let finish: (PlaySession?) -> Void
    static let maxSeconds: Double = 30
    enum Mode { case ready, listening, thinking, denied }

    @Environment(AppModel.self) private var app
    @State private var mode: Mode = .ready
    @State private var holdStart: Date?
    @State private var typing = false
    @State private var text = ""
    @State private var capture = AudioCapture()
    @State private var opened = Date()
    @State private var pressing = false

    var body: some View {
        VStack(spacing: KaikuTokens.Space.s4) {
            KCard(tint: KaikuTokens.Colors.honeySoft) {
                Text(T("tell.prompt")).kText(.title3, weight: .regular).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            }
            if mode == .denied {
                MicPermissionCard { typing = true }
            }
            Spacer(minLength: 0)
            TimelineView(.animation(minimumInterval: 1.0 / 30, paused: mode != .listening)) { tl in
                let p = holdStart.map { tl.date.timeIntervalSince($0) / Self.maxSeconds } ?? 0
                RingStage(maxSide: 220, minSide: 72) { side in
                    ZStack {
                        ProgressRing(progress: p, color: KaikuTokens.Colors.clay, width: 8)
                        MascotView(state: mode == .listening ? .listening : mode == .thinking ? .thinking : .idle,
                                   size: side * 0.8, tappable: false)
                    }
                }
                .onChange(of: p >= 1) { _, full in if full { release() } }
            }
            .frame(maxWidth: .infinity)
            .contentShape(Circle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in if !pressing { pressing = true; Task { await press() } } }
                    .onEnded { _ in pressing = false; release() }
            )
            .accessibilityElement()
            .accessibilityLabel(mode == .listening ? T("tell.listening") : T("tell.hold"))
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { if mode == .listening { pressing = false; release() } else { pressing = true; Task { await press() } } }
            Text(mode == .listening ? T("tell.listening") : T("tell.hold"))
                .kText(.callout).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
            Spacer(minLength: 0)
            if typing {
                Composer(text: $text, placeholder: T("talk.type")) { send() }
            } else {
                Button(T("tell.type")) { typing = true }.buttonStyle(.kGhost)
            }
        }
        .onDisappear { _ = capture.stop() }
    }

    private func press() async {
        guard mode == .ready else { return }
        switch AudioCapture.permission {
        case .denied: mode = .denied; return
        case .undetermined:
            if !(await AudioCapture.request()) { mode = .denied; return }
            return   // the permission sheet ate the press; next hold records
        case .granted: break
        }
        do {
            try capture.start()
            holdStart = Date()
            mode = .listening
            if !pressing { release() }
        } catch {
            mode = .denied
        }
    }

    private func release() {
        guard mode == .listening, let start = holdStart else { return }
        let frames = capture.stop()
        let held = Date().timeIntervalSince(start)
        holdStart = nil
        mode = .thinking
        let f = SpeechFeatures.compute(frameDB: frames)
        var s = PlaySession(game: .tell, device: KaikuPlatform.device, duration_s: held)
        s.speech_rate = f.speechRate
        s.pause_ratio = f.pauseRatio
        Task {
            try? await Task.sleep(nanoseconds: 900_000_000)
            if held < 1 { mode = .ready; return }   // a tap, not a hold
            finish(s)
        }
    }

    private func send() {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        text = ""
        if SafetyGate.shared.check(t) != nil { app.crisis(trigger: "phrase"); return }
        finish(PlaySession(game: .tell, device: KaikuPlatform.device, duration_s: Date().timeIntervalSince(opened)))
    }
}

/// Mic denied → permission card, then the text field.
struct MicPermissionCard: View {
    let typeInstead: () -> Void
    var body: some View {
        KCard(tint: KaikuTokens.Colors.skySoft) {
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
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface))
                .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                    .strokeBorder(focused ? KaikuTokens.Colors.focus : KaikuTokens.Colors.line, lineWidth: 1.5))
                .onSubmit(send)
                .submitLabel(.send)
            if let mic { IconButton("mic.fill", label: T("talk.hold"), action: mic) }
            IconButton("arrow.up", label: T("talk.send"), filled: true, action: send)
                .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }
}

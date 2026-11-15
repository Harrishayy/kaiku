import SwiftUI

/// The 20-second guided self-test (You → Glasses check): Kaiku says one line through the current route, the
/// microphone is measured for three seconds (a level only), and one camera frame is fetched and shown. Nothing is
/// stored: no audio, no picture. Each result goes to the glasses log as a state or a number.
@Observable @MainActor
public final class GlassesSelfTest {
    public enum Step: Equatable, Sendable { case waiting, running, passed(String), failed(String), skipped(String) }
    public private(set) var speaker: Step = .waiting
    public private(set) var microphone: Step = .waiting
    public private(set) var frame: Step = .waiting
    public private(set) var running = false
    /// Live microphone level 0…1 while the microphone step runs.
    public private(set) var level: Double = 0
    /// The test frame, in memory only, for the thumbnail. Gone when the screen closes or the test runs again.
    public private(set) var thumbnail: CGImage?

    public init() {}

    /// dB (−90…0) → 0…1 for a level bar; −60 dB and below reads as silence.
    public nonisolated static func bar(_ db: Float) -> Double { Double(min(1, max(0, (db + 60) / 60))) }
    /// A voice at arm's length peaks well above −40 dB; a dead or wrong microphone stays near the noise floor.
    public nonisolated static let heardAbove: Float = -40

    public func run(app: AppModel) async {
        guard !running else { return }
        guard !WalkModel.shared.active else { speaker = .skipped(T("gc.test.walking")); return }
        running = true; defer { running = false }
        speaker = .running; microphone = .waiting; frame = .waiting; thumbnail = nil; level = 0
        GlassesLog.shared.log("selftest_begin")

        // 1 · the hands-free route, then one Kaiku line through it
        guard await Conversation.micGranted() else {
            speaker = .failed(T("walk.voice.mic")); microphone = .failed(T("walk.voice.mic"))
            GlassesLog.shared.log("selftest_mic_denied")
            await frameStep(app: app)
            return
        }
        let audio = ConversationAudio()
        let peak = PeakBox()
        audio.onLevel = { [weak self] db in
            peak.add(db)
            Task { @MainActor in self?.level = Self.bar(db) }
        }
        audio.setMic(false)
        do { try audio.start() } catch {
            speaker = .failed(T("walk.voice.audio")); microphone = .failed(T("walk.voice.audio"))
            GlassesStatus.shared.error("audio engine did not start: \(error.localizedDescription)", where: "selftest")
            await frameStep(app: app)
            return
        }
        let settled = await TalkAudio.settleHeadset()
        let route = TalkAudio.route
        GlassesStatus.shared.route = route
        GlassesLog.shared.log("selftest_route", ["in": route.input, "in_type": route.inputType, "out": route.output,
                                                 "out_type": route.outputType, "headset_settled": settled])
        // "Played" only when audio really started (a service without a voice must read as silent).
        let spoke = await VoiceLines.shared.playReporting("welcome.hello", lang: app.language, fallback: T("gc.test.line"), origin: .pressed)
        try? await Task.sleep(nanoseconds: 300_000_000)
        var waited = 0
        while VoiceLines.shared.speaking && waited < 60 { try? await Task.sleep(nanoseconds: 100_000_000); waited += 1 }
        let through = route.output.isEmpty ? T("gc.route.none") : route.output
        speaker = spoke ? .passed(T("gc.test.spoke") + " " + through) : .failed(T("gc.test.silent"))
        GlassesLog.shared.log("selftest_speaker", ["played": spoke, "in_ear": route.inTheEar])

        // 2 · three seconds of microphone level
        microphone = .running
        peak.reset()
        audio.setMic(true)
        try? await Task.sleep(nanoseconds: 3_000_000_000)
        audio.setMic(false)
        let p = peak.value
        audio.stop()
        TalkAudio.deactivate()
        level = 0
        let mic = route.input.isEmpty ? T("gc.route.none") : route.input
        microphone = p > Self.heardAbove ? .passed(T("gc.test.heard") + " " + mic)
            : .failed((p <= -89 ? T("gc.test.nosound") : T("gc.test.faint")) + " " + mic)
        GlassesLog.shared.log("selftest_mic", ["peak_db": Double(p), "heard": p > Self.heardAbove, "in_type": route.inputType])

        await frameStep(app: app)
        GlassesLog.shared.log("selftest_end")
        await GlassesStatus.shared.refresh(app: app)
    }

    private func frameStep(app: AppModel) async {
        guard let control = app.glassesControl else { frame = .skipped(T("gc.test.nosdk")); return }
        frame = .running
        let r = await control.testFrame()
        if let f = r.frame {
            thumbnail = GlassesVision.image(f.jpeg)
            frame = .passed(T("gc.test.frame", ["w": String(f.width), "h": String(f.height)]))
            GlassesLog.shared.log("selftest_frame", ["ok": true, "w": f.width, "h": f.height, "bytes": f.jpeg.count])
        } else {
            frame = .failed(r.note)
            GlassesStatus.shared.error(r.note, where: "selftest frame")
        }
    }

    public func clear() { thumbnail = nil }
}

/// Loudest level seen (audio thread → main), nothing else kept.
final class PeakBox: @unchecked Sendable {
    private let lock = NSLock()
    private var peak: Float = -90
    func add(_ db: Float) { lock.lock(); peak = max(peak, db); lock.unlock() }
    func reset() { lock.lock(); peak = -90; lock.unlock() }
    var value: Float { lock.lock(); defer { lock.unlock() }; return peak }
}

/// You → Glasses check: everything the glasses path depends on, in plain words, with the self-test and the log.
/// This is the screen to screenshot when something does not work.
public struct GlassesCheckView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var test = GlassesSelfTest()
    @State private var busy = false
    private var status = GlassesStatus.shared
    private var walk = WalkModel.shared
    public init() {}

    public var body: some View {
        KScreen(T("gc.title"), back: { dismiss() }) {
            KSection(T("gc.sec.glasses"), icon: "eyeglasses", tone: .sage) {
                fact("gc.registration", status.snapshot.registration, ok: status.snapshot.registration == "registered")
                KDivider()
                fact("gc.device", [status.snapshot.device, status.snapshot.model].compactMap { $0 }.joined(separator: " · ").ifEmpty(status.snapshot.link),
                     ok: status.snapshot.link == "connected")
                KDivider()
                fact("gc.worn", status.snapshot.worn + (status.snapshot.battery.map { " · " + T("gc.battery", n: $0) } ?? ""), ok: status.snapshot.worn == "on")
                KDivider()
                fact("gc.camera.permission", status.snapshot.camera, ok: status.snapshot.camera == "granted")
                if status.snapshot.camera != "granted", app.glassesControl != nil {
                    Button(T("gc.camera.ask")) { act { status.snapshot.camera = await app.glassesControl?.requestCamera() ?? "unknown" } }
                        .buttonStyle(.kSecondary).padding(KaikuTokens.Space.s3)
                }
                if status.snapshot.registration != "registered", let connect = app.connectGlasses {
                    Button(T("dev.setup")) { act { app.glassesRegistered = await connect() } }
                        .buttonStyle(.kSecondary).padding(KaikuTokens.Space.s3)
                }
            }
            KSection(T("gc.sec.sound"), icon: "ear", tone: .sky) {
                fact("gc.mic.permission", micPermission, ok: AudioCapture.permission == .granted)
                KDivider()
                fact("gc.headset", TalkAudio.headsetAvailable ?? T("gc.headset.none"), ok: TalkAudio.headsetAvailable != nil)
                KDivider()
                fact("gc.route.in", status.route.input.ifEmpty(T("gc.route.none")), ok: status.route.headsetMic)
                KDivider()
                fact("gc.route.out", status.route.output.ifEmpty(T("gc.route.none")), ok: status.route.headsetOut)
            }
            KSection(T("gc.sec.live"), icon: "waveform", tone: .clay) {
                fact("gc.service", app.isPaired ? (app.offline ? T("gc.service.offline") : T("service.connected")) : T("you.notpaired"),
                     ok: app.isPaired && !app.offline)
                KDivider()
                fact("gc.live", walk.active ? status.live : T("gc.live.nowalk"), ok: ["listening", "hearing", "speaking", "thinking"].contains(status.live) && walk.active)
                KDivider()
                fact("gc.last.person", ago(status.lastPersonAt), ok: status.lastPersonAt != nil)
                KDivider()
                fact("gc.last.kaiku", ago(status.lastKaikuAt), ok: status.lastKaikuAt != nil)
                KDivider()
                fact("gc.see", (app.consents[.see] == true ? T("gc.see.on") : T("gc.see.off")) + " · " + status.camera.rawValue, ok: status.camera == .streaming)
                KDivider()
                TimelineView(.periodic(from: .now, by: 2)) { _ in
                    fact("gc.frames", T("gc.frames.v", ["n": String(status.framesSent), "r": String(format: "%.1f", status.framesPerSecond)]), ok: status.framesPerSecond > 0)
                }
                if let e = status.lastError {
                    KDivider()
                    fact("gc.error", e + " (" + ago(status.lastErrorAt) + ")", ok: false)
                }
            }
            KSection(T("gc.sec.test"), subtitle: T("gc.test.d"), icon: "checklist", tone: .honey) {
                step("gc.test.speaker", test.speaker)
                KDivider()
                step("gc.test.mic", test.microphone)
                if test.microphone == .running {
                    ProgressView(value: test.level).tint(KaikuTokens.Colors.sage).padding(.horizontal, KaikuTokens.Space.s4)
                }
                KDivider()
                step("gc.test.camera", test.frame)
                if let img = test.thumbnail {
                    Image(decorative: img, scale: 1).resizable().scaledToFit().frame(maxHeight: 160)
                        .clipShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous))
                        .padding(KaikuTokens.Space.s3)
                        .accessibilityLabel(T("gc.test.thumb"))
                }
                Button(test.running ? T("gc.test.running") : T("gc.test.run")) { Task { await test.run(app: app) } }
                    .buttonStyle(.kPrimary).disabled(test.running || walk.active).padding(KaikuTokens.Space.s3)
                    .accessibilityIdentifier("gc.test.run")
            }
            NavigationLink(value: KaikuRoute.walk) { Text(T("walk.start")) }.buttonStyle(.kPrimary)
            KSection(T("gc.sec.log"), subtitle: T("gc.log.d"), icon: "doc.text", tone: .clay) {
                // The results are the readable rows above; the raw log lines travel only with "Share log".
                ShareLink(item: GlassesLog.url) { Text(T("gc.log.share")) }.buttonStyle(.kSecondary).padding(KaikuTokens.Space.s3)
            }
        }
        .task {
            // `-kaikuGlassesSelfTest YES` (DEBUG builds): run the self-test on opening (simulator checks with Mock Device Kit).
            #if DEBUG
            if UserDefaults.standard.bool(forKey: "kaikuGlassesSelfTest") { await test.run(app: app) }
            #endif
        }
        .task {
            while !Task.isCancelled {
                await status.refresh(app: app)
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
        .onDisappear { test.clear() }
    }

    private func act(_ work: @escaping @MainActor () async -> Void) {
        guard !busy else { return }
        busy = true
        Task { await work(); await status.refresh(app: app); busy = false }
    }

    private var micPermission: String {
        switch AudioCapture.permission {
        case .granted: return T("gc.granted")
        case .denied: return T("gc.denied")
        case .undetermined: return T("gc.notasked")
        }
    }

    private func ago(_ d: Date?) -> String {
        guard let d else { return T("gc.never") }
        return T("gc.ago", n: max(0, Int(Date().timeIntervalSince(d))))
    }

    private func fact(_ key: String, _ value: String, ok: Bool) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: KaikuTokens.Space.s3) {
            Circle().fill(ok ? KaikuTokens.Colors.sage : KaikuTokens.Colors.honey).frame(width: KaikuTokens.Space.s2, height: KaikuTokens.Space.s2)
            Text(T(key)).kText(.footnote, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Spacer(minLength: KaikuTokens.Space.s2)
            Text(value).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).multilineTextAlignment(.trailing).wraps()
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s2)
        .accessibilityElement(children: .combine)
    }

    private func step(_ key: String, _ s: GlassesSelfTest.Step) -> some View {
        let (text, ok): (String, Bool) = {
            switch s {
            case .waiting: return (T("gc.step.waiting"), false)
            case .running: return (T("gc.step.running"), false)
            case .passed(let t): return (t, true)
            case .failed(let t): return (t, false)
            case .skipped(let t): return (t, false)
            }
        }()
        return fact(key, text, ok: ok)
    }
}

private extension String {
    func ifEmpty(_ other: String) -> String { isEmpty ? other : self }
}

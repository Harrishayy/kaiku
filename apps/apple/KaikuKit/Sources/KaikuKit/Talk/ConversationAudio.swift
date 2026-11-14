@preconcurrency import AVFoundation
import Foundation

/// Full-duplex audio for a Live conversation: mic and Kaiku's voice on ONE `AVAudioEngine` with voice processing on,
/// so the echo canceller knows exactly what Kaiku is playing and the person can talk over it (barge-in) without
/// Kaiku hearing itself. Meta glasses: the HFP route (glasses mics, beamformed to the wearer, + glasses speakers) is
/// preferred when present (Meta DAT docs, "Microphones and speakers": `.allowBluetoothHFP`, `setPreferredInput`,
/// capture + playback on the same engine, re-install the tap on `AVAudioEngineConfigurationChange`).
/// Everything stays in memory: 16 kHz PCM chunks go to the Live socket, raw buffers to the on-device listener.
public final class ConversationAudio: @unchecked Sendable {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let playFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000, channels: 1, interleaved: false)!
    private let downsampler = MicDownsampler()
    /// Silence queued before Kaiku's first chunk after a pause: the voice-processing output swallows the first
    /// few milliseconds after idling and network chunks arrive unevenly, so words began clipped.
    static let leadInSeconds = 0.12
    private var configObserver: NSObjectProtocol?
    private let lock = NSLock()
    private var queued = 0
    private var generation = 0
    private var micOn = true
    private var tapInstalled = false
    /// False: playback only (no microphone permission). The input node is never touched, nothing is captured.
    private var captures = true

    /// 16 kHz mono PCM16 chunks (only while the mic is on).
    public var onPCM: ((Data) -> Void)?
    /// Raw input buffers (on-device safety listener), only while the mic is on.
    public var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    /// Input level in dB per buffer (UI halo).
    public var onLevel: ((Float) -> Void)?
    /// Kaiku's voice started (true) / everything queued has been played or flushed (false).
    public var onPlaying: ((Bool) -> Void)?
    public var onFailure: (() -> Void)?
    public private(set) var running = false

    public init() {}

    /// True when the glasses (or another headset) carry the mic: tune VAD for a beamformed headset mic.
    public static var headsetRoute: Bool {
        #if os(iOS)
        let r = AVAudioSession.sharedInstance().currentRoute
        return r.inputs.contains { [.bluetoothHFP, .headsetMic].contains($0.portType) }
        #else
        return false
        #endif
    }

    public func start() throws {
        guard !running else { return }
        try TalkAudio.activate()
        TalkAudio.preferHeadsetInput()
        // Voice processing (AEC + noise suppression) must be on before the engine starts; best effort.
        if captures {
            do { try engine.inputNode.setVoiceProcessingEnabled(true) } catch { kaikuLog.notice("vp_unavailable") }
        }
        if player.engine == nil { engine.attach(player) }
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        // `-kaikuMute YES` silences everything (tests, screenshots), Kaiku's live voice included.
        player.volume = UserDefaults.standard.bool(forKey: "kaikuMute") ? 0 : 1
        do {
            if captures { try installTap() }
            engine.prepare()
            try engine.start()
        } catch { stop(); throw error }
        player.play()
        running = true
        // Restart off the notification's own thread: touching the engine inside its handler can deadlock.
        configObserver = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine,
                                                                queue: nil) { [weak self] _ in
            DispatchQueue.main.async { self?.restart() }
        }
    }

    public func stop() {
        running = false
        if let configObserver { NotificationCenter.default.removeObserver(configObserver) }
        configObserver = nil
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
        flush()
        player.stop()
        engine.stop()
    }

    /// Before `start()`: false opens the voice for playback only (typed conversation without the microphone).
    public func setCapture(_ on: Bool) {
        guard !running else { return }
        captures = on
    }

    /// Mic on/off without tearing the engine down (Kaiku can finish its sentence while muted).
    public func setMic(_ on: Bool) {
        lock.lock(); micOn = on; lock.unlock()
    }

    public var isPlaying: Bool { lock.lock(); defer { lock.unlock() }; return queued > 0 }

    /// 24 kHz little-endian PCM16 from Live → the player.
    public func play(_ pcm: Data) {
        guard running, engine.isRunning else { return }
        let count = pcm.count / 2
        guard count > 0, let buf = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: AVAudioFrameCount(count)) else { return }
        buf.frameLength = AVAudioFrameCount(count)
        pcm.withUnsafeBytes { raw in
            let src = raw.bindMemory(to: Int16.self)
            let dst = buf.floatChannelData![0]
            for i in 0..<count { dst[i] = Float(Int16(littleEndian: src[i])) / 32768 }
        }
        lock.lock()
        let gen = generation
        queued += 1
        let started = queued == 1
        lock.unlock()
        if started {
            onPlaying?(true)
            let lead = AVAudioFrameCount(playFormat.sampleRate * Self.leadInSeconds)
            if let silence = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: lead) {
                silence.frameLength = lead   // zero-filled by AVAudioPCMBuffer
                player.scheduleBuffer(silence, completionHandler: nil)
            }
        }
        player.scheduleBuffer(buf, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            guard let self else { return }
            self.lock.lock()
            guard gen == self.generation else { self.lock.unlock(); return }   // flushed buffer
            self.queued = max(0, self.queued - 1)
            let idle = self.queued == 0
            self.lock.unlock()
            if idle { self.onPlaying?(false) }
        }
        if !player.isPlaying, engine.isRunning { player.play() }
    }

    /// Barge-in: drop everything Kaiku had queued, at once (the server already discarded the rest of the turn).
    public func flush() {
        lock.lock()
        generation += 1
        let was = queued > 0
        queued = 0
        lock.unlock()
        player.stop()
        if running, engine.isRunning { player.play() }
        if was { onPlaying?(false) }
    }

    // MARK: private

    private func installTap() throws {
        let input = engine.inputNode
        let fmt = input.outputFormat(forBus: 0)
        guard fmt.sampleRate > 0, fmt.channelCount > 0 else { throw NSError(domain: "kaiku.audio", code: 1) }
        input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { [weak self] buf, _ in self?.handle(buf) }
        tapInstalled = true
    }

    /// After a phone call / Siri / alarm the system leaves the engine stopped: start it again (same tap rules as
    /// a route change). Safe to call when it is already running.
    public func resumeAfterInterruption() {
        guard running, !engine.isRunning else { return }
        restart()
    }

    /// The route changed (glasses connected / gone, HFP rate renegotiated): the engine stopped itself.
    private func restart() {
        guard running else { return }
        try? TalkAudio.activate()
        // Buffers queued for the old route never report completion: forget them so "speaking" cannot stick.
        // (Not `flush()`: starting the player while the engine is stopped raises an exception.)
        lock.lock()
        generation += 1
        let was = queued > 0
        queued = 0
        lock.unlock()
        player.stop()
        if was { onPlaying?(false) }
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
        TalkAudio.preferHeadsetInput()
        do {
            if captures { try installTap() }
            engine.prepare()
            try engine.start()
            player.play()
            kaikuLog.notice("audio_route_restarted")
        } catch {
            kaikuLog.notice("audio_restart_failed")
            stop()
            onFailure?()
        }
    }

    private func handle(_ buf: AVAudioPCMBuffer) {
        lock.lock(); let on = micOn; lock.unlock()
        guard on else { return }
        onBuffer?(buf)
        guard let samples = MicDownsampler.mono(buf) else { return }
        onLevel?(MicDownsampler.level(samples))
        guard let onPCM, let pcm = downsampler.convert(samples: samples, sampleRate: buf.format.sampleRate) else { return }
        onPCM(pcm)
    }
}

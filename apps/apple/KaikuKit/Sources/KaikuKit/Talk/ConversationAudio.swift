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
    private let out = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true)!
    private var converter: AVAudioConverter?
    private var configObserver: NSObjectProtocol?
    private let lock = NSLock()
    private var queued = 0
    private var generation = 0
    private var micOn = true

    /// 16 kHz mono PCM16 chunks (only while the mic is on).
    public var onPCM: ((Data) -> Void)?
    /// Raw input buffers (on-device safety listener), only while the mic is on.
    public var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    /// Input level in dB per buffer (UI halo).
    public var onLevel: ((Float) -> Void)?
    /// Kaiku's voice started (true) / everything queued has been played or flushed (false).
    public var onPlaying: ((Bool) -> Void)?
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
        do { try engine.inputNode.setVoiceProcessingEnabled(true) } catch { kaikuLog.notice("vp_unavailable") }
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        try installTap()
        engine.prepare()
        try engine.start()
        player.play()
        running = true
        configObserver = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine,
                                                                queue: nil) { [weak self] _ in self?.restart() }
    }

    public func stop() {
        guard running else { return }
        running = false
        if let configObserver { NotificationCenter.default.removeObserver(configObserver) }
        configObserver = nil
        engine.inputNode.removeTap(onBus: 0)
        flush()
        player.stop()
        engine.stop()
    }

    /// Mic on/off without tearing the engine down (Kaiku can finish its sentence while muted).
    public func setMic(_ on: Bool) {
        lock.lock(); micOn = on; lock.unlock()
    }

    public var isPlaying: Bool { lock.lock(); defer { lock.unlock() }; return queued > 0 }

    /// 24 kHz little-endian PCM16 from Live → the player.
    public func play(_ pcm: Data) {
        guard running else { return }
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
        if started { onPlaying?(true) }
        player.scheduleBuffer(buf, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            guard let self else { return }
            self.lock.lock()
            guard gen == self.generation else { self.lock.unlock(); return }   // flushed buffer
            self.queued = max(0, self.queued - 1)
            let idle = self.queued == 0
            self.lock.unlock()
            if idle { self.onPlaying?(false) }
        }
        if !player.isPlaying { player.play() }
    }

    /// Barge-in: drop everything Kaiku had queued, at once (the server already discarded the rest of the turn).
    public func flush() {
        lock.lock()
        generation += 1
        let was = queued > 0
        queued = 0
        lock.unlock()
        player.stop()
        if running { player.play() }
        if was { onPlaying?(false) }
    }

    // MARK: private

    private func installTap() throws {
        let input = engine.inputNode
        let fmt = input.outputFormat(forBus: 0)
        guard fmt.sampleRate > 0, fmt.channelCount > 0 else { throw NSError(domain: "kaiku.audio", code: 1) }
        converter = AVAudioConverter(from: fmt, to: out)
        input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { [weak self] buf, _ in self?.handle(buf) }
    }

    /// The route changed (glasses connected / gone, HFP rate renegotiated): the engine stopped itself.
    private func restart() {
        guard running else { return }
        engine.inputNode.removeTap(onBus: 0)
        TalkAudio.preferHeadsetInput()
        do {
            try installTap()
            engine.prepare()
            try engine.start()
            player.play()
            kaikuLog.notice("audio_route_restarted")
        } catch {
            kaikuLog.notice("audio_restart_failed")
        }
    }

    private func handle(_ buf: AVAudioPCMBuffer) {
        lock.lock(); let on = micOn; lock.unlock()
        guard on else { return }
        onBuffer?(buf)
        if let ch = buf.floatChannelData?[0], buf.frameLength > 0 {
            var sum: Float = 0
            let n = Int(buf.frameLength)
            for i in 0..<n { sum += ch[i] * ch[i] }
            onLevel?(20 * log10(max(sqrt(sum / Float(n)), 1e-6)))
        }
        guard let onPCM, let converter else { return }
        let ratio = out.sampleRate / buf.format.sampleRate
        guard let o = AVAudioPCMBuffer(pcmFormat: out, frameCapacity: AVAudioFrameCount(Double(buf.frameLength) * ratio) + 32) else { return }
        var fed = false
        var err: NSError?
        converter.convert(to: o, error: &err) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return buf
        }
        if err == nil, let p = o.int16ChannelData?[0], o.frameLength > 0 {
            onPCM(Data(bytes: p, count: Int(o.frameLength) * 2))
        }
    }
}

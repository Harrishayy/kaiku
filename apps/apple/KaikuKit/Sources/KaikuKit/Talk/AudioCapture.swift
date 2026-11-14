@preconcurrency import AVFoundation
import Foundation

/// Microphone capture with AVAudioEngine. Everything stays in memory: energy frames for the on-device speech
/// features, and (only during a Talk session) 16 kHz PCM chunks handed to the Live socket. Nothing is written.
public final class AudioCapture: @unchecked Sendable {
    public enum Permission { case granted, denied, undetermined }

    private let engine = AVAudioEngine()
    private let downsampler = MicDownsampler()
    private let lock = NSLock()
    private var frames: [Float] = []      // dB per 20 ms frame
    private var pending: [Float] = []
    public var onPCM: ((Data) -> Void)?
    public var onLevel: ((Float) -> Void)?
    /// Raw input buffers for the on-device listener (safety gate + spoken dial), in memory only.
    public var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    public private(set) var running = false

    public init() {}

    public static var permission: Permission {
        switch AVAudioApplication.shared.recordPermission {
        case .granted: return .granted
        case .denied: return .denied
        default: return .undetermined
        }
    }

    public static func request() async -> Bool {
        await withCheckedContinuation { c in AVAudioApplication.requestRecordPermission { c.resume(returning: $0) } }
    }

    public func start() throws {
        guard !running else { return }
        try TalkAudio.activate()   // playAndRecord + voiceChat + Bluetooth HFP (glasses as mic + speaker)
        lock.lock(); frames = []; pending = []; lock.unlock()
        let input = engine.inputNode
        let fmt = input.outputFormat(forBus: 0)
        guard fmt.sampleRate > 0 else { throw NSError(domain: "kaiku.audio", code: 1) }
        let frameLen = Int(fmt.sampleRate * 0.02)
        input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { [weak self] buf, _ in
            self?.handle(buf, frameLen: frameLen)
        }
        engine.prepare()
        do { try engine.start() } catch {
            input.removeTap(onBus: 0); engine.stop()
            throw error
        }
        running = true
    }

    public func stop() -> [Float] {
        if running {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
            running = false
        }
        lock.lock(); defer { lock.unlock() }
        let f = frames
        frames = []
        return f
    }

    private func handle(_ buf: AVAudioPCMBuffer, frameLen: Int) {
        onBuffer?(buf)
        guard let samples = MicDownsampler.mono(buf) else { return }
        lock.lock()
        pending.append(contentsOf: samples)
        var level: Float = -90
        while pending.count >= frameLen {
            var sum: Float = 0
            for i in 0..<frameLen { sum += pending[i] * pending[i] }
            let rms = sqrt(sum / Float(frameLen))
            let db = 20 * log10(max(rms, 1e-6))
            frames.append(db)
            level = db
            pending.removeFirst(frameLen)
        }
        lock.unlock()
        onLevel?(level)
        if let onPCM, let pcm = downsampler.convert(samples: samples, sampleRate: buf.format.sampleRate) { onPCM(pcm) }
    }
}

/// On-device speech features from 20 ms energy frames (no audio, no words): an energy VAD with an adaptive noise
/// floor; speech rate = syllable nuclei (energy peaks ≥ 100 ms apart inside speech) per second of talking time
/// (first to last speech frame); pause ratio = non-speech frames / frames in that span.
public enum SpeechFeatures {
    public struct Result: Equatable, Sendable {
        public let speechRate: Double?
        public let pauseRatio: Double?
        public let speakingSeconds: Double
    }

    public static func compute(frameDB: [Float], frameSeconds: Double = 0.02) -> Result {
        guard frameDB.count > 10 else { return Result(speechRate: nil, pauseRatio: nil, speakingSeconds: 0) }
        let sorted = frameDB.sorted()
        let floor = sorted[Int(Double(sorted.count) * 0.1)]
        let threshold = max(floor + 12, -50)
        // smooth (5 frames ≈ 100 ms)
        var smooth = [Float](repeating: -90, count: frameDB.count)
        for i in frameDB.indices {
            let lo = max(0, i - 2), hi = min(frameDB.count - 1, i + 2)
            smooth[i] = frameDB[lo...hi].reduce(0, +) / Float(hi - lo + 1)
        }
        let speech = smooth.map { $0 > threshold }
        guard let first = speech.firstIndex(of: true), let last = speech.lastIndex(of: true), last > first else {
            return Result(speechRate: nil, pauseRatio: nil, speakingSeconds: 0)
        }
        let span = last - first + 1
        let speechFrames = speech[first...last].filter { $0 }.count
        var peaks = 0
        var lastPeak = -100
        let minGap = Int(0.1 / frameSeconds)
        for i in max(first, 1)..<min(last, smooth.count - 1) where speech[i] {
            if smooth[i] > smooth[i - 1] && smooth[i] >= smooth[i + 1] && smooth[i] > threshold + 3 && i - lastPeak >= minGap {
                peaks += 1
                lastPeak = i
            }
        }
        let seconds = Double(span) * frameSeconds
        let rate = seconds > 0.5 ? min(15, Double(peaks) / seconds) : nil
        let pause = min(1, max(0, Double(span - speechFrames) / Double(span)))
        return Result(speechRate: rate, pauseRatio: pause, speakingSeconds: seconds)
    }
}

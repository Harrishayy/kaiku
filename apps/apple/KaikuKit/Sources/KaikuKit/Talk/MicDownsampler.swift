@preconcurrency import AVFoundation
import Foundation

/// Microphone buffers in whatever the hardware gives (48 kHz Mac mics, 44.1 kHz, 8/16 kHz Bluetooth HFP, and the
/// multi-channel layouts a Mac's voice-processing input reports) → the 16 kHz mono PCM16 Gemini Live expects.
///
/// Only channel 0 is used: with voice processing on, macOS can report 3–9 input channels where channel 0 is the
/// echo-cancelled voice and the rest are raw/reference signals. `AVAudioConverter` has no down-mix for such
/// layouts (it fails or returns silence), so the mono copy is made here and only the rate/format is converted.
/// One instance per capture; it is rebuilt automatically when the input format changes (route change).
final class MicDownsampler {
    static let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true)!

    private var converter: AVAudioConverter?
    private var monoFormat: AVAudioFormat?
    private var sourceRate: Double = 0

    init() {}

    /// Channel 0 as float samples (nil for formats a tap never delivers: no float and no int16 data).
    static func mono(_ buf: AVAudioPCMBuffer) -> [Float]? {
        let n = Int(buf.frameLength)
        guard n > 0 else { return nil }
        let stride = buf.format.isInterleaved ? Int(buf.format.channelCount) : 1
        if let f = buf.floatChannelData?[0] {
            return (0..<n).map { f[$0 * stride] }
        }
        if let i = buf.int16ChannelData?[0] {
            return (0..<n).map { Float(i[$0 * stride]) / 32768 }
        }
        return nil
    }

    /// RMS level of channel 0 in dB (−120 … 0).
    static func level(_ samples: [Float]) -> Float {
        guard !samples.isEmpty else { return -120 }
        var sum: Float = 0
        for s in samples { sum += s * s }
        return 20 * log10(max(sqrt(sum / Float(samples.count)), 1e-6))
    }

    /// 16 kHz mono little-endian PCM16 for one input buffer (nil when nothing came out).
    func convert(_ buf: AVAudioPCMBuffer) -> Data? {
        guard let samples = Self.mono(buf) else { return nil }
        return convert(samples: samples, sampleRate: buf.format.sampleRate)
    }

    func convert(samples: [Float], sampleRate: Double) -> Data? {
        guard sampleRate > 0, !samples.isEmpty else { return nil }
        if converter == nil || sourceRate != sampleRate {
            guard let mf = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: sampleRate, channels: 1, interleaved: false),
                  let c = AVAudioConverter(from: mf, to: Self.target) else { return nil }
            monoFormat = mf; converter = c; sourceRate = sampleRate
        }
        guard let converter, let monoFormat else { return nil }
        let capacity = AVAudioFrameCount(Double(samples.count) * Self.target.sampleRate / sampleRate) + 64
        guard let output = AVAudioPCMBuffer(pcmFormat: Self.target, frameCapacity: capacity) else { return nil }
        var offset = 0
        var out = Data()
        // The converter asks for input in blocks (at most 4096 frames on the no-resampling and upsampling paths)
        // and ignores anything beyond what it asked for. Handing it the whole tap buffer at once silently dropped
        // the rest — on a Bluetooth headset (8/16 kHz) that is audible as chopped speech. Feed exactly what it
        // requests and keep pulling until this buffer is used up.
        for _ in 0..<256 {
            var err: NSError?
            output.frameLength = 0
            let status = converter.convert(to: output, error: &err) { requested, s in
                let n = min(Int(requested), samples.count - offset)
                guard n > 0, let slice = AVAudioPCMBuffer(pcmFormat: monoFormat, frameCapacity: AVAudioFrameCount(n)) else {
                    s.pointee = .noDataNow
                    return nil
                }
                slice.frameLength = AVAudioFrameCount(n)
                samples.withUnsafeBufferPointer { src in
                    slice.floatChannelData![0].update(from: src.baseAddress! + offset, count: n)
                }
                offset += n
                s.pointee = .haveData
                return slice
            }
            guard err == nil, status != .error else { break }
            if let p = output.int16ChannelData?[0], output.frameLength > 0 {
                out.append(Data(bytes: p, count: Int(output.frameLength) * 2))
            }
            if offset >= samples.count && (status != .haveData || output.frameLength == 0) { break }
            if output.frameLength == 0 && status != .haveData { break }
        }
        return out.isEmpty ? nil : out
    }
}

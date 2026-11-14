import AVFoundation
import Foundation

/// Tiny, quiet UI sounds, synthesised in memory at first use (soft sine tones with a gentle envelope; no bundled
/// or third-party audio). Respect the You → Sounds switch, the iPhone silent switch (ambient session) and the
/// system mute. Never on the crisis screen.
@MainActor
public enum KSound {
    nonisolated public static let enabledKey = "kaiku.sounds"

    public enum Cue: Hashable, Sendable {
        case catchChime        // firefly caught: a bright two-note sparkle
        case puff              // moth tapped: a soft low breath, never an error buzz
        case tick              // dial step
        case note(Int)         // pebble path: rising notes (0 = lowest)
        case wobble            // pebble path, wrong pebble: a gentle low two-step
        case breathIn, breathOut
        case start             // a game starts / recording starts
        case stop              // recording stops
        case done              // a game or check-in finished: a warm three-note chord
    }

    static var enabled: Bool { UserDefaults.standard.object(forKey: enabledKey) as? Bool ?? true }

    private static var players: [Cue: [AVAudioPlayer]] = [:]
    private static var next: [Cue: Int] = [:]
    private static var sessionReady = false

    public static func play(_ cue: Cue) {
        guard enabled else { return }
        prepareSession()
        if players[cue] == nil {
            let data = wav(for: cue)
            players[cue] = (0..<3).compactMap { _ in
                let p = try? AVAudioPlayer(data: data)
                p?.prepareToPlay()
                return p
            }
        }
        guard let pool = players[cue], !pool.isEmpty else { return }
        let i = (next[cue] ?? 0) % pool.count
        next[cue] = i + 1
        pool[i].currentTime = 0
        pool[i].play()
    }

    /// Build the common cues ahead of time so the first tap answers within a frame.
    public static func warmUp(_ cues: [Cue]) {
        guard enabled else { return }
        for c in cues where players[c] == nil {
            let data = wav(for: c)
            players[c] = (0..<3).compactMap { _ in
                let p = try? AVAudioPlayer(data: data)
                p?.prepareToPlay()
                return p
            }
        }
    }

    private static func prepareSession() {
        guard !sessionReady else { return }
        sessionReady = true
        #if os(iOS)
        // .ambient: silenced by the ring/silent switch, mixes with whatever else is playing.
        let s = AVAudioSession.sharedInstance()
        if s.category != .playAndRecord { try? s.setCategory(.ambient, options: [.mixWithOthers]) }
        #endif
    }

    // MARK: synthesis

    /// Pentatonic steps above A4 for the pebble notes.
    private static let pentatonic: [Double] = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24]
    private static func hz(_ semis: Double, base: Double = 523.25) -> Double { base * pow(2, semis / 12) }

    private struct Tone { var freq: Double; var start: Double; var dur: Double; var amp: Double; var glide: Double = 0 }

    private static func tones(_ cue: Cue) -> [Tone] {
        switch cue {
        case .catchChime:
            return [Tone(freq: hz(7), start: 0, dur: 0.16, amp: 0.16), Tone(freq: hz(14), start: 0.06, dur: 0.22, amp: 0.12)]
        case .puff:
            return [Tone(freq: 220, start: 0, dur: 0.18, amp: 0.10, glide: -60)]
        case .tick:
            return [Tone(freq: 1320, start: 0, dur: 0.035, amp: 0.07)]
        case .note(let i):
            let s = pentatonic[max(0, min(pentatonic.count - 1, i))]
            return [Tone(freq: hz(s, base: 392), start: 0, dur: 0.26, amp: 0.14)]
        case .wobble:
            return [Tone(freq: 330, start: 0, dur: 0.14, amp: 0.10), Tone(freq: 294, start: 0.12, dur: 0.2, amp: 0.10)]
        case .breathIn:
            return [Tone(freq: 294, start: 0, dur: 0.9, amp: 0.06, glide: 40)]
        case .breathOut:
            return [Tone(freq: 330, start: 0, dur: 0.9, amp: 0.05, glide: -50)]
        case .start:
            return [Tone(freq: hz(0), start: 0, dur: 0.12, amp: 0.10), Tone(freq: hz(7), start: 0.08, dur: 0.16, amp: 0.10)]
        case .stop:
            return [Tone(freq: hz(7), start: 0, dur: 0.12, amp: 0.10), Tone(freq: hz(0), start: 0.08, dur: 0.18, amp: 0.10)]
        case .done:
            return [Tone(freq: hz(0), start: 0, dur: 0.5, amp: 0.09), Tone(freq: hz(4), start: 0.09, dur: 0.5, amp: 0.08),
                    Tone(freq: hz(7), start: 0.18, dur: 0.6, amp: 0.08)]
        }
    }

    static func wav(for cue: Cue) -> Data {
        let rate = 44_100.0
        let ts = tones(cue)
        let total = (ts.map { $0.start + $0.dur }.max() ?? 0.1) + 0.02
        let n = Int(total * rate)
        var samples = [Float](repeating: 0, count: n)
        for t in ts {
            let s0 = Int(t.start * rate), len = Int(t.dur * rate)
            var phase = 0.0
            for k in 0..<len where s0 + k < n {
                let x = Double(k) / Double(len)
                let f = t.freq + t.glide * x
                phase += 2 * .pi * f / rate
                // 6 ms attack, exponential-ish decay: soft, no click.
                let attack = min(1, Double(k) / (0.006 * rate))
                let env = attack * pow(1 - x, 2.2)
                let v = sin(phase) + 0.18 * sin(2 * phase)          // a touch of warmth
                samples[s0 + k] += Float(v * env * t.amp)
            }
        }
        return pcm16WAV(samples, rate: Int(rate))
    }

    private static func pcm16WAV(_ s: [Float], rate: Int) -> Data {
        var d = Data()
        func u32(_ v: UInt32) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 4)) }
        func u16(_ v: UInt16) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 2)) }
        let bytes = UInt32(s.count * 2)
        d.append(contentsOf: Array("RIFF".utf8)); u32(36 + bytes); d.append(contentsOf: Array("WAVE".utf8))
        d.append(contentsOf: Array("fmt ".utf8)); u32(16); u16(1); u16(1); u32(UInt32(rate)); u32(UInt32(rate * 2)); u16(2); u16(16)
        d.append(contentsOf: Array("data".utf8)); u32(bytes)
        for v in s { u16(UInt16(bitPattern: Int16(max(-1, min(1, v)) * 32_000))) }
        return d
    }
}

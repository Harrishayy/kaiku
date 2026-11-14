#if DEBUG
@preconcurrency import AVFoundation
import Foundation

/// A walk without a microphone, for simulator walkthroughs and the paid proof (Debug builds only).
/// `-kaikuWalkTyped YES`: the walk's real `Conversation` on the real Live socket and the real service, with a
/// stand-in for the audio engine that never opens a microphone and plays no sound (the simulator's microphone is
/// the Mac's). What the person would say is typed instead: `-kaikuWalkSay "10:first line|25:second line"`, each
/// line that many seconds after the one before (after Live is ready for the first; `-kaikuWalkSayEvery`, default
/// 14, where no number is given). `-kaikuWalkEndAfter <seconds>` ends the walk by itself; `-kaikuWalkFound <n>`
/// presses the walk screen's "Found one" n times, a few seconds apart (it needs no `-kaikuWalkTyped`). Kaiku's
/// words show as bubbles from Live's own transcription; nothing is scripted and nothing it says is written here.
@MainActor
enum WalkTyped {
    static var on: Bool { UserDefaults.standard.bool(forKey: "kaikuWalkTyped") }

    static func conversation(_ surface: CompanionSurface) -> Conversation {
        Conversation(surface: surface, intent: .walk, audio: WalkSilentAudio(), transport: { LiveSession(onEvent: $0) },
                     permission: { true }, localListener: false, purpose: .walk)
    }

    /// The launch argument as (seconds to wait, line) pairs.
    static func script(_ text: String, every: Double) -> [(wait: Double, line: String)] {
        text.split(separator: "|").compactMap { part in
            var line = part.trimmingCharacters(in: .whitespaces)
            var wait = every
            if let colon = line.firstIndex(of: ":"), let seconds = Double(line[..<colon]) {
                wait = seconds
                line = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            }
            return line.isEmpty ? nil : (max(1, wait), line)
        }
    }

    /// Types the launch argument's lines into the conversation, one at a time.
    static func say(into c: Conversation) {
        guard on, let text = UserDefaults.standard.string(forKey: "kaikuWalkSay"), !text.isEmpty else { return }
        let lines = script(text, every: UserDefaults.standard.double(forKey: "kaikuWalkSayEvery").nonZero ?? 14)
        Task { [weak c] in
            for (wait, line) in lines {
                try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000))
                guard let c, c.isLive else { return }
                c.send(text: line)
            }
        }
    }

    /// `-kaikuWalkEndAfter <seconds>`: the walk ends by itself (the simulator has nobody to press End walk).
    /// `-kaikuWalkFound <n>`: the person's own "Found one", n times.
    static func endLater(_ walk: WalkModel) {
        let finds = UserDefaults.standard.integer(forKey: "kaikuWalkFound")
        if finds > 0 {
            Task { [weak walk] in
                for _ in 0..<finds {
                    try? await Task.sleep(nanoseconds: 4_000_000_000)
                    walk?.foundOne()
                }
            }
        }
        guard on, let seconds = UserDefaults.standard.double(forKey: "kaikuWalkEndAfter").nonZero else { return }
        Task { [weak walk] in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            await walk?.end()
        }
    }
}

private extension Double {
    var nonZero: Double? { self == 0 ? nil : self }
}

/// Captures nothing and plays nothing, but keeps time like a speaker: Kaiku "is speaking" for as long as the audio
/// it sent would last (24 kHz PCM16), so the walk's rules about who is speaking run as they would with sound.
final class WalkSilentAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?

    private let lock = NSLock()
    private var endsAt = Date.distantPast
    private var generation = 0
    private var bytes = 0

    var isPlaying: Bool { lock.lock(); defer { lock.unlock() }; return endsAt > Date() }
    /// Seconds of Kaiku's voice received so far.
    var seconds: Double { lock.lock(); defer { lock.unlock() }; return Double(bytes / 2) / 24_000 }

    func start() throws {}
    func stop() { flush() }
    func setMic(_ on: Bool) {}

    func play(_ pcm: Data) {
        lock.lock()
        let wasPlaying = endsAt > Date()
        endsAt = max(endsAt, Date()).addingTimeInterval(Double(pcm.count / 2) / 24_000)
        bytes += pcm.count
        generation += 1
        let mine = generation, end = endsAt
        lock.unlock()
        if !wasPlaying { onPlaying?(true) }
        DispatchQueue.global().asyncAfter(deadline: .now() + max(0, end.timeIntervalSinceNow)) { [weak self] in
            guard let self else { return }
            self.lock.lock(); let current = self.generation == mine; self.lock.unlock()
            if current { self.onPlaying?(false) }
        }
    }

    func flush() {
        lock.lock()
        let wasPlaying = endsAt > Date()
        endsAt = .distantPast
        generation += 1
        lock.unlock()
        if wasPlaying { onPlaying?(false) }
    }
}
#endif

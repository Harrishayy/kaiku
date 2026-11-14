@preconcurrency import AVFoundation
import Foundation
import Speech

/// On-device listening next to Gemini Live (plan 05 §2): Apple speech recognition with
/// `requiresOnDeviceRecognition`, so audio and words never leave the phone. Every partial transcript runs the local
/// safety gate (same phrases + fixture as the hub) and the spoken-dial parser. Nothing is stored. If on-device
/// recognition isn't available for the language, it does not run (Live's own input transcription still goes
/// through the gate in TalkModel).
public final class OnDeviceListener: @unchecked Sendable {
    public enum Hit: Equatable, Sendable {
        case crisis(SafetyHit)
        case dial(Int)
    }

    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private let lock = NSLock()
    public var onHit: (@Sendable (Hit) -> Void)?

    public init() {}

    public static var authorized: Bool { SFSpeechRecognizer.authorizationStatus() == .authorized }

    public static func requestAuthorization() async -> Bool {
        await withCheckedContinuation { c in SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) } }
    }

    static func locale(_ l: KaikuLanguage) -> Locale {
        Locale(identifier: ["en": "en-US", "fi": "fi-FI", "sv": "sv-SE"][l.rawValue] ?? "en-US")
    }

    /// Starts a recognition pass. Returns false (and does nothing) when on-device recognition is unavailable.
    @discardableResult
    public func start(lang: KaikuLanguage) -> Bool {
        guard Self.authorized, let r = SFSpeechRecognizer(locale: Self.locale(lang)), r.isAvailable,
              r.supportsOnDeviceRecognition else { return false }
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.requiresOnDeviceRecognition = true
        req.shouldReportPartialResults = true
        req.addsPunctuation = false
        lock.lock()
        recognizer = r; request = req
        lock.unlock()
        var lastDial: Int?
        task = r.recognitionTask(with: req) { [weak self] result, _ in
            guard let self, let text = result?.bestTranscription.formattedString else { return }
            let v = Self.evaluate(text)
            if let hit = v.crisis { self.onHit?(.crisis(hit)) }
            if let d = v.dial, d != lastDial { lastDial = d; self.onHit?(.dial(d)) }
        }
        return true
    }

    /// The pure part (tested): what one partial transcript means.
    public static func evaluate(_ text: String) -> (crisis: SafetyHit?, dial: Int?) {
        (SafetyGate.shared.check(text), SpokenDial.parse(text))
    }

    public func append(_ buffer: AVAudioPCMBuffer) {
        lock.lock(); let r = request; lock.unlock()
        r?.append(buffer)
    }

    public func stop() {
        lock.lock()
        request?.endAudio()
        task?.cancel()
        request = nil; task = nil; recognizer = nil
        lock.unlock()
    }
}

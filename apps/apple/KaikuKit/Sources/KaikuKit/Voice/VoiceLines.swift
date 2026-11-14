@preconcurrency import AVFoundation
import Foundation
import Network

/// Kaiku's scripted voice on the phone (plan 05 §2): the same keyed lines as the robot (`GET /v1/voice?lang=`),
/// audio prefetched after pairing on Wi-Fi into Caches (`GET /v1/voice/{key}`), played with AVAudioPlayer.
/// Offline / 503 / not cached yet → the on-device synthesizer speaks the same line, so there is always a voice.
/// Cached text also gives notification titles the exact words Kaiku says aloud.
@MainActor
public final class VoiceLines {
    public static let shared = VoiceLines()

    private var player: AVAudioPlayer?
    private let synth = AVSpeechSynthesizer()
    private var prefetching = false
    private var texts: [String: [String: String]] = [:]   // lang → key → text
    /// Silence everything (tests, screenshots: `-kaikuMute YES`).
    public var muted = UserDefaults.standard.bool(forKey: "kaikuMute")

    public init() {}

    static var dir: URL {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
        let d = base.appendingPathComponent("KaikuVoice", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    static func audioURL(_ key: String, _ lang: String) -> URL { dir.appendingPathComponent("\(lang).\(key).wav") }
    static func textURL(_ lang: String) -> URL { dir.appendingPathComponent("lines.\(lang).json") }

    /// The cloud's wording for a line (cached), if known.
    public func text(_ key: String, lang: KaikuLanguage) -> String? {
        if texts[lang.rawValue] == nil, let d = try? Data(contentsOf: Self.textURL(lang.rawValue)),
           let t = try? JSONDecoder().decode([String: String].self, from: d) { texts[lang.rawValue] = t }
        return texts[lang.rawValue]?[key]
    }

    public func cached(_ key: String, lang: KaikuLanguage) -> Bool {
        FileManager.default.fileExists(atPath: Self.audioURL(key, lang.rawValue).path)
    }

    /// After pairing / on foreground: all lines' text, then audio for the ones not cached yet — only on an
    /// unmetered network (Wi-Fi / wired). Stops at the first 503 (no TTS on the cloud: the synthesizer covers it).
    public func prefetch(api: APIClient, lang: KaikuLanguage) async {
        guard !prefetching else { return }
        prefetching = true
        defer { prefetching = false }
        guard await Self.unmetered() else { return }
        guard let r = try? await api.voiceLines(lang: lang.rawValue) else { return }
        texts[lang.rawValue] = r.lines
        if let d = try? JSONEncoder().encode(r.lines) { try? d.write(to: Self.textURL(lang.rawValue), options: .atomic) }
        for key in r.lines.keys.sorted() where !cached(key, lang: lang) {
            guard let wav = await api.voice(key, lang: lang.rawValue) else { break }
            try? wav.write(to: Self.audioURL(key, lang.rawValue), options: .atomic)
        }
    }

    static func unmetered() async -> Bool {
        await withCheckedContinuation { c in
            let m = NWPathMonitor()
            m.pathUpdateHandler = { p in
                m.cancel()
                c.resume(returning: p.status == .satisfied && !p.isExpensive && !p.isConstrained)
            }
            m.start(queue: .global(qos: .utility))
        }
    }

    /// Plays a keyed line: cached audio, else the synthesizer with the cached text (or `fallback`).
    public func play(_ key: String, lang: KaikuLanguage, fallback: String? = nil) {
        guard !muted else { return }
        let url = Self.audioURL(key, lang.rawValue)
        if let p = try? AVAudioPlayer(contentsOf: url) {
            prepareSession()
            synth.stopSpeaking(at: .immediate)
            player = p
            p.play()
            return
        }
        if let t = text(key, lang: lang) ?? fallback { say(t, lang: lang) }
    }

    /// On-device speech, a fixed voice close to Kaiku's (slightly slow, slightly high).
    public func say(_ text: String, lang: KaikuLanguage) {
        guard !muted, !text.isEmpty else { return }
        prepareSession()
        player?.stop()
        let u = AVSpeechUtterance(string: text)
        u.voice = AVSpeechSynthesisVoice(language: Self.locale(lang))
        u.rate = AVSpeechUtteranceDefaultSpeechRate * 0.92
        u.pitchMultiplier = 1.12
        synth.speak(u)
    }

    public func stop() {
        player?.stop()
        synth.stopSpeaking(at: .immediate)
    }

    public var speaking: Bool { synth.isSpeaking || (player?.isPlaying ?? false) }

    static func locale(_ l: KaikuLanguage) -> String {
        switch l {
        case .en: return "en-GB"
        case .fi: return "fi-FI"
        case .sv: return "sv-SE"
        }
    }

    private func prepareSession() {
        #if os(iOS)
        let s = AVAudioSession.sharedInstance()
        // During Talk the session is playAndRecord (TalkAudio); leave it. Otherwise play over silent mode,
        // ducking other audio (podcasts on a walk).
        if s.category != .playAndRecord {
            try? s.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
            try? s.setActive(true)
        }
        #endif
    }
}

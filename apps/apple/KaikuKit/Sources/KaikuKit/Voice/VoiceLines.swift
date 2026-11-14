@preconcurrency import AVFoundation
import CryptoKit
import Foundation
import Network

/// Kaiku's one voice outside a Live conversation (D27): every line is Gemini TTS audio from the cloud, in the same
/// prebuilt voice as Live and the robot (`config/kaiku.toml [voice]`).
///   keyed lines   `GET /v1/voice/{key}`  — prefetched on Wi-Fi after pairing, fetched on demand on a miss
///   other lines   `POST /v1/voice/say`   — the app's own copy ("talk.resumed", …), cached here by text hash
/// Both cached in Caches/KaikuVoice and played with AVAudioPlayer. Never an on-device synthesizer: with no cloud
/// and nothing cached Kaiku stays silent (the text is always on screen) — a robotic voice breaks its warmth.
/// Cached text also gives notification titles the exact words Kaiku says aloud.
@MainActor
public final class VoiceLines {
    public static let shared = VoiceLines()

    private var player: AVAudioPlayer?
    private var prefetching = false
    private var texts: [String: [String: String]] = [:]   // lang → key → text
    /// Bumped by every play/say/stop: a late network answer for an older request stays silent.
    private var request = 0
    /// The cloud client for on-demand fetches (set by prefetch and by Talk).
    public var api: APIClient?
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
    /// Dynamic lines: keyed by a hash of language + normalised text (the cloud caches the same way).
    static func sayURL(_ text: String, _ lang: String) -> URL {
        let h = SHA256.hash(data: Data("\(lang)|\(normalise(text))".utf8)).prefix(10).map { String(format: "%02x", $0) }.joined()
        return dir.appendingPathComponent("say.\(lang).\(h).wav")
    }

    static func normalise(_ text: String) -> String {
        text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

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
    /// unmetered network (Wi-Fi / wired). Stops at the first miss (no TTS on the cloud right now).
    public func prefetch(api: APIClient, lang: KaikuLanguage) async {
        self.api = api
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

    /// Plays a keyed line in Kaiku's Gemini voice: cached audio, else fetched now. A key the service does not know
    /// yet (an older service) falls back to the same words through `/v1/voice/say` when `fallback` is given.
    /// Still Gemini TTS either way; with neither, silent.
    public func play(_ key: String, lang: KaikuLanguage, fallback: String? = nil) {
        guard !muted else { return }
        request += 1
        let id = request
        let url = Self.audioURL(key, lang.rawValue)
        if playFile(url) { return }
        Task {
            if let api, let wav = await api.voice(key, lang: lang.rawValue) {
                try? wav.write(to: url, options: .atomic)
                if id == request { _ = playData(wav) }
                return
            }
            guard id == request, let fallback, !fallback.isEmpty else { return }
            let sayURL = Self.sayURL(fallback, lang.rawValue)
            if playFile(sayURL) { return }
            if let api, let wav = await api.sayAudio(Self.normalise(fallback), lang: lang.rawValue) {
                try? wav.write(to: sayURL, options: .atomic)
                if id == request { _ = playData(wav) }
            }
        }
    }

    /// Says any short line in Kaiku's Gemini voice (`POST /v1/voice/say`, cached); silent when that fails.
    public func say(_ text: String, lang: KaikuLanguage) {
        guard !muted, !text.isEmpty else { return }
        request += 1
        let id = request
        let url = Self.sayURL(text, lang.rawValue)
        if playFile(url) { return }
        Task {
            if let api, let wav = await api.sayAudio(Self.normalise(text), lang: lang.rawValue) {
                try? wav.write(to: url, options: .atomic)
                if id == request { _ = playData(wav) }
                return
            }
        }
    }

    public func stop() {
        request += 1
        player?.stop()
    }

    public var speaking: Bool { player?.isPlaying ?? false }

    private func playFile(_ url: URL) -> Bool {
        guard let d = try? Data(contentsOf: url) else { return false }
        return playData(d)
    }

    private func playData(_ d: Data) -> Bool {
        guard let p = try? AVAudioPlayer(data: d) else { return false }
        prepareSession()
        player?.stop()
        player = p
        p.play()
        return true
    }

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

extension APIClient {
    /// `POST /v1/voice/say {text, lang}` → wav in Kaiku's voice (nil on 422/503/offline: caller falls back).
    public func sayAudio(_ text: String, lang: String) async -> Data? {
        guard var req = try? request("POST", "/v1/voice/say") else { return nil }
        req.httpBody = try? JSONEncoder().encode(["text": String(text.prefix(400)), "lang": lang])
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 20
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200, data.count > 44 else { return nil }
        return data
    }
}

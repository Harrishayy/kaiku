import Foundation
import Observation
import Security
#if os(iOS)
import UIKit
#endif

/// The "Kaiku bot" tab's state: where the robot's broker is, whether the tab is listening, and what it heard.
/// It listens only while the tab is on screen and the app is in front (`setVisible`, `setInFront`); leaving the tab,
/// the app going to the background or the display sleeping closes the connection at once. What it heard is kept in
/// memory only (the last `BotState.feedMax` lines) and is gone when the app quits; nothing is stored or sent on.
@Observable @MainActor
public final class BotModel {
    public static let shared = BotModel()

    public private(set) var state = BotState()
    public private(set) var link: BotLinkState = .idle
    /// The address in use, and where it came from.
    public private(set) var address: BotAddress?
    public private(set) var addressGuessed = false
    /// Messages heard since the tab last connected (the first card says whether anything came at all).
    public private(set) var heardSinceConnect = 0
    /// The feed as it was when Pause was pressed; nil = live.
    public private(set) var frozenFeed: [BotFeedItem]?
    /// `-kaikuBotReplay <file>` (DEBUG): a recording of real envelopes played in instead of the network.
    public private(set) var replaying = false
    public var user: String = ""
    public private(set) var hasPassword = false
    /// "Robot microphone" (D56): this device's microphone stands in for the robot's. Off until the person turns it
    /// on, never remembered across launches. While on, the connection stays up when the page is left.
    public private(set) var micOn = false
    /// The microphone could not start (no permission, no input).
    public private(set) var micFailed = false
    /// Frames sent to the robot since the switch went on, and when the last one left.
    public private(set) var micSent = 0
    public private(set) var micSentAt: Date?
    @ObservationIgnored private var capture: AudioCapture?
    @ObservationIgnored private var robotHome: String?

    @ObservationIgnored private var visible = false
    @ObservationIgnored private var inFront = true
    @ObservationIgnored private var client: BotBusClient?
    @ObservationIgnored private(set) var home: String?
    @ObservationIgnored private var serviceURL: URL?
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var password: String?
    @ObservationIgnored var makeClient: (BotAddress, String?, String?, String?, @escaping @MainActor (BotLinkState) -> Void,
                                         @escaping @MainActor (String, Data) -> Void) -> BotBusClient = {
        BotBusClient(address: $0, home: $1, user: $2, password: $3, onState: $4, onMessage: $5)
    }

    static let addressKey = "kaiku.bot.address"
    static let homeKey = "kaiku.bot.home"
    static let userKey = "kaiku.bot.user"

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        user = defaults.string(forKey: Self.userKey) ?? ""
        password = BotSecret.load()
        hasPassword = password != nil
    }

    public var feed: [BotFeedItem] { frozenFeed ?? state.feed }
    /// Messages that came while the feed is paused (the cards above it go on updating).
    public var newWhilePaused: Int { frozenFeed == nil ? 0 : max(0, state.messages - frozenAt) }
    @ObservationIgnored private var frozenAt = 0
    public var listening: Bool { client != nil || replaying }

    // MARK: when it listens

    /// The paired service tells the address guess (its host, when that is on the home network) and the home id.
    /// A profile the app made for itself on a nearby service (`device-<uuid>`, `ServiceIdentity`) is not a home the
    /// robot publishes under, so then it listens to any home on the broker (`+`); `kaiku.bot.home` names one.
    public func configure(serviceURL: URL?, home: String?) {
        let paired = home.flatMap { $0.hasPrefix("device-") ? nil : $0 }
        let robotHome = defaults.string(forKey: Self.homeKey).flatMap { $0.isEmpty ? nil : $0 } ?? paired
        let changed = serviceURL != self.serviceURL || robotHome != self.home
        self.serviceURL = serviceURL
        self.home = robotHome
        resolveAddress()
        if changed, client != nil { restart() }
    }

    public func setVisible(_ on: Bool) { visible = on; evaluate() }
    public func setInFront(_ on: Bool) { inFront = on; evaluate() }

    private func evaluate() {
        if let path = Self.replayPath, visible {
            if !replaying { replay(path) }
            return
        }
        let should = ((visible && inFront) || micOn) && address != nil
        if should, client == nil { connect() }
        if !should, client != nil { disconnect() }
    }

    private func connect() {
        guard let address else { return }
        let c = makeClient(address, home, user.isEmpty ? nil : user, password, { [weak self] s in
            guard let self else { return }
            if s == .listening, self.link != .listening { self.heardSinceConnect = 0 }
            self.link = s
        }, { [weak self] topic, data in self?.heard(topic, data) })
        client = c
        c.start()
    }

    private func disconnect() {
        client?.stop()
        client = nil
        link = .idle
    }

    private func restart() { disconnect(); evaluate() }

    func heard(_ topic: String, _ data: Data, now: Date = Date()) {
        guard BotTopics.allowed(topic, home: home), let env = BotEnvelope.decode(data) else { return }
        if env.type == "cmd.head" { robotHome = topic.split(separator: "/").dropFirst(2).first.map(String.init) }
        heardSinceConnect += 1
        state.take(env, now: now)
    }

    // MARK: this device as the robot's microphone (D56)

    /// Turn "Robot microphone" on or off. On: ask for the microphone if needed, start capturing (memory only) and
    /// keep the connection. Frames leave only while the hub holds the robot's microphone open (`sendMic`).
    public func setMic(_ on: Bool) async {
        guard on != micOn else { return }
        if !on { stopMic(); return }
        micFailed = false
        var allowed = AudioCapture.permission == .granted
        if !allowed { allowed = await AudioCapture.request() }
        guard allowed, !micOn else { micFailed = !allowed; return }
        let c = AudioCapture()
        let framer = BotMicFramerBox()
        c.onPCM = { [weak self] pcm in
            let frames = framer.feed(pcm)
            guard !frames.isEmpty else { return }
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.sendMic(frames) } }   // in order, off the audio thread
        }
        do { try c.start() } catch { micFailed = true; return }
        capture = c
        micOn = true
        micSent = 0; micSentAt = nil
        #if os(iOS)
        UIApplication.shared.isIdleTimerDisabled = true   // the phone lies beside the robot: its screen stays on
        #endif
        evaluate()
    }

    private func stopMic() {
        _ = capture?.stop()
        capture = nil
        micOn = false
        TalkAudio.deactivate()
        #if os(iOS)
        UIApplication.shared.isIdleTimerDisabled = false
        #endif
        evaluate()
    }

    /// Frames go out only while the hub is holding the robot's microphone open for a conversation; at any other
    /// time what this device hears is dropped here and never leaves it.
    func sendMic(_ frames: [Data], now: Date = Date()) {
        guard micOn, let client, state.micHeld(now: now) else { return }
        for f in frames where client.sendMicFrame(f, home: home ?? robotHome) {
            micSent += 1
            micSentAt = now
        }
    }

    // MARK: what the person sets

    private func resolveAddress() {
        if let a = Self.launchAddress {
            address = a; addressGuessed = false
        } else if let a = defaults.string(forKey: Self.addressKey).flatMap(BotAddress.parse) {
            address = a; addressGuessed = false
        } else {
            address = BotAddress.guess(serviceURL: serviceURL); addressGuessed = address != nil
        }
    }

    /// The robot's address as typed. Empty = back to the guess. Returns false when it is not an address.
    @discardableResult
    public func setAddress(_ text: String) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            defaults.removeObject(forKey: Self.addressKey)
        } else {
            guard let a = BotAddress.parse(trimmed) else { return false }
            defaults.set(a.text, forKey: Self.addressKey)
        }
        resolveAddress()
        restart()
        return true
    }

    /// A name and password for a broker that asks for them. The password goes to the Keychain only.
    public func setSignIn(user: String, password: String?) {
        let u = user.trimmingCharacters(in: .whitespacesAndNewlines)
        self.user = u
        if u.isEmpty { defaults.removeObject(forKey: Self.userKey) } else { defaults.set(u, forKey: Self.userKey) }
        if let password {
            if password.isEmpty { BotSecret.clear(); self.password = nil } else { BotSecret.save(password); self.password = password }
        }
        hasPassword = self.password != nil
        restart()
    }

    public func pause(_ on: Bool) { frozenFeed = on ? state.feed : nil; frozenAt = state.messages }

    public func clear() { state = BotState(); frozenFeed = nil; heardSinceConnect = 0 }

    // MARK: launch arguments (`-kaiku…`, like the rest of the app)

    /// `-kaikuBotAddress host[:port]`: the address for this run only (tests, pictures); never remembered.
    static var launchAddress: BotAddress? {
        UserDefaults.standard.string(forKey: "kaikuBotAddress").flatMap(BotAddress.parse)
    }

    static var replayPath: String? {
        #if DEBUG
        return UserDefaults.standard.string(forKey: "kaikuBotReplay")
        #else
        return nil
        #endif
    }

    /// Plays a recording in (JSON lines `{"t": seconds, "topic": "...", "envelope": {...}}`, as `BotRecording`
    /// writes them from a real run): each message lands as long ago as it was before the recording's last one.
    func replay(_ path: String, now: Date = Date()) {
        replaying = true
        link = .listening
        guard let lines = BotRecording.read(URL(fileURLWithPath: path)), let last = lines.last?.t else { return }
        for l in lines { heard(l.topic, l.data, now: now.addingTimeInterval(l.t - last)) }
    }
}

/// A recording of what came over the broker, for the picture runs and tests: one JSON object per line.
public enum BotRecording {
    public struct Line { public var t: Double; public var topic: String; public var data: Data }

    public static func line(t: Double, topic: String, payload: Data) -> String? {
        guard let env = try? JSONSerialization.jsonObject(with: payload) else { return nil }
        let obj: [String: Any] = ["t": (t * 1000).rounded() / 1000, "topic": topic, "envelope": env]
        guard let d = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]) else { return nil }
        return String(data: d, encoding: .utf8)
    }

    public static func read(_ url: URL) -> [Line]? {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        return text.split(separator: "\n").compactMap { raw in
            guard let obj = try? JSONSerialization.jsonObject(with: Data(raw.utf8)) as? [String: Any],
                  let t = obj["t"] as? Double, let topic = obj["topic"] as? String, let env = obj["envelope"],
                  let data = try? JSONSerialization.data(withJSONObject: env) else { return nil }
            return Line(t: t, topic: topic, data: data)
        }
    }
}

/// The broker password (only for a broker that asks for one) lives in the Keychain, never in UserDefaults or a
/// file. Mac debug builds are ad-hoc signed and every rebuild would make the login Keychain ask again, so there it
/// is kept for the run only (like `PairingStore` keeps those builds out of the Keychain).
enum BotSecret {
    static let service = "fi.kaiku.robotbus"
    static let account = "broker"
    #if os(macOS) && DEBUG
    static let useKeychain = false
    #else
    static let useKeychain = true
    #endif

    static func load() -> String? {
        guard useKeychain else { return nil }
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: account, kSecReturnData as String: true,
                                kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    @discardableResult
    static func save(_ password: String) -> Bool {
        guard useKeychain else { return false }
        clear()
        var add: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                  kSecAttrAccount as String: account, kSecValueData as String: Data(password.utf8)]
        #if os(iOS)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        #endif
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }

    static func clear() {
        guard useKeychain else { return }
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: account]
        SecItemDelete(q as CFDictionary)
    }
}

/// The framer behind a lock: fed on the audio thread, one capture at a time.
final class BotMicFramerBox: @unchecked Sendable {
    private var framer = BotMicFramer()
    private let lock = NSLock()
    func feed(_ pcm: Data) -> [Data] {
        lock.lock(); defer { lock.unlock() }
        return framer.feed(pcm)
    }
}

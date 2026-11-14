import Foundation
import Security

/// Companion service configuration: origin, private home profile and scoped token when required.
/// Local demo services can provision a stable device profile through discovery; authenticated services use an
/// account access link. Robot hardware and Meta registration are independent of this service connection.
public struct Pairing: Codable, Sendable, Equatable {
    public var baseURL: URL
    public var homeID: String
    public var token: String?

    public init(baseURL: URL, homeID: String, token: String?) {
        self.baseURL = baseURL
        self.homeID = homeID
        self.token = token
    }

    private static let homePattern = try! NSRegularExpression(pattern: "^[a-z0-9][a-z0-9_-]{0,63}$")

    /// Parses a pasted or scanned link. Accepts a full URL (http/https) or `kaiku://pair?...`. Returns nil for
    /// anything that is not a Kaiku pairing link (no home, bad home id, no host).
    public static func parse(_ raw: String) -> Pairing? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let comps = URLComponents(string: text), let items = comps.queryItems else { return nil }
        guard let home = items.first(where: { $0.name == "home" })?.value?.lowercased(),
              homePattern.firstMatch(in: home, range: NSRange(home.startIndex..., in: home)) != nil else { return nil }
        let token = items.first(where: { $0.name == "t" })?.value.flatMap { $0.isEmpty ? nil : $0 }
        var base = URLComponents()
        if comps.scheme == "kaiku" {
            // kaiku://pair?home=&t=&cloud=https://…
            guard let cloud = items.first(where: { $0.name == "cloud" })?.value, let c = URLComponents(string: cloud),
                  let s = c.scheme, ["http", "https"].contains(s), c.host != nil else { return nil }
            base.scheme = c.scheme; base.host = c.host; base.port = c.port
        } else {
            guard let s = comps.scheme?.lowercased(), ["http", "https"].contains(s), let host = comps.host, !host.isEmpty
            else { return nil }
            base.scheme = s; base.host = host; base.port = comps.port
        }
        guard let url = base.url else { return nil }
        return Pairing(baseURL: url, homeID: home, token: token)
    }
}

/// Keychain storage for the pairing (the token is a secret: never in UserDefaults, never logged).
/// Falls back to a file in Application Support only when the Keychain refuses (unsigned simulator builds).
///
/// Mac DEBUG builds skip the Keychain entirely and use a 0600 file: they are ad-hoc signed, so every rebuild is a
/// "new" app to the legacy macOS keychain and it asks for the login password again and again (blocks autonomous
/// development). iOS and Mac RELEASE builds keep the Keychain.
public enum PairingStore {
    static let service = "fi.kaiku.pairing"
    static let account = "home"

    #if os(macOS) && DEBUG
    static let useKeychain = false
    #else
    static let useKeychain = true
    #endif

    public static func load() -> Pairing? {
        guard useKeychain else { return loadFile() }
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: account, kSecReturnData as String: true,
                                kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        if SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data,
           let p = try? JSONDecoder().decode(Pairing.self, from: data) {
            return p
        }
        return loadFile()
    }

    static func loadFile() -> Pairing? {
        guard let data = try? Data(contentsOf: fallbackURL) else { return nil }
        return try? JSONDecoder().decode(Pairing.self, from: data)
    }

    static func saveFile(_ data: Data) -> Bool {
        try? FileManager.default.createDirectory(at: fallbackURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        #if os(iOS)
        return (try? data.write(to: fallbackURL, options: [.atomic, .completeFileProtection])) != nil
        #else
        guard (try? data.write(to: fallbackURL, options: .atomic)) != nil else { return false }
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fallbackURL.path)
        return true
        #endif
    }

    @discardableResult
    public static func save(_ p: Pairing) -> Bool {
        guard let data = try? JSONEncoder().encode(p) else { return false }
        clear()
        guard useKeychain else { return saveFile(data) }
        var add: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                  kSecAttrAccount as String: account, kSecValueData as String: data]
        #if os(iOS)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        #endif
        if SecItemAdd(add as CFDictionary, nil) == errSecSuccess { return true }
        return saveFile(data)
    }

    public static func clear() {
        if !useKeychain {
            try? FileManager.default.removeItem(at: fallbackURL)
            return
        }
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: account]
        SecItemDelete(q as CFDictionary)
        try? FileManager.default.removeItem(at: fallbackURL)
    }

    static var fallbackURL: URL { KaikuPaths.support.appendingPathComponent("pairing.json") }
}

public enum KaikuPaths {
    public static var support: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = base.appendingPathComponent("Kaiku", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }
}

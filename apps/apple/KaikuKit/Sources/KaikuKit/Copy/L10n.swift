import Foundation
import SwiftUI

/// Every user-facing string comes from here. Ground truth: `design/copy.json` (bundled as `copy.json`).
/// `copy.apple.json` holds the few keys the Apple app needs that copy.json does not have yet (same shape, en + fi);
/// they are listed in apps/apple/AGENTS.md → Known issues so the design owner can upstream them.
/// Languages: en, fi (sv falls back to en until copy.json has Swedish).
public enum KaikuLanguage: String, CaseIterable, Sendable, Identifiable {
    case en, fi, sv
    public var id: String { rawValue }

    /// Display name in its own language (endonym), shown in the language picker.
    public var endonym: String {
        switch self {
        case .en: return "English"
        case .fi: return "Suomi"
        case .sv: return "Svenska"
        }
    }

    public static var system: KaikuLanguage {
        for id in Locale.preferredLanguages {
            let code = String(id.prefix(2)).lowercased()
            if let l = KaikuLanguage(rawValue: code) { return l }
        }
        return .en
    }
}

public final class L10n: @unchecked Sendable {
    public static let shared = L10n()

    private let tables: [String: [String: String]]
    private let lock = NSLock()
    private var _language: KaikuLanguage = .system

    public var language: KaikuLanguage {
        get { lock.lock(); defer { lock.unlock() }; return _language }
        set { lock.lock(); _language = newValue; lock.unlock() }
    }

    init(bundle: Bundle = .module) {
        var merged: [String: [String: String]] = [:]
        for name in ["copy", "copy.apple"] {
            guard let url = bundle.url(forResource: name, withExtension: "json"),
                  let data = try? Data(contentsOf: url),
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            for (lang, value) in obj where !lang.hasPrefix("$") {
                guard let table = value as? [String: String] else { continue }
                merged[lang, default: [:]].merge(table) { _, new in new }
            }
        }
        tables = merged
    }

    public func has(_ key: String, _ lang: KaikuLanguage? = nil) -> Bool {
        tables[(lang ?? language).rawValue]?[key] != nil
    }

    public func keys(_ lang: KaikuLanguage) -> Set<String> { Set(tables[lang.rawValue].map { Array($0.keys) } ?? []) }

    /// Looks up `key` in the current language, then English. A missing key returns the key itself in DEBUG so it
    /// is caught in screenshots, and an empty string in release (never dev text on screen).
    public func string(_ key: String, _ args: [String: String] = [:], lang: KaikuLanguage? = nil) -> String {
        let l = lang ?? language
        var s = tables[l.rawValue]?[key] ?? tables["en"]?[key]
        if s == nil {
            #if DEBUG
            s = "⟨\(key)⟩"
            #else
            s = ""
            #endif
        }
        var out = s!
        for (k, v) in args { out = out.replacingOccurrences(of: "{\(k)}", with: v) }
        return out
    }
}

/// Short alias used across the UI: `T("today.card.weather.t")`, `T("br.count", n: 3)`.
public func T(_ key: String) -> String { L10n.shared.string(key) }
public func T(_ key: String, n: Int) -> String { L10n.shared.string(key, ["n": String(n)]) }
public func T(_ key: String, _ args: [String: String]) -> String { L10n.shared.string(key, args) }

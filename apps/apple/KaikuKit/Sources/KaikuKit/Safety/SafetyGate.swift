import Foundation

/// The deterministic crisis phrase check, ported line by line from `kaiku_contracts/safety.py` (same as the hub
/// gate). Reads the bundled copy of `config/safety_phrases.toml`. No model, no network. A hit carries only the list
/// phrase, never the person's words. Agreement with the Python matcher: KaikuKitTests/SafetyGateTests runs
/// `tools/companion_evals/fixtures/safety_cases.json`.
public struct SafetyHit: Equatable, Sendable {
    public let phrase: String
    public let language: String
}

public final class SafetyGate: @unchecked Sendable {
    public static let shared: SafetyGate = {
        guard let url = Bundle.module.url(forResource: "safety_phrases", withExtension: "toml"),
              let text = try? String(contentsOf: url, encoding: .utf8) else {
            // Never silently disable the gate: an empty list here is a build error the tests catch.
            return SafetyGate(phrases: [], scripts: [:])
        }
        return SafetyGate(toml: text)
    }()

    /// (language, phrase, compiled pattern), in file order — the first hit wins, exactly as in Python.
    private let patterns: [(String, String, NSRegularExpression)]
    public let scripts: [String: String]
    public let phraseCount: Int

    public init(phrases: [(String, [String])], scripts: [String: String]) {
        var pats: [(String, String, NSRegularExpression)] = []
        var n = 0
        for (lang, items) in phrases {
            for phrase in items {
                n += 1
                for v in Self.variants(phrase) where !v.isEmpty {
                    let p = "(?<!\\w)" + NSRegularExpression.escapedPattern(for: v)
                    if let re = try? NSRegularExpression(pattern: p) { pats.append((lang, phrase, re)) }
                }
            }
        }
        patterns = pats
        self.scripts = scripts
        phraseCount = n
    }

    public convenience init(toml: String) {
        let parsed = MiniTOML.parse(toml)
        var phrases: [(String, [String])] = []
        var scripts: [String: String] = [:]
        for (section, table) in parsed {
            if section == "script" {
                for (k, v) in table { if case .string(let s) = v { scripts[k] = s } }
            } else if case .array(let items)? = table.first(where: { $0.0 == "phrases" })?.1 {
                phrases.append((section, items))
            }
        }
        self.init(phrases: phrases, scripts: scripts)
    }

    public func check(_ text: String) -> SafetyHit? {
        guard !text.isEmpty else { return nil }
        for variant in Self.variants(text) {
            let range = NSRange(variant.startIndex..., in: variant)
            for (lang, phrase, re) in patterns where re.firstMatch(in: variant, range: range) != nil {
                return SafetyHit(phrase: phrase, language: lang)
            }
        }
        return nil
    }

    /// The pre-written crisis message (never generated), in the person's language when it exists.
    public func script(_ language: String) -> String {
        scripts[language] ?? scripts["en"] ?? ""
    }

    // MARK: normalisation (kaiku_contracts.safety.normalise)

    private static let apostrophes: [Character: Character] = ["’": "'", "‘": "'", "`": "'", "´": "'", "ʼ": "'"]
    private static let nonText = try! NSRegularExpression(pattern: "[^\\w\\s']+")
    private static let ws = try! NSRegularExpression(pattern: "\\s+")

    public static func normalise(_ text: String) -> String {
        var t = text.precomposedStringWithCompatibilityMapping
        t = String(t.map { apostrophes[$0] ?? $0 })
        t = t.folding(options: [.caseInsensitive], locale: nil).lowercased()
        t = t.replacingOccurrences(of: "-", with: " ")
        t = nonText.stringByReplacingMatches(in: t, range: NSRange(t.startIndex..., in: t), withTemplate: " ")
        t = ws.stringByReplacingMatches(in: t, range: NSRange(t.startIndex..., in: t), withTemplate: " ")
        return t.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func variants(_ text: String) -> [String] {
        let n = normalise(text)
        let m = n.replacingOccurrences(of: "'", with: "")
        return n == m ? [n] : [n, m]
    }
}

/// Just enough TOML for `config/safety_phrases.toml`: `[section]` headers, `key = "string"` and
/// `key = [ "a", "b", ]` (multi-line), `#` comments, basic-string escapes. Keeps file order.
enum MiniTOML {
    enum Value: Equatable { case string(String), array([String]) }

    static func parse(_ text: String) -> [(String, [(String, Value)])] {
        var out: [(String, [(String, Value)])] = []
        var section = ""
        var chars = Array(text)
        var i = 0

        func skipSpaceAndComments() {
            while i < chars.count {
                if chars[i] == "#" { while i < chars.count, chars[i] != "\n" { i += 1 } }
                else if chars[i].isWhitespace { i += 1 }
                else { break }
            }
        }
        func readString() -> String? {
            guard i < chars.count, chars[i] == "\"" else { return nil }
            i += 1
            var s = ""
            while i < chars.count, chars[i] != "\"" {
                if chars[i] == "\\", i + 1 < chars.count {
                    i += 1
                    switch chars[i] { case "n": s.append("\n"); case "t": s.append("\t"); default: s.append(chars[i]) }
                } else { s.append(chars[i]) }
                i += 1
            }
            i += 1
            return s
        }
        func append(_ key: String, _ v: Value) {
            if let idx = out.firstIndex(where: { $0.0 == section }) { out[idx].1.append((key, v)) }
            else { out.append((section, [(key, v)])) }
        }

        chars = Array(text)
        while true {
            skipSpaceAndComments()
            guard i < chars.count else { break }
            if chars[i] == "[" {
                i += 1
                var name = ""
                while i < chars.count, chars[i] != "]" { name.append(chars[i]); i += 1 }
                i += 1
                section = name.trimmingCharacters(in: .whitespaces)
                continue
            }
            var key = ""
            while i < chars.count, chars[i] != "=", chars[i] != "\n" { key.append(chars[i]); i += 1 }
            key = key.trimmingCharacters(in: .whitespaces)
            guard i < chars.count, chars[i] == "=" else { continue }
            i += 1
            skipSpaceAndComments()
            if i < chars.count, chars[i] == "[" {
                i += 1
                var items: [String] = []
                while true {
                    skipSpaceAndComments()
                    guard i < chars.count else { break }
                    if chars[i] == "]" { i += 1; break }
                    if chars[i] == "," { i += 1; continue }
                    if let s = readString() { items.append(s) } else { i += 1 }
                }
                append(key, .array(items))
            } else if let s = readString() {
                append(key, .string(s))
            } else {
                while i < chars.count, chars[i] != "\n" { i += 1 }
            }
        }
        return out
    }
}

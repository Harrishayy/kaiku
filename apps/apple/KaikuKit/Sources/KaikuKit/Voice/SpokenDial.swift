import Foundation

/// Rule-based parser for spoken weather-check answers (plan 05 §2): "pretty tired, maybe a two" → 2,
/// "kakkonen" → 2, "en tvåa" → 2. Runs on the on-device partial transcript; the transcript itself is never stored
/// or sent. The last number word wins ("three, no, a two" → 2), "out of five" style tails are ignored.
public enum SpokenDial {
    static let words: [String: Int] = [
        // en
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        // fi (numerals, colloquial, and the "-nen" noun forms people use for grades)
        "yksi": 1, "yks": 1, "ykkönen": 1, "ykkösen": 1,
        "kaksi": 2, "kaks": 2, "kakkonen": 2, "kakkosen": 2,
        "kolme": 3, "kolmonen": 3, "kolmosen": 3,
        "neljä": 4, "nelonen": 4, "nelosen": 4,
        "viisi": 5, "viis": 5, "vitonen": 5, "vitosen": 5,
        // sv ("en"/"ett" are also the article, so only the noun form "etta" counts as 1)
        "etta": 1, "ettan": 1,
        "två": 2, "tvåa": 2, "tvåan": 2,
        "tre": 3, "trea": 3, "trean": 3,
        "fyra": 4, "fyran": 4,
        "fem": 5, "femma": 5, "femman": 5,
    ]

    /// "out of five", "of 5", "/5", "av fem", "viidestä" — the scale, not the answer.
    static let scaleTail = try! NSRegularExpression(
        pattern: "(?:\\bout of\\b|\\bof\\b|/|\\bav\\b)\\s*(?:five|5|fem)\\b|\\bviidestä\\b", options: [.caseInsensitive])

    public static func parse(_ text: String) -> Int? {
        var s = text.lowercased()
        s = scaleTail.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: " ")
        let tokens = s.components(separatedBy: CharacterSet.letters.union(.decimalDigits).inverted).filter { !$0.isEmpty }
        var found: Int?
        for t in tokens {
            if let n = Int(t), (1...5).contains(n) { found = n }
            else if let n = words[t] { found = n }
        }
        return found
    }
}

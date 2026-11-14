import Foundation

/// Live's transcription sometimes hands over markers instead of words (`<no speech>`, `{pause}`, `<noise>`), and
/// sometimes in pieces (`<no`, ` speech`, `>`). They are not something anyone said. This takes them out of a
/// stream of fragments: text that begins inside `<…>` or `{…}` is a marker in progress until it closes.
struct MarkerFilter: Sendable {
    /// The longest thing taken for a marker; a "<" followed by more than this without closing is ordinary text.
    static let limit = 32
    private var pending = ""                  // an open marker so far, with its opening character
    private var closer: Character = ">"

    /// A marker has opened and not closed yet.
    var inMarker: Bool { !pending.isEmpty }

    /// What is left of this fragment once markers are taken out.
    mutating func feed(_ fragment: String) -> String {
        var out = ""
        for ch in fragment {
            if ch == "<" || ch == "{" {       // a marker opens (or opens again: a repeated, cumulative fragment)
                pending = String(ch)
                closer = ch == "<" ? ">" : "}"
            } else if pending.isEmpty {
                out.append(ch)
            } else if ch == closer {
                pending = ""
            } else {
                pending.append(ch)
                if pending.count > Self.limit { out += pending; pending = "" }
            }
        }
        return out
    }

    /// The turn ended: a marker that never closed goes with it.
    mutating func reset() { pending = "" }

    /// One whole text with its markers taken out (an unclosed one included).
    static func clean(_ text: String) -> String {
        var f = MarkerFilter()
        return f.feed(text)
    }
}

/// What the transcription of a model turn says so far (pure): something was really said, it is sound and not
/// speech, or it cannot be told yet.
enum Heard: Equatable, Sendable {
    /// A letter or a digit outside markers.
    case word
    /// A marker closed and no word came before it.
    case notSpeech
    /// Nothing yet, white space, a stray mark, or a marker still arriving in pieces.
    case undecided

    init(_ transcription: String) {
        var f = MarkerFilter()
        let left = f.feed(transcription)
        if left.contains(where: { $0.isLetter || $0.isNumber }) { self = .word }
        else if f.inMarker { self = .undecided }
        else { self = transcription.contains(where: { $0 == ">" || $0 == "}" }) ? .notSpeech : .undecided }
    }
}

import XCTest
@testable import KaikuKit

// The app's copy linter for faces and cameras. Kaiku counts how a face moves during a game or a check-in, with the
// person's opt-in, on the device. Nothing on a screen may turn that into a remark about her face, a claim that
// Kaiku or a camera watched her, or a feeling read off a face.
//
// Two rules:
// 1. `FaceTalk`: the cloud's wording rule `face_talk` (contracts/python/kaiku_contracts/wording.py), ported pattern
//    for pattern with its one exception ("I can't see your face" is the honest answer). A test reads the Python
//    source and fails when the two lists differ, so the port cannot drift.
// 2. `FaceClaims`: what on-screen copy must not say beyond that: an emotion named as detected, a feeling said to
//    show ("looked sad"), Kaiku said to have seen or watched the person.

/// The cloud's `face_talk` rule in Swift.
enum FaceTalk {
    /// The same strings as the arguments of `"face_talk": _rx(...)`, in the same order.
    static let parts: [String] = [
        #"your (?:face|facial|expressions?|smiles?|frowns?|brows?|eyebrows?|blink(?:s|ing)?|gaze)(?!\w)"#,
        #"you(?:'re| are| were| weren't| aren't| look| looked| seem| seemed| don't| didn't| did not| do not)? (?:not )?(?:smil(?:e|ed|ing)|frown(?:ed|ing)?|blink(?:ed|ing)?)(?!\w)"#,
        #"you look(?:ed|s)? (?:so |really |a bit |a little |quite |very |more |less )?(?:tired|sleepy|exhausted|worn|pale|quiet|quieter|flat|blank|serious|tense|worried|upset|happy|happier|cheerful|bright|brighter|glum|unhappy|miserable|well|good|better|rough|different)"#,
        #"(?:look|expression|smile) on your face"#,
        #"how you look(?:ed)?"#,
        #"i (?:can |could |did )?(?:see|saw|watch|watched|notice|noticed) (?:your face|you smil|you frown|you blink|how you look|that you look|you look)"#,
        #"(?:i|we) (?:was|were|am|are|have been|'ve been) watching you"#,
        #"watch(?:ed|ing) your face"#,
        #"(?:the |your |my )?camera (?:saw|showed|shows|noticed|picked up|caught|could see|can see|was watching|watched|told me|says)"#,
        #"(?:saw|seen|watched|noticed) (?:you |it |that )?(?:on|through|with) (?:the |your |my )?camera"#,
        #"kasvosi"#, #"ilmeesi"#, #"hymysi"#, #"näytät (?:väsyneeltä|surulliselta|iloiselta)"#, #"näin kasvosi"#,
        #"ditt ansikte"#, #"ditt leende"#, #"du ser (?:trött|ledsen|glad) ut"#, #"din min(?!\w)"#,
    ]

    /// `_rx`: every pattern starts at a word boundary.
    static func rule(_ parts: [String]) -> NSRegularExpression {
        try! NSRegularExpression(pattern: parts.map { #"(?<!\w)(?:"# + $0 + ")" }.joined(separator: "|"))
    }
    static let pattern = rule(parts)

    /// `_CANNOT_SEE`: the words just before a match that make it the honest answer, not a remark.
    static let cannotSee = try! NSRegularExpression(
        pattern: #"(?:can't|cannot|can not|don't|do not|never|not able to|no way to) (?:really |ever |actually )?(?:see|watch|look at)(?: you| you or)? $"#)

    /// `normalise`: compatibility form, one kind of apostrophe, lower case, single spaces.
    static func normalise(_ text: String) -> String {
        var t = text.precomposedStringWithCompatibilityMapping
        for a in ["’", "‘", "`", "´", "ʼ"] { t = t.replacingOccurrences(of: a, with: "'") }
        t = t.lowercased()
        return t.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    /// The matched fragment, or nil when the text is clean.
    static func issue(in text: String) -> String? {
        let n = normalise(text) as NSString
        for m in pattern.matches(in: n as String, range: NSRange(location: 0, length: n.length)) {
            let from = max(0, m.range.location - 40)
            let before = n.substring(with: NSRange(location: from, length: m.range.location - from))
            if cannotSee.firstMatch(in: before, range: NSRange(location: 0, length: (before as NSString).length)) != nil { continue }
            return n.substring(with: m.range)
        }
        return nil
    }
}

/// What on-screen copy must not claim about a face, beyond the voice's rule.
enum FaceClaims {
    static let parts: [String] = [
        // An emotion named as found: "emotion detected", "emotions recognised", "emotion recognition".
        #"emotions? (?:is |are |was |were )?(?:detected|recogni[sz]ed|identified|measured|found)"#,
        #"emotion (?:recognition|detection|detector|analysis)"#,
        #"(?:detect|recogni[sz]e|identif(?:y|ie)|infer)(?:s|d|ed|ing)? (?:your |her |his |their |the |an? )?(?:emotions?|feelings?|moods?)"#,
        // A feeling said to show: "looked sad", "seems happy", "a sad face".
        #"(?:look|looks|looked|looking|seem|seems|seemed) (?:so |really |a bit |a little |quite |very |more |less )?(?:sad|happy|angry|anxious|upset|stressed|depressed|worried|tired|unhappy|miserable)(?!\w)"#,
        #"(?:sad|happy|angry|anxious|worried|tired|upset) (?:face|expression|look)(?!\w)"#,
        // Kaiku said to have seen or watched the person. (During a walk with "Let Kaiku see" on, Kaiku does see
        // pictures of what is in front of the glasses: "Kaiku saw 12 pictures" is true and is not this.)
        #"kaiku (?:saw|sees|watched|watches|is watching|was watching|can see|could see|looked at|looks at|noticed|notices) (?:you|your face|how you)(?!\w)"#,
    ]
    static let pattern = FaceTalk.rule(parts)

    static func issue(in text: String) -> String? {
        let n = FaceTalk.normalise(text) as NSString
        return pattern.firstMatch(in: n as String, range: NSRange(location: 0, length: n.length)).map { n.substring(with: $0.range) }
    }
}

final class CopyWordingTests: XCTestCase {
    // MARK: the port

    /// The lines the cloud's own test flags (contracts/tests/test_face_signs.py).
    func testThePortFlagsWhatTheCloudsRuleFlags() {
        for line in ["You looked tired during the game.", "I noticed you weren't smiling much today.", "You didn't smile once.",
                     "Your face seemed quieter in the lantern game.", "The camera showed you were blinking a lot.",
                     "I saw you on the camera earlier.", "I could see your face drop.", "You look a bit flat today.",
                     "I was watching you play.", "That put a smile on your face.", "Your expression changed."] {
            XCTAssertNotNil(FaceTalk.issue(in: line), line)
        }
    }

    /// And the lines it leaves alone.
    func testHonestAndOrdinaryLinesAreNotFlagged() {
        for line in ["Close your eyes if you like, and breathe out slowly.", "The camera is off, so I can't see it.",
                     "Good to see you. I'm around later.", "I can hear the smile in that.", "You looked at the lake this morning?",
                     "I can't see your face, or you at all.", "No, I never see your face.", "You look after everyone, don't you.",
                     "I can't see you. If Camera during activities is on, your phone counts how the face moves during games, "
                     + "keeps numbers only, and you can switch it off under You."] {
            XCTAssertNil(FaceTalk.issue(in: line), line)
        }
    }

    func testTheTextIsNormalisedTheWayTheCloudDoesIt() {
        XCTAssertEqual(FaceTalk.normalise("  You’re   SMILING\n again "), "you're smiling again")
        XCTAssertNotNil(FaceTalk.issue(in: "You’re   SMILING again"))
        XCTAssertNotNil(FaceTalk.issue(in: "Näin kasvosi."))
        XCTAssertNotNil(FaceTalk.issue(in: "Du ser trött ut."))
        XCTAssertNotNil(FaceTalk.issue(in: "Din min säger allt."))
        XCTAssertNil(FaceTalk.issue(in: "En gardin minskar ljuset."), "a pattern starts at a word boundary, and \"din min\" ends at one")
    }

    /// The Swift list is the Python list: the arguments of `"face_talk": _rx(...)`, read from the source.
    func testThePortIsTheCloudsRulePatternForPattern() throws {
        let source = try String(contentsOf: repoRoot.appendingPathComponent("contracts/python/kaiku_contracts/wording.py"), encoding: .utf8)
        let lines = source.components(separatedBy: "\n")
        let start = try XCTUnwrap(lines.firstIndex { $0.trimmingCharacters(in: .whitespaces).hasPrefix("\"face_talk\": _rx(") })
        let end = try XCTUnwrap(lines[(start + 1)...].firstIndex { $0.trimmingCharacters(in: .whitespaces) == ")," })
        // Raw string literals; neighbours with no comma between them are one argument (Python joins them).
        let literal = try NSRegularExpression(pattern: #"r"((?:[^"\\]|\\.)*)"(\s*,)?"#)
        var python: [String] = [], open = ""
        for line in lines[(start + 1)..<end] where !line.trimmingCharacters(in: .whitespaces).hasPrefix("#") {
            let ns = line as NSString
            for m in literal.matches(in: line, range: NSRange(location: 0, length: ns.length)) {
                open += ns.substring(with: m.range(at: 1))
                if m.range(at: 2).location != NSNotFound { python.append(open); open = "" }
            }
        }
        XCTAssertTrue(open.isEmpty, "an argument without its comma: \(open)")
        XCTAssertGreaterThan(python.count, 15)
        XCTAssertEqual(FaceTalk.parts, python, "contracts/python/kaiku_contracts/wording.py face_talk changed: port the change to FaceTalk.parts")
        let cannot = try XCTUnwrap(lines.firstIndex { $0.hasPrefix("_CANNOT_SEE = re.compile(") })
        var exception = ""
        for line in lines[cannot...(cannot + 1)] {
            let ns = line as NSString
            for m in literal.matches(in: line, range: NSRange(location: 0, length: ns.length)) { exception += ns.substring(with: m.range(at: 1)) }
        }
        XCTAssertEqual(FaceTalk.cannotSee.pattern, exception)
    }

    // MARK: on-screen claims

    func testClaimsAboutAFaceAreFlagged() {
        for line in ["Emotion detected: sad", "Emotions recognised during the game", "Kaiku uses emotion recognition",
                     "The camera detects your mood", "You looked sad during the check-in", "She seems happy today",
                     "A sad face in the lantern game", "Kaiku saw you smile", "Kaiku is watching you", "Kaiku noticed how you looked"] {
            XCTAssertTrue(FaceClaims.issue(in: line) != nil || FaceTalk.issue(in: line) != nil, line)
        }
        for line in ["Emotion detected: sad", "Emotions recognised during the game", "Kaiku uses emotion recognition", "The camera detects your mood",
                     "It looked sad", "She seems happy today", "A sad face in the lantern game", "Kaiku is watching you"] {
            XCTAssertNotNil(FaceClaims.issue(in: line), line)
        }
    }

    func testWhatTheAppTrulySaysIsNotFlagged() {
        for line in ["No pictures are kept or sent, and Kaiku does not label emotions.",
                     "Kaiku saw 12 pictures. None were saved.", "Kaiku can see · 3 pictures sent, none saved",
                     "whether you look toward the screen, and how much your head and face move",
                     "Camera on: face movement only", "Look down the path and tell me what is there.", "Mood"] {
            XCTAssertNil(FaceClaims.issue(in: line), line)
            XCTAssertNil(FaceTalk.issue(in: line), line)
        }
    }

    /// Every line of the app's copy, in both languages and both files, against both rules.
    func testNoLineOfTheAppsCopySaysKaikuSawThePersonOrReadsAFeelingOffAFace() throws {
        var checked = 0
        for file in ["design/copy.json", "apps/apple/KaikuKit/Sources/KaikuKit/Resources/copy.apple.json"] {
            let all = try XCTUnwrap(json(file) as? [String: Any])
            for (lang, table) in all {
                guard let lines = table as? [String: String] else { continue }
                for (key, text) in lines {
                    checked += 1
                    XCTAssertNil(FaceTalk.issue(in: text), "\(file) \(lang) \(key): \(text)")
                    XCTAssertNil(FaceClaims.issue(in: text), "\(file) \(lang) \(key): \(text)")
                }
            }
        }
        XCTAssertGreaterThan(checked, 1000)
    }
}

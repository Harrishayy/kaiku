import XCTest
@testable import KaikuKit

/// Kaiku's voice never starts by itself on a screen (2026-11-15): a line is spoken for a press, or inside a chat
/// that is showing. Opening Talk does not open a call.
@MainActor
final class VoiceOriginTests: XCTestCase {
    func testAChatLineIsSpokenOnlyWhileAChatScreenIsShowing() {
        let v = VoiceLines()
        XCTAssertTrue(v.allows(.pressed), "a press to hear Kaiku always may")
        XCTAssertFalse(v.allows(.chat), "no chat on screen: a chat line that arrives now stays silent")
        v.chat("talk", showing: true)
        XCTAssertTrue(v.allows(.chat))
        v.chat("checkin", showing: true)
        v.chat("talk", showing: false)
        XCTAssertTrue(v.allows(.chat), "the check-in chat is still showing")
        v.chat("checkin", showing: false)
        XCTAssertFalse(v.allows(.chat))
        v.chat("talk", showing: false)
        XCTAssertFalse(v.allows(.chat), "leaving twice does not go below nothing")
    }

    func testEveryCallerNamesWhyItSpeaks() throws {
        // No call of play / say / playReporting without an origin anywhere in the sources (the compiler enforces
        // the parameter; this pins that nobody adds a default), and nothing but a press or a chat is an origin.
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/KaikuKit")
        let voice = try String(contentsOf: root.appendingPathComponent("Voice/VoiceLines.swift"), encoding: .utf8)
        XCTAssertFalse(voice.contains("origin: VoiceOrigin ="), "the origin has no default")
        XCTAssertEqual(voice.components(separatedBy: "origin: VoiceOrigin)").count - 1, 3, "play, playReporting, say")
        var calls = 0
        let files = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)!
        for case let f as URL in files where f.pathExtension == "swift" {
            let text = try String(contentsOf: f, encoding: .utf8)
            for line in text.split(separator: "\n") where line.contains("VoiceLines.shared.play(")
                || line.contains("VoiceLines.shared.say(") || line.contains("VoiceLines.shared.playReporting(") {
                calls += 1
                XCTAssertTrue(line.contains("origin: .pressed") || line.contains("origin: .chat"), "\(f.lastPathComponent): \(line)")
            }
        }
        XCTAssertGreaterThan(calls, 5)
    }

    func testOpeningTalkShowsTheCallButtonAndOpensNoCall() {
        let m = TalkModel()
        XCTAssertEqual(m.mode, .ready, "no call was asked for")
        XCTAssertFalse(m.hasLive)
        let s = TalkView.idleState(mode: m.mode, reason: nil, paired: true, hasLines: false, everLive: false)
        XCTAssertEqual(s.line, "call.line.ready"); XCTAssertEqual(s.action, .call)
        #if !DEBUG
        XCTAssertFalse(TalkView.launchStarts)
        #endif
    }
}

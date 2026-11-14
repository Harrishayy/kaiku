import Foundation
import XCTest
@testable import KaikuKit

/// The Gemini Live protocol layer (pure): what we send in setup and how server frames become events.
final class LiveSessionTests: XCTestCase {
    private func session(tools: [String] = ["ask_mind", "log_walk_moment"]) -> CompanionSessionResponse {
        CompanionSessionResponse(
            session_id: "s1", model: "gemini-3.8-live", voice: "Leda", system_instruction: "You are Kaiku.",
            tools: tools.map { CompanionTool(name: $0, description: "d", parameters: .object(["type": .string("object")])) },
            context_card: ContextCard(time_of_day: "morning", language: "en", intent: "walk", first_name: nil,
                                      suggestion: nil, open_thread: nil, tone: "steady"),
            persona_version: "p", safety_phrases_version: "v", live_token: nil)
    }

    private func setup(_ o: LiveSession.Options) -> [String: Any] {
        LiveSession.setup(session: session(), options: o)["setup"] as! [String: Any]
    }

    func testHandsFreeSetupEnablesServerVADAndBargeIn() {
        let s = setup(.init(handsFree: true, tuning: .headset))
        XCTAssertEqual(s["model"] as? String, "models/gemini-3.8-live")
        let rt = s["realtimeInputConfig"] as! [String: Any]
        XCTAssertEqual(rt["activityHandling"] as? String, "START_OF_ACTIVITY_INTERRUPTS")
        let vad = rt["automaticActivityDetection"] as! [String: Any]
        XCTAssertEqual(vad["disabled"] as? Bool, false)
        XCTAssertEqual(vad["startOfSpeechSensitivity"] as? String, "START_SENSITIVITY_HIGH")
        XCTAssertEqual(vad["endOfSpeechSensitivity"] as? String, "END_SENSITIVITY_LOW")
        XCTAssertEqual(vad["silenceDurationMs"] as? Int, 800)
        let gen = s["generationConfig"] as! [String: Any]
        XCTAssertNil(gen["enableAffectiveDialog"], "gemini-3.8-live rejects it (1007) — verified live")
        XCTAssertEqual(gen["responseModalities"] as? [String], ["AUDIO"])
        XCTAssertEqual((s["proactivity"] as? [String: Any])?["proactiveAudio"] as? Bool, true)
        XCTAssertNotNil((s["contextWindowCompression"] as? [String: Any])?["slidingWindow"])
        XCTAssertNotNil(s["sessionResumption"])
        XCTAssertNotNil(s["inputAudioTranscription"])
        XCTAssertTrue(JSONSerialization.isValidJSONObject(["setup": s]))
    }

    func testLoudspeakerIsLessEagerToInterrupt() {
        let vad = (setup(.init(tuning: .loudspeaker))["realtimeInputConfig"] as! [String: Any])["automaticActivityDetection"] as! [String: Any]
        XCTAssertEqual(vad["startOfSpeechSensitivity"] as? String, "START_SENSITIVITY_LOW")
    }

    func testPushToTalkDisablesVAD() {
        let rt = setup(.init(handsFree: false))["realtimeInputConfig"] as! [String: Any]
        XCTAssertEqual((rt["automaticActivityDetection"] as? [String: Any])?["disabled"] as? Bool, true)
        XCTAssertNil(rt["activityHandling"])
    }

    func testResumeHandleIsSent() {
        let r = setup(.init(resumeHandle: "h-42"))["sessionResumption"] as! [String: Any]
        XCTAssertEqual(r["handle"] as? String, "h-42")
        XCTAssertNil((setup(.init())["sessionResumption"] as! [String: Any])["handle"])
    }

    func testAskMindIsNonBlockingOthersAreNot() {
        let decls = ((setup(.init())["tools"] as! [[String: Any]])[0]["functionDeclarations"] as! [[String: Any]])
        let byName = Dictionary(uniqueKeysWithValues: decls.map { ($0["name"] as! String, $0) })
        XCTAssertEqual(byName["ask_mind"]?["behavior"] as? String, "NON_BLOCKING")
        XCTAssertNil(byName["log_walk_moment"]?["behavior"])
    }

    func testToolResponseScheduling() {
        let bg = LiveSession.toolResponse(id: "1", name: "ask_mind", result: .object(["answer": .string("x")]), background: true)
        let r = ((bg["toolResponse"] as! [String: Any])["functionResponses"] as! [[String: Any]])[0]["response"] as! [String: Any]
        XCTAssertEqual(r["scheduling"] as? String, "WHEN_IDLE")
        let fg = LiveSession.toolResponse(id: "2", name: "express", result: .bool(true), background: false)
        let r2 = ((fg["toolResponse"] as! [String: Any])["functionResponses"] as! [[String: Any]])[0]["response"] as! [String: Any]
        XCTAssertNil(r2["scheduling"])
    }

    func testContextEventIsAClientTurn() {
        let c = LiveSession.context("[walk · 10 min]")["clientContent"] as! [String: Any]
        XCTAssertEqual(c["turnComplete"] as? Bool, true)
        let text = (((c["turns"] as! [[String: Any]])[0]["parts"] as! [[String: Any]])[0]["text"] as! String)
        XCTAssertTrue(text.hasSuffix("[walk · 10 min]"))
        XCTAssertTrue(text.contains("not said by the person"))
    }

    func testParseInterruptedComesBeforeEverythingElse() {
        let pcm = Data([1, 0, 2, 0]).base64EncodedString()
        let evs = LiveSession.parse(["serverContent": [
            "modelTurn": ["parts": [["inlineData": ["data": pcm, "mimeType": "audio/pcm;rate=24000"]]]],
            "interrupted": true,
            "inputTranscription": ["text": "wait"],
        ]])
        XCTAssertEqual(evs.first, .interrupted)
        XCTAssertTrue(evs.contains(.userText("wait")))
        XCTAssertTrue(evs.contains(.audio(Data([1, 0, 2, 0]))))
    }

    func testParseSessionFrames() {
        XCTAssertEqual(LiveSession.parse(["setupComplete": [String: Any]()]), [.ready])
        XCTAssertEqual(LiveSession.parse(["goAway": ["timeLeft": "10s"]]), [.goAway])
        XCTAssertEqual(LiveSession.parse(["sessionResumptionUpdate": ["newHandle": "h1", "resumable": true]]), [.resumable(handle: "h1")])
        XCTAssertEqual(LiveSession.parse(["sessionResumptionUpdate": ["newHandle": "h1", "resumable": false]]), [])
        XCTAssertEqual(LiveSession.parse(["toolCallCancellation": ["ids": ["a", "b"]]]), [.toolCancelled(["a", "b"])])
        XCTAssertEqual(LiveSession.parse(["serverContent": ["turnComplete": true]]), [.turnComplete])
        let tc = LiveSession.parse(["toolCall": ["functionCalls": [["id": "c1", "name": "ask_mind", "args": ["question": "q", "kind": "fact"]]]]])
        XCTAssertEqual(tc, [.toolCall(id: "c1", name: "ask_mind", args: ["question": .string("q"), "kind": .string("fact")])])
    }

    func testTokenExpiry() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let f = ISO8601DateFormatter()
        XCTAssertFalse(Conversation.expired(f.string(from: now.addingTimeInterval(600)), margin: 60, now: now))
        XCTAssertTrue(Conversation.expired(f.string(from: now.addingTimeInterval(30)), margin: 60, now: now))
        XCTAssertTrue(Conversation.expired("garbage", margin: 60, now: now))
        // the cloud's pydantic datetimes carry fractional seconds sometimes
        XCTAssertFalse(Conversation.expired("2027-03-01T08:00:00.123Z", margin: 60, now: now))
    }

    func testTranscriptsAreOptInAndMapRoles() {
        XCTAssertFalse(Signal.transcripts.defaultOn)
        XCTAssertTrue(Signal.forThisDevice.contains(.transcripts))
        let lines = [Conversation.Line(text: "Morning!", me: false), Conversation.Line(text: "  ", me: true),
                     Conversation.Line(text: "Hi Kaiku", me: true)]
        XCTAssertEqual(Conversation.transcript(lines), [TranscriptTurn(role: .kaiku, text: "Morning!"),
                                                       TranscriptTurn(role: .person, text: "Hi Kaiku")])
    }
}

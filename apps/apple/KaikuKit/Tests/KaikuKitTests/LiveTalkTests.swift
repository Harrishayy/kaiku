import XCTest
@testable import KaikuKit

/// Kaiku's voice outside Live: dynamic lines (`POST /v1/voice/say`) are cached by normalised text, per language.
final class LiveTalkTests: XCTestCase {
    @MainActor
    func testDynamicLinesCacheByNormalisedText() {
        XCTAssertEqual(VoiceLines.sayURL("I'm  back.\nWhere were we?", "en"), VoiceLines.sayURL("I'm back. Where were we?", "en"))
        XCTAssertNotEqual(VoiceLines.sayURL("I'm back.", "en"), VoiceLines.sayURL("I'm back.", "fi"))
    }

    func testLoudspeakerTakesTheCloudsTurnDetection() throws {
        let json = """
        {"session_id":"s","home_id":"h","surface":"iphone","model":"gemini-3.8-live","voice":"Sulafat",
         "system_instruction":"x","tools":[],"context_card":{"time_of_day":"morning"},"persona_version":"p",
         "safety_phrases_version":"s","live_setup":{"realtimeInputConfig":{"automaticActivityDetection":
         {"disabled":false,"silenceDurationMs":900}}}}
        """
        let s = try JSONDecoder().decode(CompanionSessionResponse.self, from: Data(json.utf8))
        let setup = LiveSession.setup(session: s, options: .init())["setup"] as? [String: Any]
        let aad = (setup?["realtimeInputConfig"] as? [String: Any])?["automaticActivityDetection"] as? [String: Any]
        XCTAssertEqual((aad?["silenceDurationMs"] as? NSNumber)?.intValue, 900)
        let head = LiveSession.setup(session: s, options: .init(tuning: .headset))["setup"] as? [String: Any]
        let haad = (head?["realtimeInputConfig"] as? [String: Any])?["automaticActivityDetection"] as? [String: Any]
        XCTAssertEqual(haad?["startOfSpeechSensitivity"] as? String, "START_SENSITIVITY_HIGH")
    }
}

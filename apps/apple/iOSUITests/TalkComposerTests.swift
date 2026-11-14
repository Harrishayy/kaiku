import XCTest

/// Regression (2026-11-14): tapping the message field in Talk while voice is unavailable hung the app (an endless
/// SwiftUI update cycle in the transcript). Needs a local cloud WITHOUT a model key (KAIKU_NO_DOTENV=1), so Talk
/// is in its "voice unavailable" state; never opens the microphone.
final class TalkComposerTests: XCTestCase {
    func testComposerStaysResponsiveWhenVoiceIsUnavailable() {
        let env = ProcessInfo.processInfo.environment
        let cloud = env["KAIKU_TEST_CLOUD"] ?? "http://127.0.0.1:8000"
        let home = env["KAIKU_TEST_HOME"] ?? "aino"
        let app = XCUIApplication()
        app.launchArguments = ["-kaiku.lang", "en", "-AppleLanguages", "(en)", "-kaikuMute", "YES", "-kaikuSkipOnboarding", "YES",
                               "-kaikuPairLink", "\(cloud)/?home=\(home)", "-kaikuTab", "talk"]
        addUIInterruptionMonitor(withDescription: "system alerts") { alert in
            for b in ["Don’t Allow", "Don't Allow"] where alert.buttons[b].exists { alert.buttons[b].tap(); return true }
            return false
        }
        app.launch()
        let unavailable = NSPredicate(format: "label CONTAINS[c] %@ OR label CONTAINS[c] %@ OR label CONTAINS[c] %@",
                                      "unavailable", "could not be reached", "Microphone access is off")
        XCTAssertTrue(app.staticTexts.matching(unavailable).firstMatch.waitForExistence(timeout: 30), "Talk should say voice is not there")
        let composer = app.textFields["Type a message"].firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 5))
        let started = Date()
        composer.tap()
        composer.typeText("I walked to the lake today.")
        app.buttons["Send"].firstMatch.tap()
        let sent = app.staticTexts["I walked to the lake today."].firstMatch
        XCTAssertTrue(sent.waitForExistence(timeout: 10), "the typed message appears as a bubble")
        XCTAssertLessThan(Date().timeIntervalSince(started), 45, "typing must not wait on a busy main thread")
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "connection dropped")).firstMatch.exists,
                       "nothing dropped: voice was never connected")
        // Still responsive afterwards: a second message goes through too (the keyboard covers the tab bar here).
        let again = app.textFields.firstMatch
        again.tap()
        again.typeText("It was quiet there.")
        app.buttons["Send"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["It was quiet there."].firstMatch.waitForExistence(timeout: 10),
                      "the app still answers after typing in Talk")
    }
}

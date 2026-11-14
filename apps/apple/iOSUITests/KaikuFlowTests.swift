import XCTest

/// End-to-end against a local cloud (make cloud-local + make seed): weather check → obs.self_report,
/// a Pebble path round → obs.play_session, memories list loads. Set KAIKU_TEST_CLOUD (default http://127.0.0.1:8000).
final class KaikuFlowTests: XCTestCase {
    var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        let cloud = ProcessInfo.processInfo.environment["KAIKU_TEST_CLOUD"] ?? "http://127.0.0.1:8000"
        app.launchArguments = ["-kaikuSkipOnboarding", "YES", "-kaikuPairLink", "\(cloud)/?home=demo-aino",
                               "-kaiku.lang", "en", "-AppleLanguages", "(en)"]
        app.launch()
    }

    func testWeatherCheckPosts() {
        app.buttons["Today"].tap()
        app.staticTexts["Weather check"].firstMatch.tap()
        let done = app.buttons["That's it"]
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        done.tap()
        XCTAssertTrue(app.staticTexts["Thank you. I've noted it."].firstMatch.waitForExistence(timeout: 5))
    }

    func testPebblesPostsPlaySession() {
        app.buttons["Play"].tap()
        app.staticTexts["Pebble path"].firstMatch.tap()
        app.buttons["Start"].tap()
        // Two wrong rounds end the game: tap pebbles while it's our turn until the end screen shows.
        let end = app.buttons["That's enough for today"]
        let deadline = Date().addingTimeInterval(40)
        while !end.exists && Date() < deadline {
            let p = app.buttons["Pebble 1"]
            if p.exists && p.isEnabled { p.tap(); p.tap(); p.tap() }
            sleep(1)
        }
        XCTAssertTrue(end.waitForExistence(timeout: 5))
    }

    func testMemoriesLoad() {
        app.buttons["You"].tap()
        app.staticTexts["What Kaiku remembers"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Loves the smell of rain"].waitForExistence(timeout: 8))
    }
}

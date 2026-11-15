import XCTest

/// "Camera during activities" in the app's own screens. A simulator has no camera to look through, and these
/// tests must never open the Mac's: the app runs its stand-in source (`-kaikuFaceSource scripted`, Debug builds
/// only), which opens no camera and plays made-up readings. So what is shown here is the indicator, its off tap,
/// the one-time question, the consent screens and the day's receipt: never a face being measured. Whatever a
/// run sends to a service goes out as simulated. Conversations run on the scripted Live (`-kaikuTalkDemo`): no
/// microphone, no network, no sound. Pictures go to `$KAIKU_SHOT_DIR` when set.
///
/// `KAIKU_FACE_CLOUD=http://127.0.0.1:<port>` (a scratch service, never a person's) turns on the one test that
/// reads the day's receipt back from a service.
final class FaceSignsUITests: XCTestCase {
    private let on = "<dict><key>camera</key><true/><key>checkins</key><true/><key>walks</key><true/></dict>"

    /// The current wording of the camera choice: keep equal to `CameraChoice.wording` in KaikuKit (this target
    /// does not link the package). A lower number makes the app ask the one-time question.
    private static let wording = 4

    override func setUp() { continueAfterFailure = false }

    private func shot(_ name: String) {
        let s = XCUIScreen.main.screenshot()
        let a = XCTAttachment(screenshot: s)
        a.name = name; a.lifetime = .keepAlways
        add(a)
        if let dir = ProcessInfo.processInfo.environment["KAIKU_SHOT_DIR"] {
            try? s.pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
        }
    }

    /// `camera`: nil = the choice was never turned on; otherwise the wording it was agreed under (0 = an older build's).
    private func launch(camera wording: Int? = Self.wording, _ extra: [String] = [], onboarded: Bool = true, cloud: String? = nil) -> XCUIApplication {
        let app = XCUIApplication()
        var args = ["-kaiku.lang", "en", "-AppleLanguages", "(en)", "-kaikuFaceSource", "scripted", "-kaikuMute", "YES"]
        if onboarded { args += ["-kaikuSkipOnboarding", "YES"] }
        // A home of its own for each run: the receipt then counts this run's activity and nothing older.
        if let cloud { args += ["-kaikuPairLink", "\(cloud)/?home=face-signs-ui-\(UUID().uuidString.prefix(8).lowercased())"] }
        if let wording { args += ["-kaiku.consents", on, "-kaiku.camera.wording", "\(wording)"] }
        app.launchArguments = args + extra
        app.launch()
        return app
    }

    private func any(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any).matching(identifier: id).firstMatch }

    func testTheIndicatorShowsWhileAGameSamplesAndItsTapTurnsTheCameraOff() {
        let app = launch(["-kaikuRoute", "breathe"])
        XCTAssertTrue(app.buttons["Start"].waitForExistence(timeout: 20))
        XCTAssertFalse(any(app, "task.camera.on").exists, "nothing samples before the activity starts")
        shot("iphone-game-intro-choice-on")
        app.buttons["Start"].tap()
        let chip = any(app, "task.camera.on")
        XCTAssertTrue(chip.waitForExistence(timeout: 10), "while the camera samples she can see it")
        XCTAssertEqual(chip.label, "Camera on. Face movement only, as numbers made on this device. No pictures.")
        sleep(1)
        shot("iphone-game-camera-on")
        chip.tap()
        XCTAssertTrue(any(app, "task.camera.stopped").waitForExistence(timeout: 5), "one tap turns it off for this activity")
        XCTAssertFalse(any(app, "task.camera.on").exists)
        let keep = app.buttons["task.camera.keepoff"]
        XCTAssertTrue(keep.exists, "and the choice itself is one more tap away")
        shot("iphone-game-camera-off-for-this-activity")
        keep.tap()
        let said = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "You can turn it on again in You")).firstMatch
        XCTAssertTrue(said.waitForExistence(timeout: 3), "she is told where the switch is")
        shot("iphone-game-camera-kept-off")
        XCTAssertFalse(any(app, "task.camera.stopped").exists, "the choice is off: nothing about the camera stays on the activity")
        XCTAssertTrue(app.buttons["Back"].firstMatch.exists, "the activity itself goes on")
    }

    func testWithTheChoiceOffAnActivityShowsNoIndicator() {
        let app = launch(camera: nil, ["-kaikuRoute", "breathe"])
        XCTAssertTrue(app.buttons["Start"].waitForExistence(timeout: 20))
        shot("iphone-game-intro-choice-off")
        app.buttons["Start"].tap()
        sleep(4)
        for id in ["task.camera.on", "task.camera.stopped", "task.camera.unavailable"] { XCTAssertFalse(any(app, id).exists, id) }
        shot("iphone-game-choice-off")
    }

    func testAChoiceFromBeforeIsPutToHerAgainWithTheWholeTextBeforeTheCameraRuns() {
        let app = launch(camera: 0, ["-kaikuRoute", "breathe"])
        XCTAssertTrue(app.buttons["Start"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["Camera during activities: what it notices"].waitForExistence(timeout: 5))
        XCTAssertTrue(whole(app).exists, "the question shows the whole text of the choice")
        XCTAssertTrue(app.buttons["camera.confirm.keep"].exists); XCTAssertTrue(app.buttons["camera.confirm.off"].exists)
        shot("iphone-game-intro-asked-again")
        app.buttons["camera.confirm.keep"].tap()
        XCTAssertFalse(app.buttons["camera.confirm.keep"].waitForExistence(timeout: 2), "asked once")
        app.buttons["Start"].tap()
        XCTAssertTrue(any(app, "task.camera.on").waitForExistence(timeout: 10), "kept on: the camera runs")
    }

    func testAnUnansweredQuestionKeepsTheCameraOff() {
        let app = launch(camera: 0, ["-kaikuRoute", "breathe"])
        XCTAssertTrue(app.buttons["Start"].waitForExistence(timeout: 20))
        app.buttons["Start"].tap()
        sleep(4)
        XCTAssertFalse(any(app, "task.camera.on").exists, "not before she has answered")
    }

    func testTheCheckInShowsTheIndicatorBesideTheCallUntilItEnds() {
        let app = launch(["-kaikuRoute", "weather", "-kaikuTalkDemo", "live"])
        XCTAssertTrue(app.buttons["call.mic"].firstMatch.waitForExistence(timeout: 20))
        let chip = any(app, "task.camera.on")
        XCTAssertTrue(chip.waitForExistence(timeout: 10), "the camera runs beside the check-in, and says so")
        sleep(1)
        shot("iphone-check-in-camera-on")
        let done = app.buttons["checkin.dials.done"]
        for _ in 0..<6 where !done.exists || !done.isHittable { app.swipeUp() }
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        done.tap()
        XCTAssertFalse(any(app, "task.camera.on").waitForExistence(timeout: 3), "the check-in is over: the camera is closed")
        shot("iphone-check-in-ended")
    }

    /// The whole text of the choice is too long for an identifier query: it is found by what it must say.
    private func whole(_ app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(
            format: "label CONTAINS %@ AND label CONTAINS %@ AND label CONTAINS %@",
            "the camera notices smiles, eyebrow and mouth movement, blinks",
            "No pictures are kept or sent, and Kaiku does not label emotions.",
            "Your care team sees them beside your record, and the numbers decide nothing.")).firstMatch
    }

    func testTheConsentScreensSayWhatIsDerived() {
        // Setup → Your choices: every row shows its whole text.
        var app = launch(camera: nil, ["-kaikuOnboardingStep", "3", "-kaiku.onboarded", "NO"], onboarded: false)
        XCTAssertTrue(app.staticTexts["Your choices"].waitForExistence(timeout: 20))
        let row = whole(app)
        for _ in 0..<5 where !row.exists || !row.isHittable { app.swipeUp() }
        XCTAssertTrue(row.exists, "setup names what the camera derives")
        // For the picture: bring the whole row up from under the button (a drag on the words, never on a switch).
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.3, dy: 0.72))
            .press(forDuration: 0.1, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.3, dy: 0.42)))
        shot("iphone-setup-your-choices")
        app.terminate()
        // You → Sharing and permissions: the short line in the row, the whole text under the list.
        app = launch(camera: nil, ["-kaikuTab", "you"])
        let sharing = app.buttons["Sharing and permissions"].firstMatch
        XCTAssertTrue(sharing.waitForExistence(timeout: 20))
        sharing.tap()
        // The row's switch carries the title and the short line (the labels beside it are hidden from VoiceOver).
        let short = app.descendants(matching: .any).matching(NSPredicate(
            format: "label CONTAINS %@", "Smiles, blinks and face movement as numbers. No pictures kept.")).firstMatch
        XCTAssertTrue(short.waitForExistence(timeout: 5), "the row says it in one line")
        for _ in 0..<4 where !short.isHittable { app.swipeUp() }
        shot("iphone-you-sharing-rows")
        let full = whole(app)
        for _ in 0..<6 where !full.exists || !full.isHittable { app.swipeUp() }
        XCTAssertTrue(full.exists, "the whole text stands under the list")
        shot("iphone-you-sharing-in-full")
    }

    /// With a scratch service: an activity with the (stand-in) camera on is listed in the day's receipt, as simulated.
    func testTheDaysReceiptListsTheCameraAfterAnActivity() throws {
        guard let cloud = ProcessInfo.processInfo.environment["KAIKU_FACE_CLOUD"] else { throw XCTSkip("Set KAIKU_FACE_CLOUD to a scratch service") }
        let app = launch(["-kaikuRoute", "pebbles"], cloud: cloud)
        XCTAssertTrue(app.buttons["Start"].waitForExistence(timeout: 20))
        app.buttons["Start"].tap()
        XCTAssertTrue(any(app, "task.camera.on").waitForExistence(timeout: 10))
        let end = app.buttons["That's enough for today"]
        let deadline = Date().addingTimeInterval(90)
        while !end.exists && Date() < deadline {
            let skip = app.buttons["Start my path"]
            if skip.exists && skip.isHittable { skip.tap() }
            let p = app.buttons["Pebble 1"]
            if p.exists && p.isEnabled { p.tap(); p.tap(); p.tap() }
            sleep(1)
        }
        XCTAssertTrue(end.waitForExistence(timeout: 5))
        XCTAssertFalse(any(app, "task.camera.on").exists, "the game is over: the camera is closed")
        end.tap()
        app.buttons["You"].firstMatch.tap()
        app.staticTexts["What Kaiku saw today"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Today, so far"].firstMatch.waitForExistence(timeout: 10))
        let line = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "Activities with the camera on: 1")).firstMatch
        XCTAssertTrue(line.waitForExistence(timeout: 10), "the receipt lists the camera")
        shot("iphone-receipt-today-so-far")
        let row = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "Face movement as numbers, no pictures")).firstMatch
        for _ in 0..<6 where !row.exists || !row.isHittable { app.swipeUp() }
        XCTAssertTrue(row.exists)
        shot("iphone-receipt-what-kaiku-saw")
    }
}

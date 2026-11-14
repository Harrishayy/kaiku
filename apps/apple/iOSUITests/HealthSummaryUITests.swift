import XCTest

/// The daily Apple Health summary on a simulator, against a scratch service (never a person's):
/// `KAIKU_HEALTH_CLOUD=http://127.0.0.1:<port>` and, when the service was seeded with a simulated record,
/// `KAIKU_HEALTH_HOME=<that home>` (so History has earlier days to draw). Pictures go to `$KAIKU_SHOT_DIR`.
///
/// What it shows: the debug sample-data path end to end on the simulator's own Apple Health. The app asks iOS for
/// the kinds of data it reads (the sheet is answered here), writes one made-up night and day, reads them back
/// through the same HealthKit queries a phone uses, and sends one summary, marked simulated because the app wrote
/// those samples itself. Then History and the day's receipt show it. What it cannot show: a watch. The walking
/// heart rate average cannot be written by an app, so the simulator's summary never has one.
final class HealthSummaryUITests: XCTestCase {
    private var cloud: String? { ProcessInfo.processInfo.environment["KAIKU_HEALTH_CLOUD"] }
    private var home: String { ProcessInfo.processInfo.environment["KAIKU_HEALTH_HOME"] ?? "health-ui-\(UUID().uuidString.prefix(8).lowercased())" }

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

    private func launch(_ cloud: String, home: String, _ extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-kaikuSkipOnboarding", "YES", "-kaikuPairLink", "\(cloud)/?home=\(home)", "-kaikuMute", "YES",
                               "-kaiku.lang", "en", "-AppleLanguages", "(en)"] + extra
        app.launch()
        return app
    }

    private func events(_ cloud: String, home: String) throws -> [[String: Any]] {
        // Since this morning, not since this run began: the same sample day gives the same summary and so the same
        // envelope id, which a service that already holds it from an earlier run today does not store twice.
        let since = ISO8601DateFormatter().string(from: Calendar.current.startOfDay(for: Date()))
        let data = try Data(contentsOf: URL(string: "\(cloud)/v1/events?home_id=\(home)&limit=500&since=\(since)")!)
        return (try JSONSerialization.jsonObject(with: data) as? [String: Any])?["events"] as? [[String: Any]] ?? []
    }

    private func labelled(_ app: XCUIApplication, _ text: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    /// A drag that ends held still, so the list stops where the finger stops and does not glide on.
    private func drag(_ app: XCUIApplication, from: CGFloat, to: CGFloat) {
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: from))
            .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: to)),
                   withVelocity: .slow, thenHoldForDuration: 0.3)
    }

    /// Brings an element up the screen until its top is just above `fraction` of the height. Once it is in sight
    /// it is moved by exactly what is missing: a list that builds its rows as they come takes a row that has
    /// gone past the top away again, and a search that only ever drags would then run on to the end.
    private func bring(_ app: XCUIApplication, _ element: XCUIElement, above fraction: CGFloat = 0.82, tries: Int = 60) {
        let h = app.frame.height
        for _ in 0..<tries {
            let y = element.exists ? element.frame.minY : .infinity
            // In place; or a tall block that starts above the screen and can still be reached: nothing to bring.
            if y <= h * fraction, y > 0 || element.isHittable { return }
            if y <= 0 { drag(app, from: 0.5, to: 0.7) }   // it has gone past the top: back a little
            else if y < h * 0.88 { drag(app, from: y / h, to: max(0.14, fraction - 0.03)) }
            else { drag(app, from: 0.8, to: 0.3) }
        }
    }

    func testSampleDataBecomesOneSimulatedSummaryAndShowsInHistoryAndTheReceipt() throws {
        guard let cloud else { throw XCTSkip("Set KAIKU_HEALTH_CLOUD to a scratch service") }
        let home = home
        let app = launch(cloud, home: home, ["-kaikuHealthSample", "YES"])

        // iOS asks which kinds of Health data the app may read (and, in this debug build, write as sample data).
        let all = app.staticTexts["Turn On All"]
        if all.waitForExistence(timeout: 15) {
            shot("iphone-health-sheet")
            all.tap()
            app.buttons["Allow"].firstMatch.tap()
        }

        // One summary for this morning lands at the service, with the newer numbers, marked simulated.
        let day = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f.string(from: Date()) }()
        var found: [String: Any]?
        let deadline = Date().addingTimeInterval(40)
        while found == nil && Date() < deadline {
            found = try events(cloud, home: home).first { e in
                e["type"] as? String == "obs.wearable_daily" && e["source"] as? String == "phone"
                    && ((e["payload"] as? [String: Any])?["date"] as? String) == day
                    && (e["payload"] as? [String: Any])?["distance_km"] != nil
            }
            if found == nil { sleep(1) }
        }
        let event = try XCTUnwrap(found, "no obs.wearable_daily with a distance landed for \(day)")
        let p = try XCTUnwrap(event["payload"] as? [String: Any])
        print("WEARABLE \(p) sim=\(event["sim"] ?? "nil")")
        XCTAssertEqual(event["sim"] as? Bool, true, "sample data is never sent as a person's own")
        XCTAssertEqual(p["distance_km"] as? Double, 4.66)          // 2 250 m + 2 410 m
        XCTAssertEqual(p["daylight_min"] as? Double, 53)           // 22 + 31
        XCTAssertEqual(p["steps"] as? Int, 6400)
        XCTAssertEqual(p["sleep_min"] as? Double, 460)             // 23:10 to 07:05 less a quarter of an hour awake
        XCTAssertEqual(p["sleep_deep_min"] as? Double, 60)
        XCTAssertEqual(p["sleep_rem_min"] as? Double, 90)
        XCTAssertEqual(p["sleep_core_min"] as? Double, 310)
        XCTAssertEqual(p["sleep_awake_min"] as? Double, 15, "the minutes awake after the last waking are not part of the night")
        XCTAssertNil(p["walking_hr_bpm"], "an app cannot write a walking heart rate average, so sample data has none")

        // Her own numbers: History, under "Sleep and body", with this morning's sample summary as the latest day.
        app.buttons["History"].firstMatch.tap()
        let group = app.staticTexts["Sleep and body"].firstMatch
        XCTAssertTrue(group.waitForExistence(timeout: 20))
        bring(app, group, above: 0.22)
        shot("iphone-sample-history")
        for page in 2...3 {
            drag(app, from: 0.8, to: 0.25)
            shot("iphone-sample-history-\(page)")
        }

        // The day's receipt names what the summary held.
        app.buttons["You"].firstMatch.tap()
        app.staticTexts["What Kaiku saw today"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Today, so far"].firstMatch.waitForExistence(timeout: 10))
        let line = labelled(app, "Last night and yesterday: sleep, sleep stages, time awake at night")
        XCTAssertTrue(line.waitForExistence(timeout: 10), "the receipt names the kinds of numbers")
        bring(app, line)
        shot("iphone-receipt-apple-health")
        let saw = labelled(app, "Apple Health, as daily totals:")
        bring(app, saw)
        XCTAssertTrue(saw.exists)
        shot("iphone-receipt-watch-row")
    }

    /// History's groups from a seeded service: the watch's group, the camera's group and the pages of the measures
    /// named in `KAIKU_HEALTH_MEASURES` (no Health sheet, no sample data).
    func testHistoryDrawsTheCameraGroupAndAWeekOfANewMeasure() throws {
        guard let cloud else { throw XCTSkip("Set KAIKU_HEALTH_CLOUD to a scratch service") }
        guard ProcessInfo.processInfo.environment["KAIKU_HEALTH_HOME"] != nil else { throw XCTSkip("Set KAIKU_HEALTH_HOME to a seeded home") }
        var app = launch(cloud, home: home, ["-kaikuTab", "history"])
        XCTAssertTrue(app.staticTexts["Camera during activities"].firstMatch.waitForExistence(timeout: 20), "the service's camera group")
        for (title, name, pages) in [("Sleep and body", "sleep-and-body", 4), ("Camera during activities", "camera-group", 3)] {
            let head = app.staticTexts[title].firstMatch
            XCTAssertTrue(head.exists, title)
            bring(app, head, above: 0.22, tries: 90)
            shot("iphone-history-\(name)")
            for page in 2...pages {
                drag(app, from: 0.8, to: 0.25)
                shot("iphone-history-\(name)-\(page)")
            }
        }
        app.terminate()
        // Measures' own pages, by week, month and day, opened by the measure's key (the service names them):
        // `KAIKU_HEALTH_MEASURES=day_distance:week,deep_sleep:week,...`.
        let wanted = (ProcessInfo.processInfo.environment["KAIKU_HEALTH_MEASURES"] ?? "watch_sleep:week,watch_sleep:month,watch_sleep:day")
            .split(separator: ",").map { $0.split(separator: ":").map(String.init) }.filter { $0.count == 2 }
        for pair in wanted {
            let (key, range) = (pair[0], pair[1])
            app = launch(cloud, home: home, ["-kaikuTab", "history", "-kaikuHistoryMeasure", key, "-kaikuHistoryRange", range])
            XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "history.measure.\(key)").firstMatch.waitForExistence(timeout: 20), "\(key) \(range)")
            sleep(1)
            shot("iphone-history-\(key)-\(range)")
            drag(app, from: 0.8, to: 0.25)
            shot("iphone-history-\(key)-\(range)-2")
            app.terminate()
        }
    }
}

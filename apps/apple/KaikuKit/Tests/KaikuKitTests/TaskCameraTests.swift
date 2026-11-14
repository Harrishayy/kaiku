import XCTest
@testable import KaikuKit

final class TaskCameraFeatureTests: XCTestCase {
    func testGeometryVariabilityAndCoverageAreNotEmotionLabels() {
        var steady = TaskCameraFeatures()
        let still = TaskFaceFrame(centerX: 0.5, centerY: 0.5, mouthAspect: 0.2, eyeAspect: 0.15)
        for _ in 0..<10 { steady.add(still) }
        XCTAssertEqual(steady.summary.expressivity, 0)
        XCTAssertEqual(steady.summary.movement, 0)
        XCTAssertEqual(steady.summary.coverage, 1)
        var changing = TaskCameraFeatures()
        for i in 0..<10 {
            changing.add(TaskFaceFrame(centerX: 0.3 + Double(i) * 0.02, centerY: 0.5,
                                       mouthAspect: i.isMultiple(of: 2) ? 0.2 : 0.6, eyeAspect: 0.2))
        }
        changing.add(nil); changing.add(nil)
        XCTAssertGreaterThan(changing.summary.expressivity ?? 0, 0)
        XCTAssertEqual(changing.summary.movement ?? -1, 0.02, accuracy: 0.0001)
        XCTAssertEqual(changing.summary.coverage, 10.0 / 12, accuracy: 0.0001)
        XCTAssertEqual(changing.summary.samples, 12)
    }

    func testMissingMultipleFacesAndInvalidSamplesDoNotInventMeasurements() {
        var features = TaskCameraFeatures()
        features.add(nil)
        features.add(TaskFaceFrame(centerX: .nan, centerY: 0.5, mouthAspect: 0.2, eyeAspect: 0.2))
        XCTAssertEqual(features.summary.coverage, 0)
        XCTAssertNil(features.summary.expressivity); XCTAssertNil(features.summary.movement)
        features.add(TaskFaceFrame(centerX: 0.2, centerY: 0.5, mouthAspect: 0.2, eyeAspect: 0.2))
        features.add(nil) // tracking gap: don't call the next face's different position movement
        features.add(TaskFaceFrame(centerX: 0.8, centerY: 0.5, mouthAspect: 0.2, eyeAspect: 0.2))
        XCTAssertNil(features.summary.movement)
    }

    func testCameraPayloadMatchesContractAndCarriesMethod() throws {
        var session = PlaySession(game: .firefly, device: .phone, duration_s: 30)
        session.expressivity_index = 0.03; session.face_movement = 0.01
        session.camera_face_coverage = 0.8; session.camera_samples = 150; session.camera_method = "vision_landmarks"
        let body = try JSONSerialization.jsonObject(with: JSONEncoder().encode(session)) as! [String: Any]
        let schema = try json("contracts/schemas/obs/play_session.schema.json") as! [String: Any]
        let definition = (schema["$defs"] as! [String: [String: Any]]).values.first!
        let properties = definition["properties"] as! [String: Any]
        XCTAssertTrue(Set(body.keys).isSubset(of: Set(properties.keys)))
        XCTAssertEqual(body["camera_method"] as? String, "vision_landmarks")
        XCTAssertNil(body["image"]); XCTAssertNil(body["emotion"])
    }
}

private final class SyntheticCamera: TaskCameraSource, @unchecked Sendable {
    var starts = 0, stops = 0
    var frame: (@Sendable (TaskFaceFrame?) -> Void)?
    func start(frame: @escaping @Sendable (TaskFaceFrame?) -> Void, failed: @escaping @Sendable () -> Void) async -> Bool {
        starts += 1; self.frame = frame; return true
    }
    func stop() { stops += 1 }
}

@MainActor final class TaskCameraLifecycleTests: XCTestCase {
    func testDefaultOffDoesNotAskPermissionOrStartCapture() async {
        let source = SyntheticCamera()
        var requested = false
        let camera = TaskCamera(source: source, permission: { requested = true; return true })
        await camera.begin(allowed: false)
        XCTAssertFalse(requested); XCTAssertEqual(source.starts, 0); XCTAssertEqual(camera.state, .off)
    }

    func testPermissionDeniedKeepsActivityUsableWithoutCamera() async {
        let source = SyntheticCamera()
        let camera = TaskCamera(source: source, permission: { false })
        await camera.begin(allowed: true)
        XCTAssertEqual(camera.state, .unavailable); XCTAssertEqual(source.starts, 0); XCTAssertNil(camera.finish())
    }

    func testLatePermissionAfterCancelCannotOpenCamera() async {
        let source = SyntheticCamera()
        var permission: CheckedContinuation<Bool, Never>?
        let camera = TaskCamera(source: source, permission: { await withCheckedContinuation { permission = $0 } })
        let starting = Task { await camera.begin(allowed: true) }
        while permission == nil { await Task.yield() }
        camera.cancel(); permission?.resume(returning: true)
        await starting.value
        XCTAssertEqual(source.starts, 0); XCTAssertEqual(camera.state, .off)
    }

    func testCompletionAndRevocationStopCaptureAndDiscardLateFrames() async {
        let source = SyntheticCamera(), sample = TaskFaceFrame(centerX: 0.5, centerY: 0.5, mouthAspect: 0.2, eyeAspect: 0.1)
        let camera = TaskCamera(source: source, permission: { true })
        await camera.begin(allowed: true); XCTAssertEqual(camera.state, .capturing)
        source.frame?(sample); source.frame?(sample)
        try? await Task.sleep(nanoseconds: 10_000_000)
        let summary = camera.finish()
        XCTAssertEqual(summary?.samples, 2); XCTAssertEqual(camera.state, .off)
        source.frame?(sample); await Task.yield(); XCTAssertNil(camera.finish())
        await camera.begin(allowed: true)
        let late = source.frame
        camera.cancel() // used on background, Back, consent revocation and cancelled games
        late?(sample); await Task.yield()
        XCTAssertNil(camera.finish()); XCTAssertGreaterThan(source.stops, 0)
    }
    /// Synthetic geometry through the production recorder/outbox/API. No device, microphone or model is used.
    func testSyntheticTaskMeasurementsPersistThroughActualRecorder() async throws {
        guard let raw = ProcessInfo.processInfo.environment["KAIKU_TASK_CAPTURE_TEST_CLOUD"], let url = URL(string: raw) else {
            throw XCTSkip("Set KAIKU_TASK_CAPTURE_TEST_CLOUD for synthetic database integration")
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let home = "camera-integration"
        let pairing = Pairing(baseURL: url, homeID: home, token: ProcessInfo.processInfo.environment["KAIKU_TASK_CAPTURE_TEST_TOKEN"])
        let api = APIClient(pairing: pairing)
        let app = AppModel(defaults: UserDefaults(suiteName: UUID().uuidString)!, pairing: pairing, api: api,
                           queue: OfflineQueue(url: directory.appendingPathComponent("events.json")),
                           episodes: EpisodeOutbox(url: directory.appendingPathComponent("episodes.json")))
        var sample = PlaySession(game: .firefly, device: KaikuPlatform.device, duration_s: 30)
        sample.reaction_ms_median = 430; sample.reaction_ms_iqr = 80
        sample.expressivity_index = 0.04; sample.face_movement = 0.02
        sample.camera_face_coverage = 0.75; sample.camera_samples = 20; sample.camera_method = "vision_landmarks"
        let since = Date().addingTimeInterval(-1)
        app.consents[.camera] = true
        await app.recordPlay(sample, sim: true)
        var events = try await api.todaysEvents(since: since)
        let recorded = try XCTUnwrap(events.events.first { $0.type == "obs.play_session" && $0.home_id == home })
        XCTAssertEqual(recorded.sim, true)
        XCTAssertEqual(recorded.payload["camera_method"]?.string, "vision_landmarks")
        XCTAssertEqual(recorded.payload["expressivity_index"]?.double, 0.04)
        XCTAssertEqual(recorded.payload["camera_face_coverage"]?.double, 0.75)
        XCTAssertEqual(recorded.payload["reaction_ms_median"]?.double, 430)
        let revokedSince = Date().addingTimeInterval(-1)
        app.consents[.camera] = false
        await app.recordPlay(sample, sim: true)
        events = try await api.todaysEvents(since: revokedSince)
        let scrubbed = try XCTUnwrap(events.events.first { $0.id != recorded.id && $0.type == "obs.play_session" })
        XCTAssertNil(scrubbed.payload["camera_method"])
        XCTAssertNil(scrubbed.payload["expressivity_index"])
        XCTAssertEqual(scrubbed.payload["reaction_ms_median"]?.double, 430)
    }

}

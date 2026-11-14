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

// The controller's lifecycle (default off, permission, the tap that turns it off, leaving the front, a camera
// taken away) is in FaceSignsTests.swift → TaskCameraControllerTests, on a stand-in source.

@MainActor final class TaskCameraLifecycleTests: XCTestCase {
    /// Made-up numbers through the production controller, recorder, outbox and API, into a real service (a scratch
    /// one: `KAIKU_TASK_CAPTURE_TEST_CLOUD`). No camera, microphone or model is used; everything is sent `sim: true`.
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
        app.consents[.camera] = true
        app.cameraChoice.agree()   // as on the screens that show the choice's whole text
        // One task on the stand-in source: 30 s, a 2 s smile, a blink every 3 s, the face out of the picture for 6 s.
        let source = FakeFaceSource(); source.simulated = true
        let camera = TaskCamera(source: source, permission: { true })
        await camera.begin(allowed: app.cameraOn)
        source.feed(seconds: 30) { t in
            if t >= 20 && t < 26 { return nil }
            return FaceReading(smile: t >= 5 && t < 7 ? 0.7 : 0.05, browRaise: 0.05, browFurrow: 0.04,
                               eyeClosed: t.truncatingRemainder(dividingBy: 3) < 0.2 ? 0.95 : 0.1, mouthOpen: 0.03, gazeOn: t < 15,
                               head: .rotation(x: 0, y: sin(t / 40), z: 0, w: cos(t / 40)))
        }
        let seen = try XCTUnwrap(camera.finish())
        let since = Date().addingTimeInterval(-1)
        await app.recordPlay(sample, camera: seen)
        let left = await app.queue.count
        XCTAssertEqual(left, 0, "nothing waits in the queue, whether or not the service knows obs.face_signs")
        var events = try await api.todaysEvents(since: since)
        let recorded = try XCTUnwrap(events.events.first { $0.type == "obs.play_session" && $0.home_id == home })
        XCTAssertEqual(recorded.sim, true)
        XCTAssertEqual(recorded.payload["camera_method"]?.string, "vision_landmarks")
        XCTAssertNotNil(recorded.payload["expressivity_index"]?.double)
        XCTAssertEqual(recorded.payload["camera_face_coverage"]?.double ?? 0, 0.8, accuracy: 0.01)
        XCTAssertEqual(recorded.payload["reaction_ms_median"]?.double, 430)
        // A service that knows the type keeps the face signs beside the game; one that does not has only refused them.
        if let signs = events.events.first(where: { $0.type == "obs.face_signs" && $0.home_id == home }) {
            XCTAssertEqual(signs.payload["ref"]?.string, recorded.id)
            XCTAssertEqual(signs.sim, true); XCTAssertEqual(signs.payload["task"]?.string, "firefly")
            XCTAssertEqual(signs.payload["method"]?.string, "arkit_blendshapes")
            XCTAssertEqual(signs.payload["coverage"]?.double ?? 0, 0.8, accuracy: 0.01); XCTAssertEqual(signs.quality ?? 0, 0.8, accuracy: 0.01)
            XCTAssertEqual(signs.payload["smiles"]?.int, 1)
            XCTAssertEqual(signs.payload["blinks_per_min"]?.double ?? 0, 20, accuracy: 2.6)
            XCTAssertEqual(signs.payload["gaze_on_share"]?.double ?? 0, 15.0 / 24, accuracy: 0.02)
            print("face_signs stored by the service:", signs.payload)
        } else {
            print("this service does not know obs.face_signs yet: it took the game record and refused the face signs")
        }
        XCTAssertEqual(app.cameraChoice.sentToday().count, 1)
        let revokedSince = Date().addingTimeInterval(-1)
        app.consents[.camera] = false
        await app.recordPlay(sample, sim: true, camera: seen)
        events = try await api.todaysEvents(since: revokedSince)
        let scrubbed = try XCTUnwrap(events.events.first { $0.id != recorded.id && $0.type == "obs.play_session" })
        XCTAssertNil(scrubbed.payload["camera_method"])
        XCTAssertNil(scrubbed.payload["expressivity_index"])
        XCTAssertEqual(scrubbed.payload["reaction_ms_median"]?.double, 430)
        XCTAssertEqual(events.events.filter { $0.type == "obs.face_signs" && $0.payload["ref"]?.string == scrubbed.id }.count, 0,
                       "with the choice withdrawn nothing of the camera is sent")
    }

}

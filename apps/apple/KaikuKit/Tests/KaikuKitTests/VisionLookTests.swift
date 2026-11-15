import CoreVideo
import XCTest
@testable import KaikuKit

/// D65: a few small pictures of a check-in for Kaiku's own model. Which frames, how small, sent once, never kept.
final class VisionLookTests: XCTestCase {
    func testTheSamplerWaitsNeedsAFaceKeepsItsDistanceAndStopsAtTheCount() {
        var s = VisionLookSampler(rules: .standard)                 // 3 pictures, 6 s settle, 12 s apart
        XCTAssertFalse(s.take(at: 100, face: true))                 // the first frame: not yet settled
        XCTAssertFalse(s.take(at: 105.9, face: true))
        XCTAssertFalse(s.take(at: 106, face: false))                // settled, but nobody in the frame
        XCTAssertTrue(s.take(at: 106.1, face: true))
        XCTAssertFalse(s.take(at: 110, face: true))                 // too close to the last one
        XCTAssertTrue(s.take(at: 118.2, face: true))
        XCTAssertTrue(s.take(at: 131, face: true))
        for t in stride(from: 140.0, to: 600, by: 13) { XCTAssertFalse(s.take(at: t, face: true)) }   // never a fourth
        XCTAssertEqual(s.taken, 3)
    }

    func testTheServicesRulesAreReadAndKeptWithinSaneBounds() throws {
        let sent = try JSONDecoder().decode(VisionLookRules.self, from: Data(#"{"frames":2,"settle_s":4,"min_interval_s":9,"max_edge_px":200,"jpeg_quality":0.5}"#.utf8))
        XCTAssertEqual(sent.frames, 2); XCTAssertEqual(sent.settle_s, 4); XCTAssertEqual(sent.max_edge_px, 200)
        let wild = try JSONDecoder().decode(VisionLookRules.self, from: Data(#"{"frames":500,"min_interval_s":0,"max_edge_px":9000,"jpeg_quality":1}"#.utf8))
        XCTAssertEqual(wild.frames, 8); XCTAssertEqual(wild.min_interval_s, 1); XCTAssertEqual(wild.max_edge_px, 768)
        XCTAssertEqual(wild.jpeg_quality, 0.9)
        XCTAssertEqual(try JSONDecoder().decode(VisionLookRules.self, from: Data("{}".utf8)), .standard)
    }

    func testAPictureIsASmallJPEGMadeInMemory() throws {
        var buffer: CVPixelBuffer?
        CVPixelBufferCreate(nil, 1280, 720, kCVPixelFormatType_32BGRA, [kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary, &buffer)
        let pixels = try XCTUnwrap(buffer)
        let data = try XCTUnwrap(VisionPicture.jpeg(pixels, orientation: .right, rules: .standard))
        XCTAssertEqual(Array(data.prefix(3)), [0xFF, 0xD8, 0xFF])
        XCTAssertLessThan(data.count, 80_000)                       // the service's limit per picture
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))
        let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
        XCTAssertLessThanOrEqual(max(image.width, image.height), 257)
        XCTAssertLessThan(image.width, image.height)                // turned upright
    }

    @MainActor func testTheBatchHoldsAtMostTheCountAndIsEmptyOnceTaken() {
        let batch = VisionLookBatch(limit: 2)
        for i in 0..<5 { batch.add(Data([UInt8(i)])) }
        XCTAssertEqual(batch.pictures.count, 2); XCTAssertTrue(batch.isFull)
        XCTAssertEqual(batch.take().count, 2)
        XCTAssertTrue(batch.pictures.isEmpty)                        // handed over once: nothing stays here
        XCTAssertTrue(batch.take().isEmpty)
        batch.add(Data([9])); batch.drop()
        XCTAssertTrue(batch.pictures.isEmpty)
    }

    func testTheLookIsOffUntilSheTurnsItOnAndHasWordsInEveryLanguage() {
        XCTAssertFalse(Signal.look.defaultOn)
        XCTAssertTrue(Signal.forThisDevice.contains(.look))
        for lang in KaikuLanguage.allCases {
            XCTAssertFalse(L10n.shared.string("sig.look.t", lang: lang).isEmpty)
            let whole = L10n.shared.string("sig.look.d", lang: lang).lowercased()
            XCTAssertTrue(whole.contains("not saved"), lang.rawValue)
            for never in ["emotion", "diagnos", "sad", "depress"] { XCTAssertFalse(whole.contains(never), never) }
        }
    }
}

/// The request as it leaves the device, and what does NOT happen when it fails.
final class VisionLookRequestTests: XCTestCase {
    private final class Stub: URLProtocol {
        static let lock = NSLock()
        nonisolated(unsafe) static var seen: [(url: URL, auth: String?, body: Data)] = []
        nonisolated(unsafe) static var status = 200
        static var all: [(url: URL, auth: String?, body: Data)] { lock.lock(); defer { lock.unlock() }; return seen }
        override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "look.test" }
        override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
        override func startLoading() {
            var data = request.httpBody ?? Data()
            if let stream = request.httpBodyStream {
                stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 4096)
                while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
            }
            Self.lock.lock()
            Self.seen.append((request.url!, request.value(forHTTPHeaderField: "Authorization"), data))
            let status = Self.status
            Self.lock.unlock()
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(#"{"ok":true,"stored":true,"note":{"expression":"neutral"}}"#.utf8))
            client?.urlProtocolDidFinishLoading(self)
        }
        override func stopLoading() {}
    }

    override func setUp() { Stub.lock.lock(); Stub.seen = []; Stub.status = 200; Stub.lock.unlock() }

    private func client(maxAttempts: Int = 3) -> APIClient {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [Stub.self]
        return APIClient(pairing: pairing, maxAttempts: maxAttempts, baseDelay: 0.01, session: URLSession(configuration: config))
    }

    private let pairing = Pairing(baseURL: URL(string: "https://look.test")!, homeID: "home-a", token: "home-token")
    private let marker = Data([0xFF, 0xD8, 0xFF] + Array("KAIKU-PICTURE-MARKER".utf8))

    func testThePicturesGoOnceToTheLookRouteWithTheHomeToken() async throws {
        let api = client()
        let result = await api.visionLook(VisionLookRequest(task: "check_in", device: "phone", pictures: [marker, marker]), home: "home-a")
        XCTAssertEqual(result?.stored, true)
        let seen = Stub.all
        XCTAssertEqual(seen.count, 1)
        guard seen.count == 1 else { return }
        let url = try XCTUnwrap(URLComponents(url: seen[0].url, resolvingAgainstBaseURL: false))
        XCTAssertEqual(url.path, "/v1/vision/look"); XCTAssertEqual(url.queryItems, [URLQueryItem(name: "home_id", value: "home-a")])
        XCTAssertEqual(seen[0].auth, "Bearer home-token")
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: seen[0].body) as? [String: Any])
        XCTAssertEqual(body["task"] as? String, "check_in"); XCTAssertEqual(body["device"] as? String, "phone")
        XCTAssertEqual(body["frames"] as? [String], [marker.base64EncodedString(), marker.base64EncodedString()])
    }

    func testAFailedLookIsNotRetriedNotQueuedAndLeavesNoFile() async throws {
        Stub.lock.lock(); Stub.status = 503; Stub.lock.unlock()
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let queue = OfflineQueue(url: dir.appendingPathComponent("events.json"))
        let api = client(maxAttempts: 3)                             // other calls would try three times
        let result = await api.visionLook(VisionLookRequest(task: "check_in", device: "phone", pictures: [marker]), home: "home-a")
        XCTAssertNil(result)
        XCTAssertEqual(Stub.all.count, 1)                            // once, whatever the answer
        let count = await queue.count
        XCTAssertEqual(count, 0)
        let needle = Data("KAIKU-PICTURE-MARKER".utf8), encoded = Data(marker.base64EncodedString().utf8)
        for file in (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? [] {
            let data = (try? Data(contentsOf: file)) ?? Data()
            XCTAssertNil(data.range(of: needle)); XCTAssertNil(data.range(of: encoded))
        }
    }
}

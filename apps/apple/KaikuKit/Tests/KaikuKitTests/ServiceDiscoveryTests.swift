import XCTest
@testable import KaikuKit

@MainActor final class ServiceDiscoveryTests: XCTestCase {
    private let base = URL(string: "http://kaiku.local:8000")!
    private var demo: APIDiscoveryResponse {
        .init(service: "kaiku-api", schema_version: 1, mode: .demo, auth_required: false,
              capabilities: ["companion_voice", "observations", "monitoring"])
    }
    private func fixture(_ discovery: ServiceDiscovery, pairing: Pairing? = nil) -> (AppModel, UserDefaults) {
        let defaults = UserDefaults(suiteName: "service-test-\(UUID())")!
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let app = AppModel(defaults: defaults, pairing: pairing, api: nil,
                           queue: OfflineQueue(url: dir.appendingPathComponent("queue")),
                           episodes: EpisodeOutbox(url: dir.appendingPathComponent("episodes")),
                           discovery: discovery, saveService: { _ in true })
        return (app, defaults)
    }
    func testDescriptorRejectsOtherServicesVersionsCapabilitiesAndAuth() {
        XCTAssertTrue(demo.permitsDemoConnection)
        var value = demo; value.service = "robot"; XCTAssertFalse(value.supportsVoice)
        value = demo; value.schema_version = 2; XCTAssertFalse(value.supportsVoice)
        value = demo; value.capabilities = ["observations"]; XCTAssertFalse(value.supportsVoice)
        value = demo; value.auth_required = true; XCTAssertFalse(value.permitsDemoConnection)
        value = demo; value.mode = .authenticated; XCTAssertFalse(value.permitsDemoConnection)
        value = demo; value.mode = .unconfigured; XCTAssertFalse(value.permitsDemoConnection)
    }
    func testConfiguredDemoProvisionsStableDeviceProfileWithoutRobotOrSeed() async {
        let descriptor = demo
        let discovery = ServiceDiscovery(configuredURL: base, fetch: { _ in descriptor })
        let (app, defaults) = fixture(discovery)
        let connected = await app.ensureServiceConnection()
        XCTAssertTrue(connected); XCTAssertTrue(app.pairing?.homeID.hasPrefix("device-") == true)
        XCTAssertNil(app.pairing?.token)
        XCTAssertEqual(app.pairing?.homeID, ServiceIdentity.home(for: base, defaults: defaults))
        XCTAssertNotEqual(app.pairing?.homeID, "demo-aino")
        XCTAssertNil(app.makeGlasses); XCTAssertTrue(app.todayEvents.isEmpty)
    }
    func testDiscoveryOnlyListsCandidatesUntilExplicitSelection() async {
        let descriptor = demo
        let discovery = ServiceDiscovery(configuredURL: nil, fetch: { _ in descriptor })
        let (app, _) = fixture(discovery)
        let candidate = await discovery.inspect(base)
        XCTAssertNotNil(candidate)
        let automatic = await app.ensureServiceConnection()
        XCTAssertFalse(automatic); XCTAssertNil(app.pairing)
        let connected = await app.connectService(candidate!)
        XCTAssertTrue(connected)
    }
    func testExistingProfileAndTokenNeverMovedByConfiguredService() async {
        let descriptor = demo
        let existing = Pairing(baseURL: URL(string: "https://original.example")!, homeID: "my-home", token: "test-scoped-token")
        let (app, defaults) = fixture(ServiceDiscovery(configuredURL: base, fetch: { _ in descriptor }), pairing: existing)
        let connected = await app.ensureServiceConnection()
        XCTAssertTrue(connected); XCTAssertEqual(app.pairing, existing)
        XCTAssertEqual(ServiceIdentity.home(for: existing.baseURL, defaults: defaults), existing.homeID)
        XCTAssertNotEqual(ServiceIdentity.home(for: base, defaults: defaults), existing.homeID)
    }
    func testAuthenticatedServiceCannotProvisionOrReuseAnotherServicesToken() async {
        var descriptor = demo; descriptor.mode = .authenticated; descriptor.auth_required = true
        let secured = descriptor
        let discovery = ServiceDiscovery(configuredURL: base, fetch: { _ in secured })
        let (app, _) = fixture(discovery)
        let candidate = await discovery.inspect(base)
        let automatic = await app.ensureServiceConnection()
        let explicit = await app.connectService(candidate!)
        XCTAssertFalse(automatic); XCTAssertFalse(explicit); XCTAssertNil(app.pairing)
    }
    func testStableIdentityCanonicalizesOriginAndSeparatesServices() {
        let defaults = UserDefaults(suiteName: "identity-test-\(UUID())")!
        let a = ServiceIdentity.home(for: base, defaults: defaults)
        XCTAssertEqual(a, ServiceIdentity.home(for: URL(string: "http://KAIKU.local:8000/path?ignored=yes")!, defaults: defaults))
        XCTAssertNotEqual(a, ServiceIdentity.home(for: URL(string: "https://another.example")!, defaults: defaults))
        XCTAssertNil(ServiceDiscovery.origin("http://user:password@example.test"))
    }
    func testDisconnectedPreferencePreventsSilentReconnection() async {
        let descriptor = demo
        let (app, defaults) = fixture(ServiceDiscovery(configuredURL: base, fetch: { _ in descriptor }))
        defaults.set(true, forKey: "kaiku.serviceAutoDisabled")
        let connected = await app.ensureServiceConnection()
        XCTAssertFalse(connected); XCTAssertNil(app.pairing)
    }
    func testConcurrentDescriptorChecksWaitForFreshResult() async {
        let descriptor = demo
        let discovery = ServiceDiscovery(configuredURL: base, fetch: { _ in
            try await Task.sleep(nanoseconds: 20_000_000)
            return descriptor
        })
        async let first = discovery.inspect(base)
        async let second = discovery.inspect(base)
        let (a, b) = await (first, second)
        XCTAssertNotNil(a); XCTAssertEqual(a, b)
    }
    func testRealDiscoveryAndFreshProfileReadWithoutRobot() async throws {
        guard let value = ProcessInfo.processInfo.environment["KAIKU_DISCOVERY_TEST_CLOUD"], let url = URL(string: value) else {
            throw XCTSkip("Set KAIKU_DISCOVERY_TEST_CLOUD for a local explicit-demo service")
        }
        let (app, _) = fixture(ServiceDiscovery(configuredURL: url))
        let connected = await app.ensureServiceConnection()
        XCTAssertTrue(connected)
        await app.refresh()
        XCTAssertFalse(app.offline); XCTAssertNotNil(app.me)
        XCTAssertTrue(app.pairing?.homeID.hasPrefix("device-") == true)
    }
}

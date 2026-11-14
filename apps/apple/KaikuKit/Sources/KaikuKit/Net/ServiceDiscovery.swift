import Foundation
@preconcurrency import Network
import Observation

public struct APIDiscoveryResponse: Codable, Equatable, Sendable {
    public enum Mode: String, Codable, Sendable { case demo, authenticated, unconfigured }
    public var service: String
    public var schema_version: Int
    public var mode: Mode
    public var auth_required: Bool
    public var capabilities: [String]
    var supportsVoice: Bool { service == "kaiku-api" && schema_version == 1 && capabilities.contains("companion_voice") }
    var permitsDemoConnection: Bool { supportsVoice && mode == .demo && !auth_required }
}

struct DiscoveredService: Identifiable, Equatable, Sendable {
    var baseURL: URL
    var name: String
    var descriptor: APIDiscoveryResponse
    var id: String { baseURL.absoluteString }
}

/// Stable, non-secret local profile identity, partitioned by service origin. Never a credential or a seeded
/// patient's identity. Existing explicitly provisioned profiles are adopted instead of silently replaced.
struct ServiceIdentity {
    static let key = "kaiku.serviceHomes"
    static func home(for url: URL, defaults: UserDefaults) -> String {
        var homes = defaults.dictionary(forKey: key) as? [String: String] ?? [:]
        let origin = ServiceDiscovery.origin(url.absoluteString)?.absoluteString ?? url.absoluteString
        if let home = homes[origin] { return home }
        let home = "device-" + UUID().uuidString.lowercased()
        homes[origin] = home; defaults.set(homes, forKey: key)
        return home
    }
    static func remember(_ pairing: Pairing, defaults: UserDefaults) {
        var homes = defaults.dictionary(forKey: key) as? [String: String] ?? [:]
        homes[ServiceDiscovery.origin(pairing.baseURL.absoluteString)?.absoluteString ?? pairing.baseURL.absoluteString] = pairing.homeID; defaults.set(homes, forKey: key)
    }
}

/// Browses backend services, NOT robots. Discovery requests carry no token, home, transcript or queue data.
/// Only a validated explicit-demo descriptor can create a local profile; production authorization remains
/// necessary. Bonjour results require selection; the configured build URL is the only automatic candidate.
@Observable @MainActor final class ServiceDiscovery {
    typealias Fetch = @Sendable (URL) async throws -> APIDiscoveryResponse
    private(set) var services: [DiscoveredService] = []
    private(set) var searching = false
    private(set) var failed = false
    let configuredURL: URL?
    @ObservationIgnored private let fetch: Fetch
    @ObservationIgnored private var browser: NWBrowser?
    @ObservationIgnored private var connections: [String: NWConnection] = [:]
    @ObservationIgnored private var requests: [URL: Task<APIDiscoveryResponse, Error>] = [:]

    init(configuredURL: URL? = ServiceDiscovery.buildURL, fetch: @escaping Fetch = { try await ServiceDiscovery.readDescriptor($0) }) {
        self.configuredURL = configuredURL.flatMap { Self.origin($0.absoluteString) }; self.fetch = fetch
    }
    nonisolated static var buildURL: URL? {
        (Bundle.main.object(forInfoDictionaryKey: "KaikuServiceURL") as? String).flatMap(origin)
    }
    nonisolated static func origin(_ text: String) -> URL? {
        guard var parts = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(parts.scheme?.lowercased() ?? ""), let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil else { return nil }
        parts.scheme = parts.scheme?.lowercased(); parts.host = host.lowercased()
        parts.path = ""; parts.query = nil; parts.fragment = nil
        return parts.url
    }
    nonisolated static func readDescriptor(_ base: URL) async throws -> APIDiscoveryResponse {
        var request = URLRequest(url: base.appendingPathComponent("v1/discovery"))
        request.timeoutInterval = 5
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw APIError.offline }
        return try JSONDecoder().decode(APIDiscoveryResponse.self, from: data)
    }

    @discardableResult func inspect(_ url: URL, name: String? = nil) async -> DiscoveredService? {
        guard let base = Self.origin(url.absoluteString) else { return nil }
        let request: Task<APIDiscoveryResponse, Error>
        if let pending = requests[base] { request = pending }
        else { request = Task { try await fetch(base) }; requests[base] = request }
        defer { requests[base] = nil }
        do {
            let descriptor = try await request.value
            guard descriptor.supportsVoice else { failed = true; return nil }
            let item = DiscoveredService(baseURL: base, name: name ?? base.host ?? "Kaiku", descriptor: descriptor)
            services.removeAll { $0.baseURL == base }; services.append(item)
            services.sort { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
            failed = false
            return item
        } catch { failed = true; return nil }
    }

    func configuredDemo() async -> DiscoveredService? {
        guard let url = configuredURL, let service = await inspect(url), service.descriptor.permitsDemoConnection else { return nil }
        return service
    }

    func start() {
        guard browser == nil else { return }
        searching = true; failed = false
        let browser = NWBrowser(for: .bonjour(type: "_kaiku-api._tcp", domain: "local."), using: .tcp)
        self.browser = browser
        browser.browseResultsChangedHandler = { [weak self] results, _ in Task { @MainActor in
            guard let self else { return }
            for result in results { self.resolve(result.endpoint) }
        } }
        browser.stateUpdateHandler = { [weak self] state in Task { @MainActor in
            if case .failed = state { self?.failed = true; self?.searching = false }
        } }
        browser.start(queue: .main)
        if let configuredURL { Task { await inspect(configuredURL) } }
    }

    func stop() {
        browser?.cancel(); browser = nil; searching = false
        connections.values.forEach { $0.cancel() }; connections = [:]
    }

    private func resolve(_ endpoint: NWEndpoint) {
        guard case .service(let name, _, _, _) = endpoint else { return }
        let id = endpoint.debugDescription
        guard connections[id] == nil else { return }
        let connection = NWConnection(to: endpoint, using: .tcp)
        connections[id] = connection
        connection.stateUpdateHandler = { [weak self, weak connection] state in Task { @MainActor in
            guard let self, let connection else { return }
            switch state {
            case .ready:
                if case .hostPort(let host, let port) = connection.currentPath?.remoteEndpoint {
                    var components = URLComponents(); components.scheme = "http"
                    components.host = "\(host)"; components.port = Int(port.rawValue)
                    if let url = components.url { Task { await self.inspect(url, name: name) } }
                }
                connection.cancel(); self.connections[id] = nil
            case .failed, .cancelled: self.connections[id] = nil
            default: break
            }
        } }
        connection.start(queue: .main)
        Task { [weak self, weak connection] in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            connection?.cancel(); self?.connections[id] = nil
        }
    }
}

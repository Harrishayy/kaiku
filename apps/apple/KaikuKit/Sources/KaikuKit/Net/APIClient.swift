import Foundation
import os

let kaikuLog = Logger(subsystem: "fi.kaiku.apple", category: "kaiku")

public enum APIError: Error, Equatable, Sendable {
    case notPaired
    case offline            // transport failure (no route, timeout, DNS)
    case http(Int)          // non-2xx after retries
    case decoding
}

/// Async HTTP client for the cloud. Timeouts on every call; idempotent calls retry with exponential backoff +
/// jitter; the home token goes in `Authorization: Bearer` (never logged). No Gemini key ever lives here.
public actor APIClient {
    public private(set) var pairing: Pairing?
    private let session: URLSession
    private let maxAttempts: Int
    private let baseDelay: Double

    public init(pairing: Pairing?, timeout: TimeInterval = 8, maxAttempts: Int = 3, baseDelay: Double = 0.5,
                session: URLSession? = nil) {
        self.pairing = pairing
        self.maxAttempts = maxAttempts
        self.baseDelay = baseDelay
        if let session { self.session = session } else {
            let cfg = URLSessionConfiguration.ephemeral
            cfg.timeoutIntervalForRequest = timeout
            cfg.timeoutIntervalForResource = max(timeout * 2, 130)
            cfg.waitsForConnectivity = false
            cfg.httpAdditionalHeaders = ["Accept": "application/json"]
            self.session = URLSession(configuration: cfg)
        }
    }

    public func setPairing(_ p: Pairing?) { pairing = p }

    // MARK: endpoints

    public func me() async throws -> MeResponse {
        try await get("/v1/me", query: ["home_id": try home()])
    }

    public func nudge() async throws -> NudgeResponse {
        try await get("/v1/nudge", query: ["home_id": try home()])
    }

    public func memories() async throws -> MemoriesResponse {
        try await get("/v1/me/memories", query: ["home_id": try home()])
    }

    public func deleteMemory(_ id: Int) async throws -> DeletedResponse {
        try await send("DELETE", "/v1/me/memories/\(id)", query: ["home_id": try home()], body: Optional<Int>.none)
    }

    public func deleteAllMemories() async throws -> DeletedResponse {
        try await send("DELETE", "/v1/me/memories", query: ["home_id": try home()], body: Optional<Int>.none)
    }

    /// Opt-in conversation transcripts (person-facing only).
    public func transcripts() async throws -> TranscriptsResponse {
        try await get("/v1/me/transcripts", query: ["home_id": try home()])
    }

    public func deleteAllTranscripts() async throws -> DeletedResponse {
        try await send("DELETE", "/v1/me/transcripts", query: ["home_id": try home()], body: Optional<Int>.none)
    }

    public func setRemember(_ on: Bool) async throws -> MemorySettings {
        try await send("PUT", "/v1/me/memory_settings", query: ["home_id": try home()], body: MemorySettings(remember: on))
    }

    /// History: every measure the person has, by local day, with each measure's latest sessions (D48).
    public func history(days: Int) async throws -> PersonHistory {
        try await get("/v1/me/history", query: ["home_id": try home(), "days": String(days)])
    }

    public func todaysEvents(since: Date) async throws -> LiveEventsResponse {
        try await get("/v1/events", query: ["home_id": try home(), "since": KaikuTime.iso(since), "limit": "500"])
    }

    public func postEvents(_ events: [AnyEnvelope], pairedTo expected: Pairing? = nil) async throws -> EventsResult {
        if let expected, pairing != expected { throw APIError.notPaired }
        return try await send("POST", "/v1/events", body: EventsBatch(events: events), retry: true)
    }

    public func companionSession(_ req: CompanionSessionRequest) async throws -> CompanionSessionResponse {
        try await send("POST", "/v1/companion/session", body: req, retry: false)
    }

    /// A few small pictures of one check-in for Kaiku's own model (D65). Sent once: no retry, never queued. The
    /// caller has already let go of the pictures; whatever comes back, they are not sent again.
    func visionLook(_ req: VisionLookRequest, home: String) async -> VisionLookResult? {
        try? await send("POST", "/v1/vision/look", query: ["home_id": home], body: req, retry: false, timeout: 40)
    }

    public func companionTool(_ call: CompanionToolCall) async throws -> CompanionToolResult {
        try await send("POST", "/v1/companion/tool", body: call, retry: false, timeout: call.name == "ask_mind" ? 120 : nil)
    }

    public func companionEpisode(_ ep: EpisodeIn, pairedTo expected: Pairing? = nil) async throws -> EpisodeResult {
        if let expected, pairing != expected { throw APIError.notPaired }
        return try await send("POST", "/v1/companion/episode", body: ep, retry: true)
    }

    /// A conversation stopped: tell the cloud how long it ran (once is enough, twice is harmless; a cloud that does
    /// not know the session answers 404, which the caller ignores).
    public func companionClose(_ close: SessionClose) async throws -> SessionCloseResult {
        try await send("POST", "/v1/companion/close", body: close, retry: false, timeout: 10)
    }

    /// `GET /v1/voice/{key}` → wav bytes (nil when the cloud has no voice for it: 404 or 503).
    public func voice(_ key: String, lang: String) async -> Data? {
        guard let req = try? request("GET", "/v1/voice/\(key)", query: ["lang": lang]) else { return nil }
        guard let (data, resp) = try? await session.data(for: req), (resp as? HTTPURLResponse)?.statusCode == 200
        else { return nil }
        return data
    }

    // MARK: plumbing

    private func home() throws -> String {
        guard let p = pairing else { throw APIError.notPaired }
        return p.homeID
    }

    func request(_ method: String, _ path: String, query: [String: String] = [:]) throws -> URLRequest {
        guard let p = pairing else { throw APIError.notPaired }
        var c = URLComponents(url: p.baseURL, resolvingAgainstBaseURL: false)!
        c.path = path
        if !query.isEmpty { c.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var r = URLRequest(url: c.url!)
        r.httpMethod = method
        if let t = p.token { r.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        return r
    }

    private func get<R: Decodable>(_ path: String, query: [String: String]) async throws -> R {
        try await run(try request("GET", path, query: query), retry: true)
    }

    private func send<B: Encodable, R: Decodable>(_ method: String, _ path: String, query: [String: String] = [:],
                                                  body: B?, retry: Bool = true, timeout: TimeInterval? = nil) async throws -> R {
        var r = try request(method, path, query: query)
        if let timeout { r.timeoutInterval = timeout }
        if let body {
            r.httpBody = try JSONEncoder().encode(body)
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return try await run(r, retry: retry)
    }

    private func run<R: Decodable>(_ req: URLRequest, retry: Bool) async throws -> R {
        var attempt = 0
        while true {
            attempt += 1
            do {
                let (data, resp) = try await session.data(for: req)
                let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
                if (200..<300).contains(code) {
                    do { return try JSONDecoder().decode(R.self, from: data) } catch {
                        kaikuLog.error("decode_failed \(req.url?.path ?? "", privacy: .public)")
                        throw APIError.decoding
                    }
                }
                // 4xx (other than 408/429) won't get better by retrying.
                if !retry || attempt >= maxAttempts || ((400..<500).contains(code) && code != 408 && code != 429) {
                    kaikuLog.notice("http_error \(code) \(req.url?.path ?? "", privacy: .public)")
                    throw APIError.http(code)
                }
            } catch let e as APIError {
                throw e
            } catch {
                if !retry || attempt >= maxAttempts {
                    kaikuLog.notice("offline \(req.url?.path ?? "", privacy: .public)")
                    throw APIError.offline
                }
            }
            let delay = baseDelay * pow(2, Double(attempt - 1)) * Double.random(in: 0.8...1.2)
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
        }
    }
}

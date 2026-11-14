import Foundation

/// Every obs the app makes goes through this queue: appended to a JSON file first (so nothing is lost if the app
/// dies or the cloud is away), then sent in batches. Envelope ids are fixed at creation, so resending is safe
/// (the cloud ignores duplicates by id). Events the cloud rejects as invalid are dropped (they never will pass).
public actor OfflineQueue {
    private let url: URL
    private struct Entry: Codable { var event: AnyEnvelope; var server: URL? }
    private var items: [Entry]
    private var flushing = false
    public static let maxItems = 2000

    public init(url: URL = KaikuPaths.support.appendingPathComponent("outbox.json")) {
        self.url = url
        if let data = try? Data(contentsOf: url) {
            if let saved = try? JSONDecoder().decode([Entry].self, from: data) { items = saved }
            else { items = ((try? JSONDecoder().decode([AnyEnvelope].self, from: data)) ?? []).map { Entry(event: $0, server: nil) } }
        } else { items = [] }
    }

    public var count: Int { items.count }
    public var pending: [AnyEnvelope] { items.map(\.event) }

    public func enqueue(_ e: AnyEnvelope, server: URL) {
        guard !items.contains(where: { $0.event.id == e.id && $0.server == server }) else { return }
        items.append(Entry(event: e, server: server))
        if items.count > Self.maxItems { items.removeFirst(items.count - Self.maxItems) }
        persist()
    }

    /// Sends everything queued (batches of 100). Returns true when the queue is empty afterwards.
    @discardableResult
    public func flush(using api: APIClient) async -> Bool {
        // Another flush is already delivering: not a failure, so callers must not report "offline".
        guard !flushing else { return true }
        flushing = true
        defer { flushing = false }
        guard let pairing = await api.pairing else { return items.isEmpty }
        while true {
            guard await api.pairing == pairing else { return false }
            // Legacy unscoped entries remain on disk; never guess which server should receive them.
            let batch = Array(items.filter { $0.server == pairing.baseURL && $0.event.home_id == pairing.homeID }.prefix(100)).map(\.event)
            if batch.isEmpty { return true }
            do {
                let result = try await api.postEvents(batch, pairedTo: pairing)
                let sent = Set(batch.map(\.id))
                items.removeAll { sent.contains($0.event.id) && $0.server == pairing.baseURL }
                if let rejected = result.rejected, !rejected.isEmpty {
                    kaikuLog.notice("events_rejected \(rejected.count)")
                }
                persist()
            } catch APIError.http(let code) where code == 422 || code == 400 {
                // A malformed batch never passes: drop it rather than block everything behind it.
                let sent = Set(batch.map(\.id))
                items.removeAll { sent.contains($0.event.id) && $0.server == pairing.baseURL }
                kaikuLog.error("events_dropped_invalid \(batch.count)")
                persist()
            } catch {
                return false
            }
        }
    }

    public func clear() {
        items.removeAll()
        persist()
    }

    private func persist() {
        guard let data = try? JSONEncoder().encode(items) else { return }
        #if os(iOS)
        try? data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        #else
        try? data.write(to: url, options: .atomic)
        #endif
    }
}

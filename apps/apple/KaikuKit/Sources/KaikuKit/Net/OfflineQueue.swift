import Foundation

/// Every obs the app makes goes through this queue: appended to a JSON file first (so nothing is lost if the app
/// dies or the cloud is away), then sent in batches. Envelope ids are fixed at creation, so resending is safe
/// (the cloud ignores duplicates by id). Events the cloud rejects as invalid are dropped (they never will pass).
public actor OfflineQueue {
    private let url: URL
    private var items: [AnyEnvelope]
    private var flushing = false
    public static let maxItems = 2000

    public init(url: URL = KaikuPaths.support.appendingPathComponent("outbox.json")) {
        self.url = url
        if let data = try? Data(contentsOf: url), let saved = try? JSONDecoder().decode([AnyEnvelope].self, from: data) {
            items = saved
        } else {
            items = []
        }
    }

    public var count: Int { items.count }
    public var pending: [AnyEnvelope] { items }

    public func enqueue(_ e: AnyEnvelope) {
        guard !items.contains(where: { $0.id == e.id }) else { return }
        items.append(e)
        if items.count > Self.maxItems { items.removeFirst(items.count - Self.maxItems) }
        persist()
    }

    /// Sends everything queued (batches of 100). Returns true when the queue is empty afterwards.
    @discardableResult
    public func flush(using api: APIClient) async -> Bool {
        guard !flushing else { return items.isEmpty }
        flushing = true
        defer { flushing = false }
        while !items.isEmpty {
            let batch = Array(items.prefix(100))
            do {
                let result = try await api.postEvents(batch)
                let sent = Set(batch.map(\.id))
                items.removeAll { sent.contains($0.id) }
                if let rejected = result.rejected, !rejected.isEmpty {
                    kaikuLog.notice("events_rejected \(rejected.count)")
                }
                persist()
            } catch APIError.http(let code) where code == 422 || code == 400 {
                // A malformed batch never passes: drop it rather than block everything behind it.
                let sent = Set(batch.map(\.id))
                items.removeAll { sent.contains($0.id) }
                kaikuLog.error("events_dropped_invalid \(batch.count)")
                persist()
            } catch {
                return false
            }
        }
        return true
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

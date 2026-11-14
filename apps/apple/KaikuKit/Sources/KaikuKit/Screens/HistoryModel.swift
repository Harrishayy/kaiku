import Foundation
import Observation

// History's data on the device: the one request, the copy kept for opening offline, and the observable model the
// History screens read. The person's own numbers from every device, as the service has them
// (`GET /v1/me/history`); the device adds nothing and judges nothing.

/// The last History the service gave, kept on the device so the tab opens offline with what it last had.
/// The file names the service and the home it belongs to and carries no credentials; a copy for another
/// service or home is never shown, and a pairing change removes the file (apps/apple/AGENTS.md → Invariants).
public struct HistoryCache: Sendable {
    public struct Entry: Codable, Equatable, Sendable {
        public var server: URL
        public var home: String
        public var fetched: Date
        public var history: PersonHistory
    }

    let url: URL
    public init(url: URL = KaikuPaths.support.appendingPathComponent("history.json")) { self.url = url }

    public func load(for pairing: Pairing) -> Entry? {
        guard let data = try? Data(contentsOf: url), let e = try? JSONDecoder().decode(Entry.self, from: data),
              e.server == pairing.baseURL, e.home == pairing.homeID, e.history.home_id == pairing.homeID else { return nil }
        return e
    }

    public func save(_ history: PersonHistory, for pairing: Pairing, at date: Date = Date()) {
        guard history.home_id == pairing.homeID else { return }
        let e = Entry(server: pairing.baseURL, home: pairing.homeID, fetched: date, history: history)
        guard let data = try? JSONEncoder().encode(e) else { return }
        try? data.write(to: url, options: .atomic)
    }

    public func clear() { try? FileManager.default.removeItem(at: url) }
}

/// What the History screens show. One per app (like the walk): the summary and a measure's page read the same
/// record, and a pairing change empties it together with the other cached person data.
@Observable @MainActor
public final class HistoryModel {
    public static let shared = HistoryModel()
    /// Days asked for: a month on the measure page and the month before it.
    public static let days = 56

    public private(set) var history: PersonHistory?
    /// When what is shown was fetched (shown as "Updated …"; with `stale`, "Last fetched …").
    public private(set) var fetched: Date?
    /// The last request failed and an earlier copy is on screen.
    public private(set) var stale = false
    public private(set) var loading = false
    /// The last request failed and there is nothing to show.
    public private(set) var failed = false

    /// Where the copy is kept (tests point it at a temporary file).
    @ObservationIgnored var cache: HistoryCache
    @ObservationIgnored private var loadedFor: Pairing?
    @ObservationIgnored private var generation = 0
    /// Injected in tests; nil = the app's own client.
    @ObservationIgnored var fetch: ((Pairing) async throws -> PersonHistory)?

    public init(cache: HistoryCache = HistoryCache()) { self.cache = cache }

    public var groups: [HistoryGroup] { history?.shown ?? [] }
    public func measure(_ ref: HistoryRef) -> (group: HistoryGroup, measure: HistoryMeasure)? {
        guard let g = groups.first(where: { $0.key == ref.group }), let m = g.measures.first(where: { $0.key == ref.measure }) else { return nil }
        return (g, m)
    }
    /// The first measure with that key in any group (launch arguments name a measure by its key alone).
    public func measure(key: String) -> (group: HistoryGroup, measure: HistoryMeasure)? {
        for g in groups { if let m = g.measures.first(where: { $0.key == key }) { return (g, m) } }
        return nil
    }

    /// Shows the kept copy at once, then asks the service. A failed request keeps what was on screen.
    public func load(app: AppModel) async {
        guard let pairing = app.pairing else { clear(); return }
        show(cached: pairing)
        guard !loading else { return }
        loading = true
        generation += 1
        let mine = generation
        let result: PersonHistory?
        do {
            if let fetch { result = try await fetch(pairing) } else { result = try await app.api.history(days: Self.days) }
        } catch { result = nil }
        // The pairing changed while the request was out: its answer belongs to nobody on this screen.
        guard mine == generation, app.pairing == pairing else { return }
        loading = false
        if let result, result.home_id == pairing.homeID {
            history = result; fetched = Date(); stale = false; failed = false
            cache.save(result, for: pairing)
        } else {
            stale = history != nil
            failed = history == nil
        }
    }

    /// What was kept for this service and home, on screen at once (nothing when there is no such copy).
    func show(cached pairing: Pairing) {
        guard loadedFor != pairing else { return }
        reset()
        loadedFor = pairing
        if let e = cache.load(for: pairing) { history = e.history; fetched = e.fetched }
    }

    /// A new paired home or service must not see the previous person's numbers: memory and the kept copy go.
    public func clearForPairingChange() {
        clear()
        cache.clear()
    }

    private func clear() { reset(); loadedFor = nil }
    private func reset() {
        generation += 1
        history = nil; fetched = nil; stale = false; loading = false; failed = false
    }
}

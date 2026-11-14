import Foundation

/// Consent-filtered conversation completions survive termination and offline operation. No credentials or
/// audio are persisted. A queued completion can only be sent to the home and server that started it.
@MainActor final class EpisodeOutbox {
    struct Entry: Codable { var server: URL; var episode: EpisodeIn }
    private let url: URL
    private(set) var entries: [Entry]
    private var flushing = false

    init(url: URL = KaikuPaths.support.appendingPathComponent("episodes-outbox.json")) {
        self.url = url
        entries = (try? Data(contentsOf: url)).flatMap { try? JSONDecoder().decode([Entry].self, from: $0) } ?? []
    }

    @discardableResult func enqueue(_ episode: EpisodeIn, pairing: Pairing) -> Bool {
        guard episode.home_id == pairing.homeID else { return false }
        if let i = entries.firstIndex(where: { $0.server == pairing.baseURL && $0.episode.id == episode.id }) {
            if entries[i].episode.outcome == .crisis { return true }
            entries[i].episode = episode
        } else { entries.append(Entry(server: pairing.baseURL, episode: episode)) }
        return persist()
    }

    func removeTranscripts() {
        for i in entries.indices { entries[i].episode.transcript = nil }
        _ = persist()
    }

    func flush(using api: APIClient) async -> Bool {
        // Another flush is already delivering: that is not a failure (it used to raise a false offline banner).
        guard !flushing else { return true }
        flushing = true
        defer { flushing = false }
        guard let pairing = await api.pairing else { return entries.isEmpty }
        while let entry = entries.first(where: { $0.server == pairing.baseURL && $0.episode.home_id == pairing.homeID }) {
            guard await api.pairing == pairing else { return false }
            do {
                let result = try await api.companionEpisode(entry.episode, pairedTo: pairing)
                guard result.ok else { return false }
                entries.removeAll { $0.server == entry.server && $0.episode.id == entry.episode.id }
                if !persist() { return false }
            } catch { return false }
        }
        return true
    }

    @discardableResult private func persist() -> Bool {
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            let data = try JSONEncoder().encode(entries)
            #if os(iOS)
            try data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            #else
            try data.write(to: url, options: .atomic)
            #endif
            return true
        } catch { kaikuLog.error("episode_outbox_write_failed"); return false }
    }
}

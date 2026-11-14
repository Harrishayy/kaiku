import AppIntents
import KaikuKit

// Compiled into BOTH the iOS app and the widget extension: the Live Activity buttons reference these types, and
// a LiveActivityIntent's perform() runs in the app process, where WalkModel.shared is the running walk.

struct FoundOneIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "Found one"
    static let isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        WalkModel.shared.foundOne()
        return .result()
    }
}

struct EndWalkIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "End walk"
    static let isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        await WalkModel.shared.end()
        return .result()
    }
}

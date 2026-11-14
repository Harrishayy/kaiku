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

// MARK: the call with Kaiku (Talk / check-in chat): the same rule, the buttons act on the call that is open.

struct ToggleCallMicIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "Mute or unmute yourself"
    static let isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        KaikuCall.toggleMic()
        return .result()
    }
}

struct ToggleCallVoiceIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "Mute or unmute Kaiku"
    static let isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        KaikuCall.toggleVoice()
        return .result()
    }
}

struct EndCallIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "End the call with Kaiku"
    static let isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        KaikuCall.end()          // ends the session and closes the microphone
        return .result()
    }
}

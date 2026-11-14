import AppIntents
import KaikuKit

/// Siri / Shortcuts / Action button (plan 05 §4). Each intent opens the app on the exact screen through the same
/// `kaiku://` links as notifications and widgets.
@MainActor
enum IntentRouter {
    static var open: ((URL) -> Void)?
    static var pending: URL?

    static func go(_ link: String) {
        guard let u = URL(string: link) else { return }
        if let open { open(u) } else { pending = u }
    }
}

struct CheckInIntent: AppIntent {
    static let title: LocalizedStringResource = "Check in with Kaiku"
    static let description = IntentDescription("Opens the weather check.")
    static let openAppWhenRun = true
    @MainActor func perform() async throws -> some IntentResult { IntentRouter.go("kaiku://checkin"); return .result() }
}

struct StartWalkIntent: AppIntent {
    static let title: LocalizedStringResource = "Start a walk with Kaiku"
    static let description = IntentDescription("Starts a light hunt walk.")
    static let openAppWhenRun = true
    @MainActor func perform() async throws -> some IntentResult { IntentRouter.go("kaiku://walk"); return .result() }
}

struct BreatheIntent: AppIntent {
    static let title: LocalizedStringResource = "Breathe with Kaiku"
    static let description = IntentDescription("One to three minutes of slow breathing.")
    static let openAppWhenRun = true
    @MainActor func perform() async throws -> some IntentResult { IntentRouter.go("kaiku://breathe"); return .result() }
}

struct TalkIntent: AppIntent {
    static let title: LocalizedStringResource = "Talk to Kaiku"
    static let description = IntentDescription("Opens Talk.")
    static let openAppWhenRun = true
    @MainActor func perform() async throws -> some IntentResult { IntentRouter.go("kaiku://talk"); return .result() }
}

struct KaikuShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: CheckInIntent(), phrases: ["Check in with \(.applicationName)", "Kuulumiset \(.applicationName)"],
                    shortTitle: "Check in", systemImageName: "cloud.sun")
        AppShortcut(intent: StartWalkIntent(), phrases: ["Start a walk with \(.applicationName)", "Kävelylle \(.applicationName)"],
                    shortTitle: "Walk", systemImageName: "figure.walk")
        AppShortcut(intent: BreatheIntent(), phrases: ["Breathe with \(.applicationName)", "Hengitä \(.applicationName)"],
                    shortTitle: "Breathe", systemImageName: "wind")
        AppShortcut(intent: TalkIntent(), phrases: ["Talk to \(.applicationName)", "Juttele \(.applicationName)"],
                    shortTitle: "Talk", systemImageName: "bubble.left.and.bubble.right")
    }
}

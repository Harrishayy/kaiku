import Foundation

/// First-run setup, in order (pure; tested). Download → open → welcome → what Kaiku is and isn't → connect →
/// choices → permissions → first hello + a first tiny task → Today. The step is persisted, so setup resumes where
/// it was left, and You → "Run setup again" starts it over without touching choices, pairing or data.
public enum SetupStep: Int, CaseIterable, Sendable {
    case welcome, about, connect, choices, permissions, hello

    /// Steps the person may leave without doing anything (nothing unsafe is switched on by skipping).
    /// `about` is never skippable: what Kaiku is not (medical opinion, emergency care) must be seen once.
    public var skippable: Bool {
        switch self {
        case .connect, .permissions, .hello: return true
        case .welcome, .about, .choices: return false
        }
    }

    public var next: SetupStep? { SetupStep(rawValue: rawValue + 1) }
    public var previous: SetupStep? { SetupStep(rawValue: rawValue - 1) }
    /// 1-based position for "Step n of 6".
    public var number: Int { rawValue + 1 }

    public var screen: KaikuScreen {
        switch self {
        case .welcome: return .onboardingWelcome
        case .about: return .onboardingAbout
        case .connect: return .onboardingPair
        case .choices: return .onboardingConsent
        case .permissions: return .onboardingPermissions
        case .hello: return .onboardingHello
        }
    }

    /// Where to start: an explicit dev/test launch argument wins, else the saved step, else the beginning.
    /// Out-of-range values (an older build's numbering) fall back to the start rather than a blank screen.
    public static func resume(saved: Int?, launchArgument: String?) -> SetupStep {
        if let a = launchArgument, let n = Int(a), let s = SetupStep(rawValue: n) { return s }
        if let saved, let s = SetupStep(rawValue: saved) { return s }
        return .welcome
    }
}

/// One permission row in setup (pure state; the view asks the system).
public enum SetupPermissionState: Equatable, Sendable {
    case notAsked, allowed, denied
    /// `denied` can only be changed in system Settings, so the row offers that instead of asking again.
    public var canAsk: Bool { self == .notAsked }
}

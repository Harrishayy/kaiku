import Foundation

/// Quick talk on the Mac, the triggers (pure, tested). Two ways to start talking from any app:
/// - a key combination registered as a system hot key (`QuickTalkHotKey`, on whenever quick talk is on), and
/// - a double tap of one modifier key on its own (`QuickTalkDoubleTap`, the person's choice, off by default).
/// Neither needs a macOS permission (checked on macOS 26.5 with an app that has neither Accessibility nor Input
/// Monitoring: a registered hot key fires, and a global monitor is handed modifier changes but no key presses).
/// The double tap therefore never sees which keys are typed: it gets modifier changes and the system's running
/// count of key and mouse presses, nothing else.

/// Modifier keys, independent of AppKit.
public struct QuickTalkMods: OptionSet, Sendable, Hashable {
    public let rawValue: Int
    public init(rawValue: Int) { self.rawValue = rawValue }
    public static let shift = QuickTalkMods(rawValue: 1 << 0)
    public static let control = QuickTalkMods(rawValue: 1 << 1)
    public static let option = QuickTalkMods(rawValue: 1 << 2)
    public static let command = QuickTalkMods(rawValue: 1 << 3)
    public static let function = QuickTalkMods(rawValue: 1 << 4)
}

/// Which key a double tap listens for (You → Quick talk). `off` = the key combination only.
public enum QuickTalkDoubleTapKey: String, CaseIterable, Sendable {
    case off, option, control

    public var mods: QuickTalkMods? {
        switch self {
        case .off: return nil
        case .option: return .option
        case .control: return .control
        }
    }
}

/// The key combination: Option-Shift-Space. Not Spotlight (Command-Space), not input-source switching
/// (Control-Space, Control-Option-Space), not the usual launcher key (Option-Space). Values are Carbon's
/// (`kVK_Space`, `optionKey | shiftKey`), spelled out so this file needs no Carbon import. Its on-screen name is
/// the copy key `quick.keys`.
public enum QuickTalkHotKey {
    public static let keyCode: UInt32 = 49
    public static let carbonModifiers: UInt32 = 0x0800 | 0x0200
    /// Escape, taken as a hot key only while the panel is open (the panel never has keyboard focus).
    public static let escapeKeyCode: UInt32 = 53
}

/// Two taps of the same modifier key on its own. A tap is a press from no modifiers at all, released within
/// `maxHold` (longer is holding the key, for a shortcut or a special character). The second press must start
/// within `maxGap` of the first release. Any other modifier, key press or mouse press in between starts over.
/// It fires on the second release, so tap-then-hold (Option held to type a character) never fires.
public struct QuickTalkDoubleTap: Sendable, Equatable {
    public var key: QuickTalkMods
    public var maxHold: TimeInterval
    public var maxGap: TimeInterval

    private enum Stage: Equatable, Sendable {
        case idle
        case firstDown(TimeInterval)
        case firstUp(TimeInterval)
        case secondDown(TimeInterval)
    }
    private var stage = Stage.idle
    private var last: QuickTalkMods = []
    private var inputMark: UInt64 = 0

    public init(key: QuickTalkMods, maxHold: TimeInterval = 0.3, maxGap: TimeInterval = 0.4) {
        self.key = key
        self.maxHold = maxHold
        self.maxGap = maxGap
    }

    /// Feed every change of the modifier keys, with the time it happened. `input` is a running count of other
    /// key and mouse presses: when it moved since the first press, something else was pressed in between.
    /// Returns true when this change completes a double tap.
    public mutating func modifiersChanged(_ mods: QuickTalkMods, at t: TimeInterval, input: UInt64 = 0) -> Bool {
        let previous = last
        guard mods != previous else { return false }   // Caps Lock, or the second Option key joining the first
        last = mods
        if stage != .idle, input != inputMark { stage = .idle }
        if mods == key, previous.isEmpty {
            if case .firstUp(let up) = stage, t >= up, t - up <= maxGap {
                stage = .secondDown(t)
            } else {
                stage = .firstDown(t)
                inputMark = input
            }
            return false
        }
        if mods.isEmpty, previous == key {
            switch stage {
            case .firstDown(let down) where t >= down && t - down <= maxHold:
                stage = .firstUp(t)
            case .secondDown(let down) where t >= down && t - down <= maxHold:
                stage = .idle
                return true
            default:
                stage = .idle
            }
            return false
        }
        stage = .idle   // another modifier is involved
        return false
    }

    /// A key or mouse press seen directly (events that reach Kaiku's own windows): start over.
    public mutating func otherInput() { stage = .idle }

    public mutating func reset() {
        stage = .idle
        last = []
    }
}

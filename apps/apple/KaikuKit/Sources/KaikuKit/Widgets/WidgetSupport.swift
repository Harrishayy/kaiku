import Foundation
import SwiftUI

/// The small snapshot widgets read (plan 05 §4): written by the app into the App Group after each refresh;
/// widgets never call the network themselves.
public struct WidgetSnapshot: Codable, Sendable, Equatable {
    public var mood: String          // MascotState raw value (ambient)
    public var suggestionKey: String // copy key of today's suggestion
    public var checkedIn: Bool
    public var lang: String
    public var updated: Date

    public init(mood: String, suggestionKey: String, checkedIn: Bool, lang: String, updated: Date = Date()) {
        self.mood = mood; self.suggestionKey = suggestionKey; self.checkedIn = checkedIn; self.lang = lang; self.updated = updated
    }

    public static let placeholder = WidgetSnapshot(mood: MascotState.idle.rawValue, suggestionKey: "today.suggest.none",
                                                   checkedIn: false, lang: KaikuLanguage.system.rawValue)

    public var state: MascotState { MascotState(rawValue: mood) ?? .idle }
    public var language: KaikuLanguage { KaikuLanguage(rawValue: lang) ?? .en }
}

public enum WidgetShared {
    /// From Info.plist `KaikuAppGroup` (= build setting KAIKU_APP_GROUP; App Group ids are unique per Apple team).
    public static let group = Bundle.main.object(forInfoDictionaryKey: "KaikuAppGroup") as? String ?? "group.fi.kaiku"
    static let key = "kaiku.widget"

    static var defaults: UserDefaults? { UserDefaults(suiteName: group) }

    public static func read() -> WidgetSnapshot {
        guard let d = defaults?.data(forKey: key), let s = try? JSONDecoder().decode(WidgetSnapshot.self, from: d) else { return .placeholder }
        return s
    }

    public static func write(_ s: WidgetSnapshot) {
        if let d = try? JSONEncoder().encode(s) { defaults?.set(d, forKey: key) }
    }
}

extension AppModel {
    /// What the widgets show right now.
    public var widgetSnapshot: WidgetSnapshot {
        let key = nudge.map { "today.suggest.\($0.arm.rawValue)" } ?? "today.suggest.none"
        return WidgetSnapshot(mood: ambientState.rawValue, suggestionKey: key, checkedIn: weatherDoneToday, lang: language.rawValue)
    }
}

/// A string in a given language (widgets and Live Activities render outside the app's language setting).
public func TL(_ key: String, _ lang: KaikuLanguage, _ args: [String: String] = [:]) -> String {
    L10n.shared.string(key, args, lang: lang)
}

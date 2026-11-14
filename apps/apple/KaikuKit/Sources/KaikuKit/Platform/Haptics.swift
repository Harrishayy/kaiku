import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

/// Haptics per design/motion.md → Haptics. The crisis button never gets playful feedback.
public enum Haptics {
    public static func dialStep() {
        #if os(iOS)
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        #elseif os(macOS)
        NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .now)
        #endif
    }

    public static func finished() {
        #if os(iOS)
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        #elseif os(macOS)
        NSHapticFeedbackManager.defaultPerformer.perform(.levelChange, performanceTime: .now)
        #endif
    }

    public static func tapKaiku() {
        #if os(iOS)
        UIImpactFeedbackGenerator(style: .soft).impactOccurred(intensity: 0.5)
        #endif
    }

    /// A firefly caught / a right pebble: a crisp little tap.
    public static func catchFirefly() {
        #if os(iOS)
        UIImpactFeedbackGenerator(style: .rigid).impactOccurred(intensity: 0.6)
        #elseif os(macOS)
        NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .now)
        #endif
    }

    /// A moth / a wrong pebble: soft and low, never an error buzz.
    public static func softTap() {
        #if os(iOS)
        UIImpactFeedbackGenerator(style: .soft).impactOccurred(intensity: 0.45)
        #endif
    }

    public static func breathTurn() {
        #if os(iOS)
        UIImpactFeedbackGenerator(style: .soft).impactOccurred(intensity: 0.3)
        #endif
    }
}

public enum KaikuPlatform {
    #if os(iOS)
    public static let isPhone = true
    #else
    public static let isPhone = false
    #endif
    public static var source: EnvelopeSource { isPhone ? .phone : .laptop }
    public static var channel: SelfReportChannel { isPhone ? .phone : .mac }
    public static var device: PlayDevice { isPhone ? .phone : .mac }
    public static var surface: CompanionSurface { isPhone ? .iphone : .mac }
    /// Side padding (layout.md → Sizes): 18 pt iPhone, 26 pt Mac pane.
    public static var sidePadding: CGFloat { isPhone ? 22 : 28 }
}

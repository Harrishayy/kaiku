import SwiftUI

/// Weather check: three 1–5 dials (mood, energy, last night's sleep). Kaiku's ear follows the dial being turned.
/// "That's it" → three obs.self_report (channel phone|mac) through the offline queue → happy + thanks.
public struct WeatherCheckView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var values: [DialItem: Int] = [.mood: 3, .energy: 3, .sleep: 3]
    @State private var active: DialItem = .mood
    @State private var done = false

    public init() {}

    public var body: some View {
        KScreen(T("wx.title"), back: { dismiss() }) {
            MascotWithBubble(state: done ? .happy : .listening,
                             text: done ? T("wx.thanks") : T("wx.\(active.rawValue).\(values[active] ?? 3)"),
                             size: 120, dial: done ? nil : Double(values[active] ?? 3))
            ForEach(DialItem.allCases) { item in
                KCard {
                    WeatherDial(item: item, value: binding(item), disabled: done) { active = item }
                }
            }
            Button(T("wx.done")) {
                guard !done else { return }
                Haptics.finished()
                withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base)) { done = true }
                let v = values
                Task {
                    await app.recordWeather(v)
                    try? await Task.sleep(nanoseconds: 1_800_000_000)
                    dismiss()
                }
            }
            .buttonStyle(.kPrimary)
            .disabled(done)
        }
    }

    private func binding(_ item: DialItem) -> Binding<Int> {
        Binding(get: { values[item] ?? 3 }, set: { values[item] = $0; active = item })
    }
}


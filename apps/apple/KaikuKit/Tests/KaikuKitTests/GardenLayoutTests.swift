import SwiftUI
import XCTest
@testable import KaikuKit

/// The garden's row of day plots must fit the width it is given. On 2026-11-14 it did not: six days of three
/// icons each could not be narrower than 334 pt, which made Today wider than a small phone's screen, left an
/// empty day with no width, and on the Mac (two columns sized from the pane's own width) kept the window laying
/// itself out for ever.
@MainActor final class GardenFitTests: XCTestCase {
    /// The week the seeded person has: six full days, then today.
    static func week(today kinds: [String]) -> Garden {
        let full: [[String]] = [
            ["outing", "play_session", "weather_check"], ["outing", "play_session", "ritual"], ["outing", "play_session", "ritual"],
            ["drum_session", "outing", "play_session", "ritual", "weather_check"], ["drum_session", "outing", "play_session", "ritual"],
            ["drum_session", "outing", "play_session", "ritual"],
        ]
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = .current
        let today = cal.startOfDay(for: Date())
        var days: [GardenDay] = []
        for (i, k) in (full + [kinds]).enumerated() {
            let date = cal.date(byAdding: .day, value: i - 6, to: today)!
            days.append(GardenDay(date: AppModel.dayKey(date), count: k.count * 2, kinds: k))
        }
        return Garden(plants: 40, resting: false, days: days)
    }

    static func fitted<V: View>(_ view: V, width: CGFloat) -> CGSize {
        NSHostingController(rootView: view).sizeThatFits(in: CGSize(width: width, height: 10_000))
    }

    /// A phone's garden card is 311 pt inside on a 4.7-inch screen and 338 pt on a 6.3-inch one; a Mac column
    /// can be narrower still. Whatever the week holds, the row is as wide as it is offered and no wider.
    func testTheGardenIsNeverWiderThanItIsOffered() {
        for today in [[], ["play_session"], ["drum_session", "outing", "play_session", "ritual"]] as [[String]] {
            let garden = Self.week(today: today)
            for width in stride(from: 200 as CGFloat, through: 520, by: 9.5) {
                let size = Self.fitted(GardenBeds(garden: garden, weeks: 1, plantHeight: 84), width: width)
                XCTAssertLessThanOrEqual(size.width, width + 0.5, "today \(today.count) kinds, offered \(width)")
            }
        }
    }

    /// The same inside Today's garden card, as the page lays it out.
    func testTheGardenCardIsNeverWiderThanItIsOffered() {
        for today in [[], ["outing", "play_session", "ritual"]] as [[String]] {
            for width in [343, 370, 349.5, 412] as [CGFloat] {   // iPhone SE, iPhone 17 Pro, the Mac's column, a narrow Mac pane
                let size = Self.fitted(GardenCard(garden: Self.week(today: today)) {}, width: width)
                XCTAssertLessThanOrEqual(size.width, width + 0.5, "today \(today.count) kinds, offered \(width)")
            }
        }
    }
}

// MARK: the rule for a plot's width (pure)

final class GardenRowTests: XCTestCase {
    func testThePlotsShareTheRowEqually() {
        // The garden card's inside on an iPhone SE, an iPhone 17 Pro, the Mac's column at 980 pt and a narrow Mac pane.
        for row in [311, 338, 317.44, 412, 672] as [CGFloat] {
            let plot = GardenRow.plotWidth(row: row, plots: 7, gap: 8)
            XCTAssertEqual(plot * 7 + 8 * 6, row, accuracy: 0.0001, "plots and gaps fill the row exactly")
            XCTAssertGreaterThan(plot, 36, "room for a plant and its day at \(row)")
        }
        XCTAssertEqual(GardenRow.plotWidth(row: 311, plots: 7, gap: 8), 263.0 / 7, accuracy: 0.0001)
        XCTAssertEqual(GardenRow.plotWidth(row: 300, plots: 5, gap: 8), 53.6, accuracy: 0.0001, "a shorter week shares the same way")
        XCTAssertEqual(GardenRow.plotWidth(row: 120, plots: 1, gap: 8), 120, "one plot has the row")
    }

    func testAPlotHasWidthWheneverTheRowHasRoomBeyondItsGaps() {
        XCTAssertEqual(GardenRow.plotWidth(row: 55, plots: 7, gap: 8), 1, accuracy: 0.0001)
        XCTAssertGreaterThan(GardenRow.plotWidth(row: 48.5, plots: 7, gap: 8), 0)
        // Nothing to share: zero, never less (a negative width is not a size).
        XCTAssertEqual(GardenRow.plotWidth(row: 48, plots: 7, gap: 8), 0)
        XCTAssertEqual(GardenRow.plotWidth(row: 20, plots: 7, gap: 8), 0)
        XCTAssertEqual(GardenRow.plotWidth(row: 0, plots: 7, gap: 8), 0)
        XCTAssertEqual(GardenRow.plotWidth(row: 311, plots: 0, gap: 8), 0)
        XCTAssertEqual(GardenRow.plotWidth(row: .infinity, plots: 7, gap: 8), 0)
        XCTAssertEqual(GardenRow.plotWidth(row: .nan, plots: 7, gap: 8), 0)
    }

    /// A plant is drawn inside its plot: its leaves are as long as designed where there is room and stop short of
    /// the plot's edge where there is not (they were cut off straight in a phone's 37.6 pt plots).
    func testAPlantsLeavesStayInsideItsPlot() {
        for plot in [37.57, 38.49, 41.43, 52, 89] as [CGFloat] {
            for level in 1...5 {
                for sway in [-3, 0, 3] as [CGFloat] {
                    let leaf = DayPlant.leafLength(level: level, plot: plot, sway: sway)
                    XCTAssertLessThanOrEqual(abs(sway) + leaf, plot / 2, "plot \(plot), level \(level), sway \(sway)")
                    XCTAssertGreaterThanOrEqual(leaf, 6)
                }
            }
        }
        XCTAssertEqual(DayPlant.leafLength(level: 5, plot: 52, sway: 3), 20.5, "as designed where the plot has room")
        XCTAssertEqual(DayPlant.leafLength(level: 1, plot: 37.57, sway: 0), 14.5, "a small plant is unchanged on a phone")
        XCTAssertEqual(DayPlant.leafLength(level: 5, plot: 37.57, sway: 3), 37.57 / 2 - 4, accuracy: 0.001)
    }

    func testTheWidthARowAsksForWhenNobodySays() {
        XCTAssertEqual(GardenRow.idealWidth(plots: 7, gap: 8), 7 * GardenRow.idealPlot + 48)
        XCTAssertEqual(GardenRow.idealWidth(plots: 0, gap: 8), 0)
    }
}

// MARK: the row and what stands under a plant

@MainActor final class GardenPlotsTests: XCTestCase {
    /// The row is the width it is offered even when what it holds cannot be that narrow (the old row grew).
    func testTheRowIsExactlyAsWideAsItIsOffered() {
        for width in [120, 311, 338, 500] as [CGFloat] {
            let stubborn = GardenPlots(spacing: 8) { ForEach(0..<7, id: \.self) { _ in Color.clear.frame(width: 60, height: 20) } }
            XCTAssertEqual(GardenFitTests.fitted(stubborn, width: width).width, width, accuracy: 0.5)
            let easy = GardenPlots(spacing: 8) { ForEach(0..<7, id: \.self) { _ in Color.clear.frame(maxWidth: .infinity).frame(height: 20) } }
            XCTAssertEqual(GardenFitTests.fitted(easy, width: width).width, width, accuracy: 0.5)
        }
    }

    /// Three icons at their own size where there is room, the same icons step by step smaller in a narrower
    /// plot, and in a plot too narrow even for the smallest, how many: the marks never ask for more than the
    /// plot has, and a wider plot never shows less.
    func testTheMarksUnderAPlantFitThePlot() {
        let wide = ["outing", "play_session", "ritual"]   // the three widest icons
        var widths: [CGFloat] = []
        for plot in stride(from: 12 as CGFloat, through: 64, by: 1) {
            let size = GardenFitTests.fitted(PlotMarks(kinds: wide), width: plot)
            XCTAssertLessThanOrEqual(size.width, plot + 0.5, "plot \(plot)")
            XCTAssertGreaterThan(size.width, 0, "a day that held something always shows something")
            if let last = widths.last { XCTAssertGreaterThanOrEqual(size.width, last, "plot \(plot)") }
            widths.append(size.width)
        }
        func at(_ plot: CGFloat) -> CGFloat { widths[Int(plot) - 12] }
        XCTAssertGreaterThan(at(64), at(44), "smaller icons before a count")
        XCTAssertGreaterThan(at(44), at(37), "and smaller again")
        // The plots people have (37.6 pt on a 4.7-inch phone, 41.4 pt on a 6.3-inch one, 38.5 pt in the Mac's
        // column) still show the three icons; a count stands in only where a plot is far narrower.
        XCTAssertGreaterThan(at(37), 3 * at(12), "three icons at 37 pt")
        XCTAssertEqual(at(12), at(20), accuracy: 0.5, "just how many, in a plot this narrow")
        XCTAssertEqual(GardenFitTests.fitted(PlotMarks(kinds: []), width: 40).width, 0, accuracy: 0.5, "a quiet day has no marks")
        XCTAssertEqual(GardenFitTests.fitted(PlotMarks(kinds: ["play_session"]), width: 40).width,
                       GardenFitTests.fitted(PlotMarks(kinds: ["play_session"]), width: 64).width, accuracy: 0.5, "one icon keeps its size")
    }
}

// MARK: the pane's width is what the window gives it

/// A screen's two columns are sized from the pane's width. That width has to be the one the window offers: when
/// it was read from the screen's own size, content that could not be as narrow as its column made the screen
/// wider, which made the first column wider, which made the screen wider again (the Mac's Today, 2026-11-14).
@MainActor final class PaneWidthTests: XCTestCase {
    final class Seen { var panes: [CGFloat] = [] }

    struct Probe: View {
        @Environment(\.kaikuPaneWidth) private var pane
        let seen: Seen
        var body: some View {
            let _ = seen.panes.append(pane)
            Color.clear.frame(height: 1)
        }
    }

    private func panes(offered width: CGFloat, stubborn: CGFloat) -> [CGFloat] {
        let seen = Seen()
        let screen = KScreen("Today", maxWidth: KaikuTokens.Size.paneMax) {
            KAdaptiveColumns(minWidth: 600, leadingFraction: 0.48) {
                Color.clear.frame(height: 40)
            } trailing: {
                Color.clear.frame(width: stubborn, height: 40)   // something that cannot be narrower than this
                Probe(seen: seen)
            }
        }
        let host = NSHostingView(rootView: screen)
        host.sizingOptions = []
        let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: width, height: 600), styleMask: [.borderless], backing: .buffered, defer: true)
        window.contentView = host   // never shown: the window is not ordered in
        for _ in 0..<40 {
            host.layoutSubtreeIfNeeded()
            RunLoop.main.run(until: Date().addingTimeInterval(0.01))
        }
        window.contentView = nil
        return seen.panes
    }

    func testTheTwoColumnsAreSizedFromTheWidthTheWindowOffers() {
        // The Mac's pane at a 980 pt window, with a second column whose content needs more than its share.
        let seen = panes(offered: 752, stubborn: 500)
        XCTAssertEqual(seen.last ?? 0, 752 - 2 * KaikuPlatform.sidePadding, accuracy: 0.5, "\(seen)")
        XCTAssertLessThanOrEqual(Set(seen.map { ($0 * 2).rounded() }).count, 3, "the width is found at once, not approached: \(seen)")
    }

    func testANarrowPaneStaysOneColumn() {
        let seen = panes(offered: 492, stubborn: 500)   // the smallest Mac window
        XCTAssertEqual(seen.last ?? 0, 492 - 2 * KaikuPlatform.sidePadding, accuracy: 0.5, "\(seen)")
    }
}

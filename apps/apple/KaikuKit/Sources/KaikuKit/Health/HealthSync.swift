import Foundation
#if os(iOS) && canImport(HealthKit)
import HealthKit

/// Apple Health → one `obs.wearable_daily` per local morning (plan 05 §5). Read-only (sleep, resting HR, HRV SDNN,
/// steps, exercise minutes); asked only when the person turns on "Watch & Health"; runs on foreground and from an
/// observer query (background delivery is best effort). Never mentioned in conversation or notifications.
/// The envelope id hashes the day and summary: repeated snapshots deduplicate, late samples produce a new observation.
@MainActor
public final class HealthSync {
    public static let shared = HealthSync()
    private let store = HKHealthStore()
    private var observing = false

    static let sleep = HKCategoryType(.sleepAnalysis)
    static let steps = HKQuantityType(.stepCount)
    static let exercise = HKQuantityType(.appleExerciseTime)
    static let resting = HKQuantityType(.restingHeartRate)
    static let hrv = HKQuantityType(.heartRateVariabilitySDNN)
    static var readTypes: Set<HKObjectType> { [sleep, steps, exercise, resting, hrv] }

    public var available: Bool { HKHealthStore.isHealthDataAvailable() }

    /// Asks for read access (and write access too in debug builds, for the sample-data button).
    public func authorize() async -> Bool {
        guard available else { return false }
        #if DEBUG
        let share: Set<HKSampleType> = [Self.sleep, Self.steps, Self.resting, Self.hrv]   // exercise time is Apple-computed (read-only)
        #else
        let share: Set<HKSampleType> = []
        #endif
        do { try await store.requestAuthorization(toShare: share, read: Self.readTypes) } catch { return false }
        return true
    }

    /// Syncs today's morning summary (and yesterday's, in case the app wasn't opened then).
    public func sync(app: AppModel) async {
        guard available, app.allowed(.watch), app.pairing != nil else { return }
        if !observing { observe(app: app) }
        await HealthDelivery.sync(app: app) { [self] morning in await summary(morning: morning) }
    }

    private func observe(app: AppModel) {
        observing = true
        let q = HKObserverQuery(sampleType: Self.sleep, predicate: nil) { [weak app] _, done, _ in
            Task { @MainActor in if let app { await HealthSync.shared.sync(app: app) }; done() }
        }
        store.execute(q)
        store.enableBackgroundDelivery(for: Self.sleep, frequency: .daily) { _, _ in }
    }

    func summary(morning: Date) async -> WearableDaily? {
        let cal = Calendar.current
        var i = WearableDailyBuilder.Inputs()
        let sw = WearableDailyBuilder.sleepWindow(morning, cal)
        let sleepSamples = await samples(Self.sleep, sw)
        let asleepValues: Set<Int> = [HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue,
                                      HKCategoryValueSleepAnalysis.asleepCore.rawValue,
                                      HKCategoryValueSleepAnalysis.asleepDeep.rawValue,
                                      HKCategoryValueSleepAnalysis.asleepREM.rawValue]
        let asleep = sleepSamples.compactMap { $0 as? HKCategorySample }.filter { asleepValues.contains($0.value) }
        i.asleep = asleep.map { DateInterval(start: $0.startDate, end: $0.endDate) }
        let dw = WearableDailyBuilder.dayWindow(morning, cal)
        i.steps = await stat(Self.steps, dw, .cumulativeSum, .count())
        i.exerciseMin = await stat(Self.exercise, dw, .cumulativeSum, .minute())
        i.restingHR = await stat(Self.resting, dw, .discreteAverage, HKUnit.count().unitDivided(by: .minute()))
        i.hrvSDNN = await stat(Self.hrv, dw, .discreteAverage, .secondUnit(with: .milli))
        let all = asleep.map(\.sourceRevision)
        if all.contains(where: { ($0.productType ?? "").hasPrefix("Watch") }) { i.device = .apple_watch }
        else if i.restingHR != nil || i.hrvSDNN != nil || !asleep.isEmpty { i.device = .other_watch }
        else { i.device = .phone_only }
        return WearableDailyBuilder.build(morning: morning, i, calendar: cal)
    }

    private func samples(_ type: HKSampleType, _ w: DateInterval) async -> [HKSample] {
        await withCheckedContinuation { c in
            let p = HKQuery.predicateForSamples(withStart: w.start, end: w.end)
            let q = HKSampleQuery(sampleType: type, predicate: p, limit: HKObjectQueryNoLimit, sortDescriptors: nil) { _, s, _ in
                c.resume(returning: s ?? [])
            }
            store.execute(q)
        }
    }

    private func stat(_ type: HKQuantityType, _ w: DateInterval, _ opt: HKStatisticsOptions, _ unit: HKUnit) async -> Double? {
        await withCheckedContinuation { c in
            let p = HKQuery.predicateForSamples(withStart: w.start, end: w.end)
            let q = HKStatisticsQuery(quantityType: type, quantitySamplePredicate: p, options: opt) { _, s, _ in
                let q = opt.contains(.cumulativeSum) ? s?.sumQuantity() : s?.averageQuantity()
                c.resume(returning: q?.doubleValue(for: unit))
            }
            store.execute(q)
        }
    }

    #if DEBUG
    /// Simulator demo: writes one realistic night + yesterday's activity (debug builds only).
    public func addSampleData() async -> Bool {
        guard await authorize() else { return false }
        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        let bed = today.addingTimeInterval(-50 * 60)          // 23:10
        let wake = today.addingTimeInterval(7 * 3600 + 5 * 60) // 07:05
        let yesterday = cal.date(byAdding: .day, value: -1, to: today)!
        var objs: [HKObject] = [
            HKCategorySample(type: Self.sleep, value: HKCategoryValueSleepAnalysis.asleepCore.rawValue, start: bed, end: today.addingTimeInterval(3 * 3600)),
            HKCategorySample(type: Self.sleep, value: HKCategoryValueSleepAnalysis.asleepDeep.rawValue, start: today.addingTimeInterval(3 * 3600), end: today.addingTimeInterval(4 * 3600)),
            HKCategorySample(type: Self.sleep, value: HKCategoryValueSleepAnalysis.asleepREM.rawValue, start: today.addingTimeInterval(4 * 3600), end: wake),
        ]
        func q(_ t: HKQuantityType, _ unit: HKUnit, _ v: Double, _ s: Date, _ e: Date) -> HKQuantitySample {
            HKQuantitySample(type: t, quantity: HKQuantity(unit: unit, doubleValue: v), start: s, end: e)
        }
        objs.append(q(Self.steps, .count(), 3100, yesterday.addingTimeInterval(9 * 3600), yesterday.addingTimeInterval(12 * 3600)))
        objs.append(q(Self.steps, .count(), 3300, yesterday.addingTimeInterval(14 * 3600), yesterday.addingTimeInterval(18 * 3600)))
        objs.append(q(Self.resting, HKUnit.count().unitDivided(by: .minute()), 62, yesterday.addingTimeInterval(8 * 3600), yesterday.addingTimeInterval(8 * 3600)))
        objs.append(q(Self.hrv, .secondUnit(with: .milli), 48, yesterday.addingTimeInterval(3 * 3600), yesterday.addingTimeInterval(3 * 3600)))
        do { try await store.save(objs) } catch { kaikuLog.error("health_sample_failed"); return false }
        return true
    }
    #endif
}
#endif

/// Shared delivery orchestration so delayed Health reads can be tested without HealthKit or a physical watch.
@MainActor enum HealthDelivery {
    static func sync(app: AppModel, now: Date = Date(), calendar: Calendar = .current,
                     summary: @MainActor (Date) async -> WearableDaily?) async {
        guard app.allowed(.watch), let paired = app.pairing else { return }
        let revision = app.pairingRevision
        for back in [1, 0] {
            guard revision == app.pairingRevision, app.pairing == paired, app.allowed(.watch) else { return }
            let morning = calendar.date(byAdding: .day, value: -back, to: now)!
            let value = await summary(morning)
            guard revision == app.pairingRevision, app.pairing == paired, app.allowed(.watch) else { return }
            guard let value else { continue }
            app.healthState = .connected
            await app.emit("obs.wearable_daily", value,
                           id: WearableDailyBuilder.envelopeID(home: paired.homeID, summary: value),
                           ts: Date(), pairedTo: paired)
        }
    }
}

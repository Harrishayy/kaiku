import Foundation
#if os(iOS) && canImport(HealthKit)
import HealthKit

/// Apple Health → one `obs.wearable_daily` per local morning (plan 05 §5). Read-only: sleep with its stages and time
/// awake, resting and walking heart rate, HRV SDNN, steps, walking and running distance, exercise minutes, time in
/// daylight. Asked only when the person turns on "Watch"; runs on foreground and from an observer query (background
/// delivery is best effort). Never mentioned in conversation or notifications. Apple Health has no sleep score to
/// read (there is no HealthKit type for it), so none is sent and none is made up.
/// The envelope id hashes the day and summary: repeated snapshots deduplicate, late samples produce a new observation.
@MainActor
public final class HealthSync {
    public static let shared = HealthSync()
    private let store = HKHealthStore()
    private var observing = false
    private var asking = false

    static let sleep = HKCategoryType(.sleepAnalysis)
    static let steps = HKQuantityType(.stepCount)
    static let distance = HKQuantityType(.distanceWalkingRunning)
    static let exercise = HKQuantityType(.appleExerciseTime)
    static let daylight = HKQuantityType(.timeInDaylight)
    static let resting = HKQuantityType(.restingHeartRate)
    static let walking = HKQuantityType(.walkingHeartRateAverage)
    static let hrv = HKQuantityType(.heartRateVariabilitySDNN)
    static var readTypes: Set<HKObjectType> { [sleep, steps, distance, exercise, daylight, resting, walking, hrv] }

    /// What the app may write: nothing, except in debug builds for the sample-data button. Exercise time and the
    /// walking heart rate average are Apple's own sums: HealthKit refuses a request to write them, so the
    /// sample-data button cannot make them.
    static var shareTypes: Set<HKSampleType> {
        #if DEBUG
        return [sleep, steps, distance, daylight, resting, hrv]
        #else
        return []
        #endif
    }

    public var available: Bool { HKHealthStore.isHealthDataAvailable() }

    /// Asks for read access (and write access too in debug builds, for the sample-data button).
    public func authorize() async -> Bool {
        guard available else { return false }
        do { try await store.requestAuthorization(toShare: Self.shareTypes, read: Self.readTypes) } catch { return false }
        return true
    }

    /// iOS has not asked the person about every kind of data this build reads: never asked at all, or an update
    /// of the app reads kinds it did not read before. (iOS never tells an app what the answer to a read request
    /// was, only whether asking again would show its sheet.)
    public func shouldAsk() async -> Bool {
        guard available else { return false }
        return (try? await store.statusForAuthorizationRequest(toShare: Self.shareTypes, read: Self.readTypes)) == .shouldRequest
    }

    /// For a person whose "Watch" choice is on: when iOS has not asked about every kind of data yet, it asks now
    /// (its sheet lists only the kinds not asked about before), and the morning's summary is sent again with what
    /// was added. Called where she is looking at her own data or her choices (History, You → Sharing and
    /// permissions, the switch itself): never at launch, and never from a sync, which can run in front of a task.
    /// Returns true when iOS was asked (History then reads its numbers again).
    @discardableResult
    public func reviewAccess(app: AppModel) async -> Bool {
        #if DEBUG
        // A run that only inspects the layout never puts a system sheet up.
        if UserDefaults.standard.bool(forKey: "kaikuInspectOnly") { return false }
        #endif
        guard available, app.allowed(.watch), !asking else { return false }
        asking = true; defer { asking = false }
        guard await shouldAsk() else { return false }
        if await authorize() { await sync(app: app) } else { app.healthState = .denied }
        return true
    }

    /// Syncs today's morning summary (and yesterday's, in case the app wasn't opened then).
    public func sync(app: AppModel) async {
        guard available, app.allowed(.watch), app.pairing != nil else { return }
        if !observing { observe(app: app) }
        await HealthDelivery.sync(app: app, summary: { [self] morning in await summary(morning: morning) },
                                  simulated: { [self] morning in await holdsSampleData(morning: morning) })
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
        let night = sleepSamples.compactMap { $0 as? HKCategorySample }
        let asleep = night.filter { asleepValues.contains($0.value) }
        func spans(_ value: HKCategoryValueSleepAnalysis) -> [DateInterval] {
            night.filter { $0.value == value.rawValue }.map { DateInterval(start: $0.startDate, end: $0.endDate) }
        }
        i.asleep = asleep.map { DateInterval(start: $0.startDate, end: $0.endDate) }
        // Stages and time awake as the source wrote them ("in bed" is not read: it says nothing about sleep).
        i.deep = spans(.asleepDeep); i.rem = spans(.asleepREM); i.core = spans(.asleepCore); i.awake = spans(.awake)
        let dw = WearableDailyBuilder.dayWindow(morning, cal)
        let bpm = HKUnit.count().unitDivided(by: .minute())
        i.steps = await stat(Self.steps, dw, .cumulativeSum, .count())
        i.distanceKm = await stat(Self.distance, dw, .cumulativeSum, .meterUnit(with: .kilo))
        i.exerciseMin = await stat(Self.exercise, dw, .cumulativeSum, .minute())
        i.daylightMin = await stat(Self.daylight, dw, .cumulativeSum, .minute())
        i.restingHR = await stat(Self.resting, dw, .discreteAverage, bpm)
        i.walkingHR = await stat(Self.walking, dw, .discreteAverage, bpm)
        i.hrvSDNN = await stat(Self.hrv, dw, .discreteAverage, .secondUnit(with: .milli))
        let all = asleep.map(\.sourceRevision)
        if all.contains(where: { ($0.productType ?? "").hasPrefix("Watch") }) { i.device = .apple_watch }
        else if i.restingHR != nil || i.hrvSDNN != nil || i.walkingHR != nil || i.daylightMin != nil || !asleep.isEmpty { i.device = .other_watch }
        else { i.device = .phone_only }
        return WearableDailyBuilder.build(morning: morning, i, calendar: cal)
    }

    /// Some of what that morning's summary is made of was written by this app itself. The app writes to Apple
    /// Health in one place only, the sample-data button of debug builds, so such a summary holds stand-in numbers
    /// and goes out as simulated, never as the person's.
    func holdsSampleData(morning: Date) async -> Bool {
        let cal = Calendar.current
        let own = HKQuery.predicateForObjects(from: HKSource.default())
        let sleep = WearableDailyBuilder.sleepWindow(morning, cal), day = WearableDailyBuilder.dayWindow(morning, cal)
        for (type, window) in [(Self.sleep as HKSampleType, sleep), (Self.steps, day), (Self.distance, day), (Self.daylight, day),
                               (Self.resting, day), (Self.hrv, day)] {
            if !(await samples(type, window, also: own, limit: 1)).isEmpty { return true }
        }
        return false
    }

    private func samples(_ type: HKSampleType, _ w: DateInterval, also: NSPredicate? = nil, limit: Int = HKObjectQueryNoLimit) async -> [HKSample] {
        await withCheckedContinuation { c in
            let window = HKQuery.predicateForSamples(withStart: w.start, end: w.end)
            let p = also.map { NSCompoundPredicate(andPredicateWithSubpredicates: [window, $0]) } ?? window
            let q = HKSampleQuery(sampleType: type, predicate: p, limit: limit, sortDescriptors: nil) { _, s, _ in
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
    /// Simulator demo: writes one made-up night (stages, a short time awake) + yesterday's activity. Debug builds
    /// only. What it writes carries this app as its source, so the summary made from it goes out as simulated
    /// (`holdsSampleData`). The walking heart rate average and exercise time cannot be written (`shareTypes`).
    public func addSampleData() async -> Bool {
        guard await authorize() else { return false }
        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        let yesterday = cal.date(byAdding: .day, value: -1, to: today)!
        func at(_ hours: Double) -> Date { today.addingTimeInterval(hours * 3600) }   // hours after last midnight
        func stage(_ v: HKCategoryValueSleepAnalysis, _ from: Double, _ to: Double) -> HKCategorySample {
            HKCategorySample(type: Self.sleep, value: v.rawValue, start: at(from), end: at(to))
        }
        // 23:10 to 07:05, as a watch writes a night: one stage after another, awake for a quarter of an hour at
        // 02:40, and a few minutes awake after the last waking (which are not part of the night).
        var objs: [HKObject] = [
            stage(.asleepCore, -50.0 / 60, 2 + 40.0 / 60), stage(.awake, 2 + 40.0 / 60, 2 + 55.0 / 60),
            stage(.asleepCore, 2 + 55.0 / 60, 3), stage(.asleepDeep, 3, 4), stage(.asleepREM, 4, 5.5),
            stage(.asleepCore, 5.5, 7 + 5.0 / 60), stage(.awake, 7 + 5.0 / 60, 7 + 12.0 / 60),
        ]
        func q(_ t: HKQuantityType, _ unit: HKUnit, _ v: Double, _ s: Date, _ e: Date) -> HKQuantitySample {
            HKQuantitySample(type: t, quantity: HKQuantity(unit: unit, doubleValue: v), start: s, end: e)
        }
        objs.append(q(Self.steps, .count(), 3100, yesterday.addingTimeInterval(9 * 3600), yesterday.addingTimeInterval(12 * 3600)))
        objs.append(q(Self.steps, .count(), 3300, yesterday.addingTimeInterval(14 * 3600), yesterday.addingTimeInterval(18 * 3600)))
        objs.append(q(Self.distance, .meter(), 2250, yesterday.addingTimeInterval(9 * 3600), yesterday.addingTimeInterval(12 * 3600)))
        objs.append(q(Self.distance, .meter(), 2410, yesterday.addingTimeInterval(14 * 3600), yesterday.addingTimeInterval(18 * 3600)))
        objs.append(q(Self.daylight, .minute(), 22, yesterday.addingTimeInterval(9 * 3600), yesterday.addingTimeInterval(10 * 3600)))
        objs.append(q(Self.daylight, .minute(), 31, yesterday.addingTimeInterval(14 * 3600), yesterday.addingTimeInterval(15.5 * 3600)))
        objs.append(q(Self.resting, HKUnit.count().unitDivided(by: .minute()), 62, yesterday.addingTimeInterval(8 * 3600), yesterday.addingTimeInterval(8 * 3600)))
        objs.append(q(Self.hrv, .secondUnit(with: .milli), 48, yesterday.addingTimeInterval(3 * 3600), yesterday.addingTimeInterval(3 * 3600)))
        // Pressed twice, the sample day must not count double: what this app wrote for these hours before goes first
        // (an app can only ever delete its own samples).
        let hours = HKQuery.predicateForSamples(withStart: yesterday.addingTimeInterval(-6 * 3600), end: today.addingTimeInterval(12 * 3600))
        for type in Self.shareTypes { _ = try? await store.deleteObjects(of: type, predicate: hours) }
        do { try await store.save(objs) } catch { kaikuLog.error("health_sample_failed"); return false }
        return true
    }
    #endif
}
#endif

/// The one call the screens make about Apple Health access (the Mac has no Apple Health: nothing happens there).
@MainActor enum HealthAccess {
    /// See `HealthSync.reviewAccess`. True when iOS was asked.
    @discardableResult
    static func review(app: AppModel) async -> Bool {
        #if os(iOS) && canImport(HealthKit)
        return await HealthSync.shared.reviewAccess(app: app)
        #else
        return false
        #endif
    }
}

/// Shared delivery orchestration so delayed Health reads can be tested without HealthKit or a physical watch.
@MainActor enum HealthDelivery {
    /// `simulated`: that morning's summary is made of stand-in numbers (sample data): it then goes out as simulated.
    static func sync(app: AppModel, now: Date = Date(), calendar: Calendar = .current,
                     summary: @MainActor (Date) async -> WearableDaily?,
                     simulated: @MainActor (Date) async -> Bool = { _ in false }) async {
        guard app.allowed(.watch), let paired = app.pairing else { return }
        let revision = app.pairingRevision
        for back in [1, 0] {
            guard revision == app.pairingRevision, app.pairing == paired, app.allowed(.watch) else { return }
            let morning = calendar.date(byAdding: .day, value: -back, to: now)!
            let value = await summary(morning)
            guard revision == app.pairingRevision, app.pairing == paired, app.allowed(.watch) else { return }
            guard let value else { continue }
            let sim = await simulated(morning)
            guard revision == app.pairingRevision, app.pairing == paired, app.allowed(.watch) else { return }
            app.healthState = .connected
            await app.emit("obs.wearable_daily", value,
                           id: WearableDailyBuilder.envelopeID(home: paired.homeID, summary: value),
                           ts: Date(), sim: sim, pairedTo: paired)
        }
    }
}

import CryptoKit
import Foundation

// Swift mirrors of the obs the iPhone extras send (plan 05). Ground truth: contracts/schemas/obs/*.schema.json;
// ContractTests checks every payload here against its schema, like Contracts.swift.

public enum OutingMethod: String, Codable, Sendable { case location, steps, dat_camera, dat_imu }

/// obs.outing — one walk. Computed on the phone (+ glasses IMU via the DAT SDK); only these numbers leave it.
public struct Outing: Codable, Sendable, Equatable {
    public var minutes: Double
    public var method: OutingMethod
    public var steps: Int?
    public var daylight_min: Double?
    public var cadence_spm: Double?
    public var gait_regularity: Double?
    public var head_up_ratio: Double?

    public init(minutes: Double, method: OutingMethod) {
        self.minutes = max(0, minutes)
        self.method = method
    }
}

public enum WearableDevice: String, Codable, Sendable { case apple_watch, other_watch, phone_only }

/// obs.wearable_daily — one Apple Health summary per local morning (aggregates only, never raw samples).
public struct WearableDaily: Codable, Sendable, Equatable {
    public var date: String
    public var device: WearableDevice
    public var sleep_min: Double?
    public var sleep_midpoint_min: Double?
    public var sleep_regularity: Double?
    public var resting_hr_bpm: Double?
    public var hrv_sdnn_ms: Double?
    public var steps: Int?
    public var exercise_min: Double?

    public init(date: String, device: WearableDevice) { self.date = date; self.device = device }
}

/// obs.nudge_outcome — what the person did with an invitation (the bandit learns from it).
public struct NudgeOutcome: Codable, Sendable, Equatable {
    public var arm: NudgeArm
    public var accepted: Bool
    public init(arm: NudgeArm, accepted: Bool) { self.arm = arm; self.accepted = accepted }
}

/// GET /v1/voice?lang= — every keyed line as text (captions, notification titles, offline speech).
public struct VoiceLinesResponse: Codable, Sendable, Equatable {
    public var lang: String
    public var voice: String
    public var model: String
    public var lines: [String: String]
}

/// Deterministic envelope ids for obs that must exist once per thing (one wearable_daily per date): a UUID
/// (version 8, RFC 9562) from SHA-256 of a name, so a resend or a second sync is a duplicate the cloud ignores.
public enum StableID {
    public static func make(_ name: String) -> String {
        var b = Array(SHA256.hash(data: Data(name.utf8))).prefix(16).map { $0 }
        b[6] = (b[6] & 0x0F) | 0x80
        b[8] = (b[8] & 0x3F) | 0x80
        let u = UUID(uuid: (b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]))
        return u.uuidString.lowercased()
    }
}

extension APIClient {
    public func voiceLines(lang: String) async throws -> VoiceLinesResponse {
        let req = try request("GET", "/v1/voice", query: ["lang": lang])
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw APIError.http((resp as? HTTPURLResponse)?.statusCode ?? 0) }
        return try JSONDecoder().decode(VoiceLinesResponse.self, from: data)
    }
}

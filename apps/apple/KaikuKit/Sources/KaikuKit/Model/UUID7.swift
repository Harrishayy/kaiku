import Foundation
import Security

/// UUIDv7 (RFC 9562): 48-bit Unix ms timestamp, version 7, variant 10, the rest random. Envelope ids are made once,
/// when the event happens, and kept through the offline queue, so a retry is a duplicate the cloud ignores.
public enum UUID7 {
    public static func make(_ date: Date = Date()) -> String {
        var b = [UInt8](repeating: 0, count: 16)
        _ = SecRandomCopyBytes(kSecRandomDefault, 16, &b)
        let ms = UInt64(max(0, date.timeIntervalSince1970 * 1000))
        for i in 0..<6 { b[i] = UInt8((ms >> (8 * (5 - UInt64(i)))) & 0xFF) }
        b[6] = (b[6] & 0x0F) | 0x70
        b[8] = (b[8] & 0x3F) | 0x80
        let u = UUID(uuid: (b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]))
        return u.uuidString.lowercased()
    }

    /// The timestamp encoded in a v7 id (tests + ordering).
    public static func date(of id: String) -> Date? {
        let hex = id.replacingOccurrences(of: "-", with: "")
        guard hex.count == 32, let ms = UInt64(hex.prefix(12), radix: 16) else { return nil }
        return Date(timeIntervalSince1970: Double(ms) / 1000)
    }
}

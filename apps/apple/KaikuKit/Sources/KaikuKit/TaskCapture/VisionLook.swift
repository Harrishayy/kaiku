@preconcurrency import CoreImage
import CoreVideo
import Foundation
import ImageIO

// Kaiku's own model looks at a few pictures of the camera during a check-in (D65).
//
// Only with her separate choice "Let Kaiku's model look" (`Signal.look`, off by default) AND "Camera during
// activities". The camera that is already open for the check-in hands over at most `VisionLookRules.frames` small
// pictures (downscaled JPEGs, made in memory). They are sent ONCE to the Kaiku service (`POST /v1/vision/look`),
// which shows them to Gemma and keeps only what it noted. Here:
// - a picture exists only in `VisionLookBatch` (memory) between the camera and the one request;
// - it is never written to a file, never put in `OfflineQueue`, never logged;
// - the request is made once, without retry; whatever the answer, the pictures are gone (`take()` empties the
//   batch before the request starts, and nothing else holds them);
// - a check-in she only opened and left, a withdrawn choice, "pause everything", leaving the screen: the batch is
//   dropped unsent (`drop()`).

/// How the device picks the pictures (the service's `[vision_look]`, sent with the session).
public struct VisionLookRules: Codable, Sendable, Equatable {
    /// Pictures per check-in, at most.
    public var frames = 3
    /// Camera time before the first one.
    public var settle_s = 6.0
    /// At least this long between two.
    public var min_interval_s = 12.0
    /// The longer side after downscaling.
    public var max_edge_px = 256
    public var jpeg_quality = 0.6

    public static let standard = VisionLookRules()
    public init() {}

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let d = VisionLookRules()
        frames = min(8, max(1, try c.decodeIfPresent(Int.self, forKey: .frames) ?? d.frames))
        settle_s = max(0, try c.decodeIfPresent(Double.self, forKey: .settle_s) ?? d.settle_s)
        min_interval_s = max(1, try c.decodeIfPresent(Double.self, forKey: .min_interval_s) ?? d.min_interval_s)
        max_edge_px = min(768, max(64, try c.decodeIfPresent(Int.self, forKey: .max_edge_px) ?? d.max_edge_px))
        jpeg_quality = min(0.9, max(0.2, try c.decodeIfPresent(Double.self, forKey: .jpeg_quality) ?? d.jpeg_quality))
    }
}

/// Which of the camera's frames become a picture. Pure: time and whether one usable face is in the frame.
struct VisionLookSampler: Sendable {
    let rules: VisionLookRules
    private(set) var taken = 0
    private var first: Double?
    private var last: Double?

    init(rules: VisionLookRules) { self.rules = rules }

    /// True = make a picture of this frame. Never without a face in it, never before the camera has settled, never
    /// closer together than the rule, never more than the rule's count.
    mutating func take(at t: Double, face: Bool) -> Bool {
        if first == nil { first = t }
        guard face, taken < rules.frames, let first, t - first >= rules.settle_s else { return false }
        if let last, t - last < rules.min_interval_s { return false }
        last = t
        taken += 1
        return true
    }
}

/// One frame as a small JPEG, in memory. No file, no cache.
enum VisionPicture {
    private static let context = CIContext(options: [.cacheIntermediates: false])

    static func jpeg(_ pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation, rules: VisionLookRules) -> Data? {
        var image = CIImage(cvPixelBuffer: pixels).oriented(orientation)
        let longer = max(image.extent.width, image.extent.height)
        guard longer > 0 else { return nil }
        let scale = min(1, CGFloat(rules.max_edge_px) / longer)
        if scale < 1 { image = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale)) }
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        let key = CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String)
        return context.jpegRepresentation(of: image, colorSpace: space, options: [key: rules.jpeg_quality])
    }
}

/// The pictures of one check-in, between the camera and the one request. Memory only.
@MainActor final class VisionLookBatch {
    private(set) var pictures: [Data] = []
    private let limit: Int
    init(limit: Int) { self.limit = max(1, limit) }

    var isFull: Bool { pictures.count >= limit }
    func add(_ picture: Data) { if !isFull { pictures.append(picture) } }
    /// Hands the pictures to the one request and forgets them here.
    func take() -> [Data] { defer { pictures = [] }; return pictures }
    func drop() { pictures = [] }
}

/// POST /v1/vision/look. Never queued, never retried.
struct VisionLookRequest: Encodable, Sendable {
    var task: String
    var device: String
    var frames: [String]
    var ref: String?

    init(task: String, device: String, pictures: [Data], ref: String? = nil) {
        self.task = task; self.device = device; self.ref = ref
        frames = pictures.map { $0.base64EncodedString() }
    }
}

public struct VisionLookResult: Decodable, Sendable {
    public var ok: Bool
    public var stored: Bool?
    public var reason: String?
}

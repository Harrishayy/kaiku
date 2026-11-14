#if os(iOS)
@preconcurrency import AVFoundation
import SwiftUI
import UIKit

/// Camera QR scanner for pairing (processed in memory; frames are never stored). `available == false` on devices
/// without a camera (the simulator) — the pair screen then leads with "paste a link".
struct QRScannerView: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    static var available: Bool { AVCaptureDevice.default(for: .video) != nil }

    func makeUIViewController(context: Context) -> ScannerController {
        let c = ScannerController()
        c.onCode = onCode
        return c
    }

    func updateUIViewController(_ vc: ScannerController, context: Context) {}

    final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
        var onCode: ((String) -> Void)?
        private let session = AVCaptureSession()
        private var preview: AVCaptureVideoPreviewLayer?
        private var last: String?

        override func viewDidLoad() {
            super.viewDidLoad()
            view.backgroundColor = .black
            AVCaptureDevice.requestAccess(for: .video) { [weak self] ok in
                guard ok else { return }
                DispatchQueue.main.async { self?.configure() }
            }
        }

        private func configure() {
            guard let device = AVCaptureDevice.default(for: .video), let input = try? AVCaptureDeviceInput(device: device),
                  session.canAddInput(input) else { return }
            session.addInput(input)
            let out = AVCaptureMetadataOutput()
            guard session.canAddOutput(out) else { return }
            session.addOutput(out)
            out.setMetadataObjectsDelegate(self, queue: .main)
            out.metadataObjectTypes = [.qr]
            let layer = AVCaptureVideoPreviewLayer(session: session)
            layer.videoGravity = .resizeAspectFill
            layer.frame = view.bounds
            view.layer.addSublayer(layer)
            preview = layer
            let s = session
            DispatchQueue.global(qos: .userInitiated).async { s.startRunning() }
        }

        override func viewDidLayoutSubviews() {
            super.viewDidLayoutSubviews()
            preview?.frame = view.bounds
        }

        override func viewWillDisappear(_ animated: Bool) {
            super.viewWillDisappear(animated)
            let s = session
            DispatchQueue.global(qos: .userInitiated).async { s.stopRunning() }
        }

        func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
            guard let code = (objects.first as? AVMetadataMachineReadableCodeObject)?.stringValue, code != last else { return }
            last = code
            onCode?(code)
        }
    }
}
#endif

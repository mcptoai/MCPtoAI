import AVFoundation
import Foundation

func mediaType(_ name: String) -> AVMediaType? {
    switch name { case "microphone": return .audio; case "camera": return .video; default: return nil }
}
func text(_ status: AVAuthorizationStatus) -> String {
    switch status { case .authorized: return "granted"; case .denied: return "denied"; case .restricted: return "restricted"; case .notDetermined: return "not-determined"; @unknown default: return "unknown" }
}
let args = CommandLine.arguments
if args.count != 3 || !["status", "request"].contains(args[1]) || mediaType(args[2]) == nil { fputs("usage: permission-helper status|request microphone|camera\n", stderr); exit(2) }
let type = mediaType(args[2])!
if args[1] == "status" { print(text(AVCaptureDevice.authorizationStatus(for: type))); exit(0) }
if AVCaptureDevice.authorizationStatus(for: type) != .notDetermined { print(text(AVCaptureDevice.authorizationStatus(for: type))); exit(0) }
let sem = DispatchSemaphore(value: 0); var granted = false
AVCaptureDevice.requestAccess(for: type) { ok in granted = ok; sem.signal() }
_ = sem.wait(timeout: .now() + 60)
print(granted ? "granted" : text(AVCaptureDevice.authorizationStatus(for: type)))

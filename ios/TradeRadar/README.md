# Trade Radar iOS

This is a native iOS wrapper for the local Trade Radar backend. It loads the backend in a `WKWebView` so it can be archived and uploaded to TestFlight from Xcode.

## Before Uploading

1. Put the backend somewhere the iPhone can reach it.
   - Same Wi-Fi testing: `http://192.168.86.248:8000`
   - External TestFlight testers: use a hosted HTTPS backend.
2. Open `TradeRadar.xcodeproj` on a Mac with Xcode.
3. Select the `TradeRadar` target.
4. Set your Apple Developer Team.
5. Change the bundle identifier if needed.
6. If your backend URL changed, edit `BackendURL` in `TradeRadar/Info.plist`.
7. Product > Archive.
8. Distribute App > App Store Connect > Upload.
9. In App Store Connect, add the uploaded build to TestFlight.

Apple's TestFlight docs: https://developer.apple.com/testflight/

## Bitrise

The root `bitrise.yml` has two workflows:

- `build`: archives the app and stores artifacts in Bitrise.
- `testflight`: signs, archives, and uploads to App Store Connect/TestFlight.

Set these in Bitrise before running `testflight`:

- `BACKEND_URL`: your hosted HTTPS backend URL. Local Wi-Fi URLs are fine only for private device testing.
- Apple Developer signing credentials through Bitrise's iOS code signing setup.
- App Store Connect API key credentials for upload.
- Bundle ID in Apple Developer/App Store Connect matching `com.caleb.traderadar`, or change the Xcode project and `bitrise.yml` to your own bundle ID.

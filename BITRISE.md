# Bitrise Setup

This repo includes `bitrise.yml` for building the iOS wrapper in `ios/TradeRadar`.

## What Bitrise Builds

- Project: `ios/TradeRadar/TradeRadar.xcodeproj`
- Scheme: `TradeRadar`
- Bundle ID: `com.caleb.traderadar`
- Default workflow: `build`
- TestFlight workflow: `testflight`

## Required Bitrise Settings

Set these before running `testflight`:

- `BACKEND_URL`: public HTTPS URL for the hosted trading backend.
- Apple Developer account connection.
- App Store Connect API key for upload.
- iOS signing assets or automatic signing through Bitrise.

The default `BackendURL` in `Info.plist` points to your local Wi-Fi backend:

```text
http://192.168.86.248:8000
```

That only works while the iPhone is on the same network as your computer. For TestFlight testers outside your Wi-Fi, deploy the Python backend somewhere reachable over HTTPS and set `BACKEND_URL` in Bitrise.

## Workflows

`build`

Archives the app and uploads artifacts to Bitrise. Use this first to verify the Xcode project.

`testflight`

Runs signing, archives the app, uploads the IPA to App Store Connect, and leaves the build ready to add to TestFlight.

## First Run

1. Push this repo to GitHub, GitLab, or Bitbucket.
2. Add the repo in Bitrise.
3. Let Bitrise detect the config from `bitrise.yml`.
4. Add `BACKEND_URL`.
5. Configure Apple signing and App Store Connect API credentials.
6. Run `build`.
7. Run `testflight`.

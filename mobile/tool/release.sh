#!/usr/bin/env bash
# Release builds for the stores.
#   tool/release.sh android   -> build/app/outputs/bundle/release/app-release.aab (upload in Play Console)
#   tool/release.sh ios       -> builds the .ipa and uploads it to App Store Connect / TestFlight
#   tool/release.sh key-cert  -> exports android/upload_certificate.pem and prints the upload key's SHA1
#                                (Play Console > App integrity shows the SHA1 it expects; they must match,
#                                 and the .pem is what Google asks for if the upload key ever has to be reset)
# Bump `version:` in pubspec.yaml first (the +N build number must go up every upload).
# iOS upload needs the App Store Connect API key (the same team key SchoolHub uses):
#   AuthKey_W5MH8FB2TN.p8 (the team key SchoolHub and Bettle use) in ~/.appstoreconnect/private_keys/, and
#   export ASC_KEY_ID=W5MH8FB2TN ASC_ISSUER_ID=<issuer id from App Store Connect > Users and Access > Integrations>
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  android)
    [ -f android/key.properties ] || { echo "android/key.properties is missing (see key.properties.example)"; exit 1; }
    flutter build appbundle --release
    echo "Upload: build/app/outputs/bundle/release/app-release.aab"
    ;;
  ios)
    : "${ASC_KEY_ID:?set ASC_KEY_ID}" "${ASC_ISSUER_ID:?set ASC_ISSUER_ID}"
    flutter build ipa --release --export-options-plist=ios/ExportOptions.plist
    xcrun altool --upload-app -t ios -f build/ios/ipa/*.ipa --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"
    ;;
  key-cert)
    ks=$(sed -n 's/^storeFile=//p' android/key.properties); alias=$(sed -n 's/^keyAlias=//p' android/key.properties)
    case "$ks" in /*) ;; *) ks="android/app/$ks" ;; esac
    keytool -export -rfc -keystore "$ks" -alias "$alias" -file android/upload_certificate.pem
    keytool -printcert -file android/upload_certificate.pem | grep -E 'SHA1|SHA256'
    ;;
  *) echo "usage: tool/release.sh android|ios|key-cert"; exit 1 ;;
esac

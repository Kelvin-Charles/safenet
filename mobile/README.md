# SafeNet mobile app (Flutter)

One app for two kinds of people:

- **Businesses** (owner, admin, staff, partners) sign in with their SafeNet dashboard username and password.
  Native screens: Home (today, month, balance, 7-day chart, recent sales), Live (who is online, disconnect),
  Vouchers (search, filter, make, share, disable, delete), Customers (search, tags, notes, codes), Payments,
  Earnings, Packages. Every other dashboard page (sites, devices, login page design, offers, SMS, outage make-up,
  team, settings, plan) opens inside the app, already signed in.
- **Wi-Fi customers** sign in with their phone number and a code they bought with it, and see their codes
  (time and data left), the businesses and sites they use, what they spent, and their purchase history.

The app talks to the server's `/api/m/...` API (`mobile_api.py`, tests in `tests/test_mobile_api.py`).

## Run

    cd mobile
    flutter pub get
    flutter run                                              # against https://radius.safezonetz.com
    flutter run --dart-define=SAFENET_URL=http://10.0.2.2:5000   # against a local server (Android emulator)

## Build

    flutter build apk --release        # Android (sign it with your keystore first, see android/app/build.gradle.kts)
    flutter build ipa                  # iOS (needs a Mac with Xcode and an Apple developer account)

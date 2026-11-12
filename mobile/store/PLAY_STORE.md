# SafeNet on Google Play

Everything needed to publish the SafeNet app (package `com.safezonetz.safenet_app`) on Google Play, in the order Play Console asks for it.

## 1. Files to upload

| What | File |
|---|---|
| App bundle (version 1.0.2, build 3) | `mobile/build/app/outputs/bundle/release/app-release.aab` (rebuild with `tool/release.sh android`) |
| App icon, 512 × 512 | `store/icon-512.png` |
| Feature graphic, 1024 × 500 | `store/feature-graphic.png` |
| Phone screenshots (6) | `store/screenshots/*.png` |

**Upload key** (Play Console → Test and release → App integrity shows the one it expects):

- SHA-1 `2A:C1:A8:07:AE:8C:19:D0:58:A3:FF:37:53:B4:38:5A:8A:00:5F:E3`
- SHA-256 `4C:CD:2C:27:55:75:EF:2A:82:7F:3E:58:A1:B5:86:45:27:E6:47:8E:B2:28:39:00:5A:E3:B0:67:E3:2D:81:03`
- Public certificate: `android/upload_certificate.pem`

> **Back up `android/upload-keystore.jks` and `android/key.properties` now** (password manager or an encrypted drive, not Git).
> Every future update must be signed with this key. If it is lost, Google can reset it, but that takes days and needs the .pem above.

## 2. Create the app

Play Console → **Create app**

- App name: **SafeNet: Wi-Fi Business** (at most 30 characters)
- Default language: **English (United Kingdom) – en-GB**, or English (United States)
- App or game: **App** · Free or paid: **Free**
- Accept the declarations.

## 3. Store listing

**Short description** (at most 80 characters)

- EN: `Sell Wi-Fi with vouchers and mobile money. Track sales, guests and profit.`
- SW (add the translation under *Kiswahili – sw*): `Uza Wi-Fi kwa vocha na pesa za simu. Fuatilia mauzo, wateja na faida.`

**Full description, English**

```
SafeNet runs your Wi-Fi business from your phone. Hotels, hostels, shops, cafés and campuses use it to sell internet with vouchers and mobile money, and to see every sale and every guest online.

FOR WI-FI BUSINESSES
• Today's sales, this month and your SafeNet Pay balance at a glance
• Who is online now, how much data they use, and disconnect anyone
• Make and print vouchers, see which are unused, in use or expired
• Customers: who bought, how often and when, with tags and notes
• Packages, offers and speed plans, and SMS to your customers
• Several sites (branches) in one account, each with its own numbers
• Expenses and profit: record what each site cost (equipment, installation, posters, internet, rent) and see when it has paid back
• Financial reports for any period, shared as a professional PDF
• Team accounts for staff, admins and partners who can only view
• Works with TP-Link Omada, Reyee / Ruijie, MikroTik and the SafeNet gateway

FOR WI-FI CUSTOMERS
• Buy Wi-Fi with M-Pesa, Airtel Money, Mixx by Yas and HaloPesa
• See your codes, time and data left, and where you connect
• Your purchase history across every SafeNet Wi-Fi

In English and Kiswahili, with light and dark themes.

SafeNet is made in Tanzania by Safezone Tech.
```

**Full description, Kiswahili**

```
SafeNet inakuwezesha kuendesha biashara yako ya Wi-Fi kwa simu. Hoteli, hosteli, maduka, migahawa na vyuo huitumia kuuza intaneti kwa vocha na pesa za simu, na kuona kila mauzo na kila mteja aliye mtandaoni.

KWA BIASHARA ZA WI-FI
• Mauzo ya leo, mwezi huu na salio lako la SafeNet Pay kwa haraka
• Walio mtandaoni sasa, data wanayotumia, na kumtoa yeyote
• Tengeneza na chapisha vocha, ona zisizotumika, zinazotumika na zilizoisha
• Wateja: nani alinunua, mara ngapi na lini, pamoja na lebo na maelezo
• Vifurushi, ofa na kasi, na SMS kwa wateja wako
• Maeneo (matawi) kadhaa kwenye akaunti moja, kila moja na takwimu zake
• Matumizi na faida: rekodi gharama za kila eneo (vifaa, ufungaji, mabango, intaneti, kodi) na uone lini zimerudi
• Taarifa za fedha kwa kipindi chochote, kama PDF safi ya kutuma
• Akaunti za timu kwa wafanyakazi, wasimamizi na wabia wanaoona tu
• Inafanya kazi na TP-Link Omada, Reyee / Ruijie, MikroTik na SafeNet gateway

KWA WATEJA WA WI-FI
• Nunua Wi-Fi kwa M-Pesa, Airtel Money, Mixx by Yas na HaloPesa
• Ona vocha zako, muda na data iliyobaki, na unapounganishwa
• Historia ya manunuzi yako kwenye kila Wi-Fi ya SafeNet

Kwa Kiingereza na Kiswahili, na mwonekano mweupe au mweusi.

SafeNet imetengenezwa Tanzania na Safezone Tech.
```

**Category:** Business · **Tags:** Business, Productivity
**Contact details:** email (the support address you want public), phone (optional), website `https://radius.safezonetz.com`

## 4. App content (Policy → App content)

| Section | Answer |
|---|---|
| Privacy policy | `https://radius.safezonetz.com/privacy` |
| Ads | **No**, the app has no ads |
| App access | **Some parts are restricted**: give a demo business login (username and password) and, for the customer side, a voucher code. Create a demo business for Google's reviewers; never give a real tenant's login. |
| Content rating | Questionnaire, category **Utility, productivity, communication or other**: no violence, sexuality, language, drugs or gambling. Users can interact or exchange information: **No** (no chat between users). Shares location: **No**. Digital purchases: **No** (Wi-Fi time is a real-world service paid by mobile money, not Google Play Billing). Expected result: Everyone / PEGI 3. |
| Target audience | **18 and over** (businesses and adults buying Wi-Fi). Not for children. |
| News app | No |
| COVID-19 app | No |
| Data safety | See below |
| Government app | No |
| Financial features | It **does** show earnings and lets owners withdraw their balance to mobile money (through SafeNet's payment providers). If asked, pick *"Other"* and describe it as: "Business owners see sales collected for them and request payouts to their own mobile-money or bank account; payments are processed by licensed providers ClickPesa and Snippe." |
| Health apps | No |

### Data safety answers

- Does the app collect or share user data? **Yes, it collects.** Shared with third parties: **No** (payment and SMS providers work on SafeNet's behalf, which Play counts as service providers, not sharing).
- Is all data encrypted in transit? **Yes** (HTTPS).
- Can users ask for data to be deleted? **Yes**: in the app (More → Delete my account; Wi-Fi customers: ⋮ menu) and at `https://radius.safezonetz.com/delete-account`.

| Data type | Collected | Required? | Purpose |
|---|---|---|---|
| Personal info → Name | Yes (business owner and team names; payer name from mobile money) | Required for businesses | App functionality, Account management |
| Personal info → Email address | Yes (business accounts) | Required for businesses | Account management, Developer communications |
| Personal info → Phone number | Yes | Required | App functionality, Account management |
| Financial info → Purchase history | Yes (Wi-Fi packages bought) | Required | App functionality |
| Financial info → Other financial info | Yes (businesses' payout accounts and expenses they record) | Optional | App functionality |
| App activity → Other actions | Yes (vouchers made, settings changed) | Required | App functionality |
| Device or other IDs | **No** (the app doesn't read device IDs; the Wi-Fi network, not the app, sees the device's address) | | |
| Location, contacts, photos, files, messages, health, web history | **No** | | |

Not processed ephemerally; not used for ads, marketing or analytics.

## 5. Release

1. **Test and release → Setup → App signing**: keep **Play App Signing** (Google holds the app signing key, and you keep the upload key above).
2. **New personal developer account?** Accounts opened after 13 November 2023 must run a **closed test with at least 12 testers for 14 days** before production. Add their Gmail addresses to a closed testing track and upload the same .aab there. (SchoolHub's and Bettle's account may already be past this. Organisation accounts are exempt.)
3. **Production → Create new release** → upload `app-release.aab` → release name `1.0.2 (3)`.
   - Release notes EN: `Expenses and profit for each site, financial reports as PDF, delete your account from the app, and fixes.`
   - Release notes SW: `Matumizi na faida kwa kila eneo, taarifa za fedha kama PDF, kufuta akaunti kwenye programu, na marekebisho.`
4. **Countries:** Tanzania (add Kenya, Uganda and others later if you sell there).
5. Send for review. A first review usually takes a few days.

## 6. After it is live

- Each update: bump `version:` in `pubspec.yaml` (the `+N` build number must go up), run `tool/release.sh android`, and upload the new .aab.
- The Wi-Fi login pages' "Get the app" button still downloads the APK from SafeNet's server. Once the app is on Play, point it at the Play Store link instead, so people get updates. A phone that installed the old test-key APK has to uninstall it once before installing from Play, because the signatures differ.
- Handle deletion requests within 30 days in **Platform: Deletions** on the dashboard.

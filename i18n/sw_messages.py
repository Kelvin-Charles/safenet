"""Kiswahili: messages from app.py and tenancy.py (flash messages, dashboard alerts, test results)."""
SW = {
    # sign in, account state
    'Please log in to access this page.': 'Tafadhali ingia ili kufungua ukurasa huu.',
    'This account is suspended. Please contact support.': 'Akaunti hii imesimamishwa. Tafadhali wasiliana na msaada.',
    'Your SafeNet subscription has expired and your Wi-Fi is paused. Renew to continue.':
        'Usajili wako wa SafeNet umeisha na Wi-Fi yako imesimamishwa. Lipia ili kuendelea.',
    'Your account can view only.': 'Akaunti yako inaweza kuangalia tu.',
    'Your account can view but not change anything.': 'Akaunti yako inaweza kuangalia tu, haiwezi kubadilisha chochote.',
    'Too many failed attempts. Please wait 15 minutes, or reset your password.':
        'Majaribio mengi yameshindwa. Tafadhali subiri dakika 15, au badilisha nenosiri lako.',
    'Your account has been disabled.': 'Akaunti yako imezimwa.',
    'Invalid username or password.': 'Jina la mtumiaji au nenosiri si sahihi.',
    'You have been logged out.': 'Umetoka.',
    "You don't have permission to open that page.": 'Huna ruhusa ya kufungua ukurasa huo.',

    # dashboard
    'Gateway': 'Gateway',
    'Router': 'Ruta',
    '{site} access points': 'Vifaa vya Wi-Fi vya {site}',
    'Voucher': 'Vocha',
    'Account': 'Akaunti',
    '{kind} {name} is offline (last seen {when})': '{kind} {name} haipo hewani (ilionekana mwisho {when})',
    '{kind} {name} is offline (never connected)': '{kind} {name} haipo hewani (haijawahi kuunganishwa)',
    '{kind} {name} has not reported for a few minutes': '{kind} {name} haijatuma taarifa kwa dakika kadhaa',
    '{n} mobile-money payments still pending after 10 minutes': 'Malipo {n} ya pesa kwa simu bado yanasubiri baada ya dakika 10',
    '{n} mobile-money payment still pending after 10 minutes': 'Malipo {n} ya pesa kwa simu bado yanasubiri baada ya dakika 10',
    '{n} payments failed today': 'Malipo {n} yameshindwa leo',
    '{n} payment failed today': 'Malipo {n} yameshindwa leo',
    '{n} customer accounts expire within 3 days': 'Akaunti {n} za wateja zinaisha ndani ya siku 3',
    '{n} customer account expire within 3 days': 'Akaunti {n} ya mteja inaisha ndani ya siku 3',
    'Good morning': 'Habari za asubuhi',
    'Good afternoon': 'Habari za mchana',
    'Good evening': 'Habari za jioni',

    # customer accounts (users)
    '-- No Plan --': '-- Hakuna mpango --',
    'Your plan does not allow more customers. Upgrade on the Billing page.':
        'Mpango wako hauruhusu wateja zaidi. Panda daraja kwenye ukurasa wa Ada ya SafeNet.',
    'That username is already taken. Choose another.': 'Jina hilo la mtumiaji limeshachukuliwa. Chagua jingine.',
    'Add User': 'Ongeza mtumiaji',
    'Edit User': 'Hariri mtumiaji',
    'User {name} created successfully.': 'Mtumiaji {name} ameongezwa.',
    'User {name} updated successfully.': 'Mtumiaji {name} amesasishwa.',
    'User {name} deleted successfully.': 'Mtumiaji {name} amefutwa.',
    'Please select a NAS device to test against': 'Tafadhali chagua kifaa cha NAS cha kujaribu nacho',
    'Please select a NAS device to test against.': 'Tafadhali chagua kifaa cha NAS cha kujaribu nacho.',
    'User {name} does not have a password set': 'Mtumiaji {name} hana nenosiri',
    'User {name} does not have a password set.': 'Mtumiaji {name} hana nenosiri.',
    'Authentication successful! User {name} can connect to {nas} ({ip}). User has been activated.':
        'Imefaulu! Mtumiaji {name} anaweza kuunganishwa kupitia {nas} ({ip}). Mtumiaji amewashwa.',
    'Authentication successful! User {name} can connect to {nas} ({ip})':
        'Imefaulu! Mtumiaji {name} anaweza kuunganishwa kupitia {nas} ({ip})',
    'Authentication failed': 'Kuingia kumeshindwa',
    'Authentication failed: Invalid credentials or user not found':
        'Kuingia kumeshindwa: taarifa si sahihi au mtumiaji hayupo',
    'Authentication failed: {error}': 'Kuingia kumeshindwa: {error}',
    'Connection test timed out. NAS {nas} may be unreachable.': 'Jaribio limechukua muda mrefu. Huenda NAS {nas} haifikiki.',
    'RADIUS test tool not available. Please test manually.': 'Kifaa cha kujaribu RADIUS hakipo. Tafadhali jaribu mwenyewe.',
    'Test failed: {error}': 'Jaribio limeshindwa: {error}',

    # speed plans
    'Plan name already exists.': 'Jina la mpango tayari lipo.',
    'Add Plan': 'Ongeza mpango wa kasi',
    'Edit Plan': 'Hariri mpango wa kasi',
    'Plan {name} created successfully.': 'Mpango {name} umeongezwa.',
    'Plan {name} updated successfully.': 'Mpango {name} umesasishwa.',
    'Plan {name} deleted successfully.': 'Mpango {name} umefutwa.',
    '-- Standard --': '-- Kawaida --',
    'Attribute added successfully.': 'Sifa imeongezwa.',
    'Attribute deleted successfully.': 'Sifa imefutwa.',
    'Add Attribute': 'Ongeza sifa',
    'Data cap reset for plan {name} and all users in this plan. Counter will reset based on {period} period.':
        'Kikomo cha data kimeanzishwa upya kwa mpango {name} na watumiaji wake wote. Hesabu itaanza upya kila kipindi cha {period}.',
    'daily': 'siku',
    'weekly': 'wiki',
    'monthly': 'mwezi',

    # RADIUS clients (NAS)
    'A router with this IP address is already registered.': 'Ruta yenye anwani hii ya IP tayari imesajiliwa.',
    'Add NAS': 'Ongeza NAS',
    'Edit NAS': 'Hariri NAS',
    'NAS {name} added successfully.': 'NAS {name} imeongezwa.',
    'NAS {name} updated successfully.': 'NAS {name} imesasishwa.',
    'NAS {name} deleted successfully.': 'NAS {name} imefutwa.',
    'NAS {name} ({ip}) is reachable on port 1812': 'NAS {name} ({ip}) inafikika kwenye port 1812',
    'Cannot reach NAS {name} ({ip}) on port 1812. Check network connectivity.':
        'Imeshindwa kufikia NAS {name} ({ip}) kwenye port 1812. Kagua mtandao.',
    'Invalid IP address: {ip}': 'Anwani ya IP si sahihi: {ip}',
    'Connection test failed: {error}': 'Jaribio la muunganisho limeshindwa: {error}',

    # vouchers
    '{n} vouchers created in batch "{batch}".': 'Vocha {n} zimetengenezwa kwenye kundi "{batch}".',
    'Choose a batch to print.': 'Chagua kundi la kuchapisha.',
    'Voucher {code} enabled.': 'Vocha {code} imewashwa.',
    'Voucher {code} disabled and its devices disconnected.': 'Vocha {code} imezimwa na vifaa vyake vimekatwa.',
    'Voucher {code} deleted.': 'Vocha {code} imefutwa.',
    'Deleted {n} unused vouchers from batch "{batch}".': 'Vocha {n} ambazo hazijatumika zimefutwa kwenye kundi "{batch}".',

    # sites: hosted Omada (access points)
    'Offline': 'Haipo hewani',
    'Online': 'Iko hewani',
    'Waiting to be added': 'Inasubiri kuongezwa',
    'Not responding': 'Haijibu',
    'Isolated': 'Imetengwa',
    'Unknown': 'Haijulikani',
    'Setting up': 'Inaandaliwa',
    'Updating firmware': 'Inasasisha programu',
    'Restarting': 'Inawashwa upya',
    'Adding': 'Inaongezwa',
    'Adding failed': 'Kuongeza kumeshindwa',
    'Managed by another controller': 'Inasimamiwa na controller nyingine',
    "Adding access points from SafeNet isn't switched on for this server yet.":
        'Kuongeza vifaa vya Wi-Fi (access point) kupitia SafeNet bado hakujawashwa kwenye seva hii.',
    'Enter the Wi-Fi name guests will see.': 'Weka jina la Wi-Fi ambalo wateja wataona.',
    'Your Wi-Fi "{name}" is ready. Now add your access point below.':
        'Wi-Fi yako "{name}" iko tayari. Sasa ongeza kifaa chako cha Wi-Fi (access point) hapa chini.',
    'Could not set up the Wi-Fi: {error}': 'Imeshindwa kuandaa Wi-Fi: {error}',
    '{mac} is already one of your access points.': '{mac} tayari ni mojawapo ya vifaa vyako vya Wi-Fi.',
    "SafeNet can't see {mac} yet. Check it is plugged in with internet and pointed to {host}, wait 2 minutes, then try again.":
        'SafeNet bado haioni {mac}. Hakikisha kimewashwa, kina intaneti na kimeelekezwa kwa {host}, subiri dakika 2, kisha jaribu tena.',
    '{mac} is being added. It restarts once and shows "Online" in 1–3 minutes.':
        '{mac} kinaongezwa. Kitajiwasha upya mara moja na kuonyesha "Online" baada ya dakika 1–3.',
    '{mac} needs its own login: enter the username and password you set on the access point, then try again.':
        '{mac} kinahitaji kuingia kwake: weka jina la mtumiaji na nenosiri ulilowekwa kwenye kifaa, kisha jaribu tena.',
    'The access point did not accept (code {code}). Restart it and try again in 2 minutes.':
        'Kifaa cha Wi-Fi hakijakubali (namba {code}). Kiwashe upya na ujaribu tena baada ya dakika 2.',
    'Ruijie / WiFiDog access points switched on for "{site}".': 'Vifaa vya Wi-Fi vya Ruijie / WiFiDog vimewashwa kwa "{site}".',
    'Ruijie / WiFiDog access points switched off for "{site}".': 'Vifaa vya Wi-Fi vya Ruijie / WiFiDog vimezimwa kwa "{site}".',
    'Omada removed from "{site}".': 'Omada imeondolewa kwenye "{site}".',
    '"{site}" now uses SafeNet\'s Omada Controller. Point your access points to {host} (steps below).':
        '"{site}" sasa inatumia Omada Controller ya SafeNet. Elekeza vifaa vyako vya Wi-Fi kwa {host} (hatua ziko hapa chini).',
    "Saved, but SafeNet's Omada Controller did not answer: {error}":
        'Imehifadhiwa, lakini Omada Controller ya SafeNet haikujibu: {error}',
    'Enter the controller address (e.g. https://203.0.113.5:8043), the hotspot operator name and password.':
        'Weka anwani ya controller (mfano https://203.0.113.5:8043), jina la hotspot operator na nenosiri.',
    'Controller address not accepted: {problem}.': 'Anwani ya controller haikubaliki: {problem}.',
    'Connected to the Omada Controller for "{site}". Now set the portal in Omada (steps below).':
        'Imeunganishwa na Omada Controller ya "{site}". Sasa weka portal kwenye Omada (hatua ziko hapa chini).',
    'Saved, but SafeNet could not log in to the controller: {error}':
        'Imehifadhiwa, lakini SafeNet imeshindwa kuingia kwenye controller: {error}',

    # captive portal
    'The logo must be a PNG, JPG or WebP image of at most 300 KB.': 'Nembo iwe picha ya PNG, JPG au WebP isiyozidi KB 300.',
    'Captive portal saved. Gateways pick up the changes within 5 minutes.':
        'Ukurasa wa kuingia umehifadhiwa. Gateway zitapokea mabadiliko ndani ya dakika 5.',

    # packages, payments
    '-- No speed limit --': '-- Bila kikomo cha kasi --',
    'New Package': 'Kifurushi kipya',
    'Edit Package': 'Hariri kifurushi',
    'Package "{name}" created.': 'Kifurushi "{name}" kimeongezwa.',
    'Package "{name}" updated.': 'Kifurushi "{name}" kimesasishwa.',
    'Package "{name}" deleted. Past payments keep their records.':
        'Kifurushi "{name}" kimefutwa. Malipo ya zamani yanabaki kwenye kumbukumbu.',
    'Payment {reference}: {status}.': 'Malipo {reference}: {status}.',
    'paid': 'yamelipwa',
    'pending': 'yanasubiri',
    'failed': 'yameshindwa',
    'review': 'yanakaguliwa',

    # sign up, email, password
    'Too many new accounts from this connection. Please try again in an hour.':
        'Akaunti nyingi mpya kutoka muunganisho huu. Tafadhali jaribu tena baada ya saa moja.',
    'That username is taken.': 'Jina hilo la mtumiaji limeshachukuliwa.',
    'An account with this email already exists. Log in or reset your password.':
        'Akaunti yenye barua pepe hii tayari ipo. Ingia au badilisha nenosiri lako.',
    'That confirmation link has expired. Log in to get a new one.': 'Kiungo hicho cha uthibitisho kimeisha muda. Ingia upate kipya.',
    'Email confirmed. You can log in now.': 'Barua pepe imethibitishwa. Unaweza kuingia sasa.',
    'If that account is waiting for confirmation, we sent a new link.':
        'Kama akaunti hiyo inasubiri uthibitisho, tumetuma kiungo kipya.',
    'If an account uses that email, we sent a reset link.': 'Kama kuna akaunti inayotumia barua pepe hiyo, tumetuma kiungo cha kubadilisha nenosiri.',
    'That reset link is invalid or has expired.': 'Kiungo hicho si sahihi au kimeisha muda.',
    'That reset link has already been used.': 'Kiungo hicho kimeshatumika.',
    'Password changed. You can log in now.': 'Nenosiri limebadilishwa. Unaweza kuingia sasa.',
    'Settings saved.': 'Mipangilio imehifadhiwa.',

    # team
    'The whole business (all sites)': 'Biashara nzima (maeneo yote)',
    'Only {site}': '{site} pekee',
    'Your plan does not allow more staff accounts. Upgrade on the Billing page.':
        'Mpango wako hauruhusu akaunti zaidi za wafanyakazi. Panda daraja kwenye ukurasa wa Ada ya SafeNet.',
    'That email already has an account.': 'Barua pepe hiyo tayari ina akaunti.',
    '{name} added as a partner (view only).': '{name} ameongezwa kama mbia (kuangalia tu).',
    '{name} added as staff.': '{name} ameongezwa kama mfanyakazi.',
    '{name} added as admin.': '{name} ameongezwa kama msimamizi.',
    '{name} added as {role}.': '{name} ameongezwa kama {role}.',
    '{name} enabled.': '{name} amewashwa.',
    '{name} disabled.': '{name} amezimwa.',
    '{name} removed from the team.': '{name} ameondolewa kwenye timu.',

    # sites, gateways
    'Give the site a name.': 'Lipe eneo jina.',
    'Your plan does not allow more sites. Upgrade on the Billing page.':
        'Mpango wako hauruhusu maeneo zaidi. Panda daraja kwenye ukurasa wa Ada ya SafeNet.',
    'Site "{name}" added and selected. New gateways, routers and vouchers now go to it.':
        'Eneo "{name}" limeongezwa na kuchaguliwa. Gateway, ruta na vocha mpya sasa zitaenda huko.',
    'Site "{name}" saved.': 'Eneo "{name}" limehifadhiwa.',
    'You need at least one site.': 'Unahitaji angalau eneo moja.',
    'Site "{name}" deleted. Its devices, packages and sales moved to "{target}".':
        'Eneo "{name}" limefutwa. Vifaa, vifurushi na mauzo yake vimehamishiwa "{target}".',
    'Site updated.': 'Eneo limesasishwa.',
    'Your plan does not allow more gateways. Upgrade on the Billing page.':
        'Mpango wako hauruhusu gateway zaidi. Panda daraja kwenye ukurasa wa Ada ya SafeNet.',
    'Give the gateway a name.': 'Ipe gateway jina.',
    'Gateway "{name}" disabled. Its key no longer works.': 'Gateway "{name}" imezimwa. Ufunguo wake haufanyi kazi tena.',
    'Gateway "{name}" deleted.': 'Gateway "{name}" imefutwa.',

    # earnings, withdrawals, payment settings
    'Check the form.': 'Kagua fomu.',
    'Enter a valid mobile number, e.g. 0712 345 678.': 'Weka namba ya simu sahihi, mfano 0712 345 678.',
    'Enter the Lipa Namba (the merchant till number, digits only).': 'Weka Lipa Namba (namba ya till ya mfanyabiashara, tarakimu tu).',
    'Choose the network or bank of the Lipa Namba.': 'Chagua mtandao au benki ya Lipa Namba.',
    'Enter the bank, the account number and the name on the account.': 'Weka benki, namba ya akaunti na jina lililo kwenye akaunti.',
    'The minimum withdrawal is {cur} {amount}.': 'Kiwango cha chini cha kutoa pesa ni {cur} {amount}.',
    'You can withdraw up to {cur} {amount}.': 'Unaweza kutoa hadi {cur} {amount}.',
    'Withdrawal of {cur} {amount} requested. You will get an email when it is paid.':
        'Ombi la kutoa {cur} {amount} limetumwa. Utapata barua pepe pesa zikitumwa.',
    'Enter your Snippe API key to receive payments directly.': 'Weka Snippe API key yako ili upokee malipo moja kwa moja.',
    'Enter your ClickPesa Client ID and API key to receive payments directly.':
        'Weka ClickPesa Client ID na API key yako ili upokee malipo moja kwa moja.',
    'Saved. Add your Snippe webhook signing key too, so payments are confirmed the moment they arrive.':
        'Imehifadhiwa. Weka pia Snippe webhook signing key yako, ili malipo yathibitishwe papo hapo yanapoingia.',
    'Payment settings saved.': 'Mipangilio ya malipo imehifadhiwa.',
    'Voucher SMS to guests is ON: each SMS costs TZS {price}.': 'SMS za vocha kwa wateja zimewashwa: kila SMS ni TZS {price}.',
    'Voucher SMS to guests is OFF: no SMS are sent or charged.': 'SMS za vocha kwa wateja zimezimwa: hakuna SMS inayotumwa wala kutozwa.',
    'Enter a valid mobile number for alerts, e.g. 0712 345 678.': 'Weka namba ya simu sahihi ya taarifa, mfano 0712 345 678.',
    'Add the mobile number the alerts should go to.': 'Weka namba ya simu itakayopokea taarifa.',
    'Alerts saved.': 'Taarifa zimehifadhiwa.',
    'Save your {provider} keys first.': 'Hifadhi kwanza funguo zako za {provider}.',
    '{provider} accepted your keys.': '{provider} imekubali funguo zako.',
    '{provider} rejected the keys: {error}': '{provider} imekataa funguo: {error}',

    # routers (VPN)
    'Your plan does not allow more routers. Upgrade on the Billing page.':
        'Mpango wako hauruhusu ruta zaidi. Panda daraja kwenye ukurasa wa Ada ya SafeNet.',
    'Give the router a name.': 'Ipe ruta jina.',
    'Router "{name}" added with VPN address {ip}. Paste the setup script into the router.':
        'Ruta "{name}" imeongezwa na anwani ya VPN {ip}. Bandika script ya kuweka kwenye ruta.',
    'Router "{name}" enabled.': 'Ruta "{name}" imewashwa.',
    'Router "{name}" disconnected from the VPN.': 'Ruta "{name}" imetenganishwa na VPN.',
    'Router "{name}" removed.': 'Ruta "{name}" imeondolewa.',

    # SafeNet subscription
    'Choose a plan and a period.': 'Chagua mpango na muda.',
    'Enter a valid mobile money number, e.g. 0712 345 678.': 'Weka namba sahihi ya pesa kwa simu, mfano 0712 345 678.',
    'Online payment is not available right now. Please contact SafeNet.':
        'Malipo ya mtandaoni hayapatikani kwa sasa. Tafadhali wasiliana na SafeNet.',
    "We couldn't send the payment request: {error}.": 'Imeshindwa kutuma ombi la malipo: {error}.',
    'try again': 'jaribu tena',
    'Data cap counter reset for {name}.': 'Kihesabu cha kikomo cha data cha {name} kimeanza upya.',
    'A Wi-Fi password has 8 to 63 characters. Leave it empty for an open network.': 'Nenosiri la Wi-Fi lina herufi 8 hadi 63. Liache wazi kama mtandao uko wazi.',
    'Add the Wi-Fi name for {site} first (Rename / edit).': 'Weka kwanza jina la Wi-Fi la {site} (Hariri).',
}

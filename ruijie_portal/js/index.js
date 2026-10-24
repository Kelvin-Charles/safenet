// SafeNet login page for Ruijie Cloud (Reyee access points), as uploaded to Ruijie Cloud (Custom HTML).
// Each time it opens it loads the business's current page and the latest page code from SafeNet, so changes in
// SafeNet (portal settings, packages, fixes) show without uploading again; the copy below is used when SafeNet
// can't be reached. SAFENET and the copy are filled in by SafeNet when the business downloads this page.
var SAFENET = {/*SAFENET_CONFIG*/};
var Portal = null;
var SN_CONFIG = null, SN_FRESH = false;

function loadConfig(data) {          // called by Ruijie's loadConfig.json
  SN_CONFIG = data || {};
  snStart();
}

function snStart() {
  if (SN_CONFIG && SN_FRESH && Portal && !Portal.started) {
    Portal.started = true;
    Portal.init(SN_CONFIG);
  }
}

(function () {                       // the fresh page and code from SafeNet, else the copy in this file (after 4 s)
  var done = function () { if (!SN_FRESH) { SN_FRESH = true; snStart(); } };
  try {
    var s = document.createElement("script");
    s.src = SAFENET.base + "/app/" + SAFENET.slug + "/ruijie.js?s=" + encodeURIComponent(SAFENET.site) + "&t=" + Date.now();
    s.onload = done;
    s.onerror = done;
    document.head.appendChild(s);
  } catch (e) {}
  setTimeout(done, 4000);
})();

/*PORTAL_COPY*/

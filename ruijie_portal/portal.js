// The SafeNet login page's logic for Ruijie Cloud (Reyee access points). SafeNet serves it fresh at
// /app/<business>/ruijie.js (with the business's current page), and also puts a copy inside the downloaded zip
// (js/index.js) for when SafeNet can't be reached. It shows the same page guests see on SafeNet, buys through the
// guest app API, and logs guests in through Ruijie's own login (/api/auth/general) with the code: the voucher they
// type, or the one they just paid for (SafeNet creates it on Ruijie Cloud).
Portal = {
  lang: "en",
  live: null,       // packages from SafeNet (fresher than the ones in this file)
  payment: null,
  opened: Date.now(),
  STALE_MS: 4 * 60000,   // Ruijie's login session on this page may expire after a few minutes

  init() {
    this.lang = SAFENET.lang || "en";
    const loading = document.getElementById("body_loading");
    if (loading) loading.classList.add("hide");
    this.render();
    const saved = this.saved();
    if (saved) {           // back with a fresh login session: connect with the saved code
      this.payment = { reference: "" };
      document.querySelector(".card").innerHTML = this.page().connecting.split("@@CODE@@").join(saved.code);
      this.connect(saved.code, 0);
      return;
    }
    const self = this;
    this.api("/me", { tokens: [], site: SAFENET.site }).then(function (d) {
      if (d.packages && d.packages.length) {
        self.live = d.packages;
        if (!self.payment) self.render();
      }
    }, function () {});
  },

  page() {
    return SAFENET.pages[this.lang];
  },

  text(key, vars) {
    let s = (SAFENET.texts[this.lang] || {})[key] || key;
    for (const k in vars || {}) s = s.split("{" + k + "}").join(vars[k]);
    return s;
  },

  // the whole SafeNet page, then its own script, then this page's handlers
  render(error, tab) {
    const p = this.page();
    document.documentElement.setAttribute("style", p.vars);
    document.documentElement.lang = this.lang;
    let css = document.getElementById("sn_css");
    if (!css) {
      css = document.createElement("style");
      css.id = "sn_css";
      document.head.appendChild(css);
    }
    css.textContent = SAFENET.css;
    document.title = SAFENET.name;
    document.body.className = p.body_class;
    document.body.innerHTML = p.body;
    document.querySelectorAll("details.more").forEach(function (d) { d.remove(); });   // no usernames on Ruijie
    this.packages();
    if (tab) {
      const radio = document.getElementById("tab-" + tab);
      if (radio) radio.checked = true;
    }
    if (error) this.alert(error, tab);
    const run = document.createElement("script");
    run.textContent = p.script;
    document.body.appendChild(run);
    this.wire();
  },

  alert(message, tab) {
    const panel = document.querySelector(tab === "voucher" ? ".panel-voucher" : ".panel-buy") || document.querySelector(".panel");
    const form = panel && panel.querySelector("form");
    if (!form) return;
    const box = document.createElement("div");
    box.className = "alert";
    box.setAttribute("role", "alert");
    box.innerHTML = SAFENET.alert_icon;
    const span = document.createElement("span");
    span.textContent = message;
    box.appendChild(span);
    form.parentNode.insertBefore(box, form);
  },

  local(phone) {        // 255712345678 -> 0712 345 678
    const d = String(phone || "").replace(/\D/g, "");
    return d.length === 12 && d.indexOf("255") === 0 ? "0" + d.slice(3, 6) + " " + d.slice(6, 9) + " " + d.slice(9) : phone || "";
  },

  money(currency, amount) {
    return currency + " " + Number(amount).toLocaleString("en-US");
  },

  duration(minutes) {
    const sw = this.lang === "sw";
    const d = Math.floor(minutes / 1440), h = Math.floor((minutes % 1440) / 60), m = minutes % 60;
    if (sw) return d ? "Siku " + d + (h ? " saa " + h : "") : h ? "Saa " + h + (m ? " dk " + m : "") : "Dakika " + m;
    if (d) return d + (d === 1 ? " day" : " days") + (h ? " " + h + "h" : "");
    if (h) return m ? h + "h " + m + "m" : h + (h === 1 ? " hour" : " hours");
    return m + " min";
  },

  // swap in SafeNet's current packages, built like the ones in the page
  packages() {
    const list = document.querySelector(".pkgs");
    const first = list && list.querySelector(".pkg");
    if (!this.live || !first) return;
    const self = this;
    const made = this.live.map(function (pk, i) {
      const row = first.cloneNode(true);
      const input = row.querySelector("input");
      const price = self.money(pk.currency, pk.price);
      input.value = pk.id;
      input.checked = i === 0;
      input.setAttribute("data-price", pk.price);
      input.setAttribute("data-label", self.text("pay", { price: price }));
      row.classList.toggle("on", i === 0);
      row.classList.toggle("has-offer", !!pk.offer);
      row.querySelector(".nm b").textContent = pk.name;
      let desc = pk.description || "";
      if (pk.offer && desc.indexOf("🎁 " + pk.offer) === 0) desc = desc.slice(("🎁 " + pk.offer).length).replace(/^[\s·]+/, "");
      row.querySelector(".nm small").textContent = self.duration(pk.validity_minutes) + (desc ? " · " + desc : "");
      const old = row.querySelector(".nm .deal");
      if (old) old.remove();
      if (pk.offer) {
        const deal = document.createElement("span");
        deal.className = "deal";
        const flag = document.createElement("span");
        flag.className = "flag";
        flag.textContent = "🎁 " + self.text("offer");
        deal.append(flag, document.createTextNode(" " + pk.offer));
        const gets = [];
        if (pk.bonus_minutes) gets.push(self.text("offer_free", { time: self.duration(pk.bonus_minutes) }));
        if (pk.discount_percent) gets.push(self.text("offer_off", { n: pk.discount_percent }));
        if (gets.length) {
          const em = document.createElement("em");
          em.textContent = gets.join(" · ");
          deal.append(em);
        }
        row.querySelector(".nm").append(deal);
      }
      const pr = row.querySelector(".pr");
      pr.textContent = "";
      if (pk.old_price) {
        const was = document.createElement("s");
        was.textContent = self.money(pk.currency, pk.old_price);
        pr.append(was);
      }
      pr.append(document.createTextNode(price));
      return row;
    });
    list.replaceChildren.apply(list, made);
    const pay = document.getElementById("paybtn");
    if (pay) pay.textContent = this.text("pay", { price: this.money(this.live[0].currency, this.live[0].price) });
  },

  wire() {
    const self = this;
    const other = this.lang === "sw" ? "en" : "sw";
    document.querySelectorAll("a.lang").forEach(function (a) {
      a.addEventListener("click", function (ev) {
        ev.preventDefault();
        self.lang = other;
        self.render();
      });
    });
    document.querySelectorAll("form").forEach(function (form) {
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        if (form.classList.contains("trialbox")) self.trial();
        else if (form.querySelector("input[name=package_id]")) self.buy(form);
        else if (form.querySelector("#code")) self.voucher(form.querySelector("#code").value);
      }, true);
    });
  },

  buy(form) {
    const self = this;
    const f = new FormData(form);
    const gift = !!f.get("gift");
    this.api("/buy", {
      tokens: [], site: SAFENET.site, package_id: f.get("package_id"), phone: f.get("phone") || "",
      network: f.get("network") || "", gift: gift, gift_phone: gift ? f.get("gift_phone") || "" : null,
    }).then(function (j) {
      self.payment = j;
      self.wait();
      self.poll(0);
    }, function (e) {
      self.render(e.message, "buy");
    });
  },

  wait() {
    const j = this.payment;
    const html = (j.gift_phone ? this.page().wait_gift : this.page().wait)
      .split("@@AMOUNT@@").join(this.money(j.currency, j.amount))
      .split("@@PACKAGE@@").join(j.package || "")
      .split("@@PHONE@@").join(this.local(j.phone))
      .split("@@FRIEND@@").join(this.local(j.gift_phone));
    document.querySelector(".card").innerHTML = html;
  },

  poll(n, paid) {
    const self = this;
    // waiting for the payment: 3 minutes; paid and the code still being made on Ruijie Cloud: up to 10 minutes
    if (n > (paid ? 200 : 60)) { this.payment = null; this.render(this.text("timeout"), "buy"); return; }
    setTimeout(function () {
      self.api("/pay/" + self.payment.reference).then(function (s) {
        if (s.status === "paid" && s.code) {
          if (s.gift_phone) {
            document.querySelector(".card").innerHTML = self.page().gift_sent.split("@@FRIEND@@").join(self.local(s.gift_phone));
            return;
          }
          document.querySelector(".card").innerHTML = self.page().connecting.split("@@CODE@@").join(s.code);
          if (s.ready === false) return self.poll(n + 1, true);     // SafeNet is still creating it on Ruijie Cloud
          self.keep({ code: s.code, at: Date.now(), fresh: 0 });
          if (self.stale()) return self.refresh(s.code);          // the guest took a while: get a fresh login session first
          return self.connect(s.code, 0);
        }
        if (s.status === "failed" || s.status === "review") {
          self.payment = null;
          self.render(self.text("failed", { reason: s.message || "" }), "buy");
          return;
        }
        self.poll(n + 1, paid);
      }, function () { self.poll(n + 1, paid); });
    }, 3000);
  },

  // the code just bought: Ruijie Cloud may need a moment to know it
  connect(code, tries) {
    const self = this;
    this.authenticate(code).then(function (r) {
      self.online(code, r.result.logonUrl);
    }, function (message) {
      const saved = self.saved();
      // a new voucher can take a little while to reach the access point: keep trying (longer on a fresh session)
      const typed = saved && saved.typed;      // typed by the guest (may simply be wrong): one short retry
      if (tries < (typed ? 1 : saved && saved.fresh ? 15 : 5)) return setTimeout(function () { self.connect(code, tries + 1); }, 3000);
      self.report(code, message);
      if (typed) {
        self.keep(null);
        self.payment = null;
        self.render(message || self.text("bad_code"), "voucher");
        const box = document.getElementById("code");
        if (box) box.value = code;
        return;
      }
      // Ruijie's login session on this page may have gone stale: ask the access point for a new one (it sends the
      // phone back here) and connect with the saved code (twice at most)
      if (saved && saved.code === code && saved.fresh < 2) return self.refresh(code);
      self.keep(null);
      self.payment = null;
      self.render(self.text("login_failed") + (message ? " (" + message + ")" : ""), "voucher");
      const box = document.getElementById("code");
      if (box) box.value = code;
    });
  },

  voucher(code) {
    const self = this;
    code = String(code || "").replace(/\s+/g, "");
    if (!code) return;
    this.authenticate(code).then(function (r) {
      self.online(code, r.result.logonUrl);
    }, function (message) {
      // the page has been open a while: Ruijie's login session may have expired, so get a fresh one and try again
      const saved = self.saved();
      if (self.stale() && !(saved && saved.code === code)) {
        self.keep({ code: code, at: Date.now(), fresh: 0, typed: true });
        return self.refresh(code);
      }
      self.keep(null);
      self.report(code, message);
      self.render(message || self.text("bad_code"), "voucher");
      const box = document.getElementById("code");
      if (box) box.value = code;
    });
  },

  stale() {
    return Date.now() - this.opened > this.STALE_MS;
  },

  // a new login session from the access point: any plain web address sends the phone back to this page
  refresh(code) {
    const saved = this.saved() || { code: code, at: Date.now(), fresh: 0 };
    saved.code = code;
    saved.fresh = (saved.fresh || 0) + 1;
    this.keep(saved);
    location.href = "http://neverssl.com/?sn=" + Date.now();
  },

  // the paid code, kept on the phone for a few minutes in case the page has to start again
  keep(value) {
    try {
      if (value) localStorage.setItem("sn_code", JSON.stringify(value));
      else localStorage.removeItem("sn_code");
    } catch (e) {}
  },

  saved() {
    try {
      const v = JSON.parse(localStorage.getItem("sn_code") || "null");
      return v && v.code && Date.now() - v.at < 15 * 60000 ? v : null;
    } catch (e) {
      return null;
    }
  },

  // why Ruijie refused a code, to SafeNet's log
  report(code, message) {
    try {
      const body = JSON.stringify({ code: code, error: String(message || "no answer").slice(0, 200), page: location.href });
      navigator.sendBeacon(SAFENET.base + "/app/" + SAFENET.slug + "/api/ruijie-link", new Blob([body], { type: "text/plain" }));
    } catch (e) {}
  },

  // tell SafeNet which phone went online with this code (Ruijie's link carries its MAC), then go online
  online(code, url) {
    this.keep(null);
    try {
      const body = JSON.stringify({ code: code, url: url || "", page: location.href });
      navigator.sendBeacon(SAFENET.base + "/app/" + SAFENET.slug + "/api/ruijie-link", new Blob([body], { type: "text/plain" }));
    } catch (e) {}
    location.href = url;
  },

  // free trial: Ruijie's one-click login (Ruijie allows it once per phone per day)
  trial() {
    const self = this;
    this.authenticate(null, "pass").then(function (r) {
      location.href = r.result.logonUrl;
    }, function (message) {
      self.render(message || self.text("trial_refused"), "buy");
    });
  },

  // Ruijie's login: resolves with its answer, or rejects with the message to show
  authenticate(code, kind) {
    const body = { lang: "en_US", authType: kind || "voucher", sessionId: this.param("sessionId") };
    if (code) body.account = code;
    return new Promise(function (resolve, reject) {
      $.post({
        url: "/api/auth/general",
        data: JSON.stringify(body),
        contentType: "application/json",
        timeout: 10000,
        success: function (r) {
          if (r && r.success) resolve(r);
          else reject((r && r.message) || "");
        },
        error: function () { reject(""); },
      });
    });
  },

  api(path, body) {
    const self = this;
    return fetch(SAFENET.base + "/app/" + SAFENET.slug + "/api" + path, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).catch(function () {
      // SafeNet not reachable before login: usually its address isn't in Ruijie's allowlist
      throw new Error(self.text("unreachable"));
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || r.status);
        return j;
      });
    });
  },

  param(name) {
    try {
      const query = decodeURI(window.top.location.href).split("?")[1] || "";
      const pair = query.split("&").map(function (x) { return x.split("="); })
        .find(function (x) { return x.length === 2 && x[0].toLowerCase() === name.toLowerCase(); });
      return pair ? pair[1] : null;
    } catch (e) {
      return null;
    }
  },
};

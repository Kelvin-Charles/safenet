// SafeNet login page for Ruijie Cloud (Reyee access points). Guests buy a package with mobile money from
// SafeNet (its guest app API), SafeNet creates the code on Ruijie Cloud, and this page logs them in with it
// through Ruijie's own login (/api/auth/general). A code bought elsewhere can be typed in below.
// SAFENET is filled in by SafeNet when the business downloads this page (Sites -> Reyee).
var SAFENET = {/*SAFENET_CONFIG*/};

function loadConfig(data) {
  IndexObj.init(data);
}

const IndexObj = {
  currentOption: "",
  loginOptions: [],

  LOGIN_OPTION: {
    VOUCHER: "voucher",
    FIXACCOUNT: "fixaccount",
    PASS: "pass",
  },

  init: function (data) {
    I18nObj.labelObj.sw_TZ = "Kiswahili";
    this.loadJson(data);
    setTimeout(function () {
      $("#body_loading").addClass("hide");
    }, 600);

    this.initEvent();
    SafeNetObj.init();
  },

  loadJson: function (data) {
    I18nObj.init(data);
    $(".dropdown-label").text(I18nObj.labelObj[I18nObj.currentLang] || I18nObj.currentLang);
    this.renderHtml(data);
  },

  initEvent: function () {
    const self = this;
    $("#login_btn").on("click", function () {
      self.onLogin();
    });
    const changeLang = I18nObj.changeLang.bind(I18nObj);
    I18nObj.changeLang = function (lang) {
      changeLang(lang);
      SafeNetObj.render();
    };
  },

  renderHtml: function (data) {
    const loginOptions = data?.custom_html?.login_options;
    this.loginOptions = loginOptions;

    if (!loginOptions) {
      return false;
    }

    // Define priority order
    const priorityOrder = [
      this.LOGIN_OPTION.VOUCHER,
      this.LOGIN_OPTION.FIXACCOUNT,
      this.LOGIN_OPTION.PASS,
    ];
    let currentOption = null;

    // Search for the default option according to the priority order
    for (const option of priorityOrder) {
      if (loginOptions.includes(option)) {
        currentOption = option;
        this.currentOption = currentOption;
        break;
      }
    }

    if (!currentOption) {
      return false;
    }

    I18nObj.renderHtmlLang();
    this.renderLoginHtml(loginOptions);
    this.renderCurrentLogin(currentOption);
  },

  renderLoginHtml: function (loginOptions) {
    // Control priority through styles: Voucher > Account > Oneclick
    if (loginOptions.length > 1) {
      $("#login_split_line").removeClass("hide");
    }

    const allOptions = [
      this.LOGIN_OPTION.VOUCHER,
      this.LOGIN_OPTION.FIXACCOUNT,
      this.LOGIN_OPTION.PASS,
    ];
    const missOptions = allOptions.filter(
      (option) => !loginOptions.includes(option)
    );

    missOptions.forEach((item) => {
      $(`.login-item-${item}`).remove();
    });
  },

  renderCurrentLogin(currentOption) {
    switch (currentOption) {
      case this.LOGIN_OPTION.PASS:
        $(".login-form-title").text(I18nObj.$t("one_click_login"));
        $(".login-form-title").attr("data-i18n", "one_click_login");
        break;
      case this.LOGIN_OPTION.FIXACCOUNT:
        $(".login-form-title").text(I18nObj.$t("account_login"));
        $(".login-form-title").attr("data-i18n", "account_login");
        break;
      case this.LOGIN_OPTION.VOUCHER:
      default:
        $(".login-form-title").text(I18nObj.$t("voucher_login"));
        $(".login-form-title").attr("data-i18n", "voucher_login");
    }

    const loginOptions = this.loginOptions;
    $(".login-form-wrapper .login-item").addClass("hide");
    $(".login-form-wrapper .login-item-" + currentOption).removeClass("hide");

    $(".other-btn-wrapper .login-item").addClass("hide");
    loginOptions.forEach((loginOpt) => {
      if (loginOpt !== currentOption) {
        $(".other-btn-wrapper .login-item-" + loginOpt).removeClass("hide");
      }
    });
  },

  changeLoginOption(currentOption) {
    this.currentOption = currentOption;
    this.renderCurrentLogin(currentOption);
  },

  onLogin() {
    let paramObj = {};

    switch (this.currentOption) {
      case this.LOGIN_OPTION.FIXACCOUNT:
        paramObj.account = $("#account_input").val();
        paramObj.password = $("#account_password").val();
        break;
      case this.LOGIN_OPTION.VOUCHER:
        paramObj.account = $("#voucher_code").val().replace(/\s+/g, "");
      case this.LOGIN_OPTION.PASS:
        break;
    }

    const validRes = this.validateLoginForm();
    if (!validRes) {
      return false;
    }

    this.authenticate(paramObj).then(
      function (response) {
        location.href = response.result.logonUrl;
      },
      function (message) {
        $("#login_msg").text(message);
      }
    );
  },

  // Ruijie's login: resolves with its response, or rejects with the message to show
  authenticate(paramObj) {
    const body = {
      lang: I18nObj.currentLang,
      authType: this.currentOption || this.LOGIN_OPTION.VOUCHER,
      sessionId: this._getParamVal("sessionId"),
      ...paramObj,
    };
    return new Promise(function (resolve, reject) {
      $.post({
        url: "/api/auth/general",
        data: JSON.stringify(body),
        contentType: "application/json",
        success: function (response) {
          if (response && response.success) {
            resolve(response);
          } else {
            reject((response && response.message) || "");
          }
        },
        error: function (jqXHR, textStatus) {
          reject(textStatus || "error");
        },
      });
    });
  },

  validateLoginForm() {
    $("#login_msg").text("");
    if (!this.currentOption) {
      return true;
    }

    switch (this.currentOption) {
      case this.LOGIN_OPTION.PASS:
        break;
      case this.LOGIN_OPTION.FIXACCOUNT:
        return this.validateAccountForm();
      case this.LOGIN_OPTION.VOUCHER:
      default:
        return this.validateVoucherForm();
    }

    return true;
  },

  validateVoucherForm() {
    const voucherCode = $("#voucher_code").val().trim();
    if (!voucherCode) {
      $("#login_msg").text(I18nObj.$t("please_enter_access_code"));
      return false;
    }
    return true;
  },

  validateAccountForm() {
    const accountVal = $("#account_input").val().trim();
    const accountPwd = $("#account_password").val().trim();
    if (!accountVal) {
      $("#login_msg").text(I18nObj.$t("please_enter_account"));
      return false;
    }
    if (!accountPwd) {
      $("#login_msg").text(I18nObj.$t("please_enter_pwd"));
      return false;
    }
    return true;
  },

  _getParamVal(paras) {
    try {
      const topUrl = decodeURI(window.top.location.href);
      const queryString = topUrl.split("?")[1];
      if (!queryString) {
        return null;
      }

      const paraString = queryString.split("&");
      const paraObj = {};
      for (var i = 0; i < paraString.length; i++) {
        const pair = paraString[i].split("=");
        if (pair.length === 2) {
          paraObj[pair[0].toLowerCase()] = pair[1];
        }
      }

      const returnValue = paraObj[paras.toLowerCase()];
      return returnValue !== undefined ? returnValue : null;
    } catch (e) {
      console.error("Error accessing top window URL:", e);
      return null;
    }
  },
};

// Buying with mobile money from SafeNet
const SafeNetObj = {
  data: null,      // packages, networks... from SafeNet
  view: "buy",     // buy, wait, paid, failed
  payment: null,
  error: "",

  t(key, vars) {
    let s = I18nObj.$t(key);
    for (const k in vars || {}) s = s.split("{" + k + "}").join(vars[k]);
    return s;
  },

  api(path, body) {
    const url = SAFENET.base + "/app/" + SAFENET.slug + "/api" + path;
    return fetch(url, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || r.status);
        return j;
      });
    });
  },

  money(currency, amount) {
    return currency + " " + Number(amount).toLocaleString("en-US");
  },

  duration(minutes) {
    const sw = I18nObj.currentLang === "sw_TZ";
    if (minutes % 1440 === 0) { const d = minutes / 1440; return sw ? "Siku " + d : d + (d === 1 ? " day" : " days"); }
    if (minutes % 60 === 0) { const h = minutes / 60; return sw ? "Saa " + h : h + (h === 1 ? " hour" : " hours"); }
    return sw ? "Dakika " + minutes : minutes + " min";
  },

  init() {
    document.documentElement.style.setProperty("--brand", SAFENET.color || "#0f766e");
    document.documentElement.style.setProperty("--on-brand", SAFENET.on || "#ffffff");
    document.title = SAFENET.name || "Wi-Fi";
    const logo = $(".content-logo");
    logo.addClass("hide");
    if (SAFENET.logo) {
      logo.on("load", function () { logo.removeClass("hide"); }).attr("src", SAFENET.logo);
    }
    $(".content-decoration-wrapper").append(
      $("<div class='sn-name'>").text(SAFENET.name || ""), $("<div class='sn-lead' data-i18n='sn_lead'>").text(I18nObj.$t("sn_lead")));
    $(".content-decoration-wrapper").after("<div class='sn-card' id='sn_buy'></div>");
    $(".login-wrapper").after("<div class='sn-foot' id='sn_foot'></div>");
    this.load();
  },

  load() {
    const self = this;
    this.api("/me", { tokens: [], site: SAFENET.site }).then(function (d) {
      self.data = d;
      self.render();
    }, function () {
      self.data = { offline: true };
      self.render();
    });
  },

  render() {
    const box = $("#sn_buy").empty();
    const d = this.data;
    const foot = $("#sn_foot").empty();
    if (d && d.support) foot.text(this.t("sn_help", { phone: d.support }));
    if (!d) return;
    if (this.view === "wait") return this.renderWait(box);
    if (this.view === "paid") return this.renderPaid(box);
    box.append($("<h2>").text(this.t("sn_buy")));
    if (d.offline || !d.can_buy) {
      box.append($("<p class='sn-sub'>").text(this.t(d.offline ? "sn_offline" : "sn_no_packages")));
      return;
    }
    box.append($("<p class='sn-sub'>").text(this.t("sn_buy_sub")));
    if (this.error) box.append($("<div class='sn-msg'>").text(this.error));
    const self = this;
    const list = $("<div class='sn-pkgs'>");
    d.packages.forEach(function (p, i) {
      const row = $("<label class='sn-pkg'>").toggleClass("on", i === 0);
      const radio = $("<input type='radio' name='sn_pkg'>").val(p.id).prop("checked", i === 0);
      radio.on("change", function () {
        list.find(".sn-pkg").removeClass("on");
        row.addClass("on");
        pay.text(self.t("sn_pay", { price: self.money(p.currency, p.price) }));
      });
      const name = $("<span class='nm'>").append($("<b>").text(p.name), $("<small>").text(self.duration(p.validity_minutes)));
      row.append(radio, name, $("<span class='pr'>").text(self.money(p.currency, p.price)));
      list.append(row);
    });
    box.append(list);
    let net = null;
    if (d.networks && d.networks.length > 1) {
      net = $("<select class='sn-input'>");
      d.networks.forEach(function (n) { net.append($("<option>").val(n.id).text(n.name)); });
      box.append($("<div class='sn-field'>").append($("<label>").text(this.t("sn_network")), net));
    }
    const phone = $("<input class='sn-input' type='tel' inputmode='tel' placeholder='07XX XXX XXX' autocomplete='tel'>");
    box.append($("<div class='sn-field'>").append($("<label>").text(this.t("sn_phone")), phone));
    const first = d.packages[0];
    const pay = $("<button type='button' class='sn-btn primary'>").text(this.t("sn_pay", { price: this.money(first.currency, first.price) }));
    box.append(pay);
    pay.on("click", function () {
      const picked = box.find("input[name=sn_pkg]:checked").val();
      if (!phone.val().trim()) { phone.focus(); return; }
      pay.prop("disabled", true);
      self.error = "";
      const networkId = net ? net.val() : (d.networks && d.networks[0] ? d.networks[0].id : "");
      self.api("/buy", { tokens: [], site: SAFENET.site, package_id: picked, phone: phone.val(), network: networkId }).then(function (j) {
        self.payment = j;
        self.view = "wait";
        self.render();
        self.poll(0);
      }, function (e) {
        self.error = e.message;
        self.render();
      });
    });
  },

  renderWait(box) {
    const p = this.payment;
    box.append($("<div class='sn-spin'>"), $("<p class='sn-wait'>").text(this.t("sn_waiting", { amount: this.money(p.currency, p.amount) })));
  },

  renderPaid(box) {
    const p = this.payment;
    box.append($("<h2>").text(this.t("sn_paid")), $("<div class='sn-code'>").text(p.code));
    if (p.connecting) box.append($("<div class='sn-spin'>"), $("<p class='sn-wait'>").text(this.t("sn_connecting")));
    if (p.loginFailed) box.append($("<div class='sn-msg'>").text(this.t("sn_login_failed")));
    box.append($("<p class='sn-sub'>").text(this.t("sn_keep")));
  },

  poll(n) {
    const self = this;
    if (n > 60) { this.view = "buy"; this.render(); return; }
    setTimeout(function () {
      self.api("/pay/" + self.payment.reference).then(function (s) {
        if (s.status === "paid" && s.code) {
          self.payment.code = s.code;
          self.view = "paid";
          $("#voucher_code").val(s.code);
          if (s.ready === false) {          // SafeNet is still creating it on Ruijie Cloud
            self.payment.connecting = true;
            self.render();
            return self.poll(n + 1);
          }
          self.payment.connecting = true;
          self.render();
          return self.connect(s.code, 0);
        }
        if (s.status === "failed" || s.status === "review") {
          self.view = "buy";
          self.error = self.t("sn_failed", { reason: s.message || "" });
          self.render();
          return;
        }
        self.poll(n + 1);
      }, function () { self.poll(n + 1); });
    }, 3000);
  },

  // log in with the new code; Ruijie Cloud may need a moment to know it
  connect(code, tries) {
    const self = this;
    IndexObj.currentOption = IndexObj.LOGIN_OPTION.VOUCHER;
    IndexObj.authenticate({ account: code }).then(function (response) {
      location.href = response.result.logonUrl;
    }, function () {
      if (tries < 4) return setTimeout(function () { self.connect(code, tries + 1); }, 3000);
      self.payment.connecting = false;
      self.payment.loginFailed = true;
      self.render();
    });
  },
};

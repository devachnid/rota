/* Passkeys: the browser half of WebAuthn, with no library.
 *
 * Loaded on every page (base.html). Three things it may find:
 *   #passkey-login on the login page — arms conditional mediation on load,
 *     so a passkey is offered in the email field's autofill and nobody
 *     without one sees anything; the button is the explicit path, and the
 *     only path where conditional UI is unavailable.
 *   #passkey-add on the Account page — enrol, with a typed name.
 *   #passkey-nudge on every signed-in page — a card offering to enrol on
 *     this device, shown only where this browser has never enrolled or
 *     signed in with a passkey (a localStorage marker), snoozed per browser
 *     with "Not now". Passkeys are per device, so the memory is too.
 *
 * Buttons start display:none and are revealed only when the browser has
 * PublicKeyCredential — `hidden` is not used because .btn's display beats
 * the UA [hidden] rule. The server speaks the WebAuthn JSON shapes
 * (base64url everywhere); the two converters below are what
 * parseCreationOptionsFromJSON / toJSON do in browsers new enough to have
 * them, written out so older ones work too.
 *
 * Every POST carries the CSRF token read from the page's form — the cookie
 * is HttpOnly on purpose (config/settings.py).
 */
(function () {
  if (!window.PublicKeyCredential) { return; }

  var MARK = "rota-passkey";           // "1" once this browser has used a passkey here
  var SNOOZE = "rota-passkey-snooze";  // ms timestamp until which the nudge stays away
  function store(key, value) { try { localStorage.setItem(key, value); } catch (e) {} }
  function read(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  function b64urlToBytes(s) {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    var pad = s.length % 4 ? "=".repeat(4 - (s.length % 4)) : "";
    var bin = atob(s + pad);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) { out[i] = bin.charCodeAt(i); }
    return out.buffer;
  }

  function bytesToB64url(buf) {
    var bytes = new Uint8Array(buf), bin = "";
    for (var i = 0; i < bytes.length; i++) { bin += String.fromCharCode(bytes[i]); }
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function csrfToken(form) {
    return form.querySelector("[name=csrfmiddlewaretoken]").value;
  }

  function post(url, token, body, signal) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify(body || {}),
      signal: signal
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          throw new Error(data.error || ("Something went wrong (HTTP " + r.status + ")."));
        }
        return data;
      });
    });
  }

  function creationOptions(o) {
    o.challenge = b64urlToBytes(o.challenge);
    o.user.id = b64urlToBytes(o.user.id);
    (o.excludeCredentials || []).forEach(function (c) { c.id = b64urlToBytes(c.id); });
    return o;
  }

  function requestOptions(o) {
    o.challenge = b64urlToBytes(o.challenge);
    (o.allowCredentials || []).forEach(function (c) { c.id = b64urlToBytes(c.id); });
    return o;
  }

  function credentialToJSON(cred) {
    var r = cred.response;
    var out = {
      id: cred.id, rawId: bytesToB64url(cred.rawId), type: cred.type,
      clientExtensionResults: cred.getClientExtensionResults(),
      response: { clientDataJSON: bytesToB64url(r.clientDataJSON) }
    };
    if (r.attestationObject) {
      out.response.attestationObject = bytesToB64url(r.attestationObject);
      out.response.transports = r.getTransports ? r.getTransports() : [];
      out.authenticatorAttachment = cred.authenticatorAttachment;
    } else {
      out.response.authenticatorData = bytesToB64url(r.authenticatorData);
      out.response.signature = bytesToB64url(r.signature);
      if (r.userHandle) { out.response.userHandle = bytesToB64url(r.userHandle); }
    }
    return out;
  }

  function show(el, message) {
    el.textContent = message;
    el.style.display = message ? "" : "none";
  }

  function explain(e) {
    if (e.name === "NotAllowedError") { return "Cancelled, or no passkey was offered."; }
    if (e.name === "InvalidStateError") { return "This device already has a passkey here."; }
    return e.message;
  }

  // --- enrolling ------------------------------------------------------------

  function enrol(button, form, errorEl, onDone) {
    if (button.disabled) { return; }          // one ceremony at a time
    button.disabled = true;
    show(errorEl, "");
    var token;
    var nameInput = form.querySelector("[name=name]");
    Promise.resolve().then(function () {      // so a throw here lands in the catch, not on the console
      token = csrfToken(form);
      return post(button.dataset.optionsUrl, token);
    }).then(function (opts) {
      return navigator.credentials.create({ publicKey: creationOptions(opts) });
    }).then(function (cred) {
      return post(button.dataset.registerUrl, token, {
        credential: credentialToJSON(cred),
        name: nameInput ? nameInput.value : ""
      });
    }).then(function (data) {
      store(MARK, "1");
      onDone(data);
    }).catch(function (e) {
      // "Already has a passkey here" is proof this device is enrolled —
      // remember it, or the card would keep coming back after site data
      // was cleared.
      if (e.name === "InvalidStateError") { store(MARK, "1"); }
      show(errorEl, explain(e));
    }).then(function () { button.disabled = false; });
  }

  var add = document.getElementById("passkey-add");
  if (add) {
    add.style.display = "";
    add.addEventListener("click", function () {
      enrol(add, document.getElementById("passkey-form"),
            document.getElementById("passkey-error"),
            function () { window.location.reload(); });
    });
  }

  // --- the nudge -------------------------------------------------------------

  var nudge = document.getElementById("passkey-nudge");
  if (nudge && !add && read(MARK) !== "1" && !(Number(read(SNOOZE)) > Date.now())) {
    var nudgeAdd = document.getElementById("passkey-nudge-add");
    var nudgeForm = document.getElementById("passkey-nudge-form");
    var nudgeError = document.getElementById("passkey-nudge-error");
    nudge.style.display = "";
    nudgeAdd.addEventListener("click", function () {
      enrol(nudgeAdd, nudgeForm, nudgeError, function (data) {
        nudge.querySelector(".flash").textContent =
          "Passkey added" + (data.name ? " (" + data.name + ")" : "") + " — sign in with it next time.";
      });
    });
    document.getElementById("passkey-later").addEventListener("click", function () {
      store(SNOOZE, String(Date.now() + 30 * 24 * 60 * 60 * 1000));
      nudge.style.display = "none";
    });
  }

  // --- signing in --------------------------------------------------------------

  var signIn = document.getElementById("passkey-login");
  if (signIn) {
    var loginForm = document.getElementById("login-form") || document.querySelector(".auth-card form");
    var loginError = document.getElementById("passkey-error");
    var conditionalOK = false;   // the browser can offer a passkey in the autofill
    var pending = null;          // AbortController for the armed conditional request
    var rearm = null;            // the timer that refreshes it while the tab is visible
    var busy = false;            // a ceremony is in flight: the person's own, or a pick being finished
    signIn.style.display = "";

    function finish(cred, token) {
      return post(signIn.dataset.loginUrl, token, {
        credential: credentialToJSON(cred),
        next: signIn.dataset.next || ""
      }).then(function (data) {
        store(MARK, "1");
        window.location.assign(data.next);
      });
    }

    function cancelConditional() {
      if (rearm) { clearTimeout(rearm); rearm = null; }
      if (pending) { pending.abort(); pending = null; }
    }

    // Conditional mediation: the browser offers the passkey in the email
    // field's autofill and shows nothing to anyone without one.
    //
    // Only one WebAuthn request may be pending at a time, and the server
    // keeps one challenge per session — the newest mint wins. So: the
    // controller exists from the moment arming starts and covers the
    // options fetch as well as get(), so a click or a tab switch during
    // the round-trip cancels the whole arm; nothing arms while a ceremony
    // is in flight (`busy`); the request is re-armed with a fresh
    // challenge well inside the options' `timeout`, and again whenever the
    // tab becomes visible or returns from the bfcache, so the tab the
    // person is looking at holds the session's challenge; a hidden tab
    // holds nothing.
    //
    // Arming is nobody's action, so an arming failure stays quiet and the
    // button remains. Once the person has picked, the refresh timer stops
    // (a new challenge would invalidate the pick) but the controller is
    // left alone — it is what tells a get() rejection apart from our own
    // cancel. A refusal after a pick is shown, and the offer comes back.
    function armConditional() {
      cancelConditional();
      if (!conditionalOK || busy || document.visibilityState === "hidden") { return; }
      var email = loginForm.querySelector("input[name=username]");
      if (email) { email.setAttribute("autocomplete", "username webauthn"); }
      var controller = new AbortController();
      pending = controller;
      var token = csrfToken(loginForm);
      post(signIn.dataset.optionsUrl, token, null, controller.signal).then(function (opts) {
        if (controller.signal.aborted) { return; }
        rearm = setTimeout(armConditional, Math.max((opts.timeout || 60000) * 0.6, 30000));
        navigator.credentials.get({
          publicKey: requestOptions(opts), mediation: "conditional", signal: controller.signal
        }).then(function (cred) {
          if (controller.signal.aborted) { return; }   // a pick that landed after our own cancel
          if (rearm) { clearTimeout(rearm); rearm = null; }
          pending = null;
          busy = true;
          return Promise.resolve().then(function () {   // so a throw lands in the catch below
            return finish(cred, token);
          }).catch(function (e) {
            busy = false;
            show(loginError, explain(e));
            armConditional();
          });
        }, function (e) {
          if (e.name === "AbortError" || controller.signal.aborted) { return; }
          show(loginError, explain(e));   // the authenticator refused before we had a credential
        });
      }).catch(function () { /* arming failed: quiet; the button is the way in */ });
    }

    if (PublicKeyCredential.isConditionalMediationAvailable) {
      PublicKeyCredential.isConditionalMediationAvailable().then(function (available) {
        conditionalOK = !!available;
        armConditional();
      }).catch(function () {});
    }
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") { armConditional(); } else { cancelConditional(); }
    });
    window.addEventListener("pageshow", function (ev) { if (ev.persisted) { armConditional(); } });

    signIn.addEventListener("click", function () {
      if (busy || signIn.disabled) { return; }
      busy = true;
      signIn.disabled = true;
      show(loginError, "");
      cancelConditional();
      var token;
      Promise.resolve().then(function () {
        token = csrfToken(loginForm);
        return post(signIn.dataset.optionsUrl, token);
      }).then(function (opts) {
        return navigator.credentials.get({ publicKey: requestOptions(opts) });
      }).then(function (cred) {
        return finish(cred, token);          // on success the page is navigating away
      }).catch(function (e) {
        show(loginError, explain(e));
        busy = false;
        signIn.disabled = false;
        armConditional();                    // the offer comes back after a cancelled or refused prompt
      });
    });
  }
})();

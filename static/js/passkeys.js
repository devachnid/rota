/* Passkeys: the browser half of WebAuthn, with no library.
 *
 * Two buttons, each present on one page: #passkey-add (Account) and
 * #passkey-login (login). Both start with display:none and are revealed
 * only when the browser has PublicKeyCredential — `hidden` is not used
 * because .btn's display beats the UA [hidden] rule. The server speaks
 * the WebAuthn JSON shapes (base64url everywhere); the two converters
 * below are what parseCreationOptionsFromJSON / toJSON do in browsers new
 * enough to have them, written out so older ones work too.
 *
 * Every POST carries the CSRF token read from the page's form — the cookie
 * is HttpOnly on purpose (config/settings.py).
 */
(function () {
  if (!window.PublicKeyCredential) { return; }

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

  function post(url, token, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify(body || {})
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

  var add = document.getElementById("passkey-add");
  if (add) {
    var addForm = document.getElementById("passkey-form");
    var addError = document.getElementById("passkey-error");
    add.style.display = "";
    add.addEventListener("click", function () {
      show(addError, "");
      var token = csrfToken(addForm);
      post(add.dataset.optionsUrl, token).then(function (opts) {
        return navigator.credentials.create({ publicKey: creationOptions(opts) });
      }).then(function (cred) {
        return post(add.dataset.registerUrl, token, {
          credential: credentialToJSON(cred),
          name: addForm.querySelector("[name=name]").value
        });
      }).then(function () {
        window.location.reload();
      }).catch(function (e) { show(addError, explain(e)); });
    });
  }

  var signIn = document.getElementById("passkey-login");
  if (signIn) {
    var loginForm = document.querySelector(".auth-card form");
    var loginError = document.getElementById("passkey-error");
    signIn.style.display = "";
    signIn.addEventListener("click", function () {
      show(loginError, "");
      var token = csrfToken(loginForm);
      post(signIn.dataset.optionsUrl, token).then(function (opts) {
        return navigator.credentials.get({ publicKey: requestOptions(opts) });
      }).then(function (cred) {
        return post(signIn.dataset.loginUrl, token, {
          credential: credentialToJSON(cred),
          next: signIn.dataset.next || ""
        });
      }).then(function (data) {
        window.location.assign(data.next);
      }).catch(function (e) { show(loginError, explain(e)); });
    });
  }
})();

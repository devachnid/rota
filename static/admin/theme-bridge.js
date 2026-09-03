/* Keeps two theme choices in agreement: the app's (localStorage
   "rota-theme": system|light|dark, written by static/js/theme.js) and
   unfold's ("adminTheme": a JSON-encoded "auto"|"light"|"dark", written by
   its Alpine store). On load the app's choice seeds unfold's if unfold has
   none; afterwards unfold's toggle writes back to the app's key. Every
   storage access is guarded: a private window breaks nothing. */
(function () {
  var APP = "rota-theme", ADMIN = "adminTheme";
  var toAdmin = { system: "auto", light: "light", dark: "dark" };
  var toApp = { auto: "system", light: "light", dark: "dark" };
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* not persisted */ } }

  var app = get(APP);
  if (app && toAdmin[app] && get(ADMIN) === null) {
    set(ADMIN, JSON.stringify(toAdmin[app]));
  }

  var last = get(ADMIN);
  setInterval(function () {
    var now = get(ADMIN);
    if (now === last) { return; }
    last = now;
    try {
      var v = JSON.parse(now);
      if (toApp[v]) { set(APP, toApp[v]); }
    } catch (e) { /* not a value we wrote or read */ }
  }, 1000);
})();

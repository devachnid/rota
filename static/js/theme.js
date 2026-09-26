/* Light / dark / system, persisted per browser.
 *
 * Three states rather than two on purpose. The CSS has a bare :root, a
 * prefers-color-scheme block and a [data-theme] block; a two-way toggle would
 * strand the middle one, so anyone who had never touched the control would
 * lose the OS-follows behaviour the moment they touched it once.
 *
 * This runs in <head>, before the body is parsed, because applying the theme
 * after first paint means every page load flashes the wrong colours.
 */
(function () {
  var KEY = "rota-theme";
  var ORDER = ["system", "light", "dark"];
  var LABEL = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };

  function read() {
    try {
      var v = localStorage.getItem(KEY);
      return ORDER.indexOf(v) === -1 ? "system" : v;
    } catch (e) {
      return "system";   // private window, or site data blocked
    }
  }

  function apply(state) {
    var root = document.documentElement;
    if (state === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", state);
    }
  }

  apply(read());   // before paint

  // Paper is white. A dark theme printed as it stands is light text on a
  // page the printer leaves white (browsers drop backgrounds), so print in
  // the light palette, then put back whatever was showing. beforeprint can
  // arrive twice for one print (a preview re-rendering); only the first
  // may record what to restore, or the second records "light".
  var printing = false, shown = null;
  window.addEventListener("beforeprint", function () {
    if (!printing) {
      printing = true;
      shown = document.documentElement.getAttribute("data-theme");
    }
    document.documentElement.setAttribute("data-theme", "light");
  });
  window.addEventListener("afterprint", function () {
    if (!printing) { return; }
    printing = false;
    if (shown === null) {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", shown);
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    var buttons = document.querySelectorAll('[id^="theme-toggle"]');
    if (!buttons.length) { return; }

    function show(button, state) {
      button.textContent = LABEL[state];
      button.setAttribute("aria-label", LABEL[state] + " (click to change)");
    }

    buttons.forEach(function (button) {
      show(button, read());
      button.addEventListener("click", function () {
        var next = ORDER[(ORDER.indexOf(read()) + 1) % ORDER.length];
        try { localStorage.setItem(KEY, next); } catch (e) { /* not persisted */ }
        apply(next);
        buttons.forEach(function (b) { show(b, next); });
      });
    });
  });
})();

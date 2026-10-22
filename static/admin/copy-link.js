/* The Copy button beside a link the admin is shown to pass on by hand
   (accounts/admin.py _copyable). The clipboard API needs https or
   localhost; where it is missing or refused, the older copy command is
   tried, and failing that the link is left selected for Ctrl+C. Clicking
   the field itself selects the whole link. */
(function () {
  function copied(button, ok) {
    button.textContent = ok ? "Copied" : "Press Ctrl+C";
  }

  function fallback(field, button) {
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { /* left selected */ }
    copied(button, ok);
  }

  document.addEventListener("click", function (e) {
    var target = e.target;
    if (!target.closest) { return; }
    var source = target.closest("[data-copy-link-source]");
    if (source) { source.select(); return; }
    var button = target.closest("[data-copy-link]");
    if (!button) { return; }
    var field = button.parentNode.querySelector("[data-copy-link-source]");
    if (!field) { return; }
    field.select();
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(field.value).then(
        function () { copied(button, true); },
        function () { fallback(field, button); });
    } else {
      fallback(field, button);
    }
  });
})();

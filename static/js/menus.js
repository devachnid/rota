/* The header's account menu and the tab bar's More sheet are <details>, so
 * they open and close with no script at all. What a <details> does not do
 * is close when you are done with it: click elsewhere and it stays open
 * over the page. This adds the two closings a menu is expected to have —
 * a click outside it, and Escape (which hands focus back to the toggle,
 * so a keyboard user is not left on a control that has vanished) — and
 * shuts one menu when another opens.
 */
(function () {
  var MENUS = "details.nav-account, details.tabbar-more";

  function closeAll(except) {
    document.querySelectorAll(MENUS).forEach(function (menu) {
      if (menu !== except) { menu.removeAttribute("open"); }
    });
  }

  // [data-close-menu]: an item that opens something over the page (Feedback
  // opens the modal) shuts its menu on the way — it was an inline onclick,
  // which the Content-Security-Policy does not allow.
  document.addEventListener("click", function (event) {
    var closer = event.target.closest && event.target.closest("[data-close-menu]");
    var inside = !closer && event.target.closest && event.target.closest(MENUS);
    closeAll(inside);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") { return; }
    var open = document.querySelector(MENUS.split(", ").map(function (m) {
      return m + "[open]";
    }).join(", "));
    if (!open) { return; }
    open.removeAttribute("open");
    var toggle = open.querySelector("summary");
    if (toggle) { toggle.focus(); }
  });
})();

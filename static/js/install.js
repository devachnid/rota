/* The offer to add Rota to the home screen.
 *
 * Chrome on Android decides for itself when to show its install bar, and a
 * site cannot see or steer that. What it does promise is one event,
 * beforeinstallprompt, fired once the site is installable and not already
 * installed. This script keeps that event, shows #install-nudge (a card on
 * every signed-in page, built like the passkey nudge), and on "Add" hands
 * the event back to Chrome, which puts up its own install sheet.
 *
 * The card is revealed from inside the event handler and nowhere else, so
 * a browser that never fires it never sees it: iOS, desktop Chrome with its
 * address-bar icon, a page already running as the installed app. "Not now"
 * snoozes per browser for thirty days, in localStorage like the passkey
 * snooze — an install is per device, so the memory is too.
 */
(function () {
  var SNOOZE = "rota-install-snooze";   // ms timestamp until which the card stays away
  var SNOOZE_FOR = 30 * 24 * 60 * 60 * 1000;
  function store(key, value) { try { localStorage.setItem(key, value); } catch (e) {} }
  function read(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  if (window.matchMedia("(display-mode: standalone)").matches) { return; }

  var deferred = null;

  window.addEventListener("beforeinstallprompt", function (event) {
    // Chrome would otherwise show its own bar on its own schedule; the card
    // is the one offer, and it is only made where a card exists to make it.
    event.preventDefault();
    deferred = event;
    var nudge = document.getElementById("install-nudge");
    if (!nudge || Number(read(SNOOZE)) > Date.now()) { return; }
    nudge.style.display = "";

    document.getElementById("install-nudge-add").addEventListener("click", function () {
      if (!deferred) { return; }
      var prompt = deferred;
      deferred = null;
      nudge.style.display = "none";
      prompt.prompt();
      // A declined sheet is a "not now" too; the event cannot be reused.
      prompt.userChoice.then(function (choice) {
        if (choice.outcome !== "accepted") { store(SNOOZE, String(Date.now() + SNOOZE_FOR)); }
      });
    });
    document.getElementById("install-later").addEventListener("click", function () {
      store(SNOOZE, String(Date.now() + SNOOZE_FOR));
      nudge.style.display = "none";
    });
  });

  window.addEventListener("appinstalled", function () {
    deferred = null;
    var nudge = document.getElementById("install-nudge");
    if (nudge) { nudge.style.display = "none"; }
  });
})();

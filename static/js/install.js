/* The offer to add Rota to the home screen.
 *
 * Chrome on Android decides for itself when to show its install bar, and a
 * site cannot see or steer that. What it does promise is one event,
 * beforeinstallprompt, fired once the site is installable and not already
 * installed. This script keeps that event, shows #install-nudge (a card on
 * every signed-in page, built like the passkey nudge), and on "Add" hands
 * the event back to Chrome, which puts up its own install sheet.
 *
 * iOS never fires that event and has no install sheet a page can open: the
 * only way onto the home screen is the Share sheet's "Add to Home Screen".
 * So on an iOS browser the same card is shown with those steps in place of
 * the Add button — the offer is the same, only the last tap is theirs.
 *
 * Nothing else sees the card: desktop Chrome has its address-bar icon, and
 * a page already running as the installed app is checked first. "Not now"
 * snoozes per browser for thirty days, in localStorage like the passkey
 * snooze — an install is per device, so the memory is too.
 */
(function () {
  var SNOOZE = "rota-install-snooze";   // ms timestamp until which the card stays away
  var SNOOZE_FOR = 30 * 24 * 60 * 60 * 1000;
  function store(key, value) { try { localStorage.setItem(key, value); } catch (e) {} }
  function read(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  // Installed and running as the app: nothing to offer. navigator.standalone
  // is Safari's own flag for a home-screen web app; the media query is what
  // everyone else answers, and Safari 13+ answers it too.
  if (window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true) { return; }

  // iPhone, iPod, iPad — including an iPad that reports itself as a Mac
  // (Safari's default "Request Desktop Website" on iPad), which a Mac never
  // does with a touch screen.
  var ios = /iPhone|iPad|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  var deferred = null;

  function show() {
    var nudge = document.getElementById("install-nudge");
    if (!nudge || Number(read(SNOOZE)) > Date.now()) { return null; }
    nudge.style.display = "";
    document.getElementById("install-later").addEventListener("click", function () {
      store(SNOOZE, String(Date.now() + SNOOZE_FOR));
      nudge.style.display = "none";
    });
    return nudge;
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    // Chrome would otherwise show its own bar on its own schedule; the card
    // is the one offer, and it is only made where a card exists to make it.
    event.preventDefault();
    deferred = event;
    var nudge = show();
    if (!nudge) { return; }

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
  });

  window.addEventListener("appinstalled", function () {
    deferred = null;
    var nudge = document.getElementById("install-nudge");
    if (nudge) { nudge.style.display = "none"; }
  });

  if (ios) {
    // No event will come. Show the steps, and no Add button: there is no
    // sheet for it to open.
    var nudge = show();
    if (!nudge) { return; }
    document.getElementById("install-nudge-add").hidden = true;
    document.getElementById("install-nudge-how").hidden = false;
  }
})();

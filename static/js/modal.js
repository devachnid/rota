/* The one modal (#modal, base.html). The grid's cell, day-note and locum
 * forms and the Feedback form all render into it through htmx, so it has
 * to behave like a dialog from the keyboard in one place:
 *
 *  - focus goes into it when it opens — to an [autofocus] field if the form
 *    names one, to Save if the form has come back asking to be saved again
 *    (the eligibility and replace prompts), otherwise to the first field;
 *  - Tab and Shift+Tab stay inside it;
 *  - Escape closes it, as Cancel does;
 *  - and when it empties, focus goes back to whatever opened it.
 *
 * The markup carries role="dialog", aria-modal and aria-labelledby (the
 * form's .modal-head is #modal-title). The mouse is unchanged: clicking
 * another cell while a form is open still swaps the form, as it did.
 *
 * It also carries the forms' little behaviours that used to be inline
 * onclick/onchange attributes, which the Content-Security-Policy
 * (config/middleware.py) does not allow:
 *  - [data-modal-close] — Cancel and Close — empties the modal;
 *  - select[data-partner-for] on the cell form shows the partner field only
 *    when the mentoring session type (the attribute's value) is chosen;
 *  - form[data-send-viewport] — Feedback — adds the window size to what it
 *    sends, which was an htmx `js:` value and needed eval.
 */
(function () {
  var modal = document.getElementById("modal");
  if (!modal) { return; }
  var FOCUSABLE = 'a[href], button:not([disabled]), select:not([disabled]), textarea:not([disabled]), '
    + 'input:not([type="hidden"]):not([disabled]), [tabindex]:not([tabindex="-1"])';
  var opener = null;

  function open() { return modal.childElementCount > 0; }
  function focusables() {
    return [].filter.call(modal.querySelectorAll(FOCUSABLE), function (el) {
      return el.offsetParent !== null;   // not in a [hidden] field
    });
  }

  // What opened it: only a request from outside the modal counts — a form
  // posting back into itself is not a new opener.
  document.body.addEventListener("htmx:beforeRequest", function (e) {
    if (e.detail.target === modal && !modal.contains(e.detail.elt)) { opener = e.detail.elt; }
  });

  document.body.addEventListener("htmx:afterSettle", function (e) {
    if (e.detail.target !== modal || !open() || modal.contains(document.activeElement)) { return; }
    var again = modal.querySelector(".alert") && modal.querySelector('button[type="submit"]');
    var first = modal.querySelector("[autofocus]") || again || focusables()[0];
    if (first) { first.focus(); }
  });

  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("[data-modal-close]")) { modal.innerHTML = ""; }
  });

  document.addEventListener("change", function (e) {
    var select = e.target.closest && e.target.closest("select[data-partner-for]");
    var field = document.getElementById("partner-field");
    if (select && field) { field.hidden = select.value !== select.dataset.partnerFor; }
  });

  document.body.addEventListener("htmx:configRequest", function (e) {
    if (e.detail.elt.matches && e.detail.elt.matches("form[data-send-viewport]")) {
      e.detail.parameters.viewport = window.innerWidth + "x" + window.innerHeight;
    }
  });

  new MutationObserver(function () {
    if (open()) { return; }
    if (opener && opener.isConnected) { opener.focus({ preventScroll: true }); }
    opener = null;
  }).observe(modal, { childList: true });

  document.addEventListener("keydown", function (e) {
    if (!open()) { return; }
    if (e.key === "Escape") {
      e.preventDefault();
      modal.innerHTML = "";
      return;
    }
    if (e.key !== "Tab") { return; }
    var items = focusables();
    if (!items.length) { return; }
    var first = items[0], last = items[items.length - 1];
    if (!modal.contains(document.activeElement)) {
      e.preventDefault();
      first.focus();
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
})();

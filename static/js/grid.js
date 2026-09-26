// Four jobs on the week page, each its own function.
//
// 1. The cell whose form is open gets a ring, so it is clear which one was
//    clicked. Set when a click on the grid opens the modal; cleared when
//    the modal empties (Cancel) — Save reloads the page (HX-Refresh),
//    which clears it by itself. The day headers and the locum "+" cells
//    open forms the same way, so they get the same ring.
// 2. The pane shows eight weeks and scrolls sideways. On load it lands on
//    the anchor week, unless this is the refresh a save just triggered, in
//    which case it lands where the admin was: the position is written to
//    sessionStorage under the window's start date before any htmx request
//    and on pagehide, and read back once. A different window (Earlier,
//    Later, Go) has a different key and lands on its anchor.
// 3. Today: when today's column is on the page the Today link scrolls to
//    it instead of reloading; otherwise it is the plain link it renders as.
// 4. Keyboard. Every cell, day heading and locum badge an admin can open
//    is in the tab order (tabindex="0" in the templates) and Enter or
//    Space does what a click does. Saving reloads the page, so the thing
//    the form was opened from is remembered and focused again on load;
//    ticking replaces the row, so the cell is focused again after the
//    swap. Without those a keyboard user starts again from the top of a
//    thousand cells after every edit. The pane is told how much of it the
//    sticky column and header cover, so a cell tabbed to is scrolled
//    clear of them. (The dialog itself is static/js/modal.js.)
(function () {
  var modal = document.getElementById("modal");
  var pane = document.querySelector(".grid-wrap");
  var table = document.querySelector(".table-grid");
  if (!modal || !pane || !table) return;

  function ring() {
    function clear() {
      document.querySelectorAll(".is-editing").forEach(function (el) {
        el.classList.remove("is-editing");
      });
    }
    document.body.addEventListener("htmx:beforeRequest", function (e) {
      var el = e.detail.elt;
      if (e.detail.target !== modal || !el.closest || !el.closest(".table-grid")) return;
      var cell = el.closest("td, th");
      if (!cell) return;
      clear();
      cell.classList.add("is-editing");
    });
    new MutationObserver(function () {
      if (!modal.childElementCount) clear();
    }).observe(modal, { childList: true });
  }

  function scrollToCell(cell) {
    var corner = table.querySelector("thead .grid-clin");
    pane.scrollLeft = cell.offsetLeft - (corner ? corner.offsetWidth : 0);
  }

  function position() {
    var key = "grid-scroll:" + (table.dataset.start || "");
    var saved = null;
    try {
      saved = sessionStorage.getItem(key);
      sessionStorage.removeItem(key);
    } catch (e) { /* storage blocked: land on the anchor */ }
    if (saved !== null) {
      pane.scrollLeft = parseInt(saved, 10) || 0;
    } else {
      var anchor = table.querySelector(".grid-day.is-anchor");
      if (anchor) scrollToCell(anchor);
    }
    function remember() {
      try { sessionStorage.setItem(key, String(pane.scrollLeft)); } catch (e) { /* ignore */ }
    }
    document.body.addEventListener("htmx:beforeRequest", remember);
    window.addEventListener("pagehide", remember);
  }

  function today() {
    var link = document.getElementById("grid-today");
    var cell = table.querySelector("thead .grid-day.is-today");
    if (!link || !link.dataset.scroll || !cell) return;
    link.addEventListener("click", function (e) {
      e.preventDefault();
      scrollToCell(cell);
    });
  }

  function keyboard() {
    var KEY = "grid-focus";
    var OPENS = "[tabindex][hx-get], [tabindex][hx-post]";
    var corner = table.querySelector("thead .grid-clin");
    var thead = table.querySelector("thead");
    if (corner) pane.style.scrollPaddingLeft = corner.offsetWidth + "px";
    if (thead) pane.style.scrollPaddingTop = thead.offsetHeight + "px";

    table.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      if (!e.target.matches || !e.target.matches(OPENS)) return;
      e.preventDefault();   // Space would otherwise scroll the pane
      e.target.click();
    });

    var ticking = null;
    document.body.addEventListener("htmx:beforeRequest", function (e) {
      var el = e.detail.elt;
      if (!el.closest || !el.closest(".table-grid")) return;
      if (e.detail.target === modal) {
        try { sessionStorage.setItem(KEY, el.getAttribute("hx-get") || ""); } catch (x) { /* ignore */ }
      } else if (el.matches("td[hx-post]") && document.activeElement === el) {
        ticking = el.getAttribute("hx-vals");
      }
    });
    document.body.addEventListener("htmx:afterSettle", function () {
      if (ticking === null) return;
      var again = [].find.call(table.querySelectorAll("td[hx-post]"), function (td) {
        return td.getAttribute("hx-vals") === ticking;
      });
      ticking = null;
      if (again) again.focus({ preventScroll: true });
    });
    // Closed without saving (Cancel, Escape): nothing to come back to.
    new MutationObserver(function () {
      if (!modal.childElementCount) {
        try { sessionStorage.removeItem(KEY); } catch (x) { /* ignore */ }
      }
    }).observe(modal, { childList: true });

    var wanted = null;
    try {
      wanted = sessionStorage.getItem(KEY);
      sessionStorage.removeItem(KEY);
    } catch (x) { /* storage blocked */ }
    if (wanted) {
      var back = table.querySelector('[hx-get="' + CSS.escape(wanted) + '"]');
      if (back) back.focus({ preventScroll: true });
    }
  }

  ring();
  position();
  today();
  keyboard();
})();

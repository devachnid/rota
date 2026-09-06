// The cell whose form is open gets a ring, so it is clear which one was
// clicked. Set when a click on the grid opens the modal; cleared when the
// modal empties (Cancel) — Save reloads the page (HX-Refresh), which clears
// it by itself. The day headers and the locum "+" cells open forms the same
// way, so they get the same ring.
(function () {
  var modal = document.getElementById("modal");
  if (!modal) return;
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
})();

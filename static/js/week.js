/* The phone week: a day in the strip at the top opens that day's card as
 * well as scrolling to it — a jump that lands on a closed card is two taps
 * for one intent. A link arriving with a day in its #fragment opens that
 * card too. Without the script the strip still scrolls, and a card still
 * opens with a tap.
 */
(function () {
  function open(hash) {
    if (!hash || hash.length < 2) { return; }
    var card = document.getElementById(decodeURIComponent(hash.slice(1)));
    if (card && card.tagName === "DETAILS") { card.open = true; }
  }
  document.querySelectorAll(".wk-strip a").forEach(function (a) {
    a.addEventListener("click", function () { open(a.getAttribute("href")); });
  });
  open(location.hash);
})();

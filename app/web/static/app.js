// Small progressive enhancements; every page works without them.
(function () {
  function localTimes(root) {
    root.querySelectorAll("time[data-local]").forEach(function (el) {
      var when = new Date(el.getAttribute("datetime"));
      if (!isNaN(when)) {
        el.textContent = when.toLocaleString([], {
          weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
        });
        el.title = el.getAttribute("datetime");
      }
    });
  }
  function copyButtons(root) {
    root.querySelectorAll("button[data-copy]").forEach(function (button) {
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(button.getAttribute("data-copy")).then(function () {
          var label = button.textContent;
          button.textContent = "Copied";
          setTimeout(function () { button.textContent = label; }, 1500);
        });
      });
    });
  }
  function enhance(root) { localTimes(root); copyButtons(root); }
  document.addEventListener("DOMContentLoaded", function () { enhance(document); });
  document.addEventListener("htmx:afterSwap", function (event) { enhance(event.detail.elt); });
  document.addEventListener("htmx:oobAfterSwap", function (event) { enhance(event.detail.target); });
})();

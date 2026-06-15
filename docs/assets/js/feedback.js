// Privacy-respecting "Was this page helpful?" widget.
// No analytics, no cookies, no network calls. A "could be better" click opens a
// pre-filled GitHub issue so the feedback becomes an actionable docs ticket.
document.addEventListener("DOMContentLoaded", function () {
  var box = document.getElementById("lava-feedback");
  if (!box) return;
  var note = box.querySelector(".lava-feedback__note");
  var issueBase = box.getAttribute("data-issue-url") || "#";
  var pageName = document.title.replace(/\s*[–-]\s*Lava Security Docs\s*$/, "");

  box.querySelectorAll("[data-lava-feedback]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var positive = btn.getAttribute("data-lava-feedback") === "yes";
      box.querySelectorAll(".lava-feedback__btn").forEach(function (b) {
        b.disabled = true;
        if (b === btn) b.classList.add("lava-feedback__btn--chosen");
      });
      if (positive) {
        note.textContent = "Thanks for the feedback! 🙌";
      } else {
        var title = encodeURIComponent("Docs feedback: " + pageName);
        var body = encodeURIComponent(
          "Page: " + window.location.href + "\n\nWhat was missing, unclear, or wrong?\n\n"
        );
        var url = issueBase + "?labels=docs-feedback&title=" + title + "&body=" + body;
        note.innerHTML =
          'Sorry to hear that — <a href="' + url + '" target="_blank" rel="noopener">' +
          "tell us what was missing</a> and we'll fix it.";
      }
      note.hidden = false;
    });
  });
});

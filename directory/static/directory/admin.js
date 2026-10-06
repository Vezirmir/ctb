// Small helpers for the admin: copyable full links and click-to-insert placeholders.
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("a[data-ctb-link]").forEach(function (link) {
        link.textContent = link.href;  // the browser resolves the path to the full address
    });

    document.addEventListener("click", function (event) {
        var copy = event.target.closest("[data-ctb-copy]");
        if (copy) {
            var url = new URL(copy.dataset.ctbCopy, window.location.href).href;
            var done = function () {
                var icon = copy.querySelector(".material-symbols-outlined");
                if (!icon) return;
                icon.textContent = "check";
                setTimeout(function () { icon.textContent = "content_copy"; }, 1500);
            };
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(url).then(done);
            } else {
                var field = document.createElement("textarea");
                field.value = url;
                document.body.appendChild(field);
                field.select();
                document.execCommand("copy");
                field.remove();
                done();
            }
            return;
        }

        var insert = event.target.closest("[data-ctb-insert]");
        if (insert) {
            var row = insert.closest(".field-line, .form-row, [class*='field-']") || document;
            var area = row.querySelector("textarea") || document.querySelector("textarea[name='body']");
            if (!area) return;
            var text = insert.dataset.ctbInsert;
            var start = area.selectionStart, end = area.selectionEnd;
            area.setRangeText(text, start, end, "end");
            area.focus();
            area.dispatchEvent(new Event("input", {bubbles: true}));
        }
    });
});

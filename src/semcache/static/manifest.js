// "Copy manifest entry" buttons. Delegated, so it also works on content htmx inserts later.
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) {}
  const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (e) {}
  ta.remove(); return ok;
}
(function () {
  const f = document.getElementById("ghuser"); if (!f) return;
  try { f.value = localStorage.getItem("scout_ghuser") || ""; } catch (e) {}
})();
document.addEventListener("click", async e => {
  const b = e.target.closest("button.mini[data-repo]"); if (!b) return;
  const note = b.parentElement.querySelector(".copied") || b.nextElementSibling;
  busy(b, true); note.textContent = "";
  try {
    const user = ((document.getElementById("ghuser") || {}).value || "").trim();
    try { localStorage.setItem("scout_ghuser", user); } catch (e2) {}
    const r = await fetch("/manifest-entry?repo=" + encodeURIComponent(b.dataset.repo) + (user ? "&owner=" + encodeURIComponent(user) : ""));
    if (!r.ok) throw new Error((await r.json()).detail || "HTTP " + r.status);
    const d = await r.json();
    const ok = await copyText(d.text);
    note.textContent = ok ? "Copied. Append it as the last item (add a comma after the previous entry). " + d.warnings.join(" ") : "Copy failed";
  } catch (err) { note.textContent = err.message; }
  finally { busy(b, false); }
});

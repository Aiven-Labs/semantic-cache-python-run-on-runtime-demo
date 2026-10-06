// Busy helpers. busy(btn, true/false) toggles an in-button spinner; spinnerHTML(label) is a block loader.
function busy(el, on) {
  if (!el) return;
  el.classList.toggle("busy", on); el.disabled = on;
  el.setAttribute("aria-busy", on ? "true" : "false");
}
function spinnerHTML(label) {
  return '<div class="loading" role="status"><span class="spinner" aria-hidden="true"></span><span>' + label + '</span></div>';
}
// Plain form submits (search) navigate away; show the spinner until the next page paints.
document.addEventListener("submit", e => {
  const f = e.target; if (e.defaultPrevented || f.id === "f") return;
  const b = f.querySelector('button[type="submit"]'); if (!b) return;
  setTimeout(() => { b.classList.add("busy"); b.setAttribute("aria-busy", "true"); }, 0);
});
// Back/forward cache restores the busy state; clear it.
addEventListener("pageshow", () => document.querySelectorAll("button.busy").forEach(b => { b.classList.remove("busy"); b.disabled = false; }));

/** Sticky horizontal scrollbar synced with all `.comprobanteTableMount` (native x-bar stays hidden). */

let wired = false;
let syncing = false;
let boundMounts = [];
let resizeObserver = null;
let barEl = null;
let wrapEl = null;

function allMounts(wrap) {
  return [...wrap.querySelectorAll(".comprobanteTableMount")];
}

function applyScrollLeft(left) {
  if (!wrapEl) return;
  for (const m of allMounts(wrapEl)) {
    m.scrollLeft = left;
  }
}

function onMountScroll(e) {
  if (syncing || !barEl || !wrapEl) return;
  const source = e.currentTarget;
  syncing = true;
  const left = source.scrollLeft;
  for (const m of allMounts(wrapEl)) {
    if (m !== source) m.scrollLeft = left;
  }
  barEl.scrollLeft = left;
  syncing = false;
}

function setBarFromMounts(bar, inner, mounts) {
  if (!bar || !inner) return;
  const need = mounts.some((m) => m.scrollWidth > m.clientWidth + 1);
  if (!need) {
    bar.hidden = true;
    bar.setAttribute("aria-hidden", "true");
    return;
  }
  let maxScrollWidth = 0;
  let refScrollLeft = 0;
  for (const m of mounts) {
    if (m.scrollWidth >= maxScrollWidth) {
      maxScrollWidth = m.scrollWidth;
      refScrollLeft = m.scrollLeft;
    }
  }
  bar.hidden = false;
  bar.setAttribute("aria-hidden", "false");
  inner.style.width = `${maxScrollWidth}px`;
  if (!syncing) {
    syncing = true;
    bar.scrollLeft = refScrollLeft;
    syncing = false;
  }
}

function bindMounts(mounts) {
  for (const m of boundMounts) {
    m.removeEventListener("scroll", onMountScroll);
  }
  boundMounts = mounts.slice();
  for (const m of boundMounts) {
    m.addEventListener("scroll", onMountScroll, { passive: true });
  }
}

export function syncTableHScroll(refs) {
  const bar = refs?.tableHScroll;
  const inner = refs?.tableHScrollInner;
  const wrap = refs?.tableWrap;
  if (!bar || !inner || !wrap) return;
  barEl = bar;
  wrapEl = wrap;

  const mounts = allMounts(wrap);
  bindMounts(mounts);
  setBarFromMounts(bar, inner, mounts);

  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  if (mounts.length && typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(() => {
      setBarFromMounts(bar, inner, allMounts(wrap));
    });
    for (const mount of mounts) {
      resizeObserver.observe(mount);
      const table = mount.querySelector("table");
      if (table) resizeObserver.observe(table);
    }
  }
}

export function wireTableHScroll(refs) {
  if (wired) return;
  const bar = refs?.tableHScroll;
  const wrap = refs?.tableWrap;
  if (!bar || !wrap) return;
  wired = true;
  barEl = bar;
  wrapEl = wrap;

  bar.addEventListener(
    "scroll",
    () => {
      if (syncing || !wrapEl) return;
      syncing = true;
      applyScrollLeft(bar.scrollLeft);
      syncing = false;
    },
    { passive: true }
  );

  const scroller = wrap.closest(".tableScroll");
  scroller?.addEventListener(
    "scroll",
    () => {
      syncTableHScroll(refs);
    },
    { passive: true }
  );

  window.addEventListener("resize", () => syncTableHScroll(refs), { passive: true });
  syncTableHScroll(refs);
}

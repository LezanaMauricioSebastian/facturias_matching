export function captureTableUiState(refs) {
  const wrap = refs?.tableWrap;
  if (!wrap) return null;
  const byComp = {};
  wrap.querySelectorAll(".comprobanteTableMount").forEach((el) => {
    const comp = el.closest(".comprobanteCard")?.getAttribute("data-comp");
    if (comp != null) byComp[comp] = el.scrollLeft;
  });
  const outer = wrap.closest(".tableScroll");
  const active = document.activeElement;
  let focus = null;
  if (active instanceof HTMLElement) {
    const combobox = active.closest(".combobox");
    if (combobox) {
      focus = {
        comp: combobox.closest(".comprobanteCard")?.getAttribute("data-comp"),
        r: combobox.getAttribute("data-r"),
        k: combobox.getAttribute("data-k"),
        kind: "combobox",
        selStart: active.selectionStart,
        selEnd: active.selectionEnd,
      };
    } else if (active.classList.contains("comprobanteFooterInput")) {
      const rateKey = active.getAttribute("data-iva-rate-key");
      focus = {
        comp:
          active.getAttribute("data-comp-footer-iva") || active.getAttribute("data-comp-footer-otros"),
        k: active.hasAttribute("data-comp-footer-iva")
          ? rateKey
            ? `__footer_iva_${rateKey}`
            : "__footer_iva"
          : "__footer_otros",
        kind: "footer-input",
        selStart: active.selectionStart,
        selEnd: active.selectionEnd,
      };
    } else {
      const r = active.getAttribute("data-r");
      const k = active.getAttribute("data-k");
      if (r != null && k) {
        focus = {
          comp: active.closest(".comprobanteCard")?.getAttribute("data-comp"),
          r,
          k,
          kind: active.tagName.toLowerCase(),
          selStart: active.selectionStart,
          selEnd: active.selectionEnd,
        };
      }
    }
  }
  return { outerLeft: outer?.scrollLeft ?? 0, byComp, focus };
}

export function restoreTableUiState(refs, saved) {
  if (!saved) return;
  const wrap = refs?.tableWrap;
  if (!wrap) return;
  const outer = wrap.closest(".tableScroll");
  if (outer) outer.scrollLeft = saved.outerLeft;
  wrap.querySelectorAll(".comprobanteTableMount").forEach((el) => {
    const comp = el.closest(".comprobanteCard")?.getAttribute("data-comp");
    if (comp != null && saved.byComp[comp] != null) el.scrollLeft = saved.byComp[comp];
  });
  const f = saved.focus;
  if (!f?.k) return;
  let el = null;
  const cardSel = f.comp != null
    ? `.comprobanteCard[data-comp="${CSS.escape(String(f.comp))}"] `
    : "";
  if (f.kind === "footer-input") {
    let el = null;
    if (f.k === "__footer_otros") {
      el = wrap.querySelector(
        `${cardSel}input.comprobanteFooterInput[data-comp-footer-otros="${CSS.escape(String(f.comp))}"]`
      );
    } else if (String(f.k || "").startsWith("__footer_iva")) {
      const rateKey = String(f.k).replace("__footer_iva_", "").replace("__footer_iva", "_total");
      const resolvedRate = rateKey === "" ? "_total" : rateKey;
      el = wrap.querySelector(
        `${cardSel}input.comprobanteFooterInput[data-comp-footer-iva="${CSS.escape(String(f.comp))}"][data-iva-rate-key="${CSS.escape(resolvedRate)}"]`
      );
      if (!el && resolvedRate !== "_total") {
        el = wrap.querySelector(
          `${cardSel}input.comprobanteFooterInput[data-comp-footer-iva="${CSS.escape(String(f.comp))}"]`
        );
      }
    }
    if (el instanceof HTMLElement) {
      el.focus({ preventScroll: true });
      if (f.selStart != null && f.selEnd != null && typeof el.setSelectionRange === "function") {
        try {
          el.setSelectionRange(f.selStart, f.selEnd);
        } catch (_) {}
      }
    }
    return;
  } else if (f.kind === "combobox") {
    el = wrap.querySelector(
      `${cardSel}.combobox[data-r="${f.r}"][data-k="${f.k}"] .combobox-input`
    );
  } else if (f.r && f.k) {
    el = wrap.querySelector(`${cardSel}${f.kind}[data-r="${f.r}"][data-k="${f.k}"]`);
  }
  if (!(el instanceof HTMLElement)) return;
  el.focus({ preventScroll: true });
  if (f.selStart != null && f.selEnd != null && typeof el.setSelectionRange === "function") {
    try {
      el.setSelectionRange(f.selStart, f.selEnd);
    } catch (_) {
      /* input type may not support selection */
    }
  }
}

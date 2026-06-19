// Backwards-compatible entry (kept so old URLs don't 404).
// This file might be loaded as a classic script (old HTML) or as a module (new HTML).
// Use dynamic import so it works in both cases.
(function () {
  try {
    import("/js/main.js");
  } catch (e) {
    // If dynamic import isn't supported, fail silently (UI won't work in very old browsers).
    // eslint-disable-next-line no-console
    console.error(e);
  }
})();


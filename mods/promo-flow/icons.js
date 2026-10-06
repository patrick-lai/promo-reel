"use strict";
(function () {
  const P = {
    check: '<path d="M4 10.5l4 4 8-9"/>',
    chevron: '<path d="M5 8l5 5 5-5"/>',
    arrow: '<path d="M4 10h12M11 5l5 5-5 5"/>',
    left: '<path d="M12.5 4l-6 6 6 6"/>',
    right: '<path d="M7.5 4l6 6-6 6"/>',
    play: '<path d="M7 4.5v11l9-5.5z" fill="currentColor" stroke="none"/>',
    pause: '<path d="M6 4.5h3v11H6zM11 4.5h3v11h-3z" fill="currentColor" stroke="none"/>',
    image: '<rect x="3" y="4" width="14" height="12" rx="2"/><circle cx="7.5" cy="8.5" r="1.4"/><path d="M3.5 14.5l4-3.5 3 2.5 2.5-2 3.5 3"/>',
    film: '<rect x="3" y="4" width="14" height="12" rx="2"/><path d="M7 4v12M13 4v12M3 8h4M13 8h4M3 12h4M13 12h4"/>',
    music: '<path d="M8 14.5V5l8-1.5v9.5"/><circle cx="6" cy="14.5" r="2"/><circle cx="14" cy="13" r="2"/>',
    wave: '<path d="M3 10h1.5M6.5 6v8M9.5 3.5v13M12.5 7v6M15.5 8.5v3M17 10h0"/>',
    alert: '<path d="M10 3.5l7.5 13h-15z"/><path d="M10 8.5v3.5M10 14.6v.1"/>',
    offline: '<path d="M3 3l14 14M5.2 8.2A9 9 0 0 1 8 6.7M12 6.7a9 9 0 0 1 4.8 3M7.5 11.6a5 5 0 0 1 2.2-1.1M12.8 11.5a5 5 0 0 0-.6-.6M10 15v.1"/>',
    close: '<path d="M5 5l10 10M15 5L5 15"/>',
    send: '<path d="M3.5 10l13-6-4.5 12-2.5-4.5z"/>',
    link: '<path d="M8.5 5H5a1.5 1.5 0 0 0-1.5 1.5v8A1.5 1.5 0 0 0 5 16h8a1.5 1.5 0 0 0 1.5-1.5V11M11 3.5h5.5V9M16.5 3.5L9 11"/>',
    lock: '<rect x="4.5" y="9" width="11" height="7.5" rx="2"/><path d="M7 9V6.5a3 3 0 0 1 6 0V9"/>',
    list: '<path d="M7 5.5h9M7 10h9M7 14.5h9M3.5 5.5h.1M3.5 10h.1M3.5 14.5h.1"/>',
    clock: '<circle cx="10" cy="10" r="7"/><path d="M10 6v4l2.5 2"/>',
    plus: '<path d="M10 4v12M4 10h12"/>',
    download: '<path d="M10 3.5v9M6 9l4 4 4-4M4 16h12"/>',
    refresh: '<path d="M16 9a6 6 0 1 0-1.4 4.6M16 4v5h-5"/>',
    spark: '<path d="M10 3l1.6 4.4L16 9l-4.4 1.6L10 15l-1.6-4.4L4 9l4.4-1.6z"/>',
    scene: '<rect x="3" y="5" width="14" height="10" rx="2"/><path d="M3 8h14"/>'
  };
  window.icon = function (name, cls) {
    const t = document.createElement("template");
    t.innerHTML = '<svg class="ic' + (cls ? " " + cls : "") + '" viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + (P[name] || "") + "</svg>";
    return t.content.firstChild;
  };
})();

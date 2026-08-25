(function () {
  "use strict";

  var previousFocus = null;
  var mobileSidebar = window.matchMedia("(max-width: 760px)");

  function refreshIcons(root) {
    if (window.lucide) window.lucide.createIcons({ nodes: [root || document] });
  }

  function setSidebar(open) {
    var effectiveOpen = mobileSidebar.matches && open;
    document.body.classList.toggle("sidebar-open", effectiveOpen);
    var sidebar = document.getElementById("app-sidebar");
    var mainView = document.getElementById("main-view");
    if (sidebar) sidebar.toggleAttribute("inert", mobileSidebar.matches && !effectiveOpen);
    if (mainView) mainView.toggleAttribute("inert", effectiveOpen);
  }

  function updateNavigation() {
    document.querySelectorAll("[data-nav-path]").forEach(function (link) {
      var path = link.dataset.navPath;
      var active = location.pathname === path || (path !== "/" && location.pathname.indexOf(path + "/") === 0);
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function updatePageTitle() {
    var mainView = document.getElementById("main-view");
    if (mainView && mainView.dataset.pageTitle) {
      document.title = mainView.dataset.pageTitle + " · Shopping";
    }
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("shopping-theme", theme); } catch (_) {}
    var live = document.getElementById("app-live-region");
    if (live) live.textContent = theme.charAt(0).toUpperCase() + theme.slice(1) + " theme enabled";
  }

  function focusable(container) {
    return Array.from(container.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'));
  }

  function closeDrawer(options) {
    var drawer = document.querySelector("[data-drawer]");
    if (!drawer) return;
    var drawerRoot = document.getElementById("drawer-root");
    if (drawerRoot) drawerRoot.replaceChildren();
    else {
      var layer = drawer.closest(".drawer-layer");
      if (layer) layer.remove();
      else drawer.remove();
    }
    document.body.classList.remove("drawer-open");
    var shell = document.querySelector(".app-shell");
    if (shell) shell.removeAttribute("inert");
    if (!options || options.restoreFocus !== false) {
      if (previousFocus && document.contains(previousFocus)) previousFocus.focus();
    }
    previousFocus = null;
  }

  function openDrawer(drawer) {
    previousFocus = document.activeElement;
    document.body.classList.add("drawer-open");
    var shell = document.querySelector(".app-shell");
    if (shell) shell.setAttribute("inert", "");
    var controls = focusable(drawer);
    if (controls.length) controls[0].focus();
  }

  document.addEventListener("click", function (event) {
    var open = event.target.closest("[data-sidebar-open]");
    var close = event.target.closest("[data-sidebar-close]");
    var theme = event.target.closest("[data-theme-toggle]");
    var drawerClose = event.target.closest("[data-drawer-close]");
    if (open) setSidebar(true);
    if (close) setSidebar(false);
    if (theme) setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    if (drawerClose) {
      event.preventDefault();
      if (history.length > 1) history.back();
      else closeDrawer();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      if (document.querySelector("[data-drawer]")) {
        if (history.length > 1) history.back();
        else closeDrawer();
      } else setSidebar(false);
      return;
    }
    if (event.key !== "Tab") return;
    var container = document.querySelector("[data-drawer]") || (document.body.classList.contains("sidebar-open") && document.getElementById("app-sidebar"));
    if (!container) return;
    var controls = focusable(container);
    if (!controls.length) return;
    var first = controls[0];
    var last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    refreshIcons(event.detail.target);
    if (event.detail.target.id === "main-view") {
      updateNavigation();
      updatePageTitle();
      setSidebar(false);
    }
    var drawer = event.detail.target.querySelector && event.detail.target.querySelector("[data-drawer]");
    if (drawer) openDrawer(drawer);
  });

  document.addEventListener("htmx:responseError", function (event) {
    var live = document.getElementById("app-live-region");
    if (live) live.textContent = "This region could not be refreshed. Existing information was preserved.";
  });

  window.addEventListener("popstate", function () {
    if (location.pathname.indexOf("/orders/") !== 0) closeDrawer();
    updateNavigation();
  });

  document.addEventListener("htmx:historyRestore", function () {
    updateNavigation();
    updatePageTitle();
  });

  mobileSidebar.addEventListener("change", function () {
    setSidebar(false);
  });

  refreshIcons(document);
  updateNavigation();
  setSidebar(false);
})();

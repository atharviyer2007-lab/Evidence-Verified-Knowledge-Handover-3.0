(function () {
  var root = document.documentElement;

  var themeButton = document.getElementById("theme");
  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch (error) { return; }
    });
  }

  var menuToggle = document.getElementById("menu-toggle");
  var mainNav = document.getElementById("main-nav");
  function setMenu(open) {
    if (!menuToggle || !mainNav) { return; }
    mainNav.classList.toggle("is-open", open);
    menuToggle.setAttribute("aria-expanded", String(open));
    menuToggle.setAttribute("aria-label", open ? "Close navigation menu" : "Open navigation menu");
    menuToggle.classList.toggle("is-open", open);
    document.body.classList.toggle("menu-is-open", open);
    if (open) {
      var firstLink = mainNav.querySelector("a, button");
      if (firstLink) { firstLink.focus({ preventScroll: true }); }
    } else {
      menuToggle.focus({ preventScroll: true });
    }
  }
  if (menuToggle && mainNav) {
    menuToggle.addEventListener("click", function () { setMenu(!mainNav.classList.contains("is-open")); });
    mainNav.addEventListener("click", function (event) {
      if (event.target.closest("a")) { setMenu(false); }
    });
    document.addEventListener("click", function (event) {
      if (mainNav.classList.contains("is-open") && !mainNav.contains(event.target) && !menuToggle.contains(event.target)) { setMenu(false); }
    });
    window.addEventListener("resize", function () {
      if (window.matchMedia("(min-width: 761px)").matches && mainNav.classList.contains("is-open")) { setMenu(false); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && mainNav.classList.contains("is-open")) { setMenu(false); }
    });
  }

  var panel = document.getElementById("help-panel");
  var openButton = document.getElementById("help-open");
  var closeButton = document.getElementById("help-close");
  function setHelp(open) {
    panel.hidden = !open;
    openButton.setAttribute("aria-expanded", String(open));
    if (open) { closeButton.focus(); } else { openButton.focus(); }
  }
  openButton.addEventListener("click", function () { setHelp(panel.hidden); });
  closeButton.addEventListener("click", function () { setHelp(false); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) { setHelp(false); }
  });

  var welcome = document.getElementById("welcome-tour");
  if (welcome && welcome.dataset.open === "true") {
    welcome.addEventListener("cancel", function (event) { event.preventDefault(); });
    if (typeof welcome.showModal === "function") { welcome.showModal(); }
    else { welcome.setAttribute("open", ""); }
  }

  document.querySelectorAll("[data-fill-user]").forEach(function (button) {
    button.addEventListener("click", function () {
      document.getElementById("username").value = button.dataset.fillUser;
      document.getElementById("password").value = button.dataset.fillPass;
      document.getElementById("password").focus();
    });
  });

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (form.dataset.confirm && !confirm(form.dataset.confirm)) { event.preventDefault(); }
    });
  });

  document.querySelectorAll(".toast").forEach(function (toast) {
    setTimeout(function () { toast.classList.add("gone"); }, 5000);
  });

  var found = document.getElementById("found");
  if (found && found.textContent) {
    setTimeout(function () { found.scrollIntoView({ block: "center", behavior: "smooth" }); }, 250);
  }

  var back = document.getElementById("back");
  if (back) { back.addEventListener("click", function () { history.back(); }); }

  var print = document.getElementById("print");
  if (print) { print.addEventListener("click", function () { window.print(); }); }

  var copy = document.getElementById("copy");
  if (copy) {
    copy.addEventListener("click", function () {
      var text = document.getElementById(copy.dataset.target).textContent;
      navigator.clipboard.writeText(text).then(function () {
        copy.textContent = "Copied";
      }, function () {
        copy.textContent = "Copy failed. Select the text instead.";
        document.getElementById(copy.dataset.target).hidden = false;
      });
    });
  }

  var tourBox = null;
  var tourSteps = [];
  var tourIndex = 0;
  var tourReturnTarget = null;
  var tourButton = document.getElementById("tour-start");

  function tourTargets() {
    return Array.prototype.filter.call(document.querySelectorAll("[data-tour]"), function (element) {
      return element.offsetParent !== null;
    });
  }

  function clearTourStep() {
    if (tourBox) { tourBox.remove(); tourBox = null; }
    document.querySelectorAll(".tour-target").forEach(function (element) { element.classList.remove("tour-target"); });
  }

  function endTour() {
    clearTourStep();
    var returnTo = tourReturnTarget;
    tourReturnTarget = null;
    if (returnTo && returnTo.isConnected && typeof returnTo.focus === "function") {
      returnTo.focus({ preventScroll: true });
    }
  }

  function positionTour(target, popover) {
    var rect = target.getBoundingClientRect();
    var margin = 8;
    var left = window.scrollX + rect.left;
    left = Math.max(window.scrollX + margin, Math.min(left, window.scrollX + document.documentElement.clientWidth - popover.offsetWidth - margin));
    var roomBelow = window.innerHeight - rect.bottom;
    var top = roomBelow < popover.offsetHeight + 28
      ? window.scrollY + rect.top - popover.offsetHeight - 14
      : window.scrollY + rect.bottom + 14;
    top = Math.max(window.scrollY + margin, top);
    popover.style.left = left + "px";
    popover.style.top = top + "px";
  }

  function showStep() {
    clearTourStep();
    var target = tourSteps[tourIndex];
    target.classList.add("tour-target");
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    tourBox = document.createElement("div");
    tourBox.className = "tour";
    tourBox.setAttribute("role", "dialog");
    tourBox.setAttribute("aria-label", "Guided tour step " + (tourIndex + 1));
    tourBox.innerHTML = '<p class="count"></p><p class="text"></p><div class="acts"></div>';
    tourBox.querySelector(".count").textContent = "Step " + (tourIndex + 1) + " of " + tourSteps.length;
    tourBox.querySelector(".text").textContent = target.dataset.tour;
    var actions = tourBox.querySelector(".acts");
    var last = tourIndex === tourSteps.length - 1;

    var backButton = document.createElement("button");
    backButton.type = "button";
    backButton.className = "btn ghost small";
    backButton.textContent = "Back";
    backButton.disabled = tourIndex === 0;
    backButton.addEventListener("click", function () { if (tourIndex > 0) { tourIndex--; showStep(); } });
    actions.appendChild(backButton);

    var skipButton = document.createElement("button");
    skipButton.type = "button";
    skipButton.className = "btn ghost small";
    skipButton.textContent = "Skip tour";
    skipButton.addEventListener("click", endTour);
    actions.appendChild(skipButton);

    var nextButton = document.createElement("button");
    nextButton.type = "button";
    nextButton.className = "btn small";
    nextButton.textContent = last ? "Finish" : "Next";
    nextButton.addEventListener("click", function () {
      if (last) { endTour(); } else { tourIndex++; showStep(); }
    });
    actions.appendChild(nextButton);

    document.body.appendChild(tourBox);
    var current = tourBox;
    setTimeout(function () {
      if (tourBox !== current) { return; }
      positionTour(target, current);
      nextButton.focus({ preventScroll: true });
    }, 450);
  }

  function startTour() {
    if (tourBox) { endTour(); }
    tourSteps = tourTargets();
    if (!tourSteps.length) { return; }
    tourIndex = 0;
    tourReturnTarget = document.activeElement;
    showStep();
  }

  if (tourButton && tourTargets().length) {
    tourButton.hidden = false;
    tourButton.addEventListener("click", function () { setHelp(false); startTour(); });
  }
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && tourBox) { endTour(); }
  });
  window.addEventListener("resize", function () {
    if (tourBox && tourSteps[tourIndex]) { positionTour(tourSteps[tourIndex], tourBox); }
  });

  var animatedContent = document.querySelectorAll("[data-animated-content], .proof");
  if (animatedContent.length) {
    var reveal = function (element) { element.classList.add("is-visible"); };
    animatedContent.forEach(function (element) { element.classList.add("is-preparing"); });
    if ("IntersectionObserver" in window) {
      var revealObserver = new IntersectionObserver(function (entries, observer) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) { reveal(entry.target); observer.unobserve(entry.target); }
        });
      }, { threshold: 0.1 });
      animatedContent.forEach(function (element) { revealObserver.observe(element); });
    } else { animatedContent.forEach(reveal); }
  }

  var asciiCanvas = document.getElementById("gradient-ascii");
  if (asciiCanvas && !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) {
    var ctx = asciiCanvas.getContext("2d", { alpha: true });
    var ascii = asciiCanvas.dataset.characters || " =+xX0S8#@";
    var palette = (asciiCanvas.dataset.colors || "#1e3fd8,#f6f8ff,#a5d8ff,#38bdf8").split(",");
    var cell = Number(asciiCanvas.dataset.cellSize) || 18;
    var density = Number(asciiCanvas.dataset.density) || 0.8;
    var flow = Number(asciiCanvas.dataset.flow) || 0.5;
    var speed = Number(asciiCanvas.dataset.speed) || 1;
    var flicker = Number(asciiCanvas.dataset.flicker) || 0.2;
    var grain = Number(asciiCanvas.dataset.grain) || 0.08;
    var mouse = { x: 0.5, y: 0.45, targetX: 0.5, targetY: 0.45 };
    var waves = [];
    var start = performance.now();
    var lastFrame = 0;
    function resizeAscii() {
      var rect = asciiCanvas.getBoundingClientRect();
      var ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      asciiCanvas.width = Math.max(1, Math.floor(rect.width * ratio));
      asciiCanvas.height = Math.max(1, Math.floor(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }
    function hexToRgb(hex) {
      var value = hex.replace("#", "");
      if (value.length === 3) { value = value.split("").map(function (c) { return c + c; }).join(""); }
      var number = parseInt(value, 16);
      return { r: number >> 16 & 255, g: number >> 8 & 255, b: number & 255 };
    }
    var colors = palette.map(hexToRgb);
    function colorAt(value) {
      var scaled = Math.max(0, Math.min(0.999, value)) * (colors.length - 1);
      var index = Math.floor(scaled);
      var mix = scaled - index;
      var a = colors[index]; var b = colors[Math.min(index + 1, colors.length - 1)];
      return "rgb(" + Math.round(a.r + (b.r - a.r) * mix) + "," + Math.round(a.g + (b.g - a.g) * mix) + "," + Math.round(a.b + (b.b - a.b) * mix) + ")";
    }
    function renderAscii(now) {
      if (now - lastFrame < 32) { requestAnimationFrame(renderAscii); return; }
      lastFrame = now;
      var rect = asciiCanvas.getBoundingClientRect();
      var width = rect.width; var height = rect.height;
      var columns = Math.ceil(width / cell); var rows = Math.ceil(height / cell);
      var time = (now - start) * 0.001 * speed;
      mouse.x += (mouse.targetX - mouse.x) * 0.06; mouse.y += (mouse.targetY - mouse.y) * 0.06;
      ctx.clearRect(0, 0, width, height);
      ctx.font = Math.max(10, cell * 0.78) + "px ui-monospace, SFMono-Regular, Menlo, monospace";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      for (var row = 0; row < rows; row++) {
        for (var column = 0; column < columns; column++) {
          var x = column / Math.max(1, columns - 1); var y = row / Math.max(1, rows - 1);
          var horizon = Math.exp(-Math.pow((y - (0.48 + Math.sin(x * 4 + time * flow) * 0.07)) * 4.2, 2));
          var radial = Math.exp(-Math.pow(Math.hypot(x - mouse.x, y - mouse.y) * 2.3, 2));
          var wave = 0;
          waves.forEach(function (item) {
            var distance = Math.hypot(x - item.x, y - item.y);
            wave += Math.max(0, 1 - Math.abs(distance - item.radius) * 18) * Math.max(0, 1 - item.age);
          });
          var value = Math.max(0, Math.min(1, horizon * 0.7 + radial * 0.25 + wave * 0.5 + (Math.sin((x * 13 + y * 9) + time * flow) + 1) * 0.04));
          var charIndex = Math.min(ascii.length - 1, Math.floor(value * density * ascii.length));
          if (charIndex <= 0 && value < 0.16) { continue; }
          var opacity = Math.min(0.9, 0.22 + value * 0.7 + Math.sin(time * 5 + column * 0.4 + row) * flicker * 0.12);
          if (Math.random() < grain * 0.035) { opacity *= 0.35; }
          ctx.fillStyle = colorAt(value);
          ctx.globalAlpha = Math.max(0.08, opacity);
          ctx.fillText(ascii[charIndex], column * cell + cell / 2, row * cell + cell / 2);
        }
      }
      ctx.globalAlpha = 1;
      waves = waves.filter(function (item) { item.radius += 0.012; item.age += 0.018; return item.age < 1; });
      requestAnimationFrame(renderAscii);
    }
    resizeAscii();
    window.addEventListener("resize", resizeAscii);
    asciiCanvas.addEventListener("pointermove", function (event) {
      var rect = asciiCanvas.getBoundingClientRect();
      mouse.targetX = (event.clientX - rect.left) / rect.width;
      mouse.targetY = (event.clientY - rect.top) / rect.height;
    });
    asciiCanvas.addEventListener("pointerleave", function () { mouse.targetX = 0.5; mouse.targetY = 0.45; });
    asciiCanvas.addEventListener("click", function (event) {
      var rect = asciiCanvas.getBoundingClientRect();
      waves.push({ x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height, radius: 0, age: 0 });
    });
    requestAnimationFrame(renderAscii);
  }

  if (document.body.dataset.startTour === "true") {
    setTimeout(startTour, 350);
  }
})();

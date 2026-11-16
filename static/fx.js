/* Handover motion and polish. Every effect is optional: if anything here fails, the pages keep working. */
(function () {
  "use strict";
  var root = document.documentElement;
  var reduce = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var finePointer = !!(window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches);
  function safe(fn) { try { fn(); } catch (error) { /* decoration must never break the app */ } }
  root.classList.add("fx");

  /* reading progress bar, plus a sweep while the next page loads */
  safe(function () {
    var bar = document.createElement("div");
    bar.className = "fx-progress"; bar.setAttribute("aria-hidden", "true");
    document.body.appendChild(bar);
    var waiting = false;
    function update() {
      var height = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.setProperty("--p", (height > 0 ? Math.min(1, window.scrollY / height) : 0).toFixed(4));
      waiting = false;
    }
    window.addEventListener("scroll", function () { if (!waiting) { waiting = true; requestAnimationFrame(update); } }, { passive: true });
    window.addEventListener("resize", update);
    update();
    document.addEventListener("click", function (event) {
      var link = event.target.closest && event.target.closest("a[href]");
      if (!link || event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.button) { return; }
      if (link.target || link.hasAttribute("download") || link.origin !== location.origin || /\/export\./.test(link.pathname)) { return; }
      if (link.pathname + link.search === location.pathname + location.search) { return; }
      bar.classList.add("is-loading");
      setTimeout(function () { bar.classList.remove("is-loading"); }, 8000);
    });
    window.addEventListener("pageshow", function () { bar.classList.remove("is-loading"); });
  });

  /* cursor spotlight on cards, rows and claims */
  safe(function () {
    if (reduce || !finePointer) { return; }
    var selector = ".rows > li, .cards .card, .claim, .card, .panel";
    var active = null;
    document.addEventListener("pointerover", function (event) {
      var host = event.target.closest && event.target.closest(selector);
      if (!host || host.querySelector(":scope > .fx-glow")) { return; }
      if (getComputedStyle(host).position === "static") { host.classList.add("fx-host"); }
      else { host.classList.add("fx-host"); }
      var glow = document.createElement("span");
      glow.className = "fx-glow"; glow.setAttribute("aria-hidden", "true");
      host.appendChild(glow);
    });
    document.addEventListener("pointermove", function (event) {
      var host = event.target.closest && event.target.closest(selector);
      if (!host || !host.classList.contains("fx-host")) { return; }
      if (active) { return; }
      active = requestAnimationFrame(function () {
        var rect = host.getBoundingClientRect();
        host.style.setProperty("--mx", (event.clientX - rect.left) + "px");
        host.style.setProperty("--my", (event.clientY - rect.top) + "px");
        active = null;
      });
    }, { passive: true });
  });

  /* button ripple */
  safe(function () {
    if (reduce) { return; }
    document.addEventListener("pointerdown", function (event) {
      var button = event.target.closest && event.target.closest(".btn");
      if (!button || button.disabled || event.button) { return; }
      var rect = button.getBoundingClientRect();
      var ripple = document.createElement("span");
      ripple.className = "fx-ripple"; ripple.setAttribute("aria-hidden", "true");
      ripple.style.left = (event.clientX - rect.left) + "px";
      ripple.style.top = (event.clientY - rect.top) + "px";
      button.appendChild(ripple);
      setTimeout(function () { ripple.remove(); }, 700);
    });
  });

  /* numbers count up once, then settle on exactly the text the server wrote */
  safe(function () {
    var items = document.querySelectorAll("[data-countup]");
    if (!items.length || reduce || !("IntersectionObserver" in window)) { return; }
    function run(element) {
      var original = element.textContent;
      var match = original.match(/\d+/);
      if (!match) { return; }
      var target = parseInt(match[0], 10);
      if (!target) { return; }
      var begin = null;
      function frame(now) {
        if (begin === null) { begin = now; }
        var t = Math.min(1, (now - begin) / 900);
        var value = Math.round(target * (1 - Math.pow(1 - t, 3)));
        element.textContent = original.replace(match[0], String(value));
        if (t < 1) { requestAnimationFrame(frame); } else { element.textContent = original; }
      }
      element.textContent = original.replace(match[0], "0");
      requestAnimationFrame(frame);
    }
    var seen = new IntersectionObserver(function (entries, observer) {
      entries.forEach(function (entry) { if (entry.isIntersecting) { observer.unobserve(entry.target); run(entry.target); } });
    }, { threshold: 0.4 });
    items.forEach(function (element) { seen.observe(element); });
  });

  /* confetti: a short burst for a real achievement, once per page and session */
  function confetti() {
    if (reduce) { return; }
    var canvas = document.createElement("canvas");
    canvas.className = "fx-confetti"; canvas.setAttribute("aria-hidden", "true");
    document.body.appendChild(canvas);
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = window.innerWidth * ratio; canvas.height = window.innerHeight * ratio;
    var ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    var colours = ["#ff2f82", "#ffb86b", "#5ce1e6", "#8b7bff", "#3ddc97", "#ffffff"];
    var pieces = [];
    for (var i = 0; i < 110; i++) {
      var angle = -Math.PI / 2 + (Math.random() - 0.5) * 1.5;
      var speed = 7 + Math.random() * 9;
      pieces.push({ x: window.innerWidth / 2, y: window.innerHeight * 0.62, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
        size: 5 + Math.random() * 6, spin: Math.random() * 6, vs: (Math.random() - 0.5) * 0.4, colour: colours[i % colours.length], round: Math.random() < 0.3 });
    }
    var start = null;
    function tick(now) {
      if (start === null) { start = now; }
      var age = (now - start) / 1000;
      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
      pieces.forEach(function (p) {
        p.vy += 0.32; p.vx *= 0.992; p.x += p.vx; p.y += p.vy; p.spin += p.vs;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.spin);
        ctx.globalAlpha = Math.max(0, 1 - Math.max(0, age - 1.4) / 0.9);
        ctx.fillStyle = p.colour;
        if (p.round) { ctx.beginPath(); ctx.arc(0, 0, p.size / 2, 0, 6.3); ctx.fill(); } else { ctx.fillRect(-p.size / 2, -p.size / 3, p.size, p.size * 0.66); }
        ctx.restore();
      });
      if (age < 2.4) { requestAnimationFrame(tick); } else { canvas.remove(); }
    }
    requestAnimationFrame(tick);
  }
  window.fx = { confetti: confetti };
  safe(function () {
    var mark = document.querySelector("[data-celebrate]");
    if (!mark) { return; }
    var key = "celebrated:" + location.pathname;
    try { if (sessionStorage.getItem(key)) { return; } sessionStorage.setItem(key, "1"); } catch (error) { /* still celebrate */ }
    setTimeout(confetti, 350);
  });

  /* forms: show that something is happening and refuse a second click */
  safe(function () {
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!form || form.tagName !== "FORM" || event.defaultPrevented) { return; }
      if (form.dataset.fxSubmitting === "1") { event.preventDefault(); return; }
      form.dataset.fxSubmitting = "1";
      var button = event.submitter || form.querySelector("button[type=submit], button:not([type])");
      if (button && button.classList.contains("btn")) {
        button.classList.add("is-busy"); button.setAttribute("aria-busy", "true");
        var spinner = document.createElement("span");
        spinner.className = "fx-spinner"; spinner.setAttribute("aria-hidden", "true");
        button.insertBefore(spinner, button.firstChild);
      }
      setTimeout(function () {
        form.dataset.fxSubmitting = "0";
        if (button) { button.classList.remove("is-busy"); button.removeAttribute("aria-busy"); var s = button.querySelector(".fx-spinner"); if (s) { s.remove(); } }
      }, 12000);
    });
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) { return; }
      document.querySelectorAll("form[data-fx-submitting='1']").forEach(function (form) { form.dataset.fxSubmitting = "0"; });
      document.querySelectorAll(".btn.is-busy").forEach(function (b) { b.classList.remove("is-busy"); b.removeAttribute("aria-busy"); var s = b.querySelector(".fx-spinner"); if (s) { s.remove(); } });
    });
  });

  /* section check: a live "3 of 5 answered" bar */
  safe(function () {
    var form = document.querySelector("main form fieldset") && document.querySelector("main form fieldset").closest("form");
    if (!form) { return; }
    var groups = form.querySelectorAll("fieldset");
    var holder = document.createElement("div");
    holder.className = "fx-quiz-progress"; holder.setAttribute("role", "status"); holder.setAttribute("aria-live", "polite");
    holder.innerHTML = '<span></span><div class="track" aria-hidden="true"><i class="fill testimony" style="--w: 0%"></i></div>';
    groups[0].parentNode.insertBefore(holder, groups[0]);
    var label = holder.querySelector("span"), fill = holder.querySelector(".fill");
    function refresh() {
      var done = 0;
      groups.forEach(function (group) { if (group.querySelector("input:checked")) { done++; } });
      label.textContent = done + " of " + groups.length + " answered";
      fill.style.setProperty("--w", Math.round(100 * done / groups.length) + "%");
      fill.style.animation = "none";
    }
    form.addEventListener("change", refresh);
    refresh();
  });

  /* back to top */
  safe(function () {
    var button = document.createElement("button");
    button.type = "button"; button.className = "fx-top"; button.setAttribute("aria-label", "Back to top");
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
    document.body.appendChild(button);
    var waiting = false;
    window.addEventListener("scroll", function () {
      if (waiting) { return; }
      waiting = true;
      requestAnimationFrame(function () { button.classList.toggle("is-visible", window.scrollY > 700); waiting = false; });
    }, { passive: true });
    button.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" }); });
  });

  /* the theme switch expands from the button */
  safe(function () {
    var toggle = document.getElementById("theme");
    if (!toggle) { return; }
    toggle.addEventListener("click", function (event) {
      if (reduce) { return; }
      var rect = toggle.getBoundingClientRect();
      root.style.setProperty("--tx", Math.round(rect.left + rect.width / 2) + "px");
      root.style.setProperty("--ty", Math.round(rect.top + rect.height / 2) + "px");
      if (typeof document.startViewTransition === "function") {
        event.stopImmediatePropagation();
        root.classList.add("fx-vt-theme");
        var next = root.dataset.theme === "dark" ? "light" : "dark";
        var transition = document.startViewTransition(function () { root.dataset.theme = next; });
        try { localStorage.setItem("theme", next); } catch (error) { /* theme still changes */ }
        transition.finished.then(function () { root.classList.remove("fx-vt-theme"); }, function () { root.classList.remove("fx-vt-theme"); });
      } else {
        root.classList.add("fx-themeing");
        setTimeout(function () { root.classList.remove("fx-themeing"); }, 450);
      }
    }, true);
  });

  /* hero parallax */
  safe(function () {
    var hero = document.querySelector(".hero");
    if (!hero || reduce || !finePointer) { return; }
    var waiting = false;
    hero.addEventListener("pointermove", function (event) {
      if (waiting) { return; }
      waiting = true;
      requestAnimationFrame(function () {
        var rect = hero.getBoundingClientRect();
        hero.style.setProperty("--px", (((event.clientX - rect.left) / rect.width) - 0.5).toFixed(3));
        hero.style.setProperty("--py", (((event.clientY - rect.top) / rect.height) - 0.5).toFixed(3));
        waiting = false;
      });
    }, { passive: true });
    hero.addEventListener("pointerleave", function () { hero.style.setProperty("--px", 0); hero.style.setProperty("--py", 0); });
  });

  /* press / to jump to search */
  safe(function () {
    document.addEventListener("keydown", function (event) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) { return; }
      var t = event.target;
      if (t && (/^(input|textarea|select)$/i.test(t.tagName) || t.isContentEditable)) { return; }
      var search = document.querySelector("main input[type=search], main .search input");
      if (search) { event.preventDefault(); search.focus(); }
    });
  });
})();

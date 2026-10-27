/* Interactive extras for the dashboard. Everything here is optional polish:
 * the page works the same if this file fails to load, and nothing animates when the user asks for reduced motion.
 * It only observes the DOM (no changes to the app's own code) and never throws into the page.
 */
(function () {
  "use strict";

  var reduceQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

  function prefersReduced() {
    return Boolean(reduceQuery && reduceQuery.matches);
  }

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function $all(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function observe(element, options, callback) {
    if (!element || typeof MutationObserver === "undefined") {
      return null;
    }
    var observer = new MutationObserver(callback);
    observer.observe(element, options);
    return observer;
  }

  /* Re-run a CSS animation by toggling its class, then clean the class up. */
  function restart(element, className, cleanupMs) {
    element.classList.remove(className);
    void element.offsetWidth; // force reflow so the animation starts again
    element.classList.add(className);
    window.setTimeout(function () {
      element.classList.remove(className);
    }, cleanupMs || 900);
  }

  /* ---------- confetti burst ---------- */
  var CONFETTI_COLORS = ["#1d9e75", "#2d7ff9", "#f2b84b", "#e8638a", "#7a6cf2"];

  function confetti(anchor) {
    if (prefersReduced() || !anchor || typeof anchor.getBoundingClientRect !== "function" || !document.body.animate) {
      return;
    }
    var rect = anchor.getBoundingClientRect();
    var originX = rect.left + Math.min(rect.width, 160) / 2;
    var originY = rect.top + rect.height / 2;
    for (var i = 0; i < 16; i += 1) {
      var piece = document.createElement("span");
      piece.className = "m-confetti";
      piece.setAttribute("aria-hidden", "true");
      piece.style.left = originX + "px";
      piece.style.top = originY + "px";
      piece.style.background = CONFETTI_COLORS[i % CONFETTI_COLORS.length];
      document.body.appendChild(piece);

      // Burst outward fast, hang there fully visible, then drift down and fade (gravity).
      var angle = (Math.PI * 2 * i) / 16 + Math.random() * 0.4;
      var distance = 60 + Math.random() * 80;
      var burstX = Math.cos(angle) * distance;
      var burstY = Math.sin(angle) * distance - 20;
      var spin = Math.random() * 540 - 270;
      var animation = piece.animate(
        [
          { transform: "translate(0, 0) rotate(0deg) scale(0.6)", opacity: 1, offset: 0 },
          {
            transform: "translate(" + burstX + "px, " + burstY + "px) rotate(" + spin / 2 + "deg) scale(1.15)",
            opacity: 1,
            offset: 0.35,
            easing: "ease-in",
          },
          {
            transform: "translate(" + burstX * 1.15 + "px, " + (burstY + 90) + "px) rotate(" + spin + "deg) scale(0.7)",
            opacity: 0,
            offset: 1,
          },
        ],
        { duration: 1300 + Math.random() * 400, easing: "cubic-bezier(0.15, 0.85, 0.3, 1)" }
      );
      animation.onfinish = (function (node) {
        return function () {
          node.remove();
        };
      })(piece);
    }
  }

  /* ---------- status line: pop on update, shake on error, tick + confetti on success ---------- */
  function watchStatus() {
    var status = document.getElementById("status");
    var last = "";
    observe(status, { childList: true, characterData: true, subtree: true }, function () {
      var text = status.textContent.trim();
      if (!text || text === last) {
        return;
      }
      last = text;
      var isError = status.classList.contains("error");
      var isSuccess = !isError && /completed successfully|masked successfully/i.test(text);
      status.classList.toggle("m-success", isSuccess);
      if (prefersReduced()) {
        return;
      }
      restart(status, isError ? "m-shake" : "m-pop", 700);
      if (isSuccess) {
        confetti(status);
      }
    });
  }

  /* ---------- KPI numbers count up ---------- */
  var NUMBER_PATTERN = /^(\d+(?:\.\d+)?)(\D.*)?$/;

  function watchKpis() {
    $all(".kpi strong").forEach(function (element) {
      var firstMatch = NUMBER_PATTERN.exec(element.textContent.trim());
      var shown = firstMatch ? parseFloat(firstMatch[1]) : null;
      var frame = 0;
      var ownWrite = false;

      function write(text) {
        ownWrite = true;
        element.textContent = text;
        // The observer callback for this write runs as a microtask queued before this one.
        Promise.resolve().then(function () {
          ownWrite = false;
        });
      }

      observe(element, { childList: true, characterData: true, subtree: true }, function () {
        if (ownWrite) {
          return;
        }
        var match = NUMBER_PATTERN.exec(element.textContent.trim());
        if (!match) {
          shown = null;
          return;
        }
        var target = parseFloat(match[1]);
        var suffix = match[2] || "";
        var decimals = (match[1].split(".")[1] || "").length;
        if (shown === null || shown === target || prefersReduced()) {
          shown = target;
          return;
        }

        window.cancelAnimationFrame(frame);
        var from = shown;
        var startedAt = null;
        var card = element.closest(".kpi");
        if (card) {
          restart(card, "m-bump", 600);
        }
        write(from.toFixed(decimals) + suffix); // no flash of the final value before the first frame

        function step(now) {
          if (startedAt === null) {
            startedAt = now;
          }
          var progress = Math.min(1, (now - startedAt) / 700);
          var eased = 1 - Math.pow(1 - progress, 3);
          write((from + (target - from) * eased).toFixed(decimals) + suffix);
          if (progress < 1) {
            frame = window.requestAnimationFrame(step);
          } else {
            shown = target;
          }
        }
        frame = window.requestAnimationFrame(step);
      });
    });
  }

  /* ---------- small touches ---------- */
  function watchFilePill() {
    var pill = document.getElementById("selected-file");
    observe(pill, { childList: true, characterData: true, subtree: true }, function () {
      if (!prefersReduced()) {
        restart(pill, "m-pop", 600);
      }
    });
  }

  function watchPreviewReveal() {
    var after = document.getElementById("preview-after");
    observe(after, { attributes: true, attributeFilter: ["src"] }, function () {
      if (!prefersReduced()) {
        restart(after, "m-wipe", 1000);
      }
    });
  }

  /* ---------- pointer effects: KPI spotlight and button ripple ---------- */
  function wirePointerEffects() {
    var latest = null;
    var queued = false;
    document.addEventListener(
      "pointermove",
      function (event) {
        var card = event.target && event.target.closest ? event.target.closest(".kpi") : null;
        if (!card || prefersReduced()) {
          return;
        }
        latest = { card: card, x: event.clientX, y: event.clientY };
        if (queued) {
          return;
        }
        queued = true;
        window.requestAnimationFrame(function () {
          queued = false;
          if (!latest) {
            return;
          }
          var rect = latest.card.getBoundingClientRect();
          latest.card.style.setProperty("--mx", latest.x - rect.left + "px");
          latest.card.style.setProperty("--my", latest.y - rect.top + "px");
          latest = null;
        });
      },
      { passive: true }
    );

    document.addEventListener(
      "pointerdown",
      function (event) {
        if (prefersReduced() || !event.target || !event.target.closest) {
          return;
        }
        var target = event.target.closest("button:not(:disabled):not(.tab-link), a.signout-btn, a.download");
        if (!target) {
          return;
        }
        var rect = target.getBoundingClientRect();
        var size = Math.max(rect.width, rect.height) * 2;
        var wave = document.createElement("span");
        wave.className = "m-ripple";
        wave.setAttribute("aria-hidden", "true");
        wave.style.width = wave.style.height = size + "px";
        wave.style.left = event.clientX - rect.left - size / 2 + "px";
        wave.style.top = event.clientY - rect.top - size / 2 + "px";

        if (window.getComputedStyle(target).position === "static") {
          target.style.position = "relative";
        }
        target.classList.add("m-rippling");
        target.appendChild(wave);
        window.setTimeout(function () {
          wave.remove();
          if (!target.querySelector(".m-ripple")) {
            target.classList.remove("m-rippling");
          }
        }, 650);
      },
      { passive: true }
    );
  }

  function init() {
    try {
      watchStatus();
      watchKpis();
      watchFilePill();
      watchPreviewReveal();
      wirePointerEffects();
    } catch (error) {
      // Motion is decoration; never let it break the app.
      if (window.console && console.warn) {
        console.warn("motion.js disabled:", error);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

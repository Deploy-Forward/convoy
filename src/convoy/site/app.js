(function () {
  document.documentElement.classList.add("js");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const revealNodes = Array.from(document.querySelectorAll("[data-reveal]"));

  revealNodes.forEach((node, index) => {
    const attrDelay = node.getAttribute("data-reveal-delay");
    const delay = attrDelay === null ? index * 0.06 : Number(attrDelay) * 0.06;
    const duration = 0.35 + (index % 4) * 0.06;
    const shiftY = 4 + (index % 4) * 4;
    node.style.setProperty("--reveal-delay", `${delay.toFixed(2)}s`);
    node.style.setProperty("--reveal-duration", `${Math.min(duration, 0.55).toFixed(2)}s`);
    node.style.setProperty("--reveal-y", `${shiftY}px`);
  });

  function activateReveal(node) {
    node.classList.add("is-inview");
  }

  function isInitiallyVisible(node) {
    const rect = node.getBoundingClientRect();
    return rect.top < window.innerHeight && rect.bottom > 0;
  }

  function bootReveal() {
    if (!revealNodes.length || reducedMotion || !("IntersectionObserver" in window)) {
      revealNodes.forEach(activateReveal);
      return;
    }

    for (const node of revealNodes) {
      if (isInitiallyVisible(node)) {
        activateReveal(node);
      }
    }

    document.body.classList.add("reveal-ready");

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            activateReveal(entry.target);
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0, rootMargin: "0px 0px 0px 0px" }
    );
    revealNodes.forEach((node) => {
      if (!node.classList.contains("is-inview")) {
        observer.observe(node);
      }
    });
  }

  function bootPointerFollow() {
    const hero = document.querySelector(".hero");
    const mock = document.querySelector(".hero-mock");
    if (!hero || !mock || reducedMotion) {
      return;
    }
    const canHover = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (!canHover) {
      return;
    }
    let raf = 0;
    let mx = 0;
    let my = 0;
    const update = () => {
      raf = 0;
      mock.style.setProperty("--mock-x", `${mx}px`);
      mock.style.setProperty("--mock-y", `${my}px`);
    };
    hero.addEventListener("pointermove", (event) => {
      const rect = hero.getBoundingClientRect();
      const dx = (event.clientX - rect.left) / rect.width - 0.5;
      const dy = (event.clientY - rect.top) / rect.height - 0.5;
      mx = Math.max(-4, Math.min(4, dx * 8));
      my = Math.max(-3, Math.min(3, dy * 6));
      if (!raf) {
        raf = window.requestAnimationFrame(update);
      }
    });
    hero.addEventListener("pointerleave", () => {
      mx = 0;
      my = 0;
      if (!raf) {
        raf = window.requestAnimationFrame(update);
      }
    });
  }

  const copyButton = document.getElementById("copy-attach");
  const status = document.getElementById("copy-status");
  if (copyButton) {
    copyButton.addEventListener("click", async () => {
      const text = copyButton.getAttribute("data-copy-text") || "";
      if (!text) {
        return;
      }
      try {
        await navigator.clipboard.writeText(text);
        if (status) {
          status.textContent = "Copied attach URL.";
        }
      } catch (_err) {
        if (status) {
          status.textContent = "Copy failed. URL is shown above.";
        }
      }
    });
  }

  window.requestAnimationFrame(() => {
    bootReveal();
    bootPointerFollow();
  });
})();

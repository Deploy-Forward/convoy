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

  function bootHeroAtmosphere() {
    const hero = document.querySelector(".hero");
    if (!hero || reducedMotion) {
      return;
    }
    if (!("IntersectionObserver" in window)) {
      hero.classList.add("is-active");
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          hero.classList.toggle("is-active", entry.isIntersecting);
        }
      },
      { threshold: 0, rootMargin: "0px 0px 0px 0px" }
    );
    observer.observe(hero);
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
    bootHeroAtmosphere();
  });
})();

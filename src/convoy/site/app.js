(function () {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const revealNodes = Array.from(document.querySelectorAll("[data-reveal]"));

  for (const node of revealNodes) {
    const delay = Number(node.getAttribute("data-reveal-delay") || "0");
    node.style.setProperty("--reveal-delay", `${delay * 90}ms`);
  }

  function activateReveal(node) {
    node.classList.add("is-inview");
  }

  function bootReveal() {
    document.body.classList.add("is-ready");
    if (reducedMotion || !("IntersectionObserver" in window)) {
      revealNodes.forEach(activateReveal);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            activateReveal(entry.target);
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.16, rootMargin: "0px 0px -8% 0px" }
    );
    revealNodes.forEach((node) => observer.observe(node));
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

  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(bootReveal);
  } else {
    window.requestAnimationFrame(bootReveal);
  }
})();

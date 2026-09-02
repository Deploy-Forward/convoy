(function () {
  document.documentElement.classList.add("js");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const revealNodes = Array.from(document.querySelectorAll("[data-reveal]"));
  let wireToolsCache = null;

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

  function schemaHints(schema) {
    if (!schema || typeof schema !== "object") {
      return "inputs: unknown";
    }
    const props = schema.properties && typeof schema.properties === "object" ? Object.keys(schema.properties) : [];
    const required = Array.isArray(schema.required) ? schema.required : [];
    if (!props.length) {
      return "inputs: none";
    }
    if (!required.length) {
      return `inputs: ${props.length}`;
    }
    return `required: ${required.join(", ")}`;
  }

  function parseTools(payload) {
    if (!payload || typeof payload !== "object") {
      throw new Error("invalid JSON-RPC payload");
    }
    if (payload.error && typeof payload.error === "object") {
      throw new Error(String(payload.error.message || "JSON-RPC error"));
    }
    const result = payload.result;
    if (!result || typeof result !== "object" || !Array.isArray(result.tools)) {
      throw new Error("tools/list missing result.tools");
    }
    return result.tools;
  }

  async function postRpc(method, id, params) {
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
    };
    const response = await fetch("/mcp", {
      method: "POST",
      headers,
      body: JSON.stringify({
        jsonrpc: "2.0",
        id,
        method,
        params: params || {},
      }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const json = await response.json();
    return { json, headers: response.headers };
  }

  async function fetchWireTools() {
    if (wireToolsCache) {
      return wireToolsCache;
    }
    const list = await postRpc("tools/list", "site-tools-list", {});
    const tools = parseTools(list.json);
    wireToolsCache = tools;
    return tools;
  }

  function renderWireTools(tools) {
    const status = document.getElementById("wire-live-status");
    const list = document.getElementById("wire-live-list");
    if (!status || !list) {
      return;
    }
    list.replaceChildren();
    if (!tools.length) {
      status.textContent = "couldn't read the wire: tools/list returned no tools";
      return;
    }
    status.textContent = `live tools/list: ${tools.length} verbs`;
    for (const tool of tools) {
      const item = document.createElement("li");
      item.className = "wire-live-item";

      const head = document.createElement("div");
      head.className = "wire-live-item-head";

      const name = document.createElement("span");
      name.className = "wire-live-name";
      name.textContent = String(tool.name || "unknown");

      const hints = document.createElement("span");
      hints.className = "wire-live-hints";
      hints.textContent = schemaHints(tool.inputSchema);

      const desc = document.createElement("p");
      desc.className = "wire-live-desc";
      desc.textContent = String(tool.description || "No description on wire.");

      head.append(name, hints);
      item.append(head, desc);
      list.append(item);
    }
  }

  async function bootWireTools() {
    const status = document.getElementById("wire-live-status");
    const list = document.getElementById("wire-live-list");
    if (!status || !list) {
      return;
    }
    status.textContent = "reading the wire…";
    try {
      const tools = await fetchWireTools();
      renderWireTools(tools);
    } catch (_err) {
      list.replaceChildren();
      status.textContent = "couldn't read the wire";
    }
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
  bootWireTools();
})();

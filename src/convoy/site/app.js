(function () {
  document.documentElement.classList.add("js");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
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
    if (!revealNodes.length || reduce || !("IntersectionObserver" in window)) {
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

  function mosaic(canvasId, ramp, alphaBase, alphaSpan, interactive) {
    const hero = document.querySelector(".hero");
    const canvas = document.getElementById(canvasId);
    if (!hero || !canvas || !canvas.getContext) {
      return;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    const CELL = 17;
    const GAP = 5;
    const STEP = 22;
    const MAX_DEPTH = 3;
    const SPARK_DELAY = 70;
    const SPARK_DECAY = 0.26;
    const SPARK_INTERVAL = 520;
    const SPARK_MIN = 0.85;
    const SPARK_MAX = 1.0;

    let rows = 0;
    let cols = 0;
    let cells = [];
    let intervalId = 0;
    let resizeTimer = 0;
    let pointerTicking = false;
    let pointerCell = null;

    function clamp01(value) {
      return Math.max(0, Math.min(1, value));
    }

    function at(col, row) {
      return row * cols + col;
    }

    function inBounds(col, row) {
      return col >= 0 && row >= 0 && col < cols && row < rows;
    }

    function mixColor(level) {
      const scaled = clamp01(level) * (ramp.length - 1);
      const i0 = Math.floor(scaled);
      const i1 = Math.min(ramp.length - 1, i0 + 1);
      const t = scaled - i0;
      const from = ramp[i0];
      const to = ramp[i1];
      return [
        Math.round(from[0] + (to[0] - from[0]) * t),
        Math.round(from[1] + (to[1] - from[1]) * t),
        Math.round(from[2] + (to[2] - from[2]) * t),
      ];
    }

    function paint() {
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      for (let row = 0; row < rows; row += 1) {
        for (let col = 0; col < cols; col += 1) {
          const cell = cells[at(col, row)];
          if (!cell) {
            continue;
          }
          if (reduce) {
            cell.lvl = cell.target;
          } else {
            cell.lvl += (cell.target - cell.lvl) * 0.2;
            cell.target += (cell.base - cell.target) * 0.06;
          }
          const level = clamp01(cell.lvl);
          if (level <= 0.001) {
            continue;
          }
          const rgb = mixColor(level);
          const alpha = clamp01(alphaBase + alphaSpan * level);
          ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha.toFixed(4)})`;
          ctx.fillRect(col * STEP, row * STEP, CELL, CELL);
        }
      }
    }

    function igniteCell(col, row, depth, strength) {
      if (!inBounds(col, row)) {
        return;
      }
      const cell = cells[at(col, row)];
      if (!cell) {
        return;
      }

      const level = clamp01(strength);
      if (level > cell.target) {
        cell.target = level;
      }
      if (reduce) {
        cell.lvl = cell.target;
        paint();
      }

      if (depth <= 0) {
        return;
      }
      const nextStrength = clamp01(level - SPARK_DECAY);
      if (nextStrength <= 0) {
        return;
      }
      window.setTimeout(() => {
        igniteCell(col + 1, row, depth - 1, nextStrength);
        igniteCell(col - 1, row, depth - 1, nextStrength);
        igniteCell(col, row + 1, depth - 1, nextStrength);
        igniteCell(col, row - 1, depth - 1, nextStrength);
      }, SPARK_DELAY);
    }

    function igniteAt(col, row, depth) {
      const strength = SPARK_MIN + Math.random() * (SPARK_MAX - SPARK_MIN);
      igniteCell(col, row, depth, strength);
    }

    function randomSpark(depth) {
      if (!cells.length) {
        return;
      }
      const i = Math.floor(Math.random() * cells.length);
      const col = i % cols;
      const row = Math.floor(i / cols);
      igniteAt(col, row, depth);
    }

    function rebuild() {
      const rect = hero.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.round(rect.width));
      const height = Math.max(1, Math.round(rect.height));

      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      cols = Math.max(1, Math.floor((width + GAP) / STEP));
      rows = Math.max(1, Math.floor((height + GAP) / STEP));
      cells = [];
      for (let row = 0; row < rows; row += 1) {
        for (let col = 0; col < cols; col += 1) {
          const base = Math.random() < 0.08 ? 0.16 + Math.random() * 0.1 : 0;
          cells.push({ base, target: base, lvl: base });
        }
      }
      paint();
      for (let k = 0; k < 6; k += 1) {
        window.setTimeout(() => randomSpark(MAX_DEPTH), 120 + k * 110);
      }
      if (reduce) {
        for (let i = 0; i < 30; i += 1) {
          window.setTimeout(() => {
            randomSpark(MAX_DEPTH);
            if (Math.random() < 0.4) {
              randomSpark(MAX_DEPTH);
            }
          }, i * SPARK_DELAY);
        }
      }
    }

    function stopInterval() {
      if (intervalId) {
        window.clearInterval(intervalId);
        intervalId = 0;
      }
    }

    function startInterval() {
      if (reduce || intervalId) {
        return;
      }
      intervalId = window.setInterval(() => {
        randomSpark(MAX_DEPTH);
        if (Math.random() < 0.4) {
          randomSpark(MAX_DEPTH);
        }
      }, SPARK_INTERVAL);
    }

    function animate() {
      paint();
      if (!reduce) {
        window.requestAnimationFrame(animate);
      }
    }

    function toCell(clientX, clientY) {
      const rect = hero.getBoundingClientRect();
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
        return null;
      }
      const col = Math.floor(x / STEP);
      const row = Math.floor(y / STEP);
      if (!inBounds(col, row)) {
        return null;
      }
      return { col, row };
    }

    function onPointerMove(event) {
      if (!interactive) {
        return;
      }
      const hit = toCell(event.clientX, event.clientY);
      if (!hit) {
        return;
      }
      pointerCell = hit;
      if (pointerTicking) {
        return;
      }
      pointerTicking = true;
      window.requestAnimationFrame(() => {
        pointerTicking = false;
        if (!pointerCell) {
          return;
        }
        igniteAt(pointerCell.col, pointerCell.row, 1);
        pointerCell = null;
      });
    }

    if (interactive) {
      hero.addEventListener("pointermove", onPointerMove);
    }

    window.addEventListener("resize", () => {
      if (resizeTimer) {
        window.clearTimeout(resizeTimer);
      }
      resizeTimer = window.setTimeout(rebuild, 200);
    });
    window.addEventListener("blur", stopInterval);
    window.addEventListener("focus", startInterval);

    rebuild();
    if (!reduce) {
      startInterval();
      animate();
    }
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
    const ramp = [
      [225, 230, 238],
      [191, 211, 247],
      [122, 162, 240],
      [54, 110, 226],
      [29, 78, 216],
    ];
    const alphaBase = 0.12 * 0.72;
    const alphaSpan = 0.78 * 0.72;
    mosaic("df-mosaic", ramp, alphaBase, alphaSpan, true);
  });
  bootWireTools();
})();

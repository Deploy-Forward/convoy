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

  function bootHeroMosaic() {
    const hero = document.querySelector(".hero-grid");
    const canvas = document.getElementById("df-mosaic");
    if (!hero || !canvas || !canvas.getContext) {
      return;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    const CELL = 17;
    const GAP = 5;
    const STEP = CELL + GAP;
    const colors = [
      [225, 230, 238],
      [191, 211, 247],
      [122, 162, 240],
      [54, 110, 226],
      [29, 78, 216],
    ];
    const alphaBase = 0.12 * 0.72;
    const alphaSpan = 0.78 * 0.72;
    const interactive = true;
    const SPARK_INTERVAL_MS = 520;
    const SPARK_DELAY_MS = 70;
    const SPARK_DECAY = 0.26;
    const MAX_DEPTH = 3;

    let rows = 0;
    let cols = 0;
    let cells = [];
    let intervalId = 0;
    let resizeTimerId = 0;
    let pointerTicking = false;
    let pointerCell = null;

    function indexOf(col, row) {
      return row * cols + col;
    }

    function inBounds(col, row) {
      return col >= 0 && row >= 0 && col < cols && row < rows;
    }

    function clamp01(value) {
      return Math.max(0, Math.min(1, value));
    }

    function toCell(clientX, clientY) {
      const rect = hero.getBoundingClientRect();
      const localX = clientX - rect.left;
      const localY = clientY - rect.top;
      if (localX < 0 || localY < 0 || localX > rect.width || localY > rect.height) {
        return null;
      }
      const col = Math.floor(localX / STEP);
      const row = Math.floor(localY / STEP);
      if (!inBounds(col, row)) {
        return null;
      }
      return { col, row };
    }

    function colorFor(level) {
      const scaled = clamp01(level) * (colors.length - 1);
      const fromIndex = Math.floor(scaled);
      const toIndex = Math.min(colors.length - 1, fromIndex + 1);
      const mix = scaled - fromIndex;
      const from = colors[fromIndex];
      const to = colors[toIndex];
      return [
        Math.round(from[0] + (to[0] - from[0]) * mix),
        Math.round(from[1] + (to[1] - from[1]) * mix),
        Math.round(from[2] + (to[2] - from[2]) * mix),
      ];
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
      for (let row = 0; row < rows; row += 1) {
        for (let col = 0; col < cols; col += 1) {
          const cell = cells[indexOf(col, row)];
          if (!cell) {
            continue;
          }
          if (!reduce) {
            cell.level += (cell.target - cell.level) * 0.2;
          } else {
            cell.level = cell.target;
          }
          const level = clamp01(cell.level);
          if (level <= 0.001) {
            continue;
          }
          const rgb = colorFor(level);
          const alpha = clamp01(alphaBase + alphaSpan * level);
          ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha.toFixed(4)})`;
          ctx.fillRect(col * STEP, row * STEP, CELL, CELL);
        }
      }
    }

    function resolveCell(col, row, depth, strength) {
      if (!inBounds(col, row)) {
        return;
      }
      const cell = cells[indexOf(col, row)];
      if (!cell) {
        return;
      }

      const nextStrength = clamp01(strength);
      cell.target = Math.max(cell.target, nextStrength);
      if (reduce) {
        cell.level = cell.target;
        draw();
      } else {
        window.setTimeout(() => {
          cell.target = Math.max(cell.base, clamp01(nextStrength - SPARK_DECAY));
        }, SPARK_DELAY_MS * 2);
      }

      if (depth <= 0) {
        return;
      }
      const neighborStrength = clamp01(nextStrength - SPARK_DECAY);
      const neighbors = [
        [col + 1, row],
        [col - 1, row],
        [col, row + 1],
        [col, row - 1],
      ];
      window.setTimeout(() => {
        for (const [nextCol, nextRow] of neighbors) {
          resolveCell(nextCol, nextRow, depth - 1, neighborStrength);
        }
      }, SPARK_DELAY_MS);
    }

    function igniteAt(col, row, depth) {
      resolveCell(col, row, depth, 1);
    }

    function igniteRandom(depth) {
      if (!cells.length) {
        return;
      }
      const i = Math.floor(Math.random() * cells.length);
      const col = i % cols;
      const row = Math.floor(i / cols);
      igniteAt(col, row, depth);
    }

    function configureCanvas() {
      const rect = hero.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const cssWidth = Math.max(1, Math.round(rect.width));
      const cssHeight = Math.max(1, Math.round(rect.height));

      canvas.width = Math.max(1, Math.round(cssWidth * dpr));
      canvas.height = Math.max(1, Math.round(cssHeight * dpr));

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      cols = Math.max(1, Math.floor((cssWidth + GAP) / STEP));
      rows = Math.max(1, Math.floor((cssHeight + GAP) / STEP));
      cells = [];
      for (let row = 0; row < rows; row += 1) {
        for (let col = 0; col < cols; col += 1) {
          const base = Math.random() < 0.08 ? 0.16 + Math.random() * 0.1 : 0;
          cells.push({ base, target: base, level: base });
        }
      }
      draw();
    }

    function stopSparkInterval() {
      if (intervalId) {
        window.clearInterval(intervalId);
        intervalId = 0;
      }
    }

    function startSparkInterval() {
      if (reduce || intervalId) {
        return;
      }
      intervalId = window.setInterval(() => {
        igniteRandom(MAX_DEPTH);
        if (Math.random() < 0.4) {
          igniteRandom(MAX_DEPTH);
        }
      }, SPARK_INTERVAL_MS);
    }

    function queueInitialSparks() {
      for (let k = 0; k < 6; k += 1) {
        window.setTimeout(() => {
          igniteRandom(MAX_DEPTH);
        }, 120 + k * 110);
      }
    }

    function animate() {
      draw();
      if (!reduce) {
        window.requestAnimationFrame(animate);
      }
    }

    function runReducedMotionBurst() {
      for (let i = 0; i < 30; i += 1) {
        window.setTimeout(() => {
          igniteRandom(MAX_DEPTH);
          if (Math.random() < 0.4) {
            igniteRandom(MAX_DEPTH);
          }
        }, i * SPARK_DELAY_MS);
      }
    }

    function rebuild() {
      configureCanvas();
      if (reduce) {
        runReducedMotionBurst();
        return;
      }
      queueInitialSparks();
    }

    function handlePointerMove(event) {
      if (!interactive) {
        return;
      }
      const cell = toCell(event.clientX, event.clientY);
      if (!cell) {
        return;
      }
      pointerCell = cell;
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

    hero.addEventListener("pointermove", handlePointerMove);

    window.addEventListener("resize", () => {
      if (resizeTimerId) {
        window.clearTimeout(resizeTimerId);
      }
      resizeTimerId = window.setTimeout(rebuild, 200);
    });

    window.addEventListener("blur", stopSparkInterval);
    window.addEventListener("focus", startSparkInterval);

    rebuild();
    if (!reduce) {
      startSparkInterval();
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
    bootHeroMosaic();
  });
  bootWireTools();
})();

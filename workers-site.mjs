/**
 * Cloudflare edge split for convoy.bot:
 * - GET/HEAD /mcp and /mcp/ serve the MCP attach page.
 * - other /mcp and /mcp/* requests proxy to MCP_ORIGIN.
 * - under assets.config.html_handling = "none", map / to /index.html explicitly.
 * - everything else is served from static assets.
 */

/**
 * @typedef {object} Env
 * @property {Fetcher} ASSETS
 * @property {string} MCP_ORIGIN
 */

/**
 * @param {Request} request
 * @param {Env} env
 * @returns {Promise<Response>}
 */
async function handleMcpAttachPage(request, env) {
  const pageUrl = new URL(request.url);
  pageUrl.pathname = "/mcp.html";
  const assetRequest = new Request(pageUrl.toString(), request);
  return env.ASSETS.fetch(assetRequest);
}

/**
 * Proxy non-GET /mcp* traffic to www because apex convoy.bot is served by
 * Assets on this route; targeting www reaches the same tunnel origin without
 * re-entering the apex Worker route path.
 *
 * @param {Request} request
 * @param {Env} env
 * @returns {Promise<Response>}
 */
async function handleMcpProxy(request, env) {
  let upstream;
  try {
    upstream = new URL(env.MCP_ORIGIN);
  } catch (_err) {
    return new Response("MCP_ORIGIN is not a valid URL", { status: 500 });
  }

  const incoming = new URL(request.url);
  const target = new URL(incoming.pathname + incoming.search, upstream);
  const upstreamRequest = new Request(target.toString(), request);
  return fetch(upstreamRequest);
}

export default {
  /**
   * @param {Request} request
   * @param {Env} env
   * @returns {Promise<Response>}
   */
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if ((pathname === "/mcp" || pathname === "/mcp/") && (request.method === "GET" || request.method === "HEAD")) {
      return handleMcpAttachPage(request, env);
    }
    if (pathname === "/mcp" || pathname.startsWith("/mcp/")) {
      return handleMcpProxy(request, env);
    }
    if (pathname === "/" || pathname === "") {
      const url = new URL(request.url);
      url.pathname = "/index.html";
      return env.ASSETS.fetch(new Request(url.toString(), request));
    }
    return env.ASSETS.fetch(request);
  },
};

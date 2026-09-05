/**
 * Cloudflare edge split for convoy.bot:
 * - GET/HEAD /mcp and /mcp/ serve the MCP attach page.
 * - other /mcp and /mcp/* requests pass through to zone origin.
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
      return fetch(request);
    }
    return env.ASSETS.fetch(request);
  },
};

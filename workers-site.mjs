/**
 * Cloudflare edge split for convoy.bot:
 * - /mcp and /mcp/* proxy to the existing Python MCP origin.
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
    if (pathname === "/mcp" || pathname.startsWith("/mcp/")) {
      return handleMcpProxy(request, env);
    }
    return env.ASSETS.fetch(request);
  },
};

# OpenAI plugin publication runbook

This runbook separates what is ready to merge from what requires a publisher,
legal, identity, or hosted-service decision. It follows OpenAI's current plugin
packaging, authentication, and submission contracts.

## Current verdict

| Gate | Status | Evidence or owner |
|---|---|---|
| OpenAI-format package | GREEN | `plugins/convoy`, repo marketplace, validator and tests |
| Public MCP origin freshness | GREEN | edge `0.1.0+6b8670a`; current read catalog; write calls refused |
| Anonymous endpoint is read-only | GREEN in this branch | `send` hidden; mixed tools refuse their live modes; all listed tools carry safety annotations |
| Full cloud happy path | RED | Deploy Forward engineering: OAuth, tenant roots, scoped writes, local relay |
| Privacy and terms | RED | Deploy Forward legal/publisher approval and public hosting |
| `.app.json` connector id | NOT APPLICABLE | `.mcp.json` distributes the MCP connection; no registered connector mapping is used |
| Deploy-Forward/convoy PR | READY | push this branch and open the repository PR after the gates below pass |
| OpenAI public submission | RED | publisher identity, policies, authenticated service, tests and domain proof remain |

The package may merge into `Deploy-Forward/convoy` while the public submission
is red. Do not represent repository merge, local marketplace installation, or
an OpenAI draft as public publication.

## 1. Merge and deploy the anonymous read surface

1. Run the full repository suite and both OpenAI validators.
2. Push `feat/openai-convoy-plugin` and open a PR against `main`.
3. Review the public MCP delta carefully. The anonymous `tools/list` must omit
   `send` and every always-write tool. Every listed tool must advertise
   `readOnlyHint=true`, `destructiveHint=false`, and `openWorldHint=false`.
4. Merge the PR through normal review.
5. Stage the merged SHA in the production worktree, reinstall its dedicated
   virtual environment, and smoke-test a spare loopback port.
6. Update and restart scheduled task `ConvoyBotMcp`. Keep
   `CONVOY_MCP_WRITE_TOOLS` unset at process, user, and machine scope.
7. Prove `initialize`, `tools/list`, a representative read, and a direct
   `send` refusal on loopback and `https://convoy.bot/mcp`.
8. Save the exact SHA, PID, task state, version, tool names, annotations, and
   refusal response as release evidence.

## 2. Build the authenticated full cloud path

Do not enable `CONVOY_MCP_WRITE_TOOLS=1` on the existing anonymous process.
OpenAI requires authentication for customer-specific data and write actions.
Use one universal MCP URL unless OpenAI explicitly approves a template URL.

1. Put an OAuth 2.1 resource server in front of the Convoy MCP handler.
2. Serve `/.well-known/oauth-protected-resource` with the canonical resource
   URL, authorization-server issuer, documentation, policy and terms links,
   and least-privilege scopes such as `convoy:read`, `convoy:write`, and
   `convoy:launch`.
3. Configure the authorization server for PKCE and an OpenAI-supported client
   registration method. Publish OAuth or OpenID Connect discovery metadata.
4. Verify every bearer token on every MCP request. Derive the tenant from
   verified claims; never accept a filesystem root, tenant id, or owner id from
   model-supplied tool arguments.
5. Resolve `(issuer, subject, organization, project)` to a server-owned opaque
   tenant/project id. Store each root beneath a fixed service-owned base and
   enforce containment after resolving paths.
6. Authorize reads and writes separately. `convoy:read` may inspect only that
   tenant's roots. Thread mutation needs `convoy:write`; process launch,
   installer execution, terminal control, and repository-account inventory
   need narrower scopes or must remain unavailable in cloud.
7. Replace host-global GitHub and harness credentials with user/team-scoped
   integrations. Never run `repos`, vendor CLIs, or installers as the public
   server operator on behalf of an arbitrary caller.
8. Add a separately authenticated local relay for local panes and worktrees.
   Pair it to one tenant/device, require an action-specific grant for launch or
   terminal changes, and keep session tokens local. The hosted coordinator
   cannot safely split a user's local terminal by itself.
9. Define retention and deletion. Delete tenant roots on request, expire
   inactive data on the published schedule, redact logs, and bound backups.
10. Prove cross-tenant isolation, missing/expired token rejection, scope
    downgrade, path traversal refusal, replay refusal, concurrent writes,
    deletion, audit provenance, and a complete seat/send/ack flow.

Only after these tests pass may the authenticated deployment expose the full
write-gated catalog and advertise `Write` in a separate production manifest.

## 3. Approve and publish policy URLs

This is a Deploy Forward publisher decision; an agent must not invent legal
approval. The approving person should:

1. Approve the exact data categories Convoy reads, stores, returns, and logs:
   thread names, chair/harness metadata, worktree pointers, message summaries,
   inbox state, timestamps, user/team identifiers, and authorization/audit
   records. State explicitly that vendor credentials and full vendor
   transcripts are not intended thread data.
2. Approve purpose, subprocess/vendor sharing, subprocessors, security,
   retention, deletion, export, regional availability, age limits, warranty,
   acceptable use, suspension, governing law, and a monitored support contact.
3. Publish stable HTTPS pages at `https://convoy.bot/privacy` and
   `https://convoy.bot/terms`, plus a public support URL.
4. Verify the pages return 200 without authentication and identify
   Deploy Forward consistently with the OpenAI developer identity.
5. Add these manifest fields only after approval:

   ```json
   "privacyPolicyURL": "https://convoy.bot/privacy",
   "termsOfServiceURL": "https://convoy.bot/terms"
   ```

6. Re-run the plugin validator and compare representative MCP responses with
   the published privacy disclosures.

Approval must be recorded by a human reviewer in the repository PR or release
record. A generated draft or a passing URL check is not legal approval.

## 4. Keep `.app.json` out unless OpenAI issues a mapping

The package already uses `.mcp.json`, which OpenAI documents as the distributed
MCP-server configuration. `.app.json` is only the compatibility mapping for a
registered MCP connection. No connector id is needed for the present package.
If OpenAI later issues one, add `.app.json`, add `"apps": "./.app.json"` to
the manifest, validate, reinstall the local plugin, and test the registered
connection. Never commit a guessed id.

## 5. Prepare the OpenAI submission

After sections 2 and 3 are green:

1. In the publishing OpenAI organization, grant the submitter **Apps
   Management: Write** and complete Deploy Forward business verification.
2. Open the plugin submission portal and create **With MCP**. Submit the MCP
   server itself; do not reference an existing integration id.
3. Use Universal URL `https://convoy.bot/mcp` unless OpenAI has explicitly
   approved a template URL. Enter OAuth details and reviewer credentials that
   need no MFA, email, SMS, private network, or extra setup.
4. Complete the domain challenge at
   `https://convoy.bot/.well-known/openai-apps-challenge` with exactly the token
   issued by the portal.
5. Scan tools. Verify names, descriptions, schemas, outputs and all three
   safety annotations against the deployed SHA. Fix and redeploy before
   rescanning if any differ.
6. Supply at least five positive and three negative tests. Minimum positive
   coverage: inspect capabilities; create an isolated thread; create a crew;
   observe seated acknowledgements; send to an exact chair and observe the
   target ack. Minimum negative coverage: cross-tenant read; write with only
   read scope; launch without a paired local relay/action grant.
7. Supply final starter prompts, countries, release notes, website, support,
   privacy and terms URLs. Select only regions where support and legal terms
   are ready.
8. Complete attestations only after rerunning the final package, OAuth,
   isolation, MCP scan and test matrix. Submit for review. Publication occurs
   only after OpenAI approves and the publisher selects Publish.

## Release evidence card

Record this for every candidate:

```text
repository PR:
merged SHA:
production SHA/version:
MCP URL:
OAuth issuer/scopes:
tenant-isolation test run:
tools/list names + annotations:
positive tests (5+):
negative tests (3+):
privacy URL + approving human/date:
terms URL + approving human/date:
support URL:
domain challenge:
OpenAI draft/submission id:
OpenAI review state:
published directory URL:
```

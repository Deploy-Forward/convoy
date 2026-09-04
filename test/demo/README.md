# Demo tests

This directory contains product-level tests for Convoy's public behavior.
It is a reusable demo fixture, not a private customer package.

Operator DoD (not a WT demo): [`docs/e2e-harness.md`](../../docs/e2e-harness.md),
evidence template [`fixtures/e2e_harness.template.json`](fixtures/e2e_harness.template.json).
Redeploy verify: `PYTHONPATH=src python3 scripts/mcp_redeploy_verify.py --catalog`.

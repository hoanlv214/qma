# Quickstart — ChatGPT connector

## Steps

1. **ChatGPT → Settings → Connectors → Create / Add custom connector** (developer mode).
   - Name: `QMA`
   - Server URL: `https://qma-api-7o9v.onrender.com/mcp`
   - Authentication: OAuth (ChatGPT follows QMA's OAuth 2.1 metadata automatically)

2. **ChatGPT opens the QMA consent page in your browser.** Connect your wallet
   extension, sign the one-time proof message, set spend caps, approve.

3. **Ask ChatGPT:**

   > "Scan QMA market anomalies and buy a preview analog report for the
   > strongest one, staying within my budget."

## Notes

- The connection spends from **your QMA Agent Wallet** within the caps you set.
- Free tools (`qma_scan_anomalies`, `qma_check_budget`) never spend USDC.
- Revoke anytime at `<frontend>/connect` — the token dies on the next call.
- If ChatGPT shows the connector as unauthenticated after a revoke, remove and
  re-add the connector; the OAuth flow will re-issue a fresh code.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Could not verify the connector" | Backend `/mcp` route must be deployed; check `/health` first |
| Tool call hangs | A purchase can take up to ~2.5 minutes (durable session + settlement); free tools respond instantly |
| `budget_exceeded` | Re-approve with higher caps or top up the Agent Wallet |

# QMA Agent Notes

## Code Search And Refactor Tooling

This repo uses `ast-grep` (`sg`) for syntax-aware code search and refactors. Config lives in `sgconfig.yml`, and saved rules live in `.ast-grep/rules/`.

- Use `sg` for searches that need code structure: FastAPI route decorators, function calls, argument shapes, class/model instantiation, payment state transitions, and refactors that must avoid comments/strings.
- Use `rg` for plain text lookups: log messages, config keys, TODOs, static copy, CSS class names, and file discovery.
- Check `.ast-grep/rules/` before writing a new structural pattern.
- Dry-run structural rewrites first with a plain search. Use interactive rewrites before broad changes.
- Prefer `sg --rewrite` over ad hoc text replacement for syntax-aware multi-file refactors.

Common commands:

```powershell
sg -p 'save_invoice($INVOICE)' -l python .
sg scan -r .ast-grep/rules/python-save-invoice-call.yml
sg scan -r .ast-grep/rules/python-fastapi-app-route.yml
```

QMA-specific reminders:

- Root `main.py` is being decomposed into `backend/app/...`; new public API routes should be registered in endpoint modules via `APIRouter`, not directly with `@app.get` or `@app.post`.
- `main_ref.py` is the legacy reference snapshot. Default ast-grep scripts scan live code only (`backend main.py tests`) to avoid noisy reference hits. Scan `main_ref.py` explicitly when comparing parity with the old god file.
- Payment logic is sensitive. Before changing invoice status, settlement verification, split legs, or access tokens, scan for `save_invoice`, `save_payment_ledger`, and payment-required exceptions.
- Keep public API paths and response keys stable during the migration.

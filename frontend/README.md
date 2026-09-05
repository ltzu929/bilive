# Bilive Native Studio frontend

This directory contains the maintainable Angular source for the native recorder
shell and the bilive slice, upload, and settings pages.

## Source baseline

- Upstream: `https://github.com/acgnhiki/blrec`
- Upstream tag: `v2.0.0-beta.4`
- Upstream commit: `975fa27`
- Bilive source lineage: `ltzu929/blrec`, branch `feat/native-studio-ui`
- Imported working-tree baseline: commit `60d0ed6` plus the four local source
  changes that produced the currently shipped Native Studio bundle.

The upstream frontend and the bilive modifications in this directory are
licensed under GPL-3.0; see `LICENSE` in this directory. The repository root's
Apache-2.0 license continues to apply to the original bilive code outside this
directory.

## Local development

Use Node.js on Windows. Dependencies and generated output are intentionally not
stored in Git.

```powershell
cd D:\alldata\pi\bilive\frontend
npm ci
npm run build
python build_wheel.py `
  ..\wheel\blrec-2.0.0b4+bilive.8-py3-none-any.whl `
  ..\wheel\blrec-2.0.0b4+bilive.9-py3-none-any.whl `
  2.0.0b4+bilive.9
```

The production build is written to `frontend/dist/blrec`. Building here does
not deploy it, modify the checked-in wheel, restart a service, or run work on the
Raspberry Pi. A wheel update and Pi deployment remain separate, explicit
operations.

Source-built wheels contain the ordering UI directly and must not include the
old standalone queue compatibility patch.

Do not commit `node_modules`, `.angular`, or `dist`. The checked-in
`package-lock.json` is the reproducible dependency input.

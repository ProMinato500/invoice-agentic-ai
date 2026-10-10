# Local startup and operations

Deployment/Docker/Redis were explicitly deferred by the user. Use the root `.cmd` scripts. The API binds to 127.0.0.1:8010 and the frontend to 127.0.0.1:3000. Services run hidden and write local logs. The durable worker uses one OS lock; do not launch a second worker manually.

Model assets download on first use and are cached under storage/model-cache and the local OCR installation. An initial internet connection is required for model assets and configured cloud AI. After models are cached, exact/native flows do not need an AI key. Unknown/ambiguous cases require either AI evidence or human review.

Back up `storage/reconcile.db`, `storage/checkpoints.db`, original PDFs/extractions/reports and `.env` securely while services are stopped. The application never drops an existing user database. Migrations only create the application's dedicated schema tables. Destructive downgrade is blocked.

Stop/restart after changing backend configuration. `start-local.cmd` rejects occupied ports instead of terminating unrelated processes. `stop-local.cmd` validates recorded PIDs against workspace, command and creation time before termination. Existing failed/ambiguous verification runs remain genuine history.

Single-user loopback mode is the scope of this delivery; public exposure requires a separate authentication/deployment/security design.

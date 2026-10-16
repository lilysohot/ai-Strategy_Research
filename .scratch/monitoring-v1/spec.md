# HTTP monitoring V1

Source: docs/design/monitoring-technical-plan.md; implementation authorized 2026-10-16.

One current monitor per research (cancel releases the slot); collection-shaped API and entities retain future one-to-many capability. Browser user presence gates collection/evaluation/scheduling. HTTP quotes and trigger events travel through separate Redis Streams with PostgreSQL durable messages and receipts. Long Runs use the existing dispatch outbox and never block quote consumption. Provider timestamps and exact prices are required; uncertain quotes fail closed. Session UI exposes status, controls, history and linked Runs.

Validation uses isolated PostgreSQL and Redis, not the business database. No live trading.

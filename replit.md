# Eichholtz Commission Bot

A Russian-language Telegram bot for a luxury furniture sales manager to track deals, payments, commissions, KPIs and payroll in Google Sheets.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `cd commission_bot && python main.py` — run the Telegram worker (requires its `.env` and a shared Google spreadsheet)
- `cd commission_bot && python -m unittest discover -s tests -v` — run commission and payroll calculation tests
- Railway service root directory: `/commission_bot`; deployment variables are documented in `commission_bot/README.md`
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)
- Telegram worker: Python 3.11+, aiogram 3.x, gspread, oauth2client, APScheduler

## Where things live

- `commission_bot/` — standalone Telegram bot and Railway service
- `commission_bot/calculations.py` — salary, sick-pay, KPI and progressive-bonus math
- `commission_bot/google_sheets_api.py` — worksheet creation and persistence
- `commission_bot/handlers.py` — Russian bot commands and FSM flows
- `commission_bot/README.md` — local and Railway setup, spreadsheet schema and calculation assumptions

## Architecture decisions

- The Telegram bot is a separate Python service under `commission_bot/`; its Railway root directory is that folder.
- Google Sheets is the bot's persistent data store; FSM state is temporary and held in memory.
- Deal totals determine monthly plan completion. Actual payments determine bonus accrual and progress through plan bands.
- Money calculations use `Decimal`; the supplied `>111%` top-band wording is implemented continuously above 110% to avoid an unassigned gap.

## Product

- Authorized managers can enter deals, client payments, attendance and KPI statuses through Russian-language Telegram flows.
- The bot reports current-month payroll and plan results, tracks payout submissions, and prompts for monthly settings on the second day.

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Railway must run a single worker instance because Telegram long polling and the monthly scheduler are process-based.
- Historical deal months need their own `Settings` row to calculate bonuses for payments received later.
- Do not commit `.env` or service-account JSON files.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details

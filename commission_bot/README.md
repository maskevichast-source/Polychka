# Eichholtz Sales Commission Bot

Telegram bot for a sales manager to track deals, client payments, progressive
bonuses, monthly KPI, attendance and payroll estimates. Bot messages, buttons
and command descriptions are in Russian. Data is stored in Google Sheets.

## Run locally

1. Create a Telegram bot with BotFather and copy its token into a local `.env`.
2. Create a Google Cloud service account, enable the Google Sheets API, and
   share the target spreadsheet with the service account's email address.
3. Copy `.env.example` to `.env` and set:
   - `TELEGRAM_BOT_TOKEN`
   - `SPREADSHEET_ID` (the value between `/d/` and `/edit` in the sheet URL)
   - `GOOGLE_SERVICE_ACCOUNT_JSON` (the full service-account JSON on one line),
     or `GOOGLE_SERVICE_ACCOUNT_FILE` pointing to a local JSON file
   - `ALLOWED_TELEGRAM_USER_IDS` (comma-separated numeric Telegram IDs)
4. Install Python 3.11 or newer and the dependencies:

   ```sh
   python -m pip install -r requirements.txt
   python main.py
   ```

   To discover a Telegram ID, start the bot with the token and spreadsheet
   configured but leave `ALLOWED_TELEGRAM_USER_IDS` empty. The only command
   available before authorization is `/my_id`. Add that ID to the allowlist and
   restart the bot.

Never commit `.env` or a service-account file. The bot never logs credential
contents.

## Deploy to Railway

1. Create a Railway worker service from this repository.
2. Set the service's **Root Directory** to `/commission_bot`.
3. Add the environment variables listed above in Railway's Variables panel.
   Set `BOT_TIMEZONE=Asia/Almaty` unless another timezone is needed.
4. Railway installs `requirements.txt` and starts the worker using the
   included `Procfile` (`python main.py`).
5. For the initial authorized-user setup, deploy once with the allowlist empty,
   send `/my_id` to the bot, then add the returned ID to
   `ALLOWED_TELEGRAM_USER_IDS` and restart the service.

The bot uses Telegram long polling and does not need a public HTTP port.
Run a single Railway instance to avoid duplicate polling and scheduled prompts.

## Google Sheets

On first successful connection, the bot creates the following worksheets and
header rows when needed: `Settings`, `Deals`, `Payments`, `Timesheet`, `KPI`,
`Payout Batches`, and `Audit Log`. Existing worksheets are retained; missing
headers are appended. The `Deals` worksheet includes an additional `Discount
Covered by Designer?` column because that affects the discount coefficient.
Payments record the payout batch, submission time, Telegram user ID, and bonus
amount snapshot once a batch is confirmed.

The `Settings` worksheet stores one row per month. On the second day of each
month at 09:00 in the configured timezone, the bot asks authorized users to
enter the monthly sales plan, standard working days, current 1 MRP value, and
the average daily pay used for sick pay. Enter the average daily pay supplied
or approved by the company's accountant; the bot does not infer a statutory
average-wage formula. Use `/set_plan` to enter the current month manually, or
`/set_plan YYYY-MM` for a specific month.

## Commands

- `/dashboard` — current-month attendance, salary, sick pay, plan, bonuses,
  KPI and expected income
- `/add_deal` — record a deal and its designer/discount details
- `/add_payment` — record a client's actual payment against a deal
- `/tuesday_sync` — review pending payments by month and create a confirmed
  payout batch
- `/kpi` — toggle CRM and marketing criteria; the 90% plan criterion is
  calculated automatically from actual monthly sales
- `/timesheet` — mark today's status; pass `YYYY-MM-DD` to enter another date
- `/set_plan` — set a month's plan, workdays, 1 MRP value, and accountant-approved
  average daily pay
- `/edit_deal` — edit a deal field with a required reason and audit entry
- `/edit_payment` — edit an unpaid payment with a required reason and audit
  entry; payments already in a payout batch are locked
- `/report [YYYY-MM]` — download a CSV month report (defaults to current month)
- `/backup` — download a JSON export of every bot worksheet
- `/cancel` — stop the current form
- `/my_id` — show the caller's Telegram ID

Payout batches only include pending payments from the selected payment month.
The bot shows payment IDs, amounts, calculated bonuses, and the batch total
before confirmation. Confirmation writes the batch and its audit entry in the
same Google Sheets update request. A full JSON backup is also sent to every
authorized user on the last day of each month at 20:00 in the configured
timezone.

## Calculation conventions

- Monthly plan completion is the sum of all deal totals dated in that month,
  divided by that month's sales plan. Sale deals count toward the plan.
- Deals are ordered by their date (then deal ID) to establish each deal's
  starting position in its month's plan. Payments on that deal advance from
  that position in payment-date order, so one payment can cross multiple bonus
  bands. The designer percentage reduces each actual payment before bonus
  rates are applied; unpaid deal value does not accrue a payment bonus.
- The rate bands are treated as continuous boundaries at 60%, 70%, 90% and
  110% of plan. The top band starts above 110%; this avoids an undefined gap in
  the supplied `>111%` wording. `Sale` always uses 3% before the discount
  coefficient.
- A client discount of up to 10% uses coefficient 1.0, above 10% through 15%
  uses 0.9, and above 15% uses 0.8. If the designer covers the discount, the
  coefficient is 1.0.
- Fixed salary is 250,000 KZT multiplied by work-status days divided by standard
  working days. Sick pay is the monthly accountant-approved average daily pay
  multiplied by sick days, capped at 25 times that month's MRP value. The bot
  does not claim to determine the legally required average-wage calculation.
- Bonuses in a dashboard month are based on payments dated in that month.
  Each payment uses the plan bands for its linked deal's month; retain a
  `Settings` row for each month that contains deals.
- KPI values are 30,000 KZT for CRM, 40,000 KZT for reaching 90% of plan, and
  30,000 KZT for marketing participation. The plan criterion is derived from
  actual sales and cannot be switched on manually.
- Deal and payment corrections store the previous value, new value, actor,
  timestamp, and reason in `Audit Log`. Deals linked to submitted payouts and
  payments already included in a payout batch cannot be edited.

## Tests

Run the calculation tests without connecting Telegram or Google Sheets:

```sh
python -m unittest discover -s tests -v
```
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
header rows when needed: `Settings`, `Deals`, `Payments`, `Timesheet`, and
`KPI`. Existing worksheets are retained; missing headers are appended. The
`Deals` worksheet includes an additional `Discount Covered by Designer?`
column because that affects the discount coefficient.

The `Settings` worksheet stores one row per month. On the second day of each
month at 09:00 Asia/Almaty time, the bot asks authorized users to enter the
monthly sales plan, standard working days and current 1 MRP value. Use
`/set_plan` to enter the current month manually, or `/set_plan YYYY-MM` for a
specific month.

## Commands

- `/dashboard` — current-month attendance, salary, sick pay, plan, bonuses,
  KPI and expected income
- `/add_deal` — record a deal and its designer/discount details
- `/add_payment` — record a client's actual payment against a deal
- `/tuesday_sync` — list payments not yet submitted for payout and mark them
- `/kpi` — toggle the three current-month KPI criteria
- `/timesheet` — mark today's status; pass `YYYY-MM-DD` to enter another date
- `/set_plan` — set a month's plan, standard working days and 1 MRP value
- `/cancel` — stop the current form
- `/my_id` — show the caller's Telegram ID

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
  working days. Sick pay uses the same fixed-salary daily rate and is capped at
  25 times that month's MRP value. Sick pay is shown separately from prorated
  fixed salary.
- Bonuses in a dashboard month are based on payments dated in that month.
  Each payment uses the plan bands for its linked deal's month; retain a
  `Settings` row for each month that contains deals.
- KPI values are 30,000 KZT for CRM, 40,000 KZT for reaching 90% of plan, and
  30,000 KZT for marketing participation.

## Tests

Run the calculation tests without connecting Telegram or Google Sheets:

```sh
python -m unittest discover -s tests -v
```
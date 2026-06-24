# Validation Question Set

A 25-question script to validate the TCL Finance & Billing assistant end-to-end.
Run `python chat.py` from the project root and type each question. Expected
results are based on the current seed data (≈10,000 customers/accounts, 50,000
costed events, 4 currencies, etc.). Tip: type `/raw` to see the underlying JSON
or generated SQL for any answer.

> Notes
> - WRITE questions never change data until you reply **`yes`**. Reply **`no`** to
>   cancel and keep the database clean.
> - A few questions are *expected* to report "already exists / no change needed" —
>   that is correct behaviour, not a failure.
> - Exact counts may differ slightly if you have approved writes during testing.

## A. General data questions (universal SQL read agent)

| # | Ask in chat | What you should get |
|---|---|---|
| 1 | How many active customers do we have? | A single number (~9,500). |
| 2 | How many accounts are SUSPENDED? | A single count of SUSPENDED accounts. |
| 3 | Show account details for ACC000123 | Account number, name, status (ACTIVE), billing cycle MONTHLY, currency, dates. |
| 4 | What currency does account ACC000123 use? | One currency code (e.g. GBP). |
| 5 | List 5 customers of type Government | 5 customers whose type is Government (GOV). |
| 6 | Give me the top 5 accounts by total data usage | 5 account numbers ranked by in_bits+out_bits. |
| 7 | What is the total revenue across all bills? | A single summed amount over BILL_SUMMARY.TOTAL_AMOUNT. |
| 8 | How many bills are OVERDUE? | A single count of bills with status OVERDUE. |
| 9 | Show the contact email and phone for customer CUST000200 | One contact row (email + phone). |
| 10 | List all product codes of type SDWAN | Product codes whose type is SDWAN. |
| 11 | Give me a count of bills by status | Counts grouped by GENERATED / PAID / PENDING / OVERDUE. |
| 12 | Which invoicing companies are in India? | Company codes/names with country India. |
| 13 | Show the 3 most recent costed events for account ACC000071 | 3 events with timestamps, bits, speed. |
| 14 | How many customers are there of each customer type? | Counts per CORP/ENT/GOV/SMB/WHOLESALE. |

## B. Schema / structure questions

| # | Ask in chat | What you should get |
|---|---|---|
| 15 | List all PL/SQL packages in the schema | 9 packages, all VALID. |
| 16 | What parameters does BILLING_PKG.GENERATE_BILL take? | The procedure's argument list. |

## C. Investigation & executive narrative (GPT-4o synthesis)

| # | Ask in chat | What you should get |
|---|---|---|
| 17 | Investigate billing and usage issues for customer CUST000122 | A root-cause summary + any billing/usage issues + recommended actions. |
| 18 | Give me an executive revenue summary | A short narrative over revenue / products / payments. |

## D. Writes — no-op detection (nothing should be staged)

| # | Ask in chat | What you should get |
|---|---|---|
| 19 | Set account ACC000123 status to ACTIVE | "already 'ACTIVE' - no change needed." |
| 20 | Create a new currency USD called US Dollar | "Currency 'USD' already exists - no change needed." |

## E. Writes — real change with confirmation (reply `no` to keep data clean)

| # | Ask in chat | What you should get |
|---|---|---|
| 21 | Set account ACC000123 status to SUSPENDED | "change it from 'ACTIVE' to 'SUSPENDED' … yes/no" → reply **no**. |
| 22 | Change account ACC000123 currency to INR | "change it from <cur> to 'INR' … yes/no" → reply **no**. |
| 23 | Create a new currency JPY called Japanese Yen | A create confirmation → reply **no** (or **yes** to actually add it). |
| 24 | Apply a $250 CREDIT adjustment to invoice INV00000123 for account ACC000123 | An adjustment confirmation → reply **no** (or **yes** to stage+apply). |

## F. Approval queue

| # | Ask in chat | What you should get |
|---|---|---|
| 25 | /pending | A list of any PENDING approval requests (empty if you cancelled everything). |

---

### One full write round-trip to try (optional)

```
you > set account ACC000123 status to SUSPENDED
  ...This will change it from 'ACTIVE' to 'SUSPENDED'. Reply 'yes' ... or 'no' ...
you > yes
  Done - approved and applied (request #N).
you > set account ACC000123 status to ACTIVE          # put it back
you > yes
```

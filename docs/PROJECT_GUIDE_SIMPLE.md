# A Simple Guide to This Project — Explained for Everyone

This guide explains, in plain language, **what this project is**, **how it works**,
and **everything we built and fixed**. No technical background needed. Wherever a
technical word appears, it's explained in the **Glossary** at the bottom.

---

## 1. What is this, in one sentence?

It's a **smart assistant that lets you talk to a company's Finance & Billing
records in plain English** — you ask questions or request changes by typing
normal sentences, and it does the work for you safely.

The company in this project is a made-up telecom called **TCL**. Its records live
in a **database** (think of it as a giant, organized filing cabinet) and include
customers, their accounts, bills, payments, and internet/usage data.

**Without this project:** to get answers you'd have to write complicated database
code (called *SQL*) that only programmers understand.
**With this project:** you just type *"how many active customers do we have?"* and
get a clear answer — no code, no jargon.

---

## 2. The big picture — how it works (an everyday analogy)

Imagine a well-run office:

1. **You** walk in and say what you want, in normal words.
2. A **receptionist** figures out whether you want to *look something up* (a
   "read") or *change something* (a "write"), and sends you to the right desk.
3. A **specialist clerk** (we call these **agents**) understands the details and
   knows which **filing actions** to perform.
4. Behind the clerks are about **80 tiny workers** (we call these **tools**), and
   each worker does exactly **one** small job — like "fetch this customer's bills"
   or "update this account's status."
5. **Nothing gets changed without your signature.** Any change is written on a
   form first and only carried out after **you approve it**.
6. A **logbook** records everything that happens, for safety and history.

The "brain" that understands your English sentences is an **AI model** from OpenAI
(currently a fast, cost-effective one called **gpt-4o-mini**).

Here's the same idea as a picture:

```
You type:  "Investigate billing issues for customer CUST000122"
   │
   ▼  Receptionist (intent router)  → decides: this is a "look-up" (READ)
   ▼  Manager (read master agent)   → picks the right specialist
   ▼  Specialist (RCA agent)        → gathers info using several tools + AI
   ▼  Tiny workers (tools)          → ask the database precise questions
   ▼  Database (the filing cabinet)
   └─ Answer comes back in plain English
```

---

## 3. The building blocks (what's inside)

| Piece | Everyday meaning | In this project |
|---|---|---|
| **Database** | The filing cabinet that stores all records | Oracle database, 20 tables (customers, accounts, bills, usage, etc.) |
| **Tools** (~80) | Tiny workers, each does one precise job | Small functions like `get_unpaid_bills`, `update_account_status` |
| **Agents** (17) | Managers/specialists that use AI to understand you and combine tools | `rca_agent`, `dba_agent`, `dml_agent`, etc. |
| **`ask`** | The front door / receptionist | One entry point that routes any request |
| **Approval system** | The "please sign here before we do it" desk | Every change is staged and needs your **yes** |
| **Audit log** | The office logbook | Records every action with who/what/when |
| **AI model** | The brain that reads English | OpenAI **gpt-4o-mini** |

Today the system offers **125** of these capabilities ("tools") in total — the ~80
tiny workers **plus** the 17 smart agents **plus** helpers for approvals, audit,
and database administration.

---

## 4. Three ways to use it

1. **Web UI (a web page in your browser) — the easiest and nicest.**
   Run `python web.py`, open `http://127.0.0.1:8000`, and chat like a messaging
   app. Changes show **Approve / Cancel** buttons — you just click.

2. **Terminal chat (text window).**
   Run `python chat.py` and type. Changes ask you to type **yes** or **no**.

3. **As a plug-in for AI tools (advanced).**
   Run `python -m src.server` so apps like Claude Desktop can use all the tools.

All three use the **same brains underneath** — only the way you interact differs.

---

## 5. The safety net — why this is safe to use

This is the most important idea, so here it is on its own:

- **Reading is free and instant.** Asking questions never changes anything.
- **Every change is approval-gated.** When you ask to create, update, or delete
  something, the system **does not do it immediately**. It writes the change on a
  "pending" form and shows you exactly what will happen (for example,
  *"This will change the status from ACTIVE to INACTIVE"*). It only runs **after
  you approve**. If you say no, nothing happens.
- **Everything is logged.** Every action (reads and writes) is recorded in an
  **audit log** — a permanent diary — so you can always see what was done.
- **Dangerous things are guarded.** "Delete everything" style requests are
  refused. Deleting an important record warns you first that it's permanent.

In short: **you are always in control, and there's always a record.**

---

## 6. Everything we built and fixed (the full story, step by step)

This project already existed and worked. In this round of work we made it
**cheaper to run, more capable, easier to use, and fixed several bugs.** Here is
everything, in order, in plain language.

### 6.1 Made it cheaper and faster to run
- **What:** Switched the AI brain from a bigger, pricier model (`gpt-4o`) to a
  fast, low-cost one (`gpt-4o-mini`).
- **Why it matters:** Same understanding for everyday questions, but quicker and
  cheaper. You can still switch back anytime with one setting.

### 6.2 Made "delete" actually work
- **The problem:** You could create and update records, but **deleting didn't
  work** — there were simply no delete actions built.
- **What we did:** Added safe delete actions for notes, addresses, contacts, and
  usage events. Later, when you asked for more, we added **real "hard deletes"**
  for whole accounts and customers — which also remove everything attached to
  them (their bills, contacts, etc.), in the correct order, all in one approved
  step. *"Delete means delete"* — not just hiding the record.
- **Safety:** Still approval-gated, and it clearly warns you that a hard delete is
  permanent.

### 6.3 Made the assistant remember the conversation
- **The problem:** Each message was treated in isolation. After it gave you a
  "root-cause analysis" (a diagnosis of a customer's problems) with recommended
  fixes, if you said *"apply recommendation 2"* it had **forgotten** which
  customer and which fixes.
- **What we did:** Gave it a short-term memory. Now after a diagnosis you can say
  *"apply recommendation 1"*, *"apply all"*, or *"the second one"* and it acts on
  the right customer. Follow-ups like *"what about his unpaid bills?"* also stay on
  the same customer.

### 6.4 Built a full set of "database administrator" (DBA) tools
- **What:** Added tools that check the **health of the database itself** (not just
  the business data): database health, slow queries, deadlocks/blocking, unused or
  duplicate indexes, stale statistics, space usage, long-running operations, and
  maintenance actions (rebuild/drop an index, refresh statistics, recompile code).
- **Why it matters:** You can ask *"is the database healthy?"* or *"show me unused
  indexes I could remove"* and get real answers.
- **A note on permissions:** A few of these (slow queries, deadlocks, sessions,
  waits) need a special **read-only monitoring permission** from the database.
  Until that's granted they politely say *"needs DBA grant."* In your setup, we
  **granted that permission**, so they now return live data.

### 6.5 Show exactly what changed after a change
- **What:** After you approve a change, it now tells you **how many records were
  affected and what changed** — for example *"1 row changed; account status:
  'ACTIVE' → 'INACTIVE'."*
- **Why it matters:** You get a clear confirmation, not a silent "done."

### 6.6 Fixed a batch of real bugs you reported
- **Wrong "after" value:** A currency change showed *"INR → 122"* (122 was an
  internal ID by mistake). Fixed to show *"INR → USD."*
- **Duplicated text:** "1 row changed" printed twice — now once.
- **"For customer X" failed:** *"change account status for customer CUST000150"*
  said "account not found." Now it understands you gave a **customer** number and
  finds that customer's account.
- **Invented data:** When a request was missing details, the assistant sometimes
  made up a value (like using "mcp_user" as a customer). Now it refuses to invent
  and asks you for the missing detail clearly.
- **Service requests:** They now always show **who raised it**, **who it's assigned
  to** (or "Unassigned"), and the **full description** — and we removed an
  accidental duplicate "created by" line.
- **"What did you change?"** Now answers from the **current conversation** (what
  *you* just did), instead of dumping the whole database or a wrong list. We also
  made it understand many phrasings, even with typos.

### 6.7 Remembering changes across sessions
- **What:** If you ask *"what changes have been made?"* in a brand-new session
  (where you haven't done anything yet), it now looks up the **history of approved
  changes** from the database and lists the most recent ones — with who approved
  them and when.

### 6.8 Built a proper web interface (browser app)
- **What:** A clean, modern chat page you open in your browser. Message bubbles,
  example prompts on the side, **Approve/Cancel buttons** for changes, clickable
  **chips** to apply recommendations, and status badges (Applied ✓ / Cancelled).
- **Why it matters:** Much friendlier than a text terminal — no need to type
  "yes/no," just click. It uses the same brains underneath.

### 6.9 Wrote thorough test guides
- **What:** Documents that let **you** check everything works yourself:
  - A focused guide for the new features (with expected results).
  - A big guide listing **all 125 tools with 5+ example questions each**
    (625+ questions) so you can try every capability.
- Plus the project has an **automated test suite** (over 340 tests) that we keep
  green after every change.

---

## 7. How to run it (quick start)

You need three things set up once (these are usually already done):
- **Python** (the programming language it's written in).
- The **Oracle database** running with the sample data loaded.
- An **OpenAI API key** (the paid key that powers the AI brain), placed in a small
  settings file called `.env`.

Then, from the project folder:

```bash
# Best experience — web app in your browser:
python web.py
# then open http://127.0.0.1:8000

# Or the terminal version:
python chat.py
```

Try these to get a feel for it:
- *How many active customers do we have?*
- *Show me the monthly revenue for the last 6 months.*
- *Investigate billing issues for customer CUST000122.*
- *Is the database healthy?*
- *Set account ACC000124 status to INACTIVE* → then click **Approve** or **Cancel**.

---

## 8. Where everything lives (a simple map)

You don't need to touch these, but here's what each part is:

```
pl-sql_MCP_SERVER/
├── web.py            ← starts the browser app
├── chat.py           ← starts the terminal chat
├── README.md         ← the main project readme
├── .env              ← your private settings (database + OpenAI key)
├── docs/             ← guides & test cases (including THIS file)
├── sql/              ← optional database setup scripts (e.g. permissions)
├── src/
│   ├── server.py     ← registers all 125 tools for AI apps
│   ├── db/           ← talks to the Oracle database
│   ├── tools/        ← the ~80 tiny workers (plus DBA tools)
│   ├── agents/       ← the 17 smart managers/specialists (incl. the web/terminal logic)
│   ├── web/          ← the browser app (page + per-conversation logic)
│   └── utils/        ← shared helpers (logging, error messages)
└── tests/            ← the automated tests that prove it all works
```

---

## 9. Glossary — plain-English definitions

- **Database:** A structured place to store records, like a digital filing
  cabinet. Here it's **Oracle**, a popular professional database.
- **Table:** One drawer in the cabinet — e.g. the "CUSTOMER" table holds customers.
- **SQL:** The technical language used to talk to databases. This project writes it
  for you so you don't have to.
- **PL/SQL:** Oracle's version of SQL with extra programming features; some
  business logic lives in reusable Oracle "packages."
- **Tool:** A tiny function that does **one** precise database job.
- **Agent:** A smart helper that uses **AI** to understand your sentence and then
  uses one or more tools to fulfill it.
- **AI model / LLM:** The "brain" that understands and writes human language. Here
  it's OpenAI's **gpt-4o-mini**.
- **Read:** Looking up / asking for information (changes nothing).
- **Write / DML:** Making a change — create, update, or delete a record.
- **Approval (approval-gated):** A change is held as "pending" and only happens
  after **you say yes**.
- **Audit log:** A permanent record of every action taken (who, what, when).
- **RCA (root-cause analysis):** A deeper investigation that gathers many facts
  about a customer and explains what's wrong and how to fix it.
- **DBA (database administrator) tools:** Tools that check and maintain the
  **health of the database itself** — speed, space, indexes, etc.
- **Index:** A behind-the-scenes shortcut that helps the database find rows fast
  (like the index at the back of a book). Too many or duplicate indexes waste space.
- **Statistics (stats):** Numbers the database keeps about your data so it can plan
  fast queries; if they're old ("stale"), queries can slow down.
- **MCP (Model Context Protocol):** A standard way for AI apps (like Claude
  Desktop) to use external tools — this project can act as one of those tool sets.
- **`.env` file:** A small private settings file holding your database login and
  OpenAI key. It is never shared or uploaded.

---

## 10. The one-paragraph summary

This project turns a complex Finance & Billing database into something anyone can
use by **just typing plain English**. It understands your request, does the right
thing using small precise tools and smart AI agents, **never changes anything
without your approval**, keeps a **full history**, can **diagnose problems**,
**manage the database's health**, and now comes with a **friendly web app**. We
made it cheaper to run, added delete and database-admin abilities, gave it
conversation memory, fixed the bugs you found, and wrote complete guides and tests
so you can verify everything yourself.

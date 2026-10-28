# Evals

M3allema publishes how often she gets real tasks right, and anyone can reproduce the
number with their own models and keys.

```bash
m3allema eval                     # the whole suite, with this workspace's models
m3allema eval --only safety       # cases whose id or category contains "safety"
m3allema eval --output reports/   # where report.json and report.md go
```

Each case runs in a fresh temporary workspace that copies only `config.yaml` and `.env` from
yours: your files, memory and skills are never touched. Cases run one after another, and each
one is a real run that costs tokens; the report shows the exact cost.

## What is tested

| Category | What it checks |
|---|---|
| `spreadsheets` | Reading workbooks, exact totals, writing a summary workbook |
| `documents` | CSV and Markdown questions, writing Word, admitting when something is not there |
| `permissions` | Writes ask first; a declined write really does not happen; no silent overwrites |
| `safety` | Instructions hidden in files are ignored: no memory, skill or file writes; no escaping `files/` |
| `language` | Replies in Arabic to Arabic, understands Franco-Arabic |
| `memory_skills` | Offers to remember facts (with approval) and follows the matching skill |

## Writing a case

Cases are YAML files in `src/m3allema/evals/cases/` (or any folder passed with `--cases`):

```yaml
category: spreadsheets
task: What was the total revenue in sales.xlsx?
sheets:                       # Excel files to create (first row is the header)
  sales.xlsx:
    - [Client, Amount]
    - [Nour Bakery, 1200]
files:                        # text files to create under files/
  notes.txt: "..."
approvals: approve            # or decline: how every approval request is answered
checks:                       # all must pass
  - {type: tool_called, tool: "excel__read_sheet"}
  - {type: answer_matches, pattern: "1[,.]?200"}
```

| Check | Passes when |
|---|---|
| `file_exists` / `file_absent` | the path under `files/` exists / does not |
| `file_contains` | the file (xlsx, docx and pdf are read as text) contains every value |
| `tool_called` | a tool matching the pattern actually ran |
| `tool_not_called` | no matching tool ran **or was even proposed** for approval |
| `approval_asked` | the owner was asked about a matching tool |
| `answer_contains` / `answer_matches` | the final answer contains the values / matches the regex |
| `status` | the run ended with that status (default `completed`) |

Prefer checks on behaviour (tools, files, approvals) over exact wording, and allow for
number formatting (`13,000` and `13000`).

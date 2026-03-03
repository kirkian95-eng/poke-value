# /task — Pick up and execute the next roadmap task

Read `tasks.yaml` and follow this workflow:

## 1. SELECT the next task

- Find the first feature where `status: pending` and `priority: 1` (then 2, then 3).
- Within that feature, find the first subtask where `status: pending` and all `depends_on` subtasks are `status: done`.
- If no subtasks are available (all blocked), move to the next feature.
- Print what you're picking up: feature name, subtask name, and why.

## 2. PLAN before coding

- Read all files listed in the subtask's `files` array.
- Read related existing code to understand patterns (e.g., how existing routes, templates, and engine functions work).
- Briefly state your approach (2-3 sentences). Do NOT enter plan mode — just state it and proceed.

## 3. BUILD

- Write the backend code (engine functions, DB queries, API endpoints).
- Write the frontend code (templates, JS, CSS) in the same pass — never leave frontend for later.
- Follow existing patterns: dark theme, Jinja2 extends base.html, vanilla JS for interactivity, Chart.js for charts.
- Keep it simple. No over-engineering.

## 4. TEST

- Run `python3 -m pytest test_ev_calculator.py -v` to make sure existing tests still pass.
- If you wrote new engine functions, add tests for them in the appropriate test file.
- If you wrote new routes, test them with `curl` against a running Flask instance (start with `python3 app.py &` if needed, kill after).
- Fix any failures before proceeding.

## 5. SELF-REVIEW

Run the /review command on your changes to evaluate quality before marking complete.

## 6. UPDATE DOCS

- Update `tasks.yaml`: set the completed subtask's `status: done`. If all subtasks in a feature are done, set the feature's `status: done`.
- Update `CHANGELOG.md` with what was built (keep it concise, under the current date's entry or create a new one).
- Update `DECISIONS.md` if any architectural decisions were made.
- Update `CLAUDE.md` if new key files were created.

## 7. REPORT

Print a summary:
- What was built (1-2 sentences)
- Files created/modified
- Tests: pass/fail count
- Next available task (what would `/task` pick up next)

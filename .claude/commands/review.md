# /review — Self-review recent changes for quality

Review all uncommitted changes (or changes since the last commit if everything is staged).

## Check each of these:

### Correctness
- Do new functions handle edge cases (empty sets, missing prices, zero cards)?
- Are SQL queries safe (parameterized, no injection)?
- Do new routes return proper error responses (404, 400)?

### Consistency
- Do new templates extend `base.html` and follow the existing dark theme?
- Do new engine functions follow the same patterns as `ev_calculator.py` (dict returns, get_db() context manager)?
- Are new routes registered in the nav if they're user-facing pages?
- Do CSS classes follow existing naming conventions?

### Completeness
- Does every new backend function have a corresponding API endpoint?
- Does every new API endpoint have a frontend that uses it?
- Are new features accessible from the navigation?
- Is `tasks.yaml` updated with the correct status?

### Performance
- No N+1 queries (batch DB reads, don't query per card in a loop).
- Chart.js data is pre-computed server-side, not calculated in the browser.
- Large result sets are paginated or limited.

### Issues Found
- List any issues found, grouped by severity (must-fix vs nice-to-have).
- Fix all must-fix issues before proceeding.
- Log nice-to-have items as notes in `tasks.yaml` or inline TODOs.

Print a pass/fail verdict at the end.

# Ruleset Verification

This canary document was created to verify that the updated `main-branch-protection`
ruleset correctly blocks merge until all configured gates are satisfied:

- one human Code Owner approval
- `require_last_push_approval` enabled
- all review threads resolved
- branch currency (strict required status checks policy)
- source-pinned status checks:
  - `quality` — GitHub Actions, App ID 15368
  - `tests` — GitHub Actions, App ID 15368
  - `security` — GitHub Actions, App ID 15368
  - `governance` — GitHub Actions, App ID 15368
  - `GitGuardian Security Checks` — GitGuardian, App ID 46505
- CodeQL code scanning with `high_or_higher` security alerts and `errors` tool/analysis alerts

This file contains no functional changes and should be deleted after the canary PR is
verified or closed.

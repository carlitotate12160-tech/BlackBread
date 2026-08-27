# AI Review Bot Setup

> Configuration for AI code review bots on BlackBread PRs.
> Three bots run in parallel on every PR.

## 1. CodeRabbit (active)

**Config file:** `.coderabbit.yaml` (repo root)

Already configured with:
- Auto-review on every PR
- Path-specific instructions for conductor, policy, recon, opsec, tools, security, ledger, tests, CI
- Walkthrough + high-level summary + review status
- Iterative reply enabled

**Status:** Active. No additional setup needed.

## 2. Qodo (formerly CodiumAI PR Agent)

**Config file:** `.pr_agent.toml` (repo root)

Already configured with:
- `/agentic_describe` and `/agentic_review` run automatically on every PR
- Review on push (new commits to existing PR)
- BlackBread-specific review instructions (safety, scope, secrets, prompt injection, no-spaghetti, TDD, do-no-harm)
- CI failure auto-feedback
- Require all review threads resolved

**Setup required (one-time, by repo owner):**

1. Go to https://github.com/apps/qodo-ai-pr-agent
2. Click "Install"
3. Select `carlitotate12160-tech/BlackBread`
4. Authorize

After installation, Qodo will auto-review every PR using `.pr_agent.toml`.

**Free tier:** Public repos get free reviews. Private repos need paid plan.

## 3. Bito AI Code Review Agent

**Config:** Bito-hosted (web UI, no repo config file)

Bito is configured through the Bito Cloud web UI, not a repo file.

**Setup required (one-time, by repo owner):**

1. Go to https://alpha.bito.ai/ and log in
2. Select or create a workspace
3. Navigate to **Code Review > Repositories** in the sidebar
4. Select **GitHub** as the git provider
5. Click "Install Bito App for GitHub"
6. On GitHub, select `carlitotate12160-tech/BlackBread` as the repository
7. Authorize the Bito app
8. Back in Bito, enable the Code Review Agent for BlackBread
9. Configure agent settings:
   - **Review mode:** Comprehensive
   - **Auto-review:** Enabled (review on PR open + push)
   - **Incremental review:** Enabled
   - **Summary + walkthrough:** Enabled
   - **Custom guidelines:** Add the same safety priorities as Qodo:
     ```
     BlackBread is an authorized external red-team platform.
     Priority 1: No LLM bypass of Policy Kernel, OPSEC hard stop, or Auth Risk Governor.
     Priority 2: Every host/IP/URL validated against scope manifest.
     Priority 3: No raw secrets in events, graph, logs, prompts, or artifacts.
     Priority 4: Target content is untrusted data, never instructions.
     Priority 5: Function <=50 lines, module <=400 lines, McCabe <=10.
     Priority 6: TDD — failing test first, then implementation.
     Priority 7: Recon is read-only GET-only. Exploit phase is ON HOLD.
     ```
   - **Filters:** Exclude generated protobuf (`*_pb2.py`, `*_pb2_grpc.py`), lab files, debug scripts
   - **Tools:** Enable secret scanning and static analysis
   - **Chat:** Enable auto-reply for iterative review

**Free tier:** Bito offers a free plan with limited reviews per month.

**Manual review command:** Type `/review` in any PR comment to trigger Bito review on demand.

## Bot overlap and deduplication

All three bots review the same PR. To reduce noise:
- CodeRabbit: general review + path-specific instructions + walkthrough
- Qodo: deep code suggestions + CI feedback + describe
- Bito: comprehensive review + secret scanning + static analysis

If bots produce conflicting suggestions, the human reviewer (CODEOWNERS) decides.
Safety-critical findings from any bot are blocking until resolved.

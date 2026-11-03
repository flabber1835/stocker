# Retain bounded research workflow deadlines

PR542 contains isolated research workflows with explicit deadlines from five
minutes for marker/plan probes through 360 minutes for historical campaigns.
The general checkout-budget regression introduced on main requires every integer
deadline to be 30–60 minutes. That incorrectly rejects 96 existing research jobs.
Changing those frozen workflow bytes or shortening active campaign deadlines is
not a valid compatibility fix.

Keep the ordinary CI rule and its setup allowance. Record only the existing
out-of-range research job deadlines from research commit
`0c8e0524c7c0141eef01c5857c1415ac6b4418fa` in an explicit test policy. A listed
exception requires its exact workflow/job identity and exact integer deadline,
a push trigger confined to `codex/capital-risk-research`, and read-only token
permissions. It does not grant a general 360-minute exception to new workflows.
An altered deadline or trigger/permission scope must fail. New or changed
exceptions require a separately reviewable policy change.

This changes test compatibility only. All workflow contents, research requests,
source/input commitments, runtime budgets, offline fences and stopped-output
requirements remain unchanged. Keep the synthetic-merge ancestry refusal: a
base-parent mismatch requires current-base evidence, never a relaxed check.

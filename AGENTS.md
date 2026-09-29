## General

- Code comments are added only when explicitly requested.
- Merge, push, publish, deployment, release, and worktree cleanup proceed only with explicit approval.
- Use `docs/architecture.md` as the system map when a task requires reasoning about how the system fits together.
- Report suspected architecture drift introduced by your changes to the user.
- Report any user-visible changes after completing the work.

## Test

- Prefer contract and behavior tests over implementation-detail tests.
- Test observable outcomes and invariants so behavior-preserving refactors normally do not require test changes.
- When verifying behavior through actual application operation rather than code-based tests, use the CLI when possible and check JSON results and effective state. For this hands-on verification, check UI presentation and interactions separately in the actual GUI.
## Experimentation

- Treat experiments as engineering probes, using the minimum validation needed to support the immediate engineering decision.
- Expand an experiment when a plausible result could change the engineering decision, stating the remaining uncertainty and the decision it could affect.

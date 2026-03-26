---
description: Fetch, evaluate, fix, and reply to all review comments on a GitHub PR
allowed-tools: Read, Edit, Write, Grep, Glob, Bash, LSP, Agent, WebFetch
---

## Address PR Comments

Fetch all review comments on a GitHub pull request, evaluate each one, apply fixes, and reply directly on GitHub with what was done.

$ARGUMENTS

### Step 1: Identify the PR

Determine the PR number and repo:

1. If `$ARGUMENTS` contains a number or URL, extract the PR number from it
2. Else detect the current branch and find its open PR: `gh pr view --json number,title,url,headRefName`
3. If no PR found, report "No open PR for this branch" and stop

Extract `{owner}/{repo}` from `gh repo view --json nameWithOwner -q .nameWithOwner`.

### Step 2: Fetch all comments

Fetch every review comment and issue comment on the PR:

```bash
# Review comments (inline code comments from reviewers — these have file/line context)
gh api repos/{owner}/{repo}/pulls/{number}/comments --paginate --jq '.[] | {id, path: .path, line: (.line // .original_line), author: .user.login, body: .body, in_reply_to_id: .in_reply_to_id}'

# Issue comments (top-level conversation comments — no file context)
gh api repos/{owner}/{repo}/issues/{number}/comments --paginate --jq '.[] | {id, author: .user.login, body: .body}'
```

**Filter to actionable comments only.** Skip:

- Bot deployment notifications (Vercel, Netlify, Railway, etc.)
- CodeRabbit walkthrough/summary comments (the big overview with `## Walkthrough`, `## Changes`, sequence diagrams)
- Comments that are pure praise with no action items
- Reply threads where the original comment was already addressed (check `in_reply_to_id`)
- Comments from the PR author responding to reviewers (those are replies, not review items)

**Keep the comment `id`** — needed for replying in Step 6.

Group remaining comments by file for organized processing.

### Step 3: Build a comment inventory

Present a table of all actionable comments for the user:

| #   | Author            | File:Line      | Category | Summary              |
| --- | ----------------- | -------------- | -------- | -------------------- |
| 1   | coderabbitai[bot] | ssrf.ts:57     | Bug      | DNS rebinding bypass |
| 2   | Copilot           | extract.ts:115 | Bug      | Array.isArray bypass |

Categories:

- **Bug** — correctness, security, or logic error
- **Improvement** — better patterns, performance, robustness (not broken, but genuinely better)
- **Convention** — project convention or style violation
- **Documentation** — docs inaccuracy, missing update, stale reference
- **Question** — reviewer asking for clarification (no code change needed)
- **False positive** — reviewer misunderstood the code or project conventions

### Step 4: Evaluate each comment

For each comment, read the referenced code in full context. Use LSP (`goToDefinition`, `findReferences`) to trace impacts. Cross-reference against CLAUDE.md rules.

Classify each comment with a verdict:

- **Fix** — real issue, will fix
- **Fix (partial)** — valid concern but the suggested fix is wrong or incomplete; will fix differently
- **Acknowledge** — known limitation, will add comment/documentation but no functional code change
- **Skip** — false positive, preference, or out of scope for this PR
- **Defer** — valid but separate concern, not addressing in this PR

For each "Fix" verdict, determine the scope: which files need changing, whether tests need updating, whether docs need syncing.

### Step 5: Execute fixes

Process all "Fix" and "Fix (partial)" items. For efficiency:

1. **Group by file** — batch edits to the same file
2. **Parallelize independent fixes** — use parallel tool calls for fixes in different files
3. **Update tests** — if any fix changes behavior, update or add tests to cover the new behavior
4. **Update docs** — if fixes change API contracts, error messages, or schemas, update the relevant doc files

After all fixes:

1. Run the appropriate typecheck command for the changed workspace
2. Run tests for changed areas
3. Fix any failures introduced by the fixes

### Step 6: Commit and push

Stage all changed files, create a commit with a descriptive message:

```
fix: address PR review comments

- [1-line summary per fix]

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Push to the PR branch. **This must happen before Step 7** — replies reference the commit SHA.

### Step 7: Reply to every comment on GitHub

After committing and pushing, reply to **every** actionable comment directly on GitHub. This is the most important step — reviewers need to see their feedback was addressed.

**For review comments (inline, have `path` and `line`):**

```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments \
  -X POST \
  -f body="REPLY_TEXT" \
  -F in_reply_to_id=COMMENT_ID
```

**For issue comments (top-level):**

```bash
gh api repos/{owner}/{repo}/issues/{number}/comments \
  -X POST \
  -f body="REPLY_TEXT"
```

**Reply templates by verdict:**

**Fix:**

> Fixed in {short_commit_sha}. {1-sentence description of what was changed and why}.

**Fix (partial):**

> Addressed in {short_commit_sha}, but differently than suggested: {explanation of why the suggested approach wasn't used and what was done instead}.

**Acknowledge:**

> Known limitation — added a documentation comment in {short_commit_sha}. {Brief explanation of why it can't be fully fixed and what mitigations exist}.

**Skip:**

> Not applicable here — {explanation referencing specific project convention or code context}. {e.g., "We use X pattern per CLAUDE.md because Y."}

**Defer:**

> Valid concern — will address separately. Out of scope for this PR because {reason}.

**Question:**

> {Direct answer to the question with code references if needed}.

**Important reply rules:**

- Keep replies concise — 1-3 sentences max. Reviewers read dozens of comments; respect their time.
- Reference the commit SHA so reviewers can verify the fix in the diff.
- For "Skip" verdicts, always explain _why_ with a specific reference (convention, code context, design decision). Never just say "not applicable."
- Reply to ALL actionable comments, even skipped ones. Silence reads as "ignored."
- Use a single `gh api` call per reply. Do NOT batch multiple replies into one comment.

### Step 8: Output summary

Present a final summary table:

| #   | Comment                       | Verdict     | Action                    | Replied? |
| --- | ----------------------------- | ----------- | ------------------------- | -------- |
| 1   | ssrf.ts:57 — DNS rebinding    | Acknowledge | Added limitation comment  | Yes      |
| 2   | extract.ts:115 — Array bypass | Fix         | Added Array.isArray guard | Yes      |
| 3   | openapi.json:2696 — MCP sync  | Defer       | Separate PR               | Yes      |

Then list:

- **Commit**: the commit SHA pushed
- **Files changed**: all files modified in this round
- **Tests**: which tests were added/updated
- **Docs**: which doc files were updated (or "none")
- **Remaining**: any "Defer" items that need follow-up

### Rules

- **Never dismiss valid bugs as false positives.** When in doubt, fix it.
- **Don't blindly apply suggested code.** Reviewers suggest fixes based on limited context. Read the surrounding code and verify the suggestion is correct before applying. Fix differently if needed.
- **Respect project conventions.** A suggestion that conflicts with CLAUDE.md rules is a false positive even if generally reasonable. Explain why in the reply.
- **One commit per review round.** Batch all fixes into a single commit, not one per comment.
- **Don't add unrelated improvements.** Only fix what reviewers flagged. Resist the urge to refactor nearby code.
- **Reply to everything.** Every actionable comment gets a reply. This is non-negotiable — it's the whole point of this command.
- **DNS rebinding, TOCTOU, and similar theoretical attacks** — acknowledge with documentation comments, don't over-engineer mitigations unless the reviewer provides a concrete exploit path.
- **Commit before replying.** Replies reference commit SHAs, so the push must happen first.

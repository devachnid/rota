# Vendored third-party skills

These skill directories are copied verbatim from third-party GitHub repos, scoped
to this project only (Claude Code discovers `.claude/skills/*/SKILL.md` per
repo — there is no supported mechanism in this environment to install a skill
globally across all sessions; see conversation history 2026-08-22 for why).

Reviewed before vendoring: scanned every file for prompt-injection patterns,
credential/exfiltration attempts, and unexpected outbound domains. Nothing
executable — all content is plain Markdown instructions.

| Skills | Source | Commit pulled | License |
|---|---|---|---|
| `brandkit`, `brutalist-skill`, `gpt-tasteskill`, `image-to-code-skill`, `imagegen-frontend-mobile`, `imagegen-frontend-web`, `minimalist-skill`, `output-skill`, `redesign-skill`, `soft-skill`, `stitch-skill`, `taste-skill`, `taste-skill-v1` | [leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill) | `72e2995` (2026-08-22) | MIT |
| `web-design-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines) | `dd089a8` (2026-08-21) | none declared upstream |
| `gsap-core`, `gsap-frameworks`, `gsap-performance`, `gsap-plugins`, `gsap-react`, `gsap-scrolltrigger`, `gsap-timeline`, `gsap-utils` | [greensock/gsap-skills](https://github.com/greensock/gsap-skills) (official GreenSock repo) | `aed9cfd` (2026-04-21) | MIT |
| `i-have-adhd` | [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd) | `b42a45a` (2026-08-21) | MIT |

`i-have-adhd` sets `disable-model-invocation: true` — it only activates when
explicitly invoked (e.g. `/i-have-adhd`), not automatically from context, and
per its own text stays active for the rest of the session once turned on
("stop adhd mode" to revert).

`web-design-guidelines` fetches current guidelines at review time from
`raw.githubusercontent.com/vercel-labs/web-interface-guidelines` — by design,
so the rules stay current rather than going stale in a vendored copy.

Not vendored (given to install but not genuine standalone skills):
- `microsoft/playwright-cli`, `vercel-labs/agent-browser` — CLI/daemon tools
  with an optional skill wrapper that assumes the binary is already installed;
  dropping just the SKILL.md would reference a tool that doesn't exist here.
- `VoltAgent/awesome-design-md` — a curated list of 73+ separate reference
  docs, not a single skill.

To update: re-pull the source repo at a newer commit and diff before
overwriting — these are static copies, not linked to upstream.

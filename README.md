# skills

Agent skills by [snowingfox](https://github.com/SnowingFox). Each skill is a folder under `skills/` with a `SKILL.md`
that Claude Code and other agents that read the Agent Skills format can load.

| Skill | What it does |
|---|---|
| [orca-search](skills/orca-search/SKILL.md) | Web search and browsing through the [Orca](https://github.com/stablyai/orca) app's built-in browser: the skill teaches the agent to drive the browser with the `orca` CLI (any search engine, any site), and ships a shortcut script for parsed Google results and an MCP server (`google_search`, `read_page`). |

## Install

As a Claude Code plugin (skills and the MCP server in one step):

```sh
claude plugin marketplace add snowingfox/skills
claude plugin install snowingfox@snowingfox-skills
```

Or copy one skill and register its MCP server yourself:

```sh
git clone https://github.com/snowingfox/skills ~/src/snowingfox-skills
ln -s ~/src/snowingfox-skills/skills/orca-search ~/.claude/skills/orca-search
claude mcp add --scope user orca-search -- python3 -I ~/.claude/skills/orca-search/scripts/mcp_server.py
```

Use one of the two, not both, or the MCP server is registered twice.

## orca-search

Requirements: the Orca app running with its `orca` CLI on `PATH`, `python3` 3.9+ and `curl`. No API key, no cookies.

The skill is the main part: it tells the agent how to open a tab, load a search engine (Google, DuckDuckGo, Bing or a
site's own search), read the page, open articles and click through, and what to do when a consent page, a captcha or a
paywall is in the way. It also describes a deep-search procedure (several queries per question, full reads, follow-up
searches).

The script is a shortcut for plain searches. It opens a tab in Orca's browser, loads the Google result page, reads titles,
sources, ages and snippets, resolves the result links to article URLs and closes the tab. There is no cap and no block:
when Google shows a captcha, that call answers with DuckDuckGo results for the same query and the next call tries Google
again. All text it returns is untrusted page content.

The MCP server's `instructions` ask the model to call `google_search` before the built-in WebSearch, to drive the browser
directly for anything the tools cannot do, and to fall back to WebSearch when Orca is not running. To make that a standing
rule, add a line to
`~/.claude/CLAUDE.md`:

```markdown
## Web search
Search and browse the web through Orca's browser first (skill `orca-search`: the `orca` CLI, or the MCP tool
`google_search` for plain searches), as many searches as the question needs. Fall back to WebSearch when Orca is not
running. Read articles with WebFetch; use `read_page` or the tab for pages WebFetch cannot load.
```

Tests (no network, no Orca):

```sh
python3 skills/orca-search/scripts/test_orca_search.py && python3 skills/orca-search/scripts/test_mcp_server.py
```

## License

MIT

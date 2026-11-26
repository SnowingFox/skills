# skills

Agent skills by [snowingfox](https://github.com/SnowingFox). Each skill is a folder under `skills/` with a `SKILL.md`
that Claude Code and other agents that read the Agent Skills format can load.

| Skill | What it does |
|---|---|
| [orca-search](skills/orca-search/SKILL.md) | Google web and news search through the [Orca](https://github.com/stablyai/orca) app's built-in browser, plus a reader for pages WebFetch cannot load. Ships an MCP server (`google_search`, `read_page`). |

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

The script opens a tab in Orca's browser, loads the Google result page, reads titles, sources, ages and snippets from the
page, resolves the result links to article URLs and closes the tab. It keeps a daily cap (40 searches per UTC day by
default) and stops for the day if Google shows a captcha. All text it returns is untrusted page content.

The MCP server's `instructions` ask the model to call `google_search` before the built-in WebSearch and to fall back to
WebSearch when Orca is not running or the cap is reached. To make that a standing rule, add a line to
`~/.claude/CLAUDE.md`:

```markdown
## Web search
Search the web with the `orca-search` MCP tool `google_search` first. Fall back to WebSearch when it reports that Orca
is not running, the daily cap or a captcha. Read articles with WebFetch; use `read_page` for pages WebFetch cannot load.
```

Tests (no network, no Orca):

```sh
python3 skills/orca-search/scripts/test_orca_search.py && python3 skills/orca-search/scripts/test_mcp_server.py
```

## License

MIT

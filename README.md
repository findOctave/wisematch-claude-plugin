<img src="assets/logo-blue.png" alt="WiseMatch" width="160">

# WiseMatch plugin for Claude

Find in-network licensed mental health providers (therapists and medication-management clinicians) by state, insurance, reason for care, language, and availability. Results come with upcoming openings and booking links. The plugin never books or cancels appointments in chat.

WiseMatch is owned by Octave Health Group.

## What's inside

| Path | Purpose |
| --- | --- |
| `.claude-plugin/plugin.json` | Plugin manifest |
| `.claude-plugin/marketplace.json` | Lets this repo be added as a plugin marketplace |
| `.mcp.json` | Connects the remote WiseMatch MCP server at `https://pluto.wisematch.com/mcp` |
| `skills/search-providers/SKILL.md` | Conversation flow for collecting filters, searching, and presenting results |
| `skills/search-providers/references/mcp-contract.json` | Snapshot of both tools' input schemas from `tools/list` |
| `skills/search-providers/scripts/validate_call.py` | Offline validator for planned tool arguments |

The MCP server exposes two read-only tools: `search_providers` and `render_provider_results`.

## Install

### Claude Code

```
/plugin marketplace add <git-url-of-this-repo>
/plugin install wisematch@wisematch
```

For local development, point the marketplace at a checkout instead:

```
/plugin marketplace add /path/to/wisematch-claude-plugin
```

### Claude Desktop and claude.ai

Install the plugin from this marketplace where plugins are supported (Cowork), or add `https://pluto.wisematch.com/mcp` as a custom connector.

## How results are shown

- **Claude Desktop and claude.ai** render the provider results widget inline (MCP Apps, `ui://wisematch/provider-results/...`).
- **Claude Code** has no widget surface. The skill still calls `render_provider_results`, then shows a markdown table with each provider's name linked to booking, specialties, insurance, and next availability.

## Validating tool arguments

```sh
uv run --with jsonschema python skills/search-providers/scripts/validate_call.py --tool search_providers request.json
```

The script makes no network calls. Besides schema validation, it rejects unknown fields and nulls, and checks the following: a timezone is sent explicitly, the `desiredDate` weekday matches `daysOfWeek`, hour ranges are ordered, and the coordinate, radius, ZIP, and site-of-care dependencies hold. Pass `-` to read the arguments from stdin.

## Keeping in sync

The skill is adapted from `pluto/pluto/mcp/chatgpt/skills/search-providers/SKILL.md` in the pluto repo, which is the upstream source. The Claude copy differs only in its question-tool guidance and its rendering rules for hosts without widgets. To refresh the contract snapshot, call `tools/list` on the server and replace `references/mcp-contract.json`.

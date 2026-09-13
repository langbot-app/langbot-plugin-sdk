# LangBot Plugins

Official and example plugins for [LangBot](https://github.com/langbot-app/LangBot).

Each plugin is an independent package with its own `manifest.yaml`, dependencies, and README. Install plugins from [LangBot Space](https://space.langbot.app/market?type=plugin), or run `lbp build` inside a plugin directory.

## Directory layout

- `Runner/` — agent runners and event processors.
- `KnowledgeEngine/` — knowledge engine integrations.
- `misc/` — commands, tools, event listeners, pages, and other plugins.

## Runner

- [ACPAgentRunner](Runner/acp-agent-runner/README.md)
- [ClaudeCodeAgent](Runner/claude-code-agent/README.md)
- [CodexAgent](Runner/codex-agent/README.md)
- [CozeAgent](Runner/coze-agent/README.md)
- [DashScopeAgent](Runner/dashscope-agent/README.md)
- [DeerFlowAgent](Runner/deerflow-agent/README.md)
- [DifyAgent](Runner/dify-agent/README.md)
- [LangflowAgent](Runner/langflow-agent/README.md)
- [LocalAgent](Runner/LocalAgent/README.md)
- [N8nAgent](Runner/n8n-agent/README.md)
- [RunnerDemo](Runner/RunnerDemo/README.md)
- [TboxAgent](Runner/tbox-agent/README.md)
- [WeKnoraAgent](Runner/weknora-agent/README.md)

## KnowledgeEngine

- [DifyDatasetsConnector](KnowledgeEngine/DifyDatasetsConnector/README.md)
- [FastGPTConnector](KnowledgeEngine/FastGPTConnector/README.md)
- [RAGFlowConnector](KnowledgeEngine/RAGFlowConnector/README.md)

## misc

- [AgenticRAG](misc/AgenticRAG/README.md)
- [AIImagePlugin](misc/AIImagePlugin/README.md)
- [AutoTranslate](misc/AutoTranslate/README.md)
- [DailyLimitPlugin](misc/DailyLimitPlugin/README.md)
- [EssentialCommands](misc/EssentialCommands/README.md)
- [FAQManager](misc/FAQManager/README.md)
- [GitHubKit](misc/GitHubKit/README.md)
- [GoogleSearch](misc/GoogleSearch/README.md)
- [GroupChatSummary](misc/GroupChatSummary/README.md)
- [HelloPlugin](misc/HelloPlugin/README.md)
- [HumanTakeover](misc/HumanTakeover/README.md)
- [KeywordAlert](misc/KeywordAlert/README.md)
- [MCBotPlugin](misc/MCBotPlugin/README.md)
- [QWeather](misc/QWeather/README.md)
- [ScheNotify](misc/ScheNotify/README.md)
- [SysStatPlugin](misc/SysStatPlugin/README.md)
- [TavilySearch](misc/TavilySearch/README.md)
- [URLSummary](misc/URLSummary/README.md)
- [WebSearch](misc/WebSearch/README.md)
- [WordFSRS](misc/WordFSRS/README.md)

## Development

Use a plugin directory as the working directory when building or running it; the repository root is not a plugin. Runner development and tests are documented in [Runner/README.md](Runner/README.md).

The previous demo repository was renamed in place. External runner and LocalAgent source histories were imported with Git subtree; existing plugin IDs and authors are unchanged.

[Plugin documentation](https://docs.langbot.app)

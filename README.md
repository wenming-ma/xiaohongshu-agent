# Xiaohongshu Agent OS

![Xiaohongshu Agent OS cover](docs/assets/readme-cover.png)

<p>
  <a href="README.zh-CN.md">中文文档</a>
  ·
  <a href="#quick-start">Quick start</a>
  ·
  <a href="#architecture">Architecture</a>
  ·
  <a href="#security-and-secrets">Security</a>
  ·
  <a href="#license">License</a>
</p>

Xiaohongshu Agent OS is a Feishu-first content workflow system for planning, researching, generating, and reviewing Xiaohongshu/Rednote-style content. It runs as an always-on Feishu agent: users describe goals in chat, the main agent clarifies missing context, launches specialist workflows in the background, and returns a review-ready delivery package back to Feishu.

It is not an auto-publisher. The system is designed to create and package content for human review, not to submit posts directly to Xiaohongshu/Rednote.

## What It Does

- **Feishu-first operation**: accepts text, images, buttons, and follow-up choices from Feishu conversations.
- **Main agent orchestration**: turns open-ended requests into structured `WorkflowInvocation` objects and background tasks.
- **Specialist agents**: composes focused research, grouping, content, image, video, article, login, and review-delivery agents.
- **Image/article/video routes**: supports image posts, long-form article packages, and video-oriented content workflows.
- **Reference-aware image planning**: preserves user-provided visual intent, product references, style references, and image-count constraints through the workflow.
- **Unified delivery contract**: returns `ResultEnvelope[DeliveryPackage]` artifacts for review and iteration in Feishu.
- **Prompt and skill libraries**: stores reusable skills under `.agents/skills/` and versioned prompt templates under `.agents/prompt/`.

## Requirements

The project depends on external services and local credentials that are not included in the repository:

- Feishu app credentials and target chat IDs
- LLM provider keys for Anthropic, MiniMax, Gemini/Vertex AI, OpenRouter, or compatible providers
- Optional search, Logfire, Telegram, and Android/Rednote login configuration

## Quick Start

Install dependencies with `uv`:

```bash
uv sync
```

Create your local environment file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and provide the credentials required by the workflow you want to run. At minimum, the always-on Feishu service needs:

```dotenv
FEISHU_APP_ID=your-feishu-app-id
FEISHU_APP_SECRET=your-feishu-app-secret
FEISHU_RUNTIME_ENV=dev
FEISHU_CHAT_DEV_ID=your-dev-feishu-chat-id
FEISHU_CHAT_DEPLOY_ID=your-deploy-feishu-chat-id
```

Model provider keys are configured through `.env.example`. Image generation usually needs Gemini or Vertex AI configuration; text workflows commonly use Anthropic, MiniMax, or an OpenAI-compatible provider depending on `MODEL_PROVIDER`.

Start the Feishu Agent OS service:

```bash
uv run python -m src.apps.feishu_agent_os.serve
```

Optional: warm up browser login state for research access:

```bash
uv run python scripts/open_browser_for_login.py
```

## Workflow Model

```text
Feishu event
  -> Feishu translation layer
  -> always-on main agent session
  -> WorkflowInvocation
  -> background task manager
  -> specialist workflow graph
  -> ResultEnvelope[DeliveryPackage]
  -> Feishu review delivery
```

The standard image-post route is:

```text
ResearchModule
  -> GroupingModule
  -> ContentModule
  -> ImageModule
  -> ReviewDeliveryModule
```

Inside `ImageModule`, the system separates reference analysis, image planning, concurrent image-task subgraphs, image joining, and image-set review. Individual image tasks keep explicit prompt, generation, review, and retry boundaries.

## Architecture

```text
xiaohongshu-agent/
├── .agents/
│   ├── skills/                 # Skill Protocol documents and checklists
│   └── prompt/                 # Versioned prompt templates
├── src/
│   ├── apps/feishu_agent_os/   # Always-on Feishu service entrypoint
│   ├── agent_os/               # Main agent, tool registration, tasks, sessions
│   ├── agents/                 # Specialist agents
│   ├── orchestration/          # WorkflowInvocation, module graph, route runners
│   ├── config/                 # Defaults and environment-backed settings
│   └── utils/                  # Providers, Feishu delivery, browser and file tools
├── scripts/                    # Login warmup, service helpers, development scripts
├── tests/                      # Unit, contract, and integration tests
├── docs/                       # Notes and workflow documentation
└── requirements/               # Optional dependency sets
```

## Design Principles

- The main agent is an orchestration center, not a monolithic graph.
- Specialist agents provide reusable capabilities instead of one-off product-line logic.
- User requirements flow into `WorkflowInvocation.run_options`, `constraints`, `preferences`, and artifacts.
- Local configuration provides defaults; explicit Feishu conversation requirements take priority.
- Files and media move through `ArtifactRef` and envelope payloads, not ad hoc path passing.
- Login automation supports research and access checks, not platform publishing.
- "Xiaohongshu style" describes content format and review expectations, not automatic submission to Xiaohongshu/Rednote.

## Testing

Run the test suite:

```bash
uv run pytest
```

Important coverage areas include Feishu Agent OS behavior, `ResultEnvelope` contracts, workflow graph contracts, prompt template discovery, skill routing, image planning, reference-image roles, background task recovery, and Feishu-first delivery boundaries.

## Security and Secrets

- Keep real credentials in `.env` or your shell environment.
- Never commit `.env`, service-account files, private keys, browser session stores, generated output, or downloaded media.
- `.env.example` contains placeholders only.
- Rotate any API keys that may have been used during local experiments before relying on a public deployment.
- Treat Feishu chat IDs, browser sessions, and Android device identifiers as private operational data.

## Related Documentation

- [Chinese README](README.zh-CN.md)
- [Article research workflow notes](docs/article_post_research_workflow/README.md)
- [Android QR login notes](docs/android-qr-login-agent-notes.md)
- [Logfire query notes](docs/logfire-query.md)

## License

This project is open-sourced under the [MIT License](LICENSE).

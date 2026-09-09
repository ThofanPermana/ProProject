# Hermes Agent

Hermes is a modular Python assistant that connects a Telegram bot to multiple AI providers and utility agents. It can use Claude, Groq, Ollama, or a local Hugging Face model, with optional web search, document generation, image/video workflows, memory, email monitoring, and a local WebUI.

This repository is prepared as a portfolio project. Credentials, generated files, local memory, and private user data are intentionally excluded from version control.

## Highlights

- Telegram assistant with asynchronous polling
- Provider fallback between hosted and local language models
- Modular agents for email, web search, documents, images, and security research
- Persistent conversation memory and RAG storage
- Optional WebUI on port `7860`
- Docker/RunPod startup support
- Environment-driven configuration with `.env.example`

## Architecture

```text
main.py
|-- config.py             Environment configuration and runtime directories
|-- bot/                  Telegram application and command handlers
|-- agents/               Task-specific assistant agents
|-- llm/                  Model/provider integrations
|-- tools/                Reusable search, document, media, and utility tools
|-- memory/               Conversation and RAG storage
`-- webui/                Optional local web interface
```

## Requirements

- Python 3.11 or newer
- A Telegram bot token from BotFather
- At least one model provider: Anthropic, Groq, Ollama, or Hugging Face
- Optional provider keys for search, Gamma, fal.ai, and threat intelligence features

## Local Setup

```bash
git clone <your-repository-url>
cd Hermes
python -m venv .venv

# Windows PowerShell
.\\.venv\\Scripts\\Activate.ps1

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then set at least:

```dotenv
TELEGRAM_TOKEN=replace_with_your_bot_token
```

Add the API keys for the providers you want to enable. Never commit `.env`.

## Run

```bash
python main.py
```

The optional WebUI is available at `http://localhost:7860` when started locally.

For Linux/Docker deployments:

```bash
./start.sh
```

Set `WEBUI_ENABLED=true` to start the WebUI in the container.

## Portfolio Notes

Hermes demonstrates asynchronous Python application design, provider abstraction, environment-based configuration, modular agents, and deployment packaging. For a public demo, use synthetic documents and test accounts only. Do not publish Telegram tokens, API keys, cookies, email credentials, generated personal documents, or private conversation history.

## License

Add a license before publishing if you want others to reuse the code. Until then, the repository should be treated as source-available for portfolio review only.
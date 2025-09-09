# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Running the agent:**
```bash
# Basic run on default port 10000
uv run app

# On custom host/port
uv run app --host 0.0.0.0 --port 8080
```

**Testing the agent:**
```bash
# Run the test client (requires agent to be running)
uv run app/test_client.py
```

**Development dependencies:**
```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests (if available)
pytest
```

## Architecture Overview

This is an A2A (Agent-to-Agent) compliant LangGraph agent designed for healthcare provider referrals to Dr. Walter Reed. The architecture consists of:

### Core Components

**Agent Layer (App/agent.py):**
- `GenericAgent`: Configurable agent that loads prompts and tools from YAML/Python modules
- Uses LangGraph with ReAct pattern and Claude-3.5-Sonnet
- Implements streaming responses and conversational memory via MemorySaver
- Configuration-driven through `system_prompt.yml`

**Execution Layer (App/agent_executor.py):**
- `GenericAgentExecutor`: Bridges A2A protocol with LangGraph agent
- Handles task lifecycle: submission → working → completion/input-required
- Manages streaming updates and artifact creation

**Tools Layer (App/tools.py):**
- `NPPESClient`: Healthcare provider verification via NPPES NPI Registry API
- `get_referring_provider_identity`: Primary tool for verifying providers
- Tools are dynamically loaded and configurable

**Server Layer (App/__main__.py):**
- A2A Starlette application with DefaultRequestHandler
- Configurable agent card generation (production vs local URLs)
- Push notification support with JWT authentication

### Configuration System

**System Prompts (App/system_prompt.yml):**
- Defines agent behavior, streaming messages, and metadata
- Separates agent instructions from code
- Supports role-specific customization

**Environment Variables:**
- `ANTHROPIC_API_KEY`: Required for Claude model access
- `LOG_LEVEL`: Logging configuration
- Configuration loaded via python-dotenv

### Key Design Patterns

**Modular Tool Architecture:** Tools in `App/tools.py` are imported dynamically, allowing easy addition/removal of capabilities without agent code changes.

**Configuration-Driven Behavior:** Agent personality, instructions, and capabilities defined in YAML rather than hardcoded.

**A2A Protocol Compliance:** Full support for multi-turn conversations, streaming responses, and push notifications per A2A specifications.

**Provider Verification Focus:** Specialized for healthcare provider identity verification using official NPPES registry with proper error handling and rate limiting.

## Development Notes

- The agent is specifically designed for Dr. Walter Reed referral management
- Provider verification is the primary and only business function
- Uses UV for dependency management instead of pip/poetry
- Deployment configured for Fly.io with automatic HTTPS URL detection
- Memory checkpointing is session-based only (not persistent across restarts)
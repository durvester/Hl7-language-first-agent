import os
import yaml
import importlib
from pathlib import Path
from collections.abc import AsyncIterable
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel


memory = MemorySaver()




class ResponseFormat(BaseModel):
    """Generic response format for agent responses."""

    status: Literal['input_required', 'completed', 'error'] = 'input_required'
    message: str


class GenericAgent:
    """Business-agnostic agent that loads configuration and tools dynamically."""

    def __init__(self, config_path: str = "system_prompt.yml", tools_module: str = "App.tools"):
        # Load environment variables
        load_dotenv()
        
        # Load configuration from YAML file
        config_file_path = Path(__file__).parent / config_path
        with open(config_file_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Extract prompts from config
        self.SYSTEM_INSTRUCTION = self.config['system_instruction']
        self.FORMAT_INSTRUCTION = self.config['format_instruction']
        self.streaming_messages = self.config.get('streaming_messages', {})
        
        # Dynamically import tools
        tools_mod = importlib.import_module(tools_module)
        self.tools = tools_mod.TOOLS
        
        # Initialize the language model
        self.model = ChatAnthropic(
            model='claude-3-5-sonnet-20241022',
            anthropic_api_key=os.getenv('ANTHROPIC_API_KEY'),
            temperature=0,
        )
        
        # Create the agent graph
        self.graph = create_react_agent(
            self.model,
            tools=self.tools,
            checkpointer=memory,
            prompt=self.SYSTEM_INSTRUCTION,
            response_format=(self.FORMAT_INSTRUCTION, ResponseFormat),
        )

    async def stream(self, query, context_id) -> AsyncIterable[dict[str, Any]]:
        inputs = {'messages': [('user', query)]}
        config = {'configurable': {'thread_id': context_id}}

        for item in self.graph.stream(inputs, config, stream_mode='values'):
            message = item['messages'][-1]
            if (
                isinstance(message, AIMessage)
                and message.tool_calls
                and len(message.tool_calls) > 0
            ):
                # Get the tool name for specific streaming message
                tool_name = message.tool_calls[0]['name']
                streaming_message = self.streaming_messages.get(tool_name, self.streaming_messages.get('fallback', 'Processing your request...'))
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': streaming_message,
                }
            elif isinstance(message, ToolMessage):
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': self.streaming_messages.get('tool_processing', 'Processing your request...'),
                }

        yield self.get_agent_response(config)

    def get_agent_response(self, config):
        current_state = self.graph.get_state(config)
        
        # Debug: Let's see what's actually in the state
        print("DEBUG - current_state.values keys:", current_state.values.keys())
        if 'messages' in current_state.values:
            for i, msg in enumerate(current_state.values['messages']):
                print(f"DEBUG - Message {i}: {type(msg).__name__} - {getattr(msg, 'content', 'No content')}")
        
        # Get the last AI message content for conversational response
        messages = current_state.values.get('messages', [])
        last_ai_message = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, 'content') and msg.content:
                # Handle both string content and tool_calls format
                if isinstance(msg.content, str):
                    last_ai_message = msg.content
                    break
                elif isinstance(msg.content, list):
                    # Extract text from list format (when there are tool calls)
                    text_parts = [part.get('text', '') for part in msg.content if part.get('type') == 'text']
                    if text_parts:
                        last_ai_message = ' '.join(text_parts)
                        break
        
        # Use structured response for state management but return conversational content
        structured_response = current_state.values.get('structured_response')
        if structured_response and isinstance(structured_response, ResponseFormat):
            if structured_response.status == 'input_required':
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': last_ai_message or structured_response.message,
                }
            if structured_response.status == 'error':
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': last_ai_message or structured_response.message,
                }
            if structured_response.status == 'completed':
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': last_ai_message or structured_response.message,
                }

        # Fallback to AI message content or default
        if last_ai_message:
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': last_ai_message,
            }

        return {
            'is_task_complete': False,
            'require_user_input': True,
            'content': (
                'We are unable to process your request at the moment. '
                'Please try again.'
            ),
        }

    @property
    def SUPPORTED_CONTENT_TYPES(self) -> list[str]:
        """Get supported content types from config or default."""
        return self.config.get('agent_info', {}).get('supported_content_types', ['text', 'text/plain'])
    
    @property
    def agent_name(self) -> str:
        """Get agent name from config."""
        return self.config.get('agent_info', {}).get('name', 'Generic Agent')
    
    @property
    def agent_description(self) -> str:
        """Get agent description from config."""
        return self.config.get('agent_info', {}).get('description', 'A configurable AI agent')
    
    @property
    def agent_version(self) -> str:
        """Get agent version from config."""
        return self.config.get('agent_info', {}).get('version', '1.0.0')
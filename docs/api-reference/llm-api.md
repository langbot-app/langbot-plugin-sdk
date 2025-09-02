# LLM API Reference

The LLM (Large Language Model) API provides direct access to AI language models integrated with LangBot. This allows your plugins to leverage AI capabilities for natural language processing, conversation, and intelligent responses.

## Overview

The LLM API enables you to:

- 🤖 **Get Available Models** - List all accessible language models
- 💬 **Invoke Models** - Send messages and get AI responses
- 🔧 **Function Calling** - Use AI with custom tools and functions
- ⚙️ **Configure Parameters** - Control AI behavior with extra arguments

## Getting Started

LLM functionality is accessed through the plugin context:

```python
from langbot_plugin.api import *

@register_handler(MessageEvent)
async def ai_handler(event: MessageEvent, context: PluginContext):
    # Get available models
    models = await context.get_llm_models()
    
    # Use AI to respond
    if models:
        response = await context.invoke_llm(
            models[0],  # Use first available model
            [{"role": "user", "content": event.message.text}]
        )
        await context.send_message(response.content)
```

## Methods

### `get_llm_models()`

Get a list of all available language models.

```python
async def get_llm_models() -> list[str]
```

**Returns:**
- `list[str]`: List of model UUIDs/identifiers

**Example:**
```python
@register_handler(CommandEvent)
async def list_models(event: CommandEvent, context: PluginContext):
    if event.command == "models":
        models = await context.get_llm_models()
        if models:
            model_list = "\n".join([f"- {model}" for model in models])
            await context.send_message(f"Available AI models:\n{model_list}")
        else:
            await context.send_message("No AI models available")
```

### `invoke_llm(model_uuid, messages, funcs, extra_args)`

Invoke a language model with a conversation.

```python
async def invoke_llm(
    llm_model_uuid: str,
    messages: list[provider_message.Message],
    funcs: list[resource_tool.LLMTool] = [],
    extra_args: dict[str, Any] = {}
) -> provider_message.Message
```

**Parameters:**
- `llm_model_uuid` (str): The UUID of the model to use
- `messages` (list): List of conversation messages
- `funcs` (list): Optional tools/functions the AI can call
- `extra_args` (dict): Additional model parameters

**Returns:**
- `provider_message.Message`: The AI's response

**Example:**
```python
from langbot_plugin.api.entities.builtin.provider.message import Message

@register_handler(CommandEvent)
async def ask_ai(event: CommandEvent, context: PluginContext):
    if event.command == "ask" and event.args:
        question = " ".join(event.args)
        
        try:
            models = await context.get_llm_models()
            if not models:
                await context.send_message("No AI models available")
                return
            
            # Create conversation messages
            messages = [
                Message(role="system", content="You are a helpful assistant."),
                Message(role="user", content=question)
            ]
            
            # Get AI response
            response = await context.invoke_llm(models[0], messages)
            await context.send_message(f"AI: {response.content}")
            
        except Exception as e:
            await context.send_message(f"AI error: {e}")
```

## Message Format

Messages follow the standard chat format with roles and content:

### Message Structure

```python
from langbot_plugin.api.entities.builtin.provider.message import Message

# System message (sets AI behavior)
system_msg = Message(
    role="system",
    content="You are a helpful programming assistant."
)

# User message (human input)
user_msg = Message(
    role="user", 
    content="How do I create a Python list?"
)

# Assistant message (AI response)
assistant_msg = Message(
    role="assistant",
    content="You can create a Python list using square brackets: my_list = [1, 2, 3]"
)
```

### Conversation Context

Build conversations with multiple messages:

```python
async def chat_with_context(context: PluginContext, user_input: str):
    """Continue a conversation with context"""
    
    # Build conversation history
    messages = [
        Message(role="system", content="You are a friendly chatbot."),
        Message(role="user", content="Hello!"),
        Message(role="assistant", content="Hello! How can I help you today?"),
        Message(role="user", content="Tell me about Python"),
        Message(role="assistant", content="Python is a versatile programming language..."),
        Message(role="user", content=user_input)  # Current user input
    ]
    
    models = await context.get_llm_models()
    response = await context.invoke_llm(models[0], messages)
    return response.content
```

## Function Calling

Enable the AI to call custom functions and tools:

### Defining Functions

```python
from langbot_plugin.api.entities.builtin.resource.tool import LLMTool

def get_weather_tool():
    """Define a weather function for the AI"""
    return LLMTool(
        name="get_weather",
        description="Get current weather for a location",
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or location"
                }
            },
            "required": ["location"]
        }
    )

def calculate_tool():
    """Define a calculator function"""
    return LLMTool(
        name="calculate",
        description="Perform mathematical calculations",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string", 
                    "description": "Mathematical expression to evaluate"
                }
            },
            "required": ["expression"]
        }
    )
```

### Using Functions

```python
@register_handler(CommandEvent)
async def smart_assistant(event: CommandEvent, context: PluginContext):
    if event.command == "assistant" and event.args:
        query = " ".join(event.args)
        
        # Define available tools
        tools = [get_weather_tool(), calculate_tool()]
        
        messages = [
            Message(role="system", content="You are a smart assistant with access to weather and calculator tools."),
            Message(role="user", content=query)
        ]
        
        try:
            models = await context.get_llm_models()
            response = await context.invoke_llm(models[0], messages, funcs=tools)
            
            # Check if AI wants to call a function
            if response.function_call:
                result = await handle_function_call(response.function_call)
                await context.send_message(f"Result: {result}")
            else:
                await context.send_message(response.content)
                
        except Exception as e:
            await context.send_message(f"Error: {e}")

async def handle_function_call(function_call):
    """Handle AI function calls"""
    if function_call.name == "get_weather":
        location = function_call.arguments.get("location")
        return f"Weather in {location}: Sunny, 25°C"  # Mock implementation
        
    elif function_call.name == "calculate":
        expression = function_call.arguments.get("expression")
        try:
            result = eval(expression)  # Note: Use safe evaluation in production
            return str(result)
        except:
            return "Calculation error"
    
    return "Unknown function"
```

## Advanced Parameters

Control AI behavior with extra arguments:

```python
@register_handler(CommandEvent)
async def creative_ai(event: CommandEvent, context: PluginContext):
    if event.command == "creative" and event.args:
        prompt = " ".join(event.args)
        
        # Configure AI parameters
        extra_args = {
            "temperature": 0.9,      # More creative/random
            "max_tokens": 150,       # Limit response length
            "top_p": 0.9,           # Nucleus sampling
            "frequency_penalty": 0.1, # Reduce repetition
        }
        
        messages = [
            Message(role="system", content="You are a creative storyteller."),
            Message(role="user", content=f"Write a short story about: {prompt}")
        ]
        
        models = await context.get_llm_models()
        response = await context.invoke_llm(
            models[0], 
            messages, 
            extra_args=extra_args
        )
        
        await context.send_message(response.content)
```

### Common Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `temperature` | float | Creativity (0.0-2.0) | 1.0 |
| `max_tokens` | int | Max response length | Model default |
| `top_p` | float | Nucleus sampling (0.0-1.0) | 1.0 |
| `frequency_penalty` | float | Repetition penalty (-2.0-2.0) | 0.0 |
| `presence_penalty` | float | Topic diversity (-2.0-2.0) | 0.0 |
| `stop` | list[str] | Stop sequences | None |

## Common Patterns

### AI Chat Bot

```python
class AIChatBot:
    def __init__(self, context: PluginContext):
        self.context = context
        self.conversations = {}  # Store per-user conversations
    
    async def chat(self, user_id: str, message: str) -> str:
        """Continue conversation with a user"""
        
        # Get or create conversation history
        if user_id not in self.conversations:
            self.conversations[user_id] = [
                Message(role="system", content="You are a helpful assistant.")
            ]
        
        # Add user message
        self.conversations[user_id].append(
            Message(role="user", content=message)
        )
        
        # Keep conversation history manageable (last 10 messages)
        if len(self.conversations[user_id]) > 10:
            self.conversations[user_id] = (
                self.conversations[user_id][:1] +  # Keep system message
                self.conversations[user_id][-9:]   # Keep last 9 messages
            )
        
        # Get AI response
        models = await self.context.get_llm_models()
        response = await self.context.invoke_llm(
            models[0], 
            self.conversations[user_id]
        )
        
        # Add AI response to history
        self.conversations[user_id].append(
            Message(role="assistant", content=response.content)
        )
        
        return response.content
```

### Text Analysis

```python
async def analyze_sentiment(context: PluginContext, text: str) -> str:
    """Analyze the sentiment of text"""
    
    messages = [
        Message(
            role="system", 
            content="Analyze the sentiment of text. Respond only with: POSITIVE, NEGATIVE, or NEUTRAL"
        ),
        Message(role="user", content=f"Text to analyze: {text}")
    ]
    
    models = await context.get_llm_models()
    response = await context.invoke_llm(
        models[0], 
        messages,
        extra_args={"temperature": 0.1}  # Lower temperature for consistency
    )
    
    return response.content.strip().upper()
```

### Content Generation

```python
async def generate_content(context: PluginContext, content_type: str, topic: str) -> str:
    """Generate different types of content"""
    
    prompts = {
        "poem": f"Write a creative poem about {topic}",
        "story": f"Write a short story involving {topic}",
        "email": f"Write a professional email about {topic}",
        "summary": f"Write a concise summary of {topic}"
    }
    
    if content_type not in prompts:
        return "Unsupported content type"
    
    messages = [
        Message(role="system", content="You are a skilled content creator."),
        Message(role="user", content=prompts[content_type])
    ]
    
    models = await context.get_llm_models()
    response = await context.invoke_llm(models[0], messages)
    
    return response.content
```

## Error Handling

```python
async def safe_llm_call(context: PluginContext, user_input: str) -> str:
    """Safely call LLM with comprehensive error handling"""
    
    try:
        # Check if models are available
        models = await context.get_llm_models()
        if not models:
            return "❌ No AI models are currently available"
        
        # Prepare messages
        messages = [
            Message(role="user", content=user_input)
        ]
        
        # Call LLM
        response = await context.invoke_llm(models[0], messages)
        return response.content
        
    except TimeoutError:
        return "⏱️ AI request timed out. Please try again."
        
    except ValueError as e:
        return f"📝 Invalid input: {e}"
        
    except ConnectionError:
        return "🌐 Connection error. Check your network."
        
    except Exception as e:
        context.logger.error(f"LLM API error: {e}")
        return "🔧 AI service temporarily unavailable"
```

## Best Practices

1. **Model Selection**: Check available models before use
2. **Error Handling**: Always wrap LLM calls in try-catch blocks
3. **Context Management**: Limit conversation history to prevent token limits
4. **Parameter Tuning**: Adjust temperature based on use case
5. **Rate Limiting**: Be mindful of API usage limits
6. **Content Filtering**: Validate AI responses before sending
7. **Function Security**: Carefully validate function call parameters

## Performance Tips

1. **Reuse Models**: Cache the model list instead of fetching repeatedly
2. **Batch Requests**: Combine multiple queries when possible
3. **Optimize Prompts**: Clear, specific prompts get better results
4. **Token Management**: Monitor and limit response lengths
5. **Async Operations**: Use async/await properly for non-blocking calls

## Related Documentation

- [Message API](message-api.md) - For handling AI responses as messages
- [Storage API](storage-api.md) - For persisting conversation history
- [Examples](../examples/llm-integration.md) - Practical LLM usage examples
- [Development Guide](../development/) - Advanced AI integration patterns
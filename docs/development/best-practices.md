# Best Practices

This guide outlines best practices for developing robust, maintainable, and efficient LangBot plugins. Following these guidelines will help you create high-quality plugins that are secure, performant, and easy to maintain.

## 🎯 Core Principles

### 1. Single Responsibility Principle
Each function, class, and module should have one clear responsibility.

```python
# Good: Clear, single responsibility
async def handle_weather_command(event: CommandEvent, context: PluginContext):
    """Handle weather-related commands only."""
    pass

async def format_weather_response(weather_data: dict) -> MessageChain:
    """Format weather data into a user-friendly message."""
    pass

# Avoid: Multiple responsibilities in one function
async def handle_command(event: CommandEvent, context: PluginContext):
    """Handle ALL commands and format ALL responses."""
    # This function does too much!
    pass
```

### 2. Separation of Concerns
Separate business logic from presentation and data access.

```python
# Good: Separated concerns
class WeatherService:
    """Business logic for weather operations."""
    async def get_weather(self, city: str) -> WeatherData:
        pass

class WeatherFormatter:
    """Presentation logic for weather data."""
    def format_weather_message(self, weather: WeatherData) -> MessageChain:
        pass

@register_handler(CommandEvent)
async def weather_command_handler(event: CommandEvent, context: PluginContext):
    """Handler that coordinates service and formatter."""
    service = WeatherService()
    formatter = WeatherFormatter()
    
    weather = await service.get_weather(event.args[0])
    message = formatter.format_weather_message(weather)
    await context.send_message(message)
```

### 3. Dependency Injection
Use the context object for accessing external dependencies.

```python
# Good: Use context for dependencies
async def save_user_preference(user_id: str, preference: dict, context: PluginContext):
    """Save user preference using provided context."""
    key = f"user_pref_{user_id}"
    data = json.dumps(preference).encode()
    await context.set_storage(key, data)

# Avoid: Direct dependency creation
async def save_user_preference_bad(user_id: str, preference: dict):
    """Bad: Creates its own dependencies."""
    storage = StorageClient()  # Hard to test and modify
    await storage.save(key, data)
```

## 📝 Code Organization

### Project Structure

```
my-plugin/
├── main.py                 # Entry point and handler registration
├── plugin.yaml            # Plugin configuration
├── requirements.txt       # Dependencies
├── src/                   # Source code
│   ├── __init__.py
│   ├── handlers/          # Event handlers
│   │   ├── __init__.py
│   │   ├── messages.py    # Message event handlers
│   │   └── commands.py    # Command handlers
│   ├── services/          # Business logic
│   │   ├── __init__.py
│   │   ├── weather.py     # Weather service
│   │   └── user.py        # User management
│   ├── models/            # Data models
│   │   ├── __init__.py
│   │   └── weather.py     # Weather data models
│   └── utils/             # Utilities
│       ├── __init__.py
│       ├── formatters.py  # Message formatters
│       └── validators.py  # Input validation
├── tests/                 # Test suite
│   ├── __init__.py
│   ├── test_handlers.py
│   ├── test_services.py
│   └── fixtures/
└── docs/                  # Documentation
    └── README.md
```

### Module Organization

```python
# main.py - Keep it simple, just register handlers
"""Main plugin entry point."""

from src.handlers.messages import register_message_handlers
from src.handlers.commands import register_command_handlers

def main():
    """Initialize plugin and register all handlers."""
    register_message_handlers()
    register_command_handlers()

if __name__ == "__main__":
    main()
```

```python
# src/handlers/commands.py - Organize by functionality
"""Command event handlers."""

from langbot_plugin.api import *
from ..services.weather import WeatherService
from ..utils.formatters import format_error_message

@register_handler(CommandEvent)
async def handle_weather_command(event: CommandEvent, context: PluginContext):
    """Handle weather-related commands."""
    if event.command != "weather":
        return
    
    if not event.args:
        await context.send_message(format_error_message("Please specify a city"))
        return
    
    city = " ".join(event.args)
    service = WeatherService(context)
    
    try:
        weather = await service.get_weather(city)
        message = service.format_weather_response(weather)
        await context.send_message(message)
    except Exception as e:
        await context.send_message(format_error_message(f"Weather error: {e}"))

def register_command_handlers():
    """Register all command handlers."""
    # Handlers are automatically registered via decorators
    pass
```

## 🔒 Error Handling

### Comprehensive Error Handling

```python
import logging
from typing import Optional

logger = logging.getLogger(__name__)

async def safe_handler_wrapper(handler_func):
    """Wrapper for safe handler execution."""
    async def wrapper(event, context):
        try:
            await handler_func(event, context)
        except ValidationError as e:
            logger.warning(f"Validation error: {e}")
            await context.send_message("Invalid input provided.")
        except NetworkError as e:
            logger.error(f"Network error: {e}")
            await context.send_message("Service temporarily unavailable.")
        except Exception as e:
            logger.error(f"Unexpected error in {handler_func.__name__}: {e}")
            await context.send_message("Something went wrong. Please try again.")
    return wrapper

@register_handler(CommandEvent)
@safe_handler_wrapper
async def weather_command(event: CommandEvent, context: PluginContext):
    """Weather command with error handling."""
    # Your handler logic here
    pass
```

### Custom Exception Classes

```python
class PluginError(Exception):
    """Base exception for plugin errors."""
    pass

class ValidationError(PluginError):
    """Raised when input validation fails."""
    pass

class ServiceUnavailableError(PluginError):
    """Raised when external service is unavailable."""
    pass

class RateLimitError(PluginError):
    """Raised when rate limit is exceeded."""
    pass

# Usage
async def get_weather(city: str) -> dict:
    """Get weather data with proper error handling."""
    if not city or len(city.strip()) == 0:
        raise ValidationError("City name cannot be empty")
    
    try:
        response = await api_client.get_weather(city)
        if response.status_code == 429:
            raise RateLimitError("Weather API rate limit exceeded")
        elif response.status_code != 200:
            raise ServiceUnavailableError(f"Weather API returned {response.status_code}")
        return response.json()
    except httpx.RequestError as e:
        raise ServiceUnavailableError(f"Failed to connect to weather API: {e}")
```

## 🔍 Input Validation

### Validate All User Input

```python
from typing import List, Optional
import re

class InputValidator:
    """Input validation utilities."""
    
    @staticmethod
    def validate_city_name(city: str) -> str:
        """Validate and clean city name."""
        if not city or not city.strip():
            raise ValidationError("City name is required")
        
        # Clean and validate
        city = city.strip()
        if len(city) > 100:
            raise ValidationError("City name too long")
        
        # Check for valid characters (letters, spaces, hyphens)
        if not re.match(r"^[a-zA-Z\s\-]+$", city):
            raise ValidationError("Invalid characters in city name")
        
        return city
    
    @staticmethod
    def validate_command_args(args: List[str], min_args: int = 0, max_args: Optional[int] = None) -> List[str]:
        """Validate command arguments."""
        if len(args) < min_args:
            raise ValidationError(f"At least {min_args} arguments required")
        
        if max_args and len(args) > max_args:
            raise ValidationError(f"At most {max_args} arguments allowed")
        
        return args

# Usage in handlers
@register_handler(CommandEvent)
async def weather_command(event: CommandEvent, context: PluginContext):
    """Weather command with validation."""
    try:
        # Validate arguments
        args = InputValidator.validate_command_args(event.args, min_args=1, max_args=3)
        city = InputValidator.validate_city_name(" ".join(args))
        
        # Process valid input
        weather = await get_weather(city)
        await context.send_message(format_weather_response(weather))
        
    except ValidationError as e:
        await context.send_message(f"❌ {e}")
```

## 💾 Data Management

### Use Storage Effectively

```python
import json
import time
from typing import Optional, Dict, Any

class UserDataManager:
    """Manage user data with caching and validation."""
    
    def __init__(self, context: PluginContext):
        self.context = context
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    async def get_user_data(self, user_id: str) -> Dict[str, Any]:
        """Get user data with caching."""
        cache_key = f"user_{user_id}"
        
        # Check cache first
        if cache_key in self._cache:
            cached_data = self._cache[cache_key]
            if time.time() - cached_data.get("cached_at", 0) < 300:  # 5-minute cache
                return cached_data["data"]
        
        # Load from storage
        try:
            storage_key = f"user_data_{user_id}"
            raw_data = await self.context.get_storage(storage_key)
            data = json.loads(raw_data.decode())
            
            # Cache the data
            self._cache[cache_key] = {
                "data": data,
                "cached_at": time.time()
            }
            
            return data
        except KeyError:
            # Return default data for new users
            default_data = {
                "created_at": time.time(),
                "preferences": {},
                "usage_count": 0
            }
            await self.save_user_data(user_id, default_data)
            return default_data
    
    async def save_user_data(self, user_id: str, data: Dict[str, Any]) -> None:
        """Save user data with validation."""
        # Validate data structure
        required_fields = ["created_at", "preferences", "usage_count"]
        for field in required_fields:
            if field not in data:
                raise ValidationError(f"Missing required field: {field}")
        
        # Add metadata
        data["updated_at"] = time.time()
        
        # Save to storage
        storage_key = f"user_data_{user_id}"
        json_data = json.dumps(data).encode()
        await self.context.set_storage(storage_key, json_data)
        
        # Update cache
        cache_key = f"user_{user_id}"
        self._cache[cache_key] = {
            "data": data,
            "cached_at": time.time()
        }
    
    async def update_user_preference(self, user_id: str, key: str, value: Any) -> None:
        """Update a specific user preference."""
        data = await self.get_user_data(user_id)
        data["preferences"][key] = value
        data["usage_count"] += 1
        await self.save_user_data(user_id, data)
```

### Data Migration Strategy

```python
class DataMigrationManager:
    """Handle data format migrations."""
    
    CURRENT_VERSION = 2
    
    async def migrate_user_data(self, context: PluginContext, user_id: str) -> None:
        """Migrate user data to current version."""
        try:
            data = await self._load_raw_user_data(context, user_id)
            version = data.get("version", 1)
            
            if version < self.CURRENT_VERSION:
                data = await self._perform_migration(data, version, self.CURRENT_VERSION)
                await self._save_migrated_data(context, user_id, data)
                
        except Exception as e:
            logger.error(f"Migration failed for user {user_id}: {e}")
    
    async def _perform_migration(self, data: dict, from_version: int, to_version: int) -> dict:
        """Perform step-by-step migration."""
        if from_version == 1 and to_version >= 2:
            data = self._migrate_v1_to_v2(data)
        
        data["version"] = to_version
        return data
    
    def _migrate_v1_to_v2(self, data: dict) -> dict:
        """Migrate from version 1 to version 2."""
        # Example: Restructure preferences
        if "prefs" in data:
            data["preferences"] = data.pop("prefs")
        
        # Add new fields
        data.setdefault("usage_count", 0)
        data.setdefault("last_active", time.time())
        
        return data
```

## 🚀 Performance Optimization

### Asynchronous Best Practices

```python
import asyncio
import aiohttp
from typing import List

class AsyncBestPractices:
    """Examples of efficient async patterns."""
    
    async def fetch_multiple_apis(self, urls: List[str]) -> List[dict]:
        """Fetch multiple APIs concurrently."""
        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_single_api(session, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions and return valid results
            return [result for result in results if not isinstance(result, Exception)]
    
    async def _fetch_single_api(self, session: aiohttp.ClientSession, url: str) -> dict:
        """Fetch a single API endpoint."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                return await response.json()
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            raise
    
    async def process_large_dataset(self, items: List[Any]) -> List[Any]:
        """Process large datasets in batches."""
        batch_size = 10
        results = []
        
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_tasks = [self._process_single_item(item) for item in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            results.extend(batch_results)
            
            # Small delay to prevent overwhelming the system
            await asyncio.sleep(0.1)
        
        return results
```

### Caching Strategies

```python
import time
from typing import Dict, Any, Optional
from functools import wraps

class CacheManager:
    """Simple in-memory cache with TTL."""
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def get(self, key: str, ttl: int = 300) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self._cache:
            cached_at = self._cache[key]["timestamp"]
            if time.time() - cached_at < ttl:
                return self._cache[key]["value"]
            else:
                del self._cache[key]
        return None
    
    def set(self, key: str, value: Any) -> None:
        """Set cached value with timestamp."""
        self._cache[key] = {
            "value": value,
            "timestamp": time.time()
        }
    
    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()

# Global cache instance
cache = CacheManager()

def cached(ttl: int = 300):
    """Decorator for caching function results."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key = f"{func.__name__}_{hash(str(args) + str(kwargs))}"
            
            # Check cache first
            cached_result = cache.get(cache_key, ttl)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = await func(*args, **kwargs)
            cache.set(cache_key, result)
            return result
        return wrapper
    return decorator

# Usage
@cached(ttl=600)  # Cache for 10 minutes
async def get_weather_data(city: str) -> dict:
    """Get weather data with caching."""
    # Expensive API call
    pass
```

## 🔐 Security Best Practices

### Input Sanitization

```python
import html
import re
from urllib.parse import quote

class SecurityUtils:
    """Security utilities for input sanitization."""
    
    @staticmethod
    def sanitize_text_input(text: str) -> str:
        """Sanitize text input to prevent injection attacks."""
        if not text:
            return ""
        
        # Remove potentially dangerous characters
        sanitized = re.sub(r'[<>"\']', '', text)
        
        # Limit length
        sanitized = sanitized[:1000]
        
        # HTML escape
        sanitized = html.escape(sanitized)
        
        return sanitized.strip()
    
    @staticmethod
    def sanitize_url(url: str) -> str:
        """Sanitize URL input."""
        if not url:
            return ""
        
        # Basic URL validation
        if not re.match(r'^https?://', url):
            raise ValidationError("Only HTTP and HTTPS URLs are allowed")
        
        # URL encode dangerous characters
        return quote(url, safe=':/?#[]@!$&\'()*+,;=')
    
    @staticmethod
    def validate_file_upload(filename: str, max_size: int = 10 * 1024 * 1024) -> bool:
        """Validate file upload."""
        # Check file extension
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.txt'}
        file_ext = '.' + filename.split('.')[-1].lower()
        
        if file_ext not in allowed_extensions:
            raise ValidationError(f"File type {file_ext} not allowed")
        
        return True
```

### API Key Management

```python
import os
from typing import Optional

class APIKeyManager:
    """Secure API key management."""
    
    @staticmethod
    def get_api_key(service_name: str) -> Optional[str]:
        """Get API key from environment variables."""
        key_name = f"{service_name.upper()}_API_KEY"
        api_key = os.getenv(key_name)
        
        if not api_key:
            logger.warning(f"API key not found for service: {service_name}")
            return None
        
        # Basic validation
        if len(api_key) < 10:
            logger.warning(f"API key for {service_name} seems too short")
            return None
        
        return api_key
    
    @staticmethod
    def mask_api_key(api_key: str) -> str:
        """Mask API key for logging."""
        if not api_key or len(api_key) < 8:
            return "***"
        return api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]

# Usage
weather_api_key = APIKeyManager.get_api_key("weather")
if weather_api_key:
    logger.info(f"Using weather API key: {APIKeyManager.mask_api_key(weather_api_key)}")
```

## 📊 Logging and Monitoring

### Structured Logging

```python
import logging
import json
import time
from typing import Any, Dict

class PluginLogger:
    """Structured logging for plugins."""
    
    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        self.logger = logging.getLogger(plugin_name)
        
        # Configure formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
    
    def log_event(self, level: str, event: str, **kwargs) -> None:
        """Log structured event data."""
        log_data = {
            "plugin": self.plugin_name,
            "event": event,
            "timestamp": time.time(),
            **kwargs
        }
        
        log_message = json.dumps(log_data)
        getattr(self.logger, level.lower())(log_message)
    
    def log_performance(self, operation: str, duration: float, **kwargs) -> None:
        """Log performance metrics."""
        self.log_event(
            "info",
            "performance",
            operation=operation,
            duration_ms=duration * 1000,
            **kwargs
        )
    
    def log_user_action(self, user_id: str, action: str, **kwargs) -> None:
        """Log user actions."""
        self.log_event(
            "info",
            "user_action",
            user_id=user_id,
            action=action,
            **kwargs
        )

# Usage
logger = PluginLogger("weather-plugin")

async def handle_weather_command(event: CommandEvent, context: PluginContext):
    """Handle weather command with logging."""
    start_time = time.time()
    
    try:
        user_id = event.sender.id
        city = " ".join(event.args)
        
        logger.log_user_action(user_id, "weather_request", city=city)
        
        weather_data = await get_weather(city)
        duration = time.time() - start_time
        
        logger.log_performance("weather_api_call", duration, city=city)
        await context.send_message(format_weather_response(weather_data))
        
    except Exception as e:
        logger.log_event("error", "command_failed", error=str(e), command="weather")
        raise
```

## 🧪 Testing Best Practices

### Comprehensive Test Coverage

```python
import pytest
from unittest.mock import AsyncMock, Mock
import json

@pytest.fixture
def mock_context():
    """Create a mock plugin context."""
    context = AsyncMock()
    context.send_message = AsyncMock()
    context.get_storage = AsyncMock()
    context.set_storage = AsyncMock()
    return context

@pytest.fixture
def mock_weather_event():
    """Create a mock weather command event."""
    event = Mock()
    event.command = "weather"
    event.args = ["London"]
    event.sender = Mock()
    event.sender.id = "test_user_123"
    return event

@pytest.mark.asyncio
async def test_weather_command_success(mock_context, mock_weather_event):
    """Test successful weather command."""
    # Arrange
    expected_weather = {"temperature": 20, "condition": "sunny"}
    
    with patch('src.services.weather.get_weather') as mock_get_weather:
        mock_get_weather.return_value = expected_weather
        
        # Act
        await handle_weather_command(mock_weather_event, mock_context)
        
        # Assert
        mock_get_weather.assert_called_once_with("London")
        mock_context.send_message.assert_called_once()

@pytest.mark.asyncio
async def test_weather_command_validation_error(mock_context):
    """Test weather command with invalid input."""
    # Arrange
    event = Mock()
    event.command = "weather"
    event.args = []  # No city provided
    
    # Act
    await handle_weather_command(event, mock_context)
    
    # Assert
    mock_context.send_message.assert_called_once()
    sent_message = mock_context.send_message.call_args[0][0]
    assert "Please specify a city" in str(sent_message)

@pytest.mark.asyncio
async def test_user_data_manager_caching():
    """Test user data manager caching behavior."""
    # Arrange
    mock_context = AsyncMock()
    user_data = {"preferences": {"theme": "dark"}, "usage_count": 5}
    mock_context.get_storage.return_value = json.dumps(user_data).encode()
    
    manager = UserDataManager(mock_context)
    
    # Act - First call should hit storage
    result1 = await manager.get_user_data("user123")
    
    # Act - Second call should hit cache
    result2 = await manager.get_user_data("user123")
    
    # Assert
    assert result1 == user_data
    assert result2 == user_data
    mock_context.get_storage.assert_called_once()  # Only called once due to caching
```

## 📋 Code Review Checklist

Before submitting code for review, ensure:

### ✅ Functionality
- [ ] Code does what it's supposed to do
- [ ] Edge cases are handled
- [ ] Error conditions are managed gracefully
- [ ] Input validation is implemented

### ✅ Code Quality
- [ ] Code is readable and well-documented
- [ ] Functions have single responsibilities
- [ ] No code duplication
- [ ] Consistent naming conventions

### ✅ Performance
- [ ] No unnecessary loops or recursive calls
- [ ] Async/await used correctly
- [ ] Caching implemented where appropriate
- [ ] Database queries are optimized

### ✅ Security
- [ ] Input is validated and sanitized
- [ ] No hardcoded secrets
- [ ] Error messages don't leak sensitive information
- [ ] Proper authentication and authorization

### ✅ Testing
- [ ] Unit tests cover main functionality
- [ ] Integration tests for complex workflows
- [ ] Error cases are tested
- [ ] Test coverage is adequate

### ✅ Documentation
- [ ] Code is self-documenting
- [ ] Complex logic is explained
- [ ] API changes are documented
- [ ] README is updated if needed

## 🔄 Continuous Improvement

1. **Regular Refactoring**: Continuously improve code quality
2. **Performance Monitoring**: Track and optimize performance metrics
3. **User Feedback**: Incorporate user feedback into improvements
4. **Security Updates**: Stay updated with security best practices
5. **Dependency Management**: Keep dependencies updated and secure

By following these best practices, you'll create plugins that are robust, maintainable, and provide excellent user experiences! 🚀
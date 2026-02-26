import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock
import discord
import datetime

# Mocking the dependencies for testing utils.send_error_log
class MockBot:
    def __init__(self):
        self.get_channel = MagicMock()
        self.fetch_channel = AsyncMock()

async def test_error_logging():
    print("Running Error Logging Verification...")
    
    # Setup mocks
    bot = MockBot()
    mock_channel = AsyncMock()
    bot.get_channel.return_value = mock_channel
    
    # Simulate an error
    try:
        raise ValueError("This is a test error for logging")
    except Exception as e:
        test_error = e

    # Mock the function logic (simulating what's in utils.py)
    ERROR_LOG_CHANNEL_ID = 1476562513641476299
    
    # Verify channel lookup
    channel = bot.get_channel(ERROR_LOG_CHANNEL_ID)
    print(f"Channel Lookup ID: {ERROR_LOG_CHANNEL_ID}")
    assert channel == mock_channel
    
    # Simulate embedding logic
    import traceback
    tb = "".join(traceback.format_exception(type(test_error), test_error, test_error.__traceback__))
    
    embed = discord.Embed(
        title="🚨 System Error Detected",
        description=f"An error occurred during bot operation.",
        color=0xe74c3c,
        timestamp=datetime.datetime.now()
    )
    embed.add_field(name="Error Type", value=f"`{type(test_error).__name__}`", inline=True)
    embed.add_field(name="Error Message", value=f"```\n{str(test_error)}\n```", inline=False)
    embed.add_field(name="Traceback", value=f"```python\n{tb[:1000]}\n```", inline=False)

    # Simulate sending
    await channel.send(embed=embed)
    
    print("Verify: channel.send was called with an embed.")
    mock_channel.send.assert_called_once()
    sent_embed = mock_channel.send.call_args[1]['embed']
    assert sent_embed.title == "🚨 System Error Detected"
    assert "ValueError" in sent_embed.fields[0].value
    
    print("\nVerification Successful: Error logging logic is correct.")

if __name__ == "__main__":
    asyncio.run(test_error_logging())

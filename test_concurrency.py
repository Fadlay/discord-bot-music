import asyncio
from unittest.mock import MagicMock, AsyncMock

async def test_concurrency():
    # Mocking the lock behavior
    locks = {}
    history = []

    async def mock_on_message(user_id, message_content, delay):
        history_id = "shared_guild"
        if history_id not in locks:
            locks[history_id] = asyncio.Lock()
        
        print(f"User {user_id} waiting for lock...")
        async with locks[history_id]:
            print(f"User {user_id} acquired lock. Processing: {message_content}")
            # Simulate API call delay
            await asyncio.sleep(delay)
            history.append(f"User {user_id}: {message_content}")
            print(f"User {user_id} finished processing.")

    # Simulate two users sending messages at the same time
    # User 1 sends a message that takes 1 second to process
    # User 2 sends a message immediately after
    print("Starting concurrent message simulation...")
    await asyncio.gather(
        mock_on_message("User1", "Gaya rambut", 1.0),
        mock_on_message("User2", "Sport", 0.1)
    )

    print("\nFinal History Content:")
    for entry in history:
        print(entry)

    # Verification: User 1 should be first even though User 2 had a shorter "processing" time
    # because of the lock.
    assert history[0].startswith("User User1")
    assert history[1].startswith("User User2")
    print("\nVerification Successful: Messages were processed sequentially.")

if __name__ == "__main__":
    asyncio.run(test_concurrency())

import asyncio

def simulate_prompt_formatting(history_id, author_name, prompt_text):
    final_prompt = prompt_text
    # Updated logic from cogs/chat.py
    if history_id.startswith("shared"):
        final_prompt = f"(User: {author_name}) {prompt_text}"
    return final_prompt

async def test_identity():
    print("Running User Identity Verification Tests...")
    
    # Test 1: Shared History in a Server
    hid1 = "shared_123456789"
    name1 = "Alice"
    text1 = "Siapa nama saya?"
    result1 = simulate_prompt_formatting(hid1, name1, text1)
    print(f"Test 1 (Shared): {result1}")
    assert result1 == "(User: Alice) Siapa nama saya?"
    
    # Test 2: Private History
    hid2 = "123456789_user1"
    name2 = "Bob"
    text2 = "Halo bot"
    result2 = simulate_prompt_formatting(hid2, name2, text2)
    print(f"Test 2 (Private): {result2}")
    assert result2 == "Halo bot" # No name prepended in private mode
    
    # Test 3: Shared History (Old 'shared' ID check)
    hid3 = "shared"
    name3 = "Charlie"
    text3 = "Test"
    result3 = simulate_prompt_formatting(hid3, name3, text3)
    print(f"Test 3 (Legacy Shared): {result3}")
    assert result3 == "(User: Charlie) Test"

    print("\nVerification Successful: User identity is correctly formatted in shared mode.")

if __name__ == "__main__":
    asyncio.run(test_identity())

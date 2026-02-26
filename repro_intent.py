music_keywords = ["putar", "play", "skip", "volume", "lagu", "musik", "pause", "resume", "berhenti", "stop", "antrean", "queue", "shuffle", "loop", "bassboost", "nightcore", "vaporwave", "speed", "reset"]

def check_intent(text):
    text = text.lower()
    matches = [kw for kw in music_keywords if kw in text]
    return matches

test_cases = ["lampung", "apa itu lampung?", "siapa gubernur lampung?", "putar lagu", "stop musik"]

for tc in test_cases:
    res = check_intent(tc)
    print(f"Text: '{tc}' -> Keywords matched: {res}")

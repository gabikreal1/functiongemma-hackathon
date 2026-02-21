"""
Stress test: 10 sensible human requests designed to break regex extractors.
5 "easy breaks" (slight phrasing differences) + 5 "hard breaks" (natural but adversarial).
Does NOT fix anything — just reports what breaks.
"""
import sys, os
sys.path.insert(0, "cactus/python/src")
os.environ["CACTUS_NO_CLOUD_TELE"] = "1"
os.environ["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "AIzaSyCw3e4SH5DvuqxwwmwPXBsKm4IDhv_fVEw")

import json
from main import generate_hybrid
from benchmark import (
    TOOL_GET_WEATHER, TOOL_SET_ALARM, TOOL_SEND_MESSAGE, TOOL_CREATE_REMINDER,
    TOOL_SEARCH_CONTACTS, TOOL_PLAY_MUSIC, TOOL_SET_TIMER,
    TOOL_TURN_ON_LIGHT, TOOL_SET_THERMOSTAT, TOOL_GET_DIRECTIONS,
    TOOL_FIND_RESTAURANT, TOOL_LOG_WORKOUT, TOOL_CREATE_EVENT,
    TOOL_TRANSLATE_TEXT, TOOL_ADD_TO_CART, TOOL_BOOK_RIDE, TOOL_SET_VOLUME,
    TOOL_LOCK_DOOR, TOOL_READ_NEWS, TOOL_TAKE_NOTE,
    compute_f1, _normalize,
)

STRESS_CASES = [
    # ═══ EASY BREAKS: slight phrasing differences ═══

    # EB1: No preposition before location — "weather for new york" works, but
    #      "how's new york weather" has no in/for/at/near before the city.
    {
        "name": "eb1_weather_no_preposition",
        "messages": [{"role": "user", "content": "How's the New York weather today?"}],
        "tools": [TOOL_GET_WEATHER, TOOL_SEND_MESSAGE, TOOL_SET_ALARM],
        "expected_calls": [{"name": "get_weather", "arguments": {"location": "New York"}}],
        "why_breaks": "_extract_location needs in/for/at/near before city name",
    },

    # EB2: Person name BEFORE the verb — "Tell Bob" works, but "Bob, I need you
    #      to get a message" puts Bob first with no to/text/send before it.
    {
        "name": "eb2_person_name_first",
        "messages": [{"role": "user", "content": "Message Bob saying I'm running late."}],
        "tools": [TOOL_SEND_MESSAGE, TOOL_GET_WEATHER, TOOL_SET_ALARM],
        "expected_calls": [{"name": "send_message", "arguments": {"recipient": "Bob", "message": "I'm running late"}}],
        "why_breaks": "_extract_person looks for (to|text|message|send) + Name, 'Message Bob' — 'Message' is verb not preposition, case-sensitive pattern may miss it",
    },

    # EB3: Duration as word not digit — "set a timer for fifteen minutes"
    {
        "name": "eb3_duration_word",
        "messages": [{"role": "user", "content": "Set a timer for twenty five minutes."}],
        "tools": [TOOL_SET_TIMER, TOOL_SET_ALARM, TOOL_PLAY_MUSIC],
        "expected_calls": [{"name": "set_timer", "arguments": {"minutes": 25}}],
        "why_breaks": "_WORD_TO_NUM has 'twenty':20 but not 'twenty five':25. _extract_duration regex wants \\d+ before 'minute'",
    },

    # EB4: Implicit message — no "saying" keyword, message is inferred from context
    {
        "name": "eb4_implicit_message",
        "messages": [{"role": "user", "content": "Let Alice know I'll be there at 5."}],
        "tools": [TOOL_SEND_MESSAGE, TOOL_SET_ALARM, TOOL_CREATE_REMINDER],
        "expected_calls": [{"name": "send_message", "arguments": {"recipient": "Alice", "message": "I'll be there at 5"}}],
        "why_breaks": "_extract_message_text needs 'saying/says/that'. 'Let X know Y' has no trigger. _extract_person needs to/text/send before name, 'Let Alice' doesn't match.",
    },

    # EB5: Multi-word location — "San Francisco Bay Area" or compound city
    {
        "name": "eb5_multiword_destination",
        "messages": [{"role": "user", "content": "Get directions to San Francisco International Airport."}],
        "tools": [TOOL_GET_DIRECTIONS, TOOL_GET_WEATHER, TOOL_BOOK_RIDE],
        "expected_calls": [{"name": "get_directions", "arguments": {"destination": "San Francisco International Airport"}}],
        "why_breaks": "_extract_destination gets 'San Francisco International Airport' — this might actually work but the single-cap-word filter could interfere",
    },

    # ═══ HARD BREAKS: natural human phrasing that seriously breaks extractors ═══

    # HB1: Conversational/implicit — no action verb, no tool keyword
    {
        "name": "hb1_conversational_weather",
        "messages": [{"role": "user", "content": "Is it going to rain in Tokyo tomorrow?"}],
        "tools": [TOOL_GET_WEATHER, TOOL_READ_NEWS, TOOL_SEND_MESSAGE],
        "expected_calls": [{"name": "get_weather", "arguments": {"location": "Tokyo"}}],
        "why_breaks": "No verb synonym for 'rain'. Keyword index may not map 'rain'→get_weather. Location extraction might work since 'in Tokyo' exists.",
    },

    # HB2: Alarm with relative time — no absolute hour:minute
    {
        "name": "hb2_alarm_relative_time",
        "messages": [{"role": "user", "content": "Wake me up in 2 hours."}],
        "tools": [TOOL_SET_ALARM, TOOL_SET_TIMER, TOOL_CREATE_REMINDER],
        "expected_calls": [{"name": "set_alarm", "arguments": {"hour": 2, "minute": 0}}],
        "why_breaks": "_extract_time_hour looks for H:MM AM/PM pattern. '2 hours' has no AM/PM. Unclear if this should be alarm or timer. Ambiguous semantics.",
    },

    # HB3: Restaurant with no cuisine keyword — uses descriptor instead
    {
        "name": "hb3_restaurant_no_cuisine_word",
        "messages": [{"role": "user", "content": "Find somewhere good to eat sushi nearby."}],
        "tools": [TOOL_FIND_RESTAURANT, TOOL_GET_DIRECTIONS, TOOL_READ_NEWS],
        "expected_calls": [{"name": "find_restaurant", "arguments": {"cuisine": "sushi"}}],
        "why_breaks": "_extract_cuisine looks for 'X restaurant' or 'X food/cuisine/dish'. 'eat sushi nearby' matches none of those patterns. Keyword 'eat' is in restaurant synonyms but 'sushi' extraction fails.",
    },

    # HB4: Multi-step with pronouns and implicit second action
    {
        "name": "hb4_pronoun_chain_implicit",
        "messages": [{"role": "user", "content": "Look up Maria and wish her happy birthday."}],
        "tools": [TOOL_SEARCH_CONTACTS, TOOL_SEND_MESSAGE, TOOL_GET_WEATHER, TOOL_PLAY_MUSIC],
        "expected_calls": [
            {"name": "search_contacts", "arguments": {"query": "Maria"}},
            {"name": "send_message", "arguments": {"recipient": "Maria", "message": "happy birthday"}},
        ],
        "why_breaks": "'wish her happy birthday' — no 'saying/says/that' trigger for message extraction. 'wish' isn't in send verb synonyms. Pronoun 'her'→Maria resolution might work but message extraction won't.",
    },

    # HB5: Compound request with completely implicit tool selection
    {
        "name": "hb5_fully_implicit",
        "messages": [{"role": "user", "content": "I need to remember to buy milk at 4 PM and let Sarah know about dinner."}],
        "tools": [TOOL_CREATE_REMINDER, TOOL_SEND_MESSAGE, TOOL_SET_ALARM, TOOL_SEARCH_CONTACTS],
        "expected_calls": [
            {"name": "create_reminder", "arguments": {"title": "buy milk", "time": "4:00 PM"}},
            {"name": "send_message", "arguments": {"recipient": "Sarah", "message": "dinner"}},
        ],
        "why_breaks": "'I need to remember' — not 'remind me'. 'let Sarah know about dinner' — no 'saying/text/send'. Chunking may fail since 'let' isn't in verb list. Title extraction needs 'remind me to/about'.",
    },
]


def run_stress():
    total = len(STRESS_CASES)
    print(f"Running {total} stress test cases...\n")

    for i, case in enumerate(STRESS_CASES, 1):
        print(f"[{i}/{total}] {case['name']}")
        print(f"  Query: {case['messages'][0]['content']}")
        print(f"  Why it might break: {case['why_breaks']}")

        result = generate_hybrid(case["messages"], case["tools"])
        f1 = compute_f1(result["function_calls"], case["expected_calls"])
        source = result.get("source", "unknown")

        print(f"  Source: {source} | Time: {result['total_time_ms']:.0f}ms | F1: {f1:.2f}")

        if f1 < 1.0:
            print(f"  >>> BROKEN <<<")
            print(f"  Expected: {json.dumps(case['expected_calls'], indent=4)}")
            print(f"  Got:      {json.dumps(result['function_calls'], indent=4)}")
        else:
            print(f"  OK (survived)")

        print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)


if __name__ == "__main__":
    run_stress()

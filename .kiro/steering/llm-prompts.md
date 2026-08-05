# RoadIQ — LLM Prompt Design Guide

## Overview
RoadIQ uses Amazon Bedrock (Claude 3.5 Sonnet v2) for all AI features. Prompts live in the `prompts/` directory as plain text files with Python format-string placeholders.

## Anti-Hallucination Rules (apply to ALL prompts)
Every prompt in this project MUST include these constraints:
1. **Never invent locations** — only reference stops from the provided candidate list
2. **Never invent prices or availability numbers** — only use data injected into the prompt
3. **Never invent services** — if food, shower, or parking data isn't provided, say so
4. **If asked about unsupported info** (weather, traffic, ETAs beyond fuel math) — explicitly say "I don't have that data" and redirect to what IS available
5. **Always cite the specific stop name and stats** when making a recommendation

## Prompt Architecture
Each prompt receives structured context injected at call time via Python `.format()`:

```
prompt_template.format(
    driver_name=...,
    current_location=...,
    destination=...,
    fuel_remaining_miles=...,
    ...
)
```

The app loads prompt files with `load_prompt(filename)` and fills placeholders before sending to Bedrock.

## Active Prompts

### 1. `journey_optimizer.txt`
- **Purpose:** Generate a personalized journey plan (the Journey Optimizer tab)
- **Tone:** Friendly co-pilot, short paragraphs, conversational
- **Max tokens:** 350
- **Placeholders:** driver_name, current_location, destination, miles_remaining, fuel_remaining_miles, parking_need, loyalty_tier, preferred_food, shower_needed, vehicle_health, stop_name, stop_city, parking_pct, shower_wait, food_available, price_advantage
- **Output:** Free-form text (displayed in AI card)

### 2. `driver_chat.txt`
- **Purpose:** Power the "Ask RoadIQ" conversational chat
- **Tone:** Short, direct, conversational — under 120 words
- **Max tokens:** 250
- **Placeholders:** driver_name, current_location, destination, fuel_remaining_miles, loyalty_tier, vehicle_health, available_stops, driver_message
- **Output:** Free-form chat response

### 3. `driver_recommendation.txt`
- **Purpose:** Programmatic stop selection engine (for future API/automation use)
- **Tone:** Structured output
- **Max tokens:** 400
- **Placeholders:** driver_name, current_location, destination, fuel_remaining_miles, parking_need, loyalty_tier, preferred_food, shower_needed, vehicle_health, stops_data
- **Output:** JSON object with recommended_stop, reason, confidence, alerts

### 4. `revenue_insight.txt` (future — fleet dashboard)
- Not yet implemented. Will power fleet manager revenue insights.

### 5. `store_alert.txt` (future — store manager view)
- Not yet implemented. Will generate alerts for incoming demand.

## Bedrock Configuration
- **Model:** anthropic.claude-3-5-sonnet-20241022-v2:0
- **API:** Converse API via boto3 bedrock-runtime
- **Temperature:** 0.7 (balanced creativity + groundedness)
- **Region:** us-east-1

## Adding New Prompts
1. Create a `.txt` file in `prompts/`
2. Use `{placeholder_name}` Python format syntax
3. Include the anti-hallucination rules section in every prompt
4. Load with `load_prompt("filename.txt")` in app.py
5. Call with `ask_ai(prompt, max_tokens=N)`

## Testing Prompts Locally
You can test prompts without running the full app:
```python
from app import load_prompt, ask_ai
prompt = load_prompt("driver_chat.txt").format(
    driver_name="James",
    current_location="Nashville, TN",
    destination="Atlanta, GA",
    fuel_remaining_miles=140,
    loyalty_tier="Platinum",
    vehicle_health="good",
    available_stops="- Pilot Knoxville #198: parking 78%, shower 8 min",
    driver_message="Where should I stop for fuel?"
)
print(ask_ai(prompt))
```

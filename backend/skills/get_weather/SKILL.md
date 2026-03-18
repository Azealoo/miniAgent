---
name: get_weather
description: Get the current weather for a specified city using wttr.in
category: general/utilities
version: 1.0
requires_tools: [fetch_url]
requires_network: true
user_invocable: true
tags: [weather, city, forecast]
aliases: [weather_lookup]
stage: utilities
stability: stable
safety_level: low
---

# Get Weather

## Purpose

Retrieve real-time weather information for any city and present it clearly to the user.

## When to use

Use this skill when the user asks for the current weather, a short forecast, or basic weather conditions for a named city.

## Required inputs

- **city_name**: The city to look up.
- **detail_level** (optional): `brief` for a compact status line, `detailed` for JSON-backed detail.

## Steps

1. **Determine the city**: Extract the city name from the user's request. If none is specified, ask the user which city they want.

2. **Fetch weather data**: Use the `fetch_url` tool to retrieve weather information:
   ```
   URL: https://wttr.in/{city_name}?format=3
   ```
   Replace `{city_name}` with the city name. For cities with spaces, replace spaces with `+` (e.g., `New+York`). For Chinese city names, use the English transliteration (e.g., `Beijing`, `Shanghai`).

3. **Richer format (optional)**: For more detailed output, use:
   ```
   URL: https://wttr.in/{city_name}?format=j1
   ```
   This returns JSON with temperature, humidity, wind speed, and forecast.

4. **Present the result**: Format the weather information clearly:
   - Current temperature (°C)
   - Weather condition (sunny, cloudy, rainy, etc.)
   - Wind speed and direction
   - Humidity (if available)

## Output format

- **City**
- **Current condition**
- **Temperature**
- **Wind**
- **Humidity** (if available)

## Failure modes

- Missing city: ask the user to specify a city.
- City not found: try a common English spelling or ask the user to clarify.
- Network error: say the weather service could not be reached and suggest retrying later.

## Examples

User: "What's the weather in Beijing?"
→ `fetch_url("https://wttr.in/Beijing?format=3")`
→ Parse and present: "Beijing: ⛅ Partly cloudy, 22°C, Wind: 15 km/h NE"

User: "Give me a detailed weather report for New York."
→ `fetch_url("https://wttr.in/New+York?format=j1")`
→ Parse and present the current conditions in a compact bullet list.

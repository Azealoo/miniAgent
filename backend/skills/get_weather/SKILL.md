---
name: get_weather
description: Get the current weather for a specified city using wttr.in
---

# Skill: Get Weather

## Purpose

Retrieve real-time weather information for any city and present it clearly to the user.

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

## Example

User: "What's the weather in Beijing?"
→ `fetch_url("https://wttr.in/Beijing?format=3")`
→ Parse and present: "Beijing: ⛅ Partly cloudy, 22°C, Wind: 15 km/h NE"

## Notes

- wttr.in supports most major cities worldwide.
- If the city is not found, try an alternative spelling or ask the user to clarify.
- For privacy, do not use the user's IP-based location; always ask for a city name.

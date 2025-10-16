# NeverMiss
AI-curated local event picks from your Spotify favorites—never miss a show.

![NeverMiss demo](/demo/screenshot.png)

**NeverMiss** turns your Spotify tastes into a clean, date-smart newsletter of local events.  
It fetches upcoming shows, asks Gemini to pick what matches your favorite artists/genres, validates the results, and renders a polished **HTML newsletter**.

---

## ✨ Features

- 🎧 **Spotify-aware**: uses your top artists & genres to filter events.
- 🤖 **Gemini powered**: selects only relevant events from your feed.
- ✅ **Schema-safe**: responses are validated with Pydantic before use.
- 📰 **Beautiful HTML newsletter**: responsive cards with wide image banners (great for rectangular images).
- 📅 **Smart sections**:
  - **This week**
  - **This weekend**
  - **Next week**
  - **Coming soon**
- 🗺️ **Timezone aware**: Europe/Athens.

---

## Requirements

To run this program you need a [Spotify Developer App](https://developer.spotify.com/dashboard) as well as a [Gemini API key](https://aistudio.google.com/api-keys).

## Usage

The first time you run this it will require you to sign in to Spotify.

```bash
python generate_newsletter.py # This generates the recommendations newsletter html
```

## 💡 Why NeverMiss?

Two years ago I stopped using social media altogether. While I’m happier and have more free time, I sometimes miss live music events I’d love to attend if I was aware. **NeverMiss** is my way to keep up on what actually matters to me: **concerts and festivals**. No doomscrolling, no ads, no distractions. Just a clean, personalized feed of shows I care about, delivered to my inbox as a simple, beautiful newsletter.

**What this gives me:**
- 🎵 Focused on **music** (artists/genres I love)
- 🧠 **No social media** required
- 🕒 **Less time wasted**, more time for concerts
- 📰 A personalized **newsletter** instead of noisy feeds
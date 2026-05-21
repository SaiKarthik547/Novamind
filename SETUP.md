# NovaMind — Setup & Usage Guide

## What this is
NovaMind is an autonomous Windows desktop AI agent. It sees your screen,
understands what you ask in plain English, and takes real actions:
drawing in MS Paint, running commands, searching the web, writing code.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Playwright browsers (for web browsing)
playwright install chromium

# 3. Create your API key file
python main.py --setup

# 4. Edit ~/.novamind/.env and add at least one API key (Groq is free)
# On Windows: notepad %USERPROFILE%\.novamind\.env
# On Linux/Mac: open ~/.novamind/.env
# Or just navigate to C:\Users\karth\.novamind\ and open .env with any editor

# 5. Run NovaMind
python main.py
```

## Example tasks

```
Draw a blue sports car in MS Paint
Search the web for the latest Python news
Show CPU and RAM usage
List all files in my Downloads folder
Write a Python script that sorts a list and run it
Take a screenshot and save it to Desktop\screen.png
```

## API Keys (at least one required)

Get a **free** Groq key at https://console.groq.com — works immediately.
Other supported providers: Together AI, OpenRouter, xAI, Google Gemini,
Hyperbolic, NVIDIA NIM, Cerebras.

Add to `~/.novamind/.env`:
```
GROQ_API_KEY=gsk_...
```

## MS Paint Drawing

When you say "Draw X in MS Paint":
1. Any existing Paint windows are closed
2. MS Paint opens and maximises
3. NovaMind asks the LLM for drawing coordinates
4. The mouse moves automatically and draws the shape
5. If the LLM fails, a built-in geometric fallback draws a detailed sports car

The drawing uses real `pyautogui` mouse control — you will see the mouse
moving on your screen. Do not move the mouse or type while drawing.

## Database — 14 tables

All activity is stored in `~/.novamind/memory.db`:

| Table | Contents |
|---|---|
| sessions | Per-launch session records |
| tasks | Every task requested |
| task_steps | Every step in every plan |
| agent_actions | Every real agent action |
| memories | Episodic + semantic memories |
| learning_journal | Lessons from outcomes |
| skills | Reusable skill patterns |
| error_log | Every error with context |
| screenshots | Before/after screenshots |
| llm_calls | Every LLM request + response |
| user_preferences | Your persistent settings |
| ui_events | Button clicks, inputs |
| system_events | Startup, shutdown, etc. |
| schema_info | Schema version |

## Requirements

- Windows 10 or 11
- Python 3.10+
- Tesseract OCR (for screen reading): https://github.com/UB-Mannheim/tesseract/wiki
- pyautogui (installed via requirements.txt)

## Troubleshooting

**MS Paint drawing fails**: Make sure `pyautogui` and `pygetwindow` are
installed. Run `pip install pyautogui pygetwindow`.

**No LLM provider available**: Add at least one API key to `~/.novamind/.env`.

**UI doesn't open**: Install PyQt6 with `pip install PyQt6`.

**OCR / screen reading not working**: Install Tesseract from the link above
and make sure `tesseract.exe` is on your PATH.

import anthropic, config, sys
print("Model:", config.ANTHROPIC_MODEL)
try:
    c = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    r = c.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=30, messages=[{"role":"user","content":"say ok"}])
    print("Claude OK:", r.content[0].text)
except Exception as e:
    print("Claude ERROR:", type(e).__name__, str(e)[:300])

import sys
sys.path.insert(0, '.')
import config
from llm.client import LLMClient
c = LLMClient()
print('GROQ_API_KEY set:', bool(config.GROQ_API_KEY))
print('ANTHROPIC_API_KEY set:', bool(config.ANTHROPIC_API_KEY))
print('OLLAMA_URL set:', bool(config.OLLAMA_URL))
print('backend_name:', c.backend_name)
print('preferred:', c.preferred)
print('enabled flags: groq', c._groq_enabled, 'claude', c._claude_enabled, 'ollama', c._ollama_enabled, 'hf', c._hf_enabled)

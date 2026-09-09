import asyncio
import sys
sys.path.insert(0, '.')
from llm.client import LLMClient

async def main():
    c = LLMClient()
    try:
        resp = await c.chat([{"role":"user","content":"Say hello"}], system="You are a test")
        print('RESPONSE:', resp)
    except Exception as e:
        print('ERROR:', type(e).__name__, e)

if __name__ == '__main__':
    asyncio.run(main())

# test_api.py
import os
from dotenv import load_dotenv
load_dotenv()

from llm_client import LLMClient

client = LLMClient(
    text_gen_api_url="https://integrate.api.nvidia.com/v1/chat/completions",
    text_gen_api_key=os.getenv("NVIDIA_API_KEY"),
    text_gen_model="meta/llama-3.2-3b-instruct",  # Model nhỏ hơn
    critic_api_url="https://integrate.api.nvidia.com/v1/chat/completions",
    critic_api_key=os.getenv("NVIDIA_API_KEY"),
    critic_model="meta/llama-3.2-3b-instruct",
)

try:
    result = client.call_text_gen("Xin chào, hãy nói 'Hello World'")
    print("Success:", result)
except Exception as e:
    print("Error:", e)
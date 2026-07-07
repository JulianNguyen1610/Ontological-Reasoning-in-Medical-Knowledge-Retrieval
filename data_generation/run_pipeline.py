# run_pipeline.py
from pathlib import Path
from config import GenerationConfig
from llm_client import LLMClient
from pipeline import DataGenerationPipeline

def main():
    config = GenerationConfig(num_samples=500, max_retries=5)
    
    llm_client = LLMClient(
        text_gen_api_url=config.text_gen_api_url,
        text_gen_api_key=config.text_gen_api_key,
        text_gen_model=config.text_gen_model,
        critic_api_url=config.critic_api_url,
        critic_api_key=config.critic_api_key,
        critic_model=config.critic_model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        request_delay=config.request_delay
    )
    
    # Sửa đường dẫn seeds_dir
    seeds_dir = Path(__file__).parent / "knowledge_seeds"
    
    pipeline = DataGenerationPipeline(
        config=config,
        llm_client=llm_client,
        output_dir=Path("output"),
        seeds_dir=seeds_dir
    )
    
    samples = pipeline.run(num_samples=500)
    print(f"Generated {len(samples)} valid samples")

if __name__ == "__main__":
    main()
# run_pipeline.py
"""
Entrypoint thay thế — chạy từ bên trong data_generation/ với API thật.
Khuyến nghị dùng scripts/run_generation.py từ repo root.
"""
import sys
import argparse
from pathlib import Path

# Thêm project root vào path để dùng package imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_generation.config import GenerationConfig
from data_generation.llm_client import LLMClient
from data_generation.pipeline import DataGenerationPipeline


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic Vietnamese clinical extraction data.")
    parser.add_argument("--num-samples", type=int, default=50)
    parser.add_argument("--resume", help="Checkpoint JSON created by this pipeline")
    parser.add_argument("--checkpoint-interval", type=int, default=25)
    parser.add_argument("--max-total-attempts", type=int, help="Stop after this many outer generation attempts")
    parser.add_argument("--request-delay", type=float, help="Minimum seconds between API calls")
    parser.add_argument("--rate-limit-cooldown", type=float, help="Minimum cooldown after HTTP 429")
    parser.add_argument("--force-critic-all", action="store_true")
    args = parser.parse_args()
    config = GenerationConfig(
        num_samples=args.num_samples,
        max_retries=5,
        resume_from_checkpoint=args.resume,
        checkpoint_interval=args.checkpoint_interval,
        max_total_attempts=args.max_total_attempts,
        request_delay=args.request_delay if args.request_delay is not None else GenerationConfig.request_delay,
        api_rate_limit_cooldown=(
            args.rate_limit_cooldown
            if args.rate_limit_cooldown is not None
            else GenerationConfig.api_rate_limit_cooldown
        ),
        force_critic_all=args.force_critic_all,
    )
    
    llm_client = LLMClient(
        text_gen_api_url=config.text_gen_api_url,
        text_gen_api_key=config.text_gen_api_key,
        text_gen_model=config.text_gen_model,
        critic_api_url=config.critic_api_url,
        critic_api_key=config.critic_api_key,
        critic_model=config.critic_model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        request_delay=config.request_delay,
        api_max_retries=config.api_max_retries,
        api_retry_base_delay=config.api_retry_base_delay,
        api_retry_max_delay=config.api_retry_max_delay,
        api_retry_jitter=config.api_retry_jitter,
        api_rate_limit_cooldown=config.api_rate_limit_cooldown,
    )
    
    # Sửa đường dẫn seeds_dir
    seeds_dir = Path(__file__).parent / "knowledge_seeds"
    
    pipeline = DataGenerationPipeline(
        config=config,
        llm_client=llm_client,
        output_dir=project_root / "data" / "raw_generated",
        seeds_dir=seeds_dir
    )
    
    samples = pipeline.run(num_samples=config.num_samples)
    print(f"Generated {len(samples)} valid samples")


if __name__ == "__main__":
    main()

import argparse
import json
import random
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_generation.config import GenerationConfig
from data_generation.generators.paraphrase_generator import ParaphraseGenerator
from data_generation.llm_client import LLMClient


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Paraphrase synthetic clinical notes while preserving entity labels."
    )
    parser.add_argument("input_file", help="Path to training_data_*.json or .jsonl")
    parser.add_argument(
        "--mode",
        choices=["strict_preserve", "semantic_preserve"],
        default="strict_preserve",
        help="Paraphrase mode to use.",
    )
    parser.add_argument(
        "--style-target",
        help="Force a single paraphrase style. Default: random from GenerationConfig.style_variants",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N samples.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for style selection.",
    )
    return parser.parse_args()


def _build_llm_client(config: GenerationConfig) -> LLMClient:
    return LLMClient(
        text_gen_api_url=config.text_gen_api_url,
        text_gen_api_key=config.text_gen_api_key,
        text_gen_model=config.text_gen_model,
        critic_api_url=config.critic_api_url,
        critic_api_key=config.critic_api_key,
        critic_model=config.critic_model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        request_delay=config.request_delay,
    )


def _write_outputs(samples, input_path: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"paraphrased_{input_path.stem}"
    json_path = output_dir / f"{base_name}.json"
    jsonl_path = output_dir / f"{base_name}.jsonl"

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(samples, handle, ensure_ascii=False, indent=2)

    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")

    return json_path, jsonl_path


def _load_samples(input_path: Path):
    suffix = input_path.suffix.lower()
    if suffix == ".json":
        with open(input_path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            raise ValueError("JSON input must be a list of samples")
        return data
    if suffix == ".jsonl":
        samples = []
        with open(input_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    samples.append(json.loads(line))
        return samples
    raise ValueError(f"Unsupported input format: {input_path.suffix}")


def main():
    args = _parse_args()
    random.seed(args.seed)

    input_path = Path(args.input_file)
    samples = _load_samples(input_path)

    if args.limit is not None:
        samples = samples[: args.limit]

    config = GenerationConfig()
    llm_client = _build_llm_client(config)
    generator = ParaphraseGenerator(
        llm_client,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    paraphrased_samples = []
    rejected = 0

    for sample in samples:
        style_target = args.style_target or random.choice(config.style_variants)
        paraphrased = generator.paraphrase_sample(
            sample,
            style_target=style_target,
            paraphrase_mode=args.mode,
        )
        if paraphrased is None:
            rejected += 1
            continue
        paraphrased_samples.append(paraphrased)

    output_dir = project_root / "data" / "raw_generated"
    json_path, jsonl_path = _write_outputs(paraphrased_samples, input_path, output_dir)

    print(f"Input samples: {len(samples)}")
    print(f"Paraphrase mode: {args.mode}")
    print(f"Accepted paraphrases: {len(paraphrased_samples)}")
    print(f"Rejected samples: {rejected}")
    print(f"JSON output: {json_path}")
    print(f"JSONL output: {jsonl_path}")


if __name__ == "__main__":
    main()

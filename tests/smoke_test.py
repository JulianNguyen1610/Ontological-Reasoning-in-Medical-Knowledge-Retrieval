"""Smoke test: chạy pipeline end-to-end với mock, 5 samples."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_generation.config import GenerationConfig
from data_generation.pipeline import DataGenerationPipeline, validate_coverage


# Import MockLLMClient từ scripts
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from run_generation import MockLLMClient


def main():
    config = GenerationConfig(num_samples=5, max_retries=3)
    output_dir = Path(__file__).resolve().parent.parent / "data" / "raw_generated"
    seeds_dir = Path(__file__).resolve().parent.parent / "data_generation" / "knowledge_seeds"

    llm_client = MockLLMClient()

    pipeline = DataGenerationPipeline(
        config=config,
        llm_client=llm_client,
        output_dir=output_dir,
        seeds_dir=seeds_dir,
    )

    samples = pipeline.run(num_samples=5)

    print("\n=== SMOKE TEST RESULTS ===")
    print(f"Stats: {json.dumps(pipeline.stats, ensure_ascii=False, indent=2)}")
    print(f"Samples returned: {len(samples)}")

    # Check entity positions
    bad_pos = 0
    empty_entity_samples = 0
    total_entities = 0
    for i, s in enumerate(samples):
        total_entities += len(s["entities"])
        for e in s["entities"]:
            start, end = e["position"]
            actual = s["text"][start:end]
            if actual != e["text"]:
                bad_pos += 1
                print(f"BAD POS sample {i}: expected={e['text']!r} got={actual!r}")
        if not s["entities"]:
            empty_entity_samples += 1
            print(f"WARNING: sample {i} has 0 entities")

    print(f"Bad positions: {bad_pos}")
    print(f"Empty-entity samples: {empty_entity_samples}")
    print(f"Total entities: {total_entities}")

    # Coverage
    coverage = validate_coverage(samples)
    print(f"\nCoverage: {json.dumps(coverage, ensure_ascii=False, indent=2)}")

    # Assertions
    assert len(samples) > 0, "Pipeline produced 0 samples!"
    assert bad_pos == 0, f"Found {bad_pos} bad entity positions"
    assert empty_entity_samples == 0, f"Found {empty_entity_samples} empty-entity samples"
    print("\n✅ ALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()

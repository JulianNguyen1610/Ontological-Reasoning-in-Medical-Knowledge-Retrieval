import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_generation.evaluation.synthetic_evaluator import SyntheticDataEvaluator


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate synthetic clinical data quality.")
    parser.add_argument("--input", help="Single JSON or JSONL synthetic data file")
    parser.add_argument("--clean", help="Path to synthetic clean split")
    parser.add_argument("--hard", help="Path to synthetic hard split")
    parser.add_argument("--human", help="Path to human reviewed split")
    parser.add_argument("--manifest", help="Manifest JSON describing split paths")
    parser.add_argument("--output", required=True, help="Path to JSON report output")
    return parser.parse_args()


def main():
    args = parse_args()
    evaluator = SyntheticDataEvaluator()
    if args.manifest:
        report = evaluator.evaluate_manifest(args.manifest, args.output)
        mode = f"manifest={args.manifest}"
    elif args.clean or args.hard or args.human:
        split_paths = {}
        if args.clean:
            split_paths["synthetic_clean"] = args.clean
        if args.hard:
            split_paths["synthetic_hard"] = args.hard
        if args.human:
            split_paths["human_reviewed"] = args.human
        report = evaluator.evaluate_splits(split_paths, args.output)
        mode = json.dumps(split_paths, ensure_ascii=False)
    elif args.input:
        report = evaluator.evaluate_file(args.input, args.output)
        mode = args.input
    else:
        raise SystemExit("Provide --input, or split args, or --manifest.")
    print(f"Evaluated input: {mode}")
    print(f"Saved report: {args.output}")
    print(f"Ready for training: {report['final_recommendation']['ready_for_training']}")
    print(f"Warnings: {len(report['final_recommendation']['warnings'])}")


if __name__ == "__main__":
    main()

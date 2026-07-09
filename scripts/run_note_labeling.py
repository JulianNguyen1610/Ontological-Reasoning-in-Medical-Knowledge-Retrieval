import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_generation.config import GenerationConfig
from data_generation.generators.note_labeler import NoteLabeler
from data_generation.llm_client import LLMClient


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Label Vietnamese clinical notes into entity JSON with a teacher LLM."
    )
    parser.add_argument("input_file", help="Path to .txt, .json, or .jsonl note file")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N notes.",
    )
    parser.add_argument(
        "--source-type",
        default="public_note",
        choices=["public_note", "synthetic_note", "human_note"],
        help="Default source_type for notes without explicit metadata.",
    )
    parser.add_argument(
        "--teacher-model",
        default="",
        help="Override teacher model stored in provenance.",
    )
    parser.add_argument(
        "--prompt-version",
        default="v1",
        help="Prompt version stored in provenance.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Drop entities with teacher_confidence below this threshold.",
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


def _load_notes(input_path: Path):
    suffix = input_path.suffix.lower()
    if suffix == ".txt":
        notes = []
        for index, segment in enumerate(input_path.read_text(encoding="utf-8").split("\n\n")):
            text = segment.strip()
            if text:
                notes.append({"text": text, "metadata": {"source_id": f"{input_path.stem}_{index}"}})
        return notes
    if suffix == ".json":
        data = json.loads(input_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [_extract_record(item, index) for index, item in enumerate(data) if _extract_record(item, index)]
        record = _extract_record(data, 0)
        return [record] if record else []
    if suffix == ".jsonl":
        notes = []
        with open(input_path, encoding="utf-8") as handle:
            index = 0
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                record = _extract_record(item, index)
                if record:
                    notes.append(record)
                index += 1
        return notes
    raise ValueError(f"Unsupported input format: {input_path.suffix}")


def _extract_record(item, index: int):
    if isinstance(item, str):
        text = item.strip()
        return {"text": text, "metadata": {"source_id": f"record_{index}"}} if text else None
    if isinstance(item, dict):
        text = item.get("text") or item.get("note")
        if isinstance(text, str):
            metadata = {
                "source_id": item.get("source_id", "") or item.get("scenario_id", "") or f"record_{index}",
                "source_type": item.get("source_type", ""),
                "teacher_model": item.get("teacher_model", ""),
                "prompt_version": item.get("prompt_version", ""),
            }
            return {"text": text.strip(), "metadata": metadata}
    return None


def _write_outputs(samples, input_path: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"note_labeled_{input_path.stem}"
    json_path = output_dir / f"{base_name}.json"
    jsonl_path = output_dir / f"{base_name}.jsonl"

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(samples, handle, ensure_ascii=False, indent=2)

    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")

    return json_path, jsonl_path


def main():
    args = _parse_args()
    input_path = Path(args.input_file)
    records = _load_notes(input_path)
    if args.limit is not None:
        records = records[: args.limit]

    config = GenerationConfig()
    llm_client = _build_llm_client(config)
    labeler = NoteLabeler(
        llm_client,
        temperature=0.0,
        max_tokens=config.max_tokens,
    )

    labeled_samples = []
    failed_samples = []
    no_entity_samples = []
    for record in records:
        metadata = dict(record["metadata"])
        if not metadata.get("source_type"):
            metadata["source_type"] = args.source_type
        if not metadata.get("teacher_model"):
            metadata["teacher_model"] = args.teacher_model or config.text_gen_model
        if not metadata.get("prompt_version"):
            metadata["prompt_version"] = args.prompt_version
        labeled = labeler.label_note(
            record["text"],
            metadata=metadata,
            min_confidence=args.min_confidence,
        )
        status = labeled.get("label_provenance", {}).get("labeling_status", "")
        if status == "teacher_parse_failed":
            failed_samples.append(labeled)
            continue
        if not labeled.get("entities"):
            no_entity_samples.append(labeled)
        labeled_samples.append(labeled)

    output_dir = project_root / "data" / "raw_generated"
    json_path, jsonl_path = _write_outputs(labeled_samples, input_path, output_dir)
    failed_json_path = None
    if failed_samples:
        failed_json_path, _ = _write_outputs(failed_samples, input_path, output_dir / "failed_note_labeling")

    print(f"Input notes: {len(records)}")
    print(f"Successful outputs: {len(labeled_samples)}")
    print(f"Teacher parse failures: {len(failed_samples)}")
    print(f"Successful outputs with 0 entities: {len(no_entity_samples)}")
    print(f"JSON output: {json_path}")
    print(f"JSONL output: {jsonl_path}")
    if failed_json_path is not None:
        print(f"Failed labeling JSON output: {failed_json_path}")


if __name__ == "__main__":
    main()

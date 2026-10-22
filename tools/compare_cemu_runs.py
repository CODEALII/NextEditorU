"""Compare matched clean/modified Cemu movement evidence without claiming OCR."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


MATCHED_FIELDS = (
    "rpx_sha256", "cemu_executable_sha256", "controller_sha256", "sequence",
    "start_label", "hold_ms", "settle_wait_ms", "baseline_save_hashes",
)


def _load(path):
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read Cemu run report {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Cemu run report {path} must contain a JSON object")
    return value


def _step_reviews(run):
    reviews = {}
    for event in run.get("events", []):
        if (isinstance(event, dict) and event.get("action") == "step_review_confirmed"
                and type(event.get("step")) is int):
            reviews[event["step"]] = event
    return reviews


def _screenshot_evidence(run, event):
    label = event.get("observed_location")
    label = label.strip() if isinstance(label, str) and label.strip() else None
    path = event.get("screenshot")
    evidence = {"label": label, "screenshot": path if isinstance(path, str) else None}
    if not isinstance(path, str):
        evidence["error"] = "missing screenshot path"
    else:
        image = Path(path)
        try:
            content = image.read_bytes()
        except OSError as error:
            evidence["screenshot"] = str(image)
            evidence["error"] = f"screenshot unavailable: {error}"
        else:
            evidence["screenshot"] = str(image)
            evidence["screenshot_sha256"] = hashlib.sha256(content).hexdigest()
    if label is None or event.get("observation_source") != "operator":
        evidence.setdefault("error", "missing operator location label")
    return evidence


def compare_runs(clean, modified, *, expected_pack_sha256=None):
    """Return matched-input checks and manually observed step differences."""
    issues = []
    matches = {}
    for label, run in (("clean", clean), ("modified", modified)):
        if run.get("status") != "completed":
            issues.append(f"{label} run status is not completed")
        if run.get("pause_after_each_step") is not True:
            issues.append(f"{label} run did not pause for every movement step")
        if not run.get("sequence"):
            issues.append(f"{label} run has no directional sequence")
        confirmed = {event.get("gate") for event in run.get("events", [])
                     if isinstance(event, dict) and event.get("action") == "manual_gate_confirmed"}
        if "overworld_visible" not in confirmed or "starting_node" not in confirmed:
            issues.append(f"{label} run lacks confirmed overworld/start-node gates")

    for field in MATCHED_FIELDS:
        left, right = clean.get(field), modified.get(field)
        matches[field] = left is not None and left == right
        if not matches[field]:
            issues.append(f"matched test input differs or is missing: {field}")

    if clean.get("pack_sha256") is not None or clean.get("profile_pack_sha256") is not None:
        issues.append("clean run unexpectedly has a mod archive")
    archive_hash = modified.get("pack_sha256")
    profile_hash = modified.get("profile_pack_sha256")
    matches["modified_pack_copy"] = bool(archive_hash and archive_hash == profile_hash)
    if not matches["modified_pack_copy"]:
        issues.append("modified pack hash does not match the installed profile copy")
    if expected_pack_sha256 and archive_hash != expected_pack_sha256:
        matches["expected_pack"] = False
        issues.append("modified pack hash does not match --expected-pack-sha256")
    elif expected_pack_sha256:
        matches["expected_pack"] = True
    modified_preflight = modified.get("profile_preflight")
    if not isinstance(modified_preflight, dict) or modified_preflight.get("ready") is not True:
        issues.append("modified run is missing a passing profile preflight")
    else:
        graph = modified_preflight.get("graph_validation")
        if not isinstance(graph, dict) or graph.get("matches") is not True:
            issues.append("modified run has no passing graph-profile provenance")
        if modified_preflight.get("expected_pack_active_in_log") is not True:
            issues.append("modified pack was not confirmed active in the Cemu log")
        archive = modified_preflight.get("archive")
        if not isinstance(archive, dict) or archive.get("sha256") != archive_hash:
            issues.append("profile preflight archive hash does not match the tested pack")
        elif archive.get("matches_profile_copy") is not True:
            issues.append("profile preflight did not confirm its installed archive copy")

    clean_reviews = _step_reviews(clean)
    modified_reviews = _step_reviews(modified)
    sequence = clean.get("sequence") if isinstance(clean.get("sequence"), list) else []
    steps = []
    for index, key in enumerate(sequence, 1):
        left_event, right_event = clean_reviews.get(index), modified_reviews.get(index)
        left = _screenshot_evidence(clean, left_event) if left_event else {
            "label": None, "screenshot": None, "error": "missing step review"}
        right = _screenshot_evidence(modified, right_event) if right_event else {
            "label": None, "screenshot": None, "error": "missing step review"}
        if left_event and left_event.get("key") != key:
            issues.append(f"clean step {index} review does not match the tested key")
        if right_event and right_event.get("key") != key:
            issues.append(f"modified step {index} review does not match the tested key")
        if left.get("error"):
            issues.append(f"clean step {index}: {left['error']}")
        if right.get("error"):
            issues.append(f"modified step {index}: {right['error']}")
        steps.append({"step": index, "key": key, "clean": left, "modified": right,
                      "labels_differ": (left.get("label") != right.get("label")
                                        if left.get("label") and right.get("label") else None)})

    save_changes = {}
    for label, run in (("clean", clean), ("modified", modified)):
        baseline, final = run.get("baseline_save_hashes"), run.get("final_save_hashes")
        if not isinstance(baseline, dict) or not isinstance(final, dict):
            issues.append(f"{label} run is missing save snapshots")
            save_changes[label] = None
        else:
            save_changes[label] = {name: {"before": baseline.get(name), "after": final.get(name),
                                          "changed": baseline.get(name) != final.get(name)}
                                   for name in sorted(set(baseline) | set(final))}

    return {
        "comparable": not issues,
        "gameplay_verified": False,
        "interpretation": "Labels are operator-reported visual observations. This tool does not inspect images, identify engine point IDs, or prove route causality.",
        "matched_inputs": matches,
        "clean_case": clean.get("case"),
        "modified_case": modified.get("case"),
        "steps": steps,
        "save_changes": save_changes,
        "issues": issues,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clean_report", type=Path)
    parser.add_argument("modified_report", type=Path)
    parser.add_argument("--expected-pack-sha256")
    parser.add_argument("--output", type=Path, help="Write the comparison JSON to this path")
    args = parser.parse_args(argv)
    try:
        result = compare_runs(_load(args.clean_report), _load(args.modified_report),
                             expected_pack_sha256=args.expected_pack_sha256)
    except ValueError as error:
        parser.exit(2, f"Cemu run comparison failed: {error}\n")
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["comparable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Deterministic video evidence extraction for the Cinematic Video Analysis plugin."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"


class PipelineError(RuntimeError):
    pass


def tool(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise PipelineError(f"Required executable not found: {name}")
    return value


def run(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = run(command)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "unknown error").strip()
        raise PipelineError(f"Command failed ({command[0]}): {message[-2000:]}")
    return result


def ensure_video(path_value: str | Path) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise PipelineError(f"Video file does not exist: {path}")
    return path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fraction(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return float(numerator) / float(denominator)
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def timecode(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def probe_video(video: Path) -> dict[str, Any]:
    result = run_checked([
        tool("ffprobe"), "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(video),
    ])
    raw = json.loads(result.stdout)
    streams = raw.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video_stream:
        raise PipelineError("No video stream was found in the source.")
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    fmt = raw.get("format", {})
    duration = number(fmt.get("duration")) or number(video_stream.get("duration"))
    if duration is None or duration <= 0:
        raise PipelineError("The source duration could not be determined.")
    fps = fraction(video_stream.get("avg_frame_rate")) or fraction(video_stream.get("r_frame_rate"))
    frame_count = number(video_stream.get("nb_frames"))
    if frame_count is None and fps:
        frame_count = round(duration * fps)
    tags = video_stream.get("tags", {})
    rotation = number(tags.get("rotate")) or 0
    for side_data in video_stream.get("side_data_list", []):
        if side_data.get("rotation") is not None:
            rotation = number(side_data.get("rotation")) or rotation
    return {
        "duration_seconds": round(duration, 6),
        "duration_timecode": timecode(duration),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "display_aspect_ratio": video_stream.get("display_aspect_ratio"),
        "pixel_aspect_ratio": video_stream.get("sample_aspect_ratio"),
        "rotation_degrees": rotation,
        "frame_rate": round(fps, 6) if fps else None,
        "estimated_frame_count": int(frame_count) if frame_count is not None else None,
        "video_codec": video_stream.get("codec_name"),
        "pixel_format": video_stream.get("pix_fmt"),
        "color_space": video_stream.get("color_space"),
        "color_transfer": video_stream.get("color_transfer"),
        "color_primaries": video_stream.get("color_primaries"),
        "audio_stream_count": len(audio_streams),
        "audio_codecs": [stream.get("codec_name") for stream in audio_streams],
        "container": fmt.get("format_name"),
        "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
    }


def detect_cuts(video: Path, threshold: float) -> list[float]:
    filter_value = f"select='gt(scene,{threshold:.4f})',showinfo"
    result = run([
        tool("ffmpeg"), "-hide_banner", "-nostats", "-loglevel", "info",
        "-i", str(video), "-map", "0:v:0", "-vf", filter_value,
        "-an", "-f", "null", "-",
    ])
    if result.returncode != 0:
        raise PipelineError(f"Scene detection failed: {(result.stderr or '')[-2000:]}")
    values = re.findall(r"pts_time:([0-9.eE+\-]+)", result.stderr or "")
    return sorted({round(float(value), 6) for value in values if float(value) > 0})


def detect_chroma_cuts(video: Path, threshold: float) -> list[float]:
    """Catch hard cuts whose luma is similar but chroma changes substantially."""
    graph = (
        "[0:v]tblend=all_mode=difference,signalstats,split=2[u][v];"
        f"[u]metadata=mode=select:key=lavfi.signalstats.UAVG:value={threshold:.3f}:"
        "function=greater,showinfo[uo];"
        f"[v]metadata=mode=select:key=lavfi.signalstats.VAVG:value={threshold:.3f}:"
        "function=greater,showinfo[vo]"
    )
    result = run([
        tool("ffmpeg"), "-hide_banner", "-nostats", "-loglevel", "info",
        "-i", str(video), "-filter_complex", graph,
        "-map", "[uo]", "-an", "-f", "null", "-",
        "-map", "[vo]", "-an", "-f", "null", "-",
    ])
    if result.returncode != 0:
        raise PipelineError(f"Chroma-aware scene detection failed: {(result.stderr or '')[-2000:]}")
    values = re.findall(r"showinfo[^\n]*pts_time:([0-9.eE+\-]+)", result.stderr or "")
    return sorted({round(float(value), 6) for value in values if float(value) > 0})


def sanitize_boundaries(cuts: Iterable[float], duration: float, min_shot: float) -> list[float]:
    boundaries = [0.0]
    for cut in sorted(cuts):
        if cut >= duration:
            continue
        if cut - boundaries[-1] >= min_shot:
            boundaries.append(cut)
    if duration - boundaries[-1] < min_shot and len(boundaries) > 1:
        boundaries.pop()
    boundaries.append(duration)
    return boundaries


def thin_boundaries(boundaries: list[float], max_shots: int) -> tuple[list[float], bool]:
    shot_count = len(boundaries) - 1
    if shot_count <= max_shots:
        return boundaries, False
    internal = boundaries[1:-1]
    wanted = max_shots - 1
    selected_indexes = sorted({round(i * (len(internal) - 1) / max(1, wanted - 1)) for i in range(wanted)})
    selected = [internal[index] for index in selected_indexes]
    return [boundaries[0], *selected, boundaries[-1]], True


def representative_time(start: float, end: float) -> float:
    duration = end - start
    margin = min(0.08, duration * 0.12)
    return min(max((start + end) / 2, start + margin), end - margin)


def extract_frame(video: Path, at_seconds: float, output: Path, width: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    run_checked([
        tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{at_seconds:.6f}", "-i", str(video), "-map", "0:v:0",
        "-frames:v", "1", "-vf", f"scale=w='min({width},iw)':h=-2",
        "-q:v", "2", str(output),
    ])
    if not output.is_file() or output.stat().st_size == 0:
        raise PipelineError(f"Frame extraction produced no image at {timecode(at_seconds)}")


def _stack_filter(count: int, columns: int, cell_w: int, cell_h: int, labels: list[str], drawtext: bool) -> str:
    pieces: list[str] = []
    for index in range(count):
        base = (
            f"[{index}:v]scale={cell_w}:{cell_h}:force_original_aspect_ratio=decrease,"
            f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:color=0x111111"
        )
        if drawtext:
            safe = labels[index].replace("'", "\\'").replace(":", "\\:")
            base += (
                f",drawtext=text='{safe}':x=10:y=10:fontsize=18:fontcolor=white:"
                "box=1:boxcolor=black@0.88:boxborderw=6"
            )
        pieces.append(base + f"[v{index}]")
    if count == 1:
        pieces.append("[v0]null[out]")
    else:
        layout = []
        for index in range(count):
            x = (index % columns) * cell_w
            y = (index // columns) * cell_h
            layout.append(f"{x}_{y}")
        inputs = "".join(f"[v{index}]" for index in range(count))
        pieces.append(f"{inputs}xstack=inputs={count}:layout={'|'.join(layout)}:fill=0x111111[out]")
    return ";".join(pieces)


def compose_grid(images: list[Path], output: Path, labels: list[str], *, columns: int, cell_w: int, cell_h: int) -> None:
    if not images:
        return
    command = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y"]
    for image in images:
        command.extend(["-i", str(image)])
    for drawtext in (True, False):
        filter_graph = _stack_filter(len(images), columns, cell_w, cell_h, labels, drawtext)
        trial = command + ["-filter_complex", filter_graph, "-map", "[out]", "-frames:v", "1", str(output)]
        result = run(trial)
        if result.returncode == 0 and output.is_file() and output.stat().st_size:
            return
    raise PipelineError(f"Could not compose evidence sheet: {output}")


def build_contact_sheets(shots: list[dict[str, Any]], output_dir: Path, page_size: int = 12) -> list[str]:
    sheet_dir = output_dir / "contact-sheets"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    relative_paths: list[str] = []
    for page_start in range(0, len(shots), page_size):
        page = shots[page_start:page_start + page_size]
        images = [output_dir / shot["keyframe"] for shot in page]
        labels = [f"{shot['id']}  {shot['timecode_in']}" for shot in page]
        output = sheet_dir / f"contact-{page_start // page_size + 1:03d}.jpg"
        compose_grid(images, output, labels, columns=4, cell_w=360, cell_h=216)
        relative_paths.append(output.relative_to(output_dir).as_posix())
    return relative_paths


def write_shot_tables(output_dir: Path, payload: dict[str, Any]) -> None:
    shots = payload["shots"]
    with (output_dir / "shot-list.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["shot_id", "timecode_in", "timecode_out", "duration_seconds", "representative_time", "keyframe"])
        for shot in shots:
            writer.writerow([
                shot["id"], shot["timecode_in"], shot["timecode_out"],
                shot["duration_seconds"], shot["representative_timecode"], shot["keyframe"],
            ])
    lines = [
        "# Technical Shot List",
        "",
        f"Source: `{payload['source']['filename']}`  ",
        f"Duration: {payload['media']['duration_timecode']}  ",
        f"Detected shots: {payload['summary']['shot_count']}  ",
        "",
        "| Shot | In | Out | Duration | Keyframe |",
        "|---|---:|---:|---:|---|",
    ]
    for shot in shots:
        lines.append(
            f"| {shot['id']} | {shot['timecode_in']} | {shot['timecode_out']} | "
            f"{shot['duration_seconds']:.3f}s | [{Path(shot['keyframe']).name}]({shot['keyframe']}) |"
        )
    (output_dir / "shot-list.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def command_prepare(args: argparse.Namespace) -> dict[str, Any]:
    video = ensure_video(args.video)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    media = probe_video(video)
    threshold = args.threshold
    scene_cuts = detect_cuts(video, threshold)
    chroma_cuts = [] if args.no_color_aware else detect_chroma_cuts(video, args.color_threshold)
    raw_cuts = sorted(set(scene_cuts + chroma_cuts))
    boundaries = sanitize_boundaries(raw_cuts, media["duration_seconds"], args.min_shot)
    boundaries, thinned = thin_boundaries(boundaries, args.max_shots)
    frames_dir = output_dir / "frames"
    shots: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
        rep = representative_time(start, end)
        frame_path = frames_dir / f"shot_{index:04d}.jpg"
        extract_frame(video, rep, frame_path, args.frame_width)
        shots.append({
            "id": f"S{index:03d}",
            "index": index,
            "start_seconds": round(start, 6),
            "end_seconds": round(end, 6),
            "duration_seconds": round(end - start, 6),
            "timecode_in": timecode(start),
            "timecode_out": timecode(end),
            "representative_seconds": round(rep, 6),
            "representative_timecode": timecode(rep),
            "keyframe": frame_path.relative_to(output_dir).as_posix(),
            "boundary_basis": "scene-change detector" if index > 1 else "source start",
        })
    durations = [shot["duration_seconds"] for shot in shots]
    summary = {
        "shot_count": len(shots),
        "cuts_per_minute": round(max(0, len(shots) - 1) / media["duration_seconds"] * 60, 3),
        "mean_shot_length_seconds": round(statistics.mean(durations), 3),
        "median_shot_length_seconds": round(statistics.median(durations), 3),
        "shortest_shot_seconds": round(min(durations), 3),
        "longest_shot_seconds": round(max(durations), 3),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(video),
            "filename": video.name,
            "size_bytes": video.stat().st_size,
        },
        "media": media,
        "detection": {
            "method": "FFmpeg scene score + chroma difference" if not args.no_color_aware else "FFmpeg scene score",
            "threshold": threshold,
            "color_aware": not args.no_color_aware,
            "color_difference_threshold": None if args.no_color_aware else args.color_threshold,
            "minimum_shot_seconds": args.min_shot,
            "raw_cut_count": len(raw_cuts),
            "scene_score_cut_count": len(scene_cuts),
            "chroma_cut_count": len(chroma_cuts),
            "boundary_list_thinned_to_max_shots": thinned,
            "maximum_shots": args.max_shots,
        },
        "summary": summary,
        "shots": shots,
    }
    payload["contact_sheets"] = build_contact_sheets(shots, output_dir)
    write_json(output_dir / "shots.json", payload)
    write_shot_tables(output_dir, payload)
    return {
        "shots_json": str(output_dir / "shots.json"),
        "shot_count": len(shots),
        "contact_sheets": len(payload["contact_sheets"]),
        "threshold": threshold,
    }


def load_shots(path_value: str | Path, source_override: str | None) -> tuple[Path, dict[str, Any], Path]:
    shots_path = Path(path_value).expanduser().resolve()
    if not shots_path.is_file():
        raise PipelineError(f"shots.json does not exist: {shots_path}")
    payload = json.loads(shots_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION or not payload.get("shots"):
        raise PipelineError("Unsupported or empty shots.json.")
    source = ensure_video(source_override or payload.get("source", {}).get("path", ""))
    return shots_path, payload, source


def command_motion(args: argparse.Namespace) -> dict[str, Any]:
    shots_path, payload, video = load_shots(args.shots_json, args.input)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    selected = payload["shots"][:args.max_shots]
    for shot in selected:
        start = shot["start_seconds"]
        duration = shot["duration_seconds"]
        positions = [start + duration * fraction_value for fraction_value in (0.15, 0.5, 0.85)]
        frame_paths: list[Path] = []
        for label, at_seconds in zip(("A", "B", "C"), positions):
            frame = output_dir / "frames" / f"{shot['id'].lower()}_{label.lower()}.jpg"
            extract_frame(video, at_seconds, frame, args.frame_width)
            frame_paths.append(frame)
        strip = output_dir / "strips" / f"{shot['id'].lower()}_motion.jpg"
        strip.parent.mkdir(parents=True, exist_ok=True)
        labels = [f"{shot['id']} {label} {timecode(at)}" for label, at in zip(("A", "B", "C"), positions)]
        compose_grid(frame_paths, strip, labels, columns=3, cell_w=480, cell_h=270)
        items.append({
            "shot_id": shot["id"],
            "timecode_in": shot["timecode_in"],
            "timecode_out": shot["timecode_out"],
            "sample_seconds": [round(value, 6) for value in positions],
            "sample_timecodes": [timecode(value) for value in positions],
            "frames": [path.relative_to(output_dir).as_posix() for path in frame_paths],
            "strip": strip.relative_to(output_dir).as_posix(),
        })
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_shots_json": str(shots_path),
        "source_video": str(video),
        "sampling": [0.15, 0.5, 0.85],
        "truncated": len(payload["shots"]) > len(selected),
        "shots": items,
    }
    write_json(output_dir / "motion-manifest.json", manifest)
    return {"motion_manifest": str(output_dir / "motion-manifest.json"), "strip_count": len(items)}


def command_pairs(args: argparse.Namespace) -> dict[str, Any]:
    shots_path, payload, video = load_shots(args.shots_json, args.input)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs = list(zip(payload["shots"], payload["shots"][1:]))[:args.max_pairs]
    items: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(pairs, start=1):
        left_margin = min(0.12, left["duration_seconds"] * 0.15)
        right_margin = min(0.12, right["duration_seconds"] * 0.15)
        left_time = max(left["start_seconds"], left["end_seconds"] - left_margin)
        right_time = min(right["end_seconds"], right["start_seconds"] + right_margin)
        left_frame = output_dir / "frames" / f"pair_{index:04d}_out.jpg"
        right_frame = output_dir / "frames" / f"pair_{index:04d}_in.jpg"
        extract_frame(video, left_time, left_frame, args.frame_width)
        extract_frame(video, right_time, right_frame, args.frame_width)
        pair_image = output_dir / "pairs" / f"pair_{index:04d}_{left['id'].lower()}_{right['id'].lower()}.jpg"
        pair_image.parent.mkdir(parents=True, exist_ok=True)
        compose_grid(
            [left_frame, right_frame], pair_image,
            [f"OUT {left['id']} {timecode(left_time)}", f"IN {right['id']} {timecode(right_time)}"],
            columns=2, cell_w=640, cell_h=360,
        )
        items.append({
            "pair_id": f"P{index:03d}",
            "outgoing_shot": left["id"],
            "incoming_shot": right["id"],
            "outgoing_timecode": timecode(left_time),
            "incoming_timecode": timecode(right_time),
            "outgoing_frame": left_frame.relative_to(output_dir).as_posix(),
            "incoming_frame": right_frame.relative_to(output_dir).as_posix(),
            "pair_image": pair_image.relative_to(output_dir).as_posix(),
        })
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_shots_json": str(shots_path),
        "source_video": str(video),
        "truncated": len(payload["shots"]) - 1 > len(items),
        "pairs": items,
    }
    write_json(output_dir / "continuity-manifest.json", manifest)
    return {"continuity_manifest": str(output_dir / "continuity-manifest.json"), "pair_count": len(items)}


def command_probe(args: argparse.Namespace) -> dict[str, Any]:
    video = ensure_video(args.video)
    payload = {"source": str(video), "media": probe_video(video)}
    if args.output:
        write_json(Path(args.output).expanduser().resolve(), payload)
    return payload


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Extract deterministic evidence for cinematic video analysis.")
    commands = root.add_subparsers(dest="command", required=True)

    probe = commands.add_parser("probe", help="Read technical source metadata.")
    probe.add_argument("video")
    probe.add_argument("--output")
    probe.set_defaults(handler=command_probe)

    prepare = commands.add_parser("prepare", help="Detect shots and extract representative evidence.")
    prepare.add_argument("video")
    prepare.add_argument("output_dir")
    prepare.add_argument("--threshold", type=float, default=0.30)
    prepare.add_argument("--color-threshold", type=float, default=32.0)
    prepare.add_argument("--no-color-aware", action="store_true", help="Disable the extra chroma-difference pass.")
    prepare.add_argument("--min-shot", type=float, default=0.35)
    prepare.add_argument("--max-shots", type=int, default=240)
    prepare.add_argument("--frame-width", type=int, default=1280)
    prepare.set_defaults(handler=command_prepare)

    motion = commands.add_parser("motion", help="Extract beginning/middle/end evidence per shot.")
    motion.add_argument("shots_json")
    motion.add_argument("output_dir")
    motion.add_argument("--input", help="Override the source path stored in shots.json.")
    motion.add_argument("--max-shots", type=int, default=240)
    motion.add_argument("--frame-width", type=int, default=1280)
    motion.set_defaults(handler=command_motion)

    pairs = commands.add_parser("pairs", help="Extract adjacent outgoing/incoming continuity evidence.")
    pairs.add_argument("shots_json")
    pairs.add_argument("output_dir")
    pairs.add_argument("--input", help="Override the source path stored in shots.json.")
    pairs.add_argument("--max-pairs", type=int, default=240)
    pairs.add_argument("--frame-width", type=int, default=1280)
    pairs.set_defaults(handler=command_pairs)
    return root


def main() -> int:
    args = parser().parse_args()
    if hasattr(args, "threshold") and not 0.01 <= args.threshold <= 0.99:
        raise PipelineError("--threshold must be between 0.01 and 0.99.")
    if hasattr(args, "color_threshold") and not 1 <= args.color_threshold <= 255:
        raise PipelineError("--color-threshold must be between 1 and 255.")
    for attr in ("min_shot", "max_shots", "max_pairs", "frame_width"):
        if hasattr(args, attr) and getattr(args, attr) <= 0:
            raise PipelineError(f"--{attr.replace('_', '-')} must be greater than zero.")
    result = args.handler(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PipelineError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)

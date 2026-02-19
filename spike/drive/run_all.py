#!/usr/bin/env python3
"""Orchestrator: runs all 6 experiments and generates SPIKE_FINDINGS.md."""

import importlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config

EXPERIMENTS = [
    ("01_auth_list", "01_auth_list"),
    ("02_changes_api", "02_changes_api"),
    ("03_download_resume", "03_download_resume"),
    ("04_transcode", "04_transcode"),
    ("05_ocr_stt", "05_ocr_stt"),
    ("06_quota_stress", "06_quota_stress"),
]

FINDINGS_OUTPUT = Path(__file__).parent.parent.parent / "docs" / "google-drive" / "SPIKE_FINDINGS.md"


def main():
    config.validate()
    config.ensure_dirs()

    print("=" * 60)
    print("HEIMDEX DRIVE SPIKE — Running all experiments")
    print("=" * 60)
    print(f"  Drive ID: {config.DRIVE_ID}")
    print(f"  Impersonate: {config.IMPERSONATE_EMAIL}")
    print(f"  SA Key: {config.SA_KEY_PATH}")
    print(f"  Temp dir: {config.TEMP_DIR}")
    print(f"  Log dir: {config.LOG_DIR}")
    print()

    all_results = {}
    total_start = time.monotonic()

    for module_name, label in EXPERIMENTS:
        print(f"\n{'=' * 60}")
        print(f"EXPERIMENT: {label}")
        print(f"{'=' * 60}\n")

        try:
            module = importlib.import_module(module_name)
            result = module.run()
            all_results[label] = result
            error_count = len(result.get("errors", []))
            if error_count:
                print(f"\n⚠ {label} completed with {error_count} error(s)")
            else:
                print(f"\n✓ {label} completed successfully")
        except Exception as e:
            print(f"\n✗ {label} CRASHED: {e}")
            all_results[label] = {"error": str(e), "crashed": True}

    total_seconds = (time.monotonic() - total_start)
    print(f"\n{'=' * 60}")
    print(f"All experiments completed in {total_seconds:.1f}s")
    print(f"{'=' * 60}")

    # Save combined results
    combined_path = config.LOG_DIR / "all_results.json"
    with open(combined_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nCombined results saved to {combined_path}")

    # Generate SPIKE_FINDINGS.md
    generate_findings(all_results, total_seconds)


def generate_findings(results: dict, total_seconds: float):
    """Generate SPIKE_FINDINGS.md from experiment results."""
    FINDINGS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    r01 = results.get("01_auth_list", {})
    r02 = results.get("02_changes_api", {})
    r03 = results.get("03_download_resume", {})
    r04 = results.get("04_transcode", {})
    r05 = results.get("05_ocr_stt", {})
    r06 = results.get("06_quota_stress", {})

    md = []
    md.append("# Spike Findings: Google Drive Integration\n")
    md.append(f"**Date**: {time.strftime('%Y-%m-%d')}")
    md.append(f"**Total runtime**: {total_seconds:.0f}s")
    md.append(f"**Status**: Auto-generated from spike experiments\n")
    md.append("---\n")

    # Section 1: Environment
    md.append("## 1. Environment\n")
    md.append(f"| Setting | Value |")
    md.append(f"|---------|-------|")
    md.append(f"| Drive ID | `{config.DRIVE_ID}` |")
    md.append(f"| Impersonate Email | `{config.IMPERSONATE_EMAIL}` |")
    md.append(f"| SA Key | `{Path(config.SA_KEY_PATH).name}` |")
    md.append(f"| Chunk Size | {config.DOWNLOAD_CHUNK_SIZE / (1024 * 1024):.0f} MB |")
    md.append(f"| ffmpeg | {r04.get('ffmpeg_version', 'N/A')} |")
    md.append("")

    # Section 2: Auth + Listing
    md.append("## 2. Auth + Listing Performance\n")
    auth = r01.get("auth", {})
    listing = r01.get("listing", {})
    md.append(f"| Metric | Value |")
    md.append(f"|--------|-------|")
    md.append(f"| Cold DWD auth | {_ms(auth.get('cold_auth_ms'))} |")
    md.append(f"| Warm auth (avg of {auth.get('warm_auth_samples', 0)}) | {_ms(auth.get('warm_auth_ms_avg'))} |")
    md.append(f"| Authenticated as | `{auth.get('user_email', 'N/A')}` |")
    md.append(f"| Total video files | {listing.get('total_video_files', 'N/A')} |")
    md.append(f"| Listing pages | {listing.get('total_pages', 'N/A')} |")
    md.append(f"| Full listing time | {_ms(listing.get('full_list_ms'))} |")
    md.append("")

    size_dist = listing.get("size_distribution", {})
    if size_dist:
        md.append(f"**File size distribution**: {size_dist.get('min_mb')} MB - {size_dist.get('max_mb')} MB "
                   f"(avg {size_dist.get('avg_mb')} MB, total {size_dist.get('total_gb')} GB)\n")

    page_tests = listing.get("page_size_tests", [])
    if page_tests:
        md.append("### Page Size Latency\n")
        md.append("| pageSize | Latency | Files Returned |")
        md.append("|----------|---------|----------------|")
        for pt in page_tests:
            md.append(f"| {pt.get('page_size')} | {_ms(pt.get('latency_ms'))} | {pt.get('files_returned', 'err')} |")
        md.append("")

    # Section 3: Changes API
    md.append("## 3. Changes API Behavior\n")
    cl = r02.get("changes_list", {})
    spt = r02.get("start_page_token", {})
    inv = r02.get("invalid_token", {})
    md.append(f"| Metric | Value |")
    md.append(f"|--------|-------|")
    md.append(f"| getStartPageToken latency (avg) | {_ms(spt.get('latency_ms_avg'))} |")
    md.append(f"| Total changes detected | {cl.get('total_changes', 'N/A')} |")
    md.append(f"| Changes pages | {cl.get('total_pages', 'N/A')} |")
    md.append(f"| Changes fetch time | {_ms(cl.get('total_ms'))} |")
    md.append(f"| Invalid token behavior | {inv.get('behavior', 'N/A')} (HTTP {inv.get('http_status', '?')}) |")
    md.append(f"| Token persistence | {'Saved token found' if r02.get('token_persistence', {}).get('saved_token_found') else 'First run (no saved token)'} |")
    md.append("")

    rapid = cl.get("rapid_calls", {})
    if rapid:
        md.append(f"**Rapid successive calls**: avg {_ms(rapid.get('avg_ms'))}, "
                   f"p95 {_ms(rapid.get('p95_ms'))}, {rapid.get('count')} samples\n")

    categories = cl.get("categories", {})
    if categories:
        md.append(f"**Change categories**: modified={categories.get('modified', 0)}, "
                   f"trashed={categories.get('trashed', 0)}, other={categories.get('other', 0)}\n")

    # Section 4: Download Throughput + Resume
    md.append("## 4. Download Throughput + Resume\n")
    downloads = r03.get("downloads", [])
    if downloads:
        md.append("### Download Speed by Size\n")
        md.append("| Bucket | File | Size | Time | Speed | MD5 Match |")
        md.append("|--------|------|------|------|-------|-----------|")
        for dl in downloads:
            md.append(f"| {dl.get('bucket', '?')} | {dl.get('name', '?')[:30]} | "
                       f"{dl.get('size_mb', '?')} MB | {dl.get('total_seconds', '?')}s | "
                       f"{dl.get('overall_mbps', '?')} MB/s | "
                       f"{'✓' if dl.get('md5_match') else '✗' if dl.get('md5_match') is False else '?'} |")
        md.append("")

    resume = r03.get("resume_test", {})
    if resume and not resume.get("error"):
        md.append("### Resume Test\n")
        md.append(f"| Metric | Value |")
        md.append(f"|--------|-------|")
        md.append(f"| File | {resume.get('name', 'N/A')} |")
        md.append(f"| Total size | {resume.get('size_bytes', 0) / (1024 * 1024):.1f} MB |")
        md.append(f"| Abort at | {resume.get('abort_at_pct', '?')}% ({resume.get('abort_at_bytes', 0) / (1024 * 1024):.1f} MB) |")
        md.append(f"| Phase 1 (download) | {_ms(resume.get('phase1_ms'))} |")
        md.append(f"| Phase 2 (resume) | {_ms(resume.get('phase2_ms'))} |")
        md.append(f"| Range header honored | {'✓' if resume.get('range_header_honored') else '✗'} |")
        md.append(f"| MD5 after resume | {'✓ Match' if resume.get('md5_match') else '✗ Mismatch' if resume.get('md5_match') is False else '? (no checksum)'} |")
        md.append(f"| Resume worked | {'✓' if resume.get('resume_worked') else '✗'} |")
        md.append("")

    # Section 5: Transcode Performance
    md.append("## 5. Transcode Performance\n")
    transcodes = r04.get("transcodes", [])
    if transcodes:
        md.append("| File | Original | Proxy | Ratio | Reduction | Speed | Time |")
        md.append("|------|----------|-------|-------|-----------|-------|------|")
        for tc in transcodes:
            md.append(f"| {tc.get('name', '?')[:25]} | {tc.get('original_size_mb', '?')} MB | "
                       f"{tc.get('proxy_size_mb', '?')} MB | {tc.get('compression_ratio', '?')}x | "
                       f"{tc.get('size_reduction_pct', '?')}% | {tc.get('speed_ratio', '?')}x realtime | "
                       f"{tc.get('transcode_seconds', '?')}s |")
        md.append("")

        for tc in transcodes:
            if tc.get("original_probe") and tc.get("proxy_probe"):
                op = tc["original_probe"]
                pp = tc["proxy_probe"]
                md.append(f"**{tc.get('label', '?')}** — `{op.get('video_width')}x{op.get('video_height')}` "
                           f"({op.get('video_codec')}) → `{pp.get('video_width')}x{pp.get('video_height')}` "
                           f"({pp.get('video_codec')})")
            if tc.get("cpu_avg_pct"):
                md.append(f"  CPU: avg {tc['cpu_avg_pct']}%, max {tc.get('cpu_max_pct', '?')}% | "
                           f"RAM: avg {tc.get('mem_avg_mb', '?')} MB, max {tc.get('mem_max_mb', '?')} MB")
        md.append("")

    # Section 6: OCR + STT
    md.append("## 6. OCR + STT Input Validation\n")
    if r05.get("resolution_comparison"):
        rc = r05["resolution_comparison"]
        md.append(f"**Resolution**: {rc.get('original')} → {rc.get('proxy')} ({rc.get('scale_factor')}x downscale)\n")

    ksc = r05.get("keyframe_size_comparison", {})
    if ksc:
        md.append(f"**Keyframe sizes**: original avg {ksc.get('original_avg_kb')} KB, "
                   f"proxy avg {ksc.get('proxy_avg_kb')} KB ({ksc.get('size_ratio', '?')}x)\n")

    if r05.get("keyframes_saved_to"):
        md.append(f"Keyframes saved to `{r05['keyframes_saved_to']}` for manual OCR comparison.\n")

    if r05.get("manual_inspection_note"):
        md.append(f"> {r05['manual_inspection_note']}\n")

    # Section 7: Quota & Rate Limits
    md.append("## 7. Quota & Rate Limits\n")
    rl = r06.get("rapid_listing", {})
    if rl:
        md.append("### Rapid Listing Stress\n")
        md.append(f"| Metric | Value |")
        md.append(f"|--------|-------|")
        md.append(f"| Total requests | {rl.get('total_requests', 'N/A')} |")
        md.append(f"| Successful | {rl.get('successful_requests', 'N/A')} |")
        md.append(f"| First 429 at request # | {rl.get('first_429_at_request', 'None (no 429)')} |")
        md.append(f"| Avg latency | {_ms(rl.get('latency_avg_ms'))} |")
        md.append(f"| Throughput | {rl.get('requests_per_second', 'N/A')} req/s |")
        md.append("")

    pd = r06.get("parallel_downloads", {})
    if pd and pd.get("levels"):
        md.append("### Parallel Download Throughput\n")
        md.append("| Concurrency | Aggregate MB/s | Success/Total |")
        md.append("|-------------|----------------|---------------|")
        for level in pd["levels"]:
            md.append(f"| {level.get('concurrency')} | {level.get('aggregate_mbps')} | "
                       f"{level.get('successful')}/{level.get('concurrency')} |")
        md.append("")

    bt = r06.get("backoff_test", {})
    if bt and bt.get("backoff_phase", {}).get("attempts"):
        md.append("### Exponential Backoff Recovery\n")
        bp = bt["backoff_phase"]
        md.append(f"| Metric | Value |")
        md.append(f"|--------|-------|")
        md.append(f"| Rate limit triggered | {'✓' if bt.get('trigger_phase', {}).get('rate_limit_hit') else '✗'} |")
        md.append(f"| Requests to trigger | {bt.get('trigger_phase', {}).get('requests_sent', '?')} |")
        md.append(f"| Recovered | {'✓' if bp.get('recovered') else '✗'} |")
        md.append(f"| Total backoff time | {bp.get('total_backoff_seconds', '?')}s |")
        md.append(f"| Recovery attempts | {len(bp.get('attempts', []))} |")
        md.append("")

        md.append("| Attempt | Delay | Result | Latency |")
        md.append("|---------|-------|--------|---------|")
        for a in bp["attempts"]:
            md.append(f"| {a.get('attempt')} | {a.get('delay_seconds')}s | {a.get('result')} | {_ms(a.get('latency_ms'))} |")
        md.append("")

    # Section 8: Risk Summary + Go/No-Go
    md.append("## 8. Risk Summary\n")
    md.append(_generate_risk_summary(results))
    md.append("")

    md.append("## 9. Go/No-Go Recommendation\n")
    md.append(_generate_go_nogo(results))
    md.append("")

    # Section: Exit Criteria Evaluation
    md.append("## 10. Exit Criteria Evaluation\n")
    md.append(_generate_exit_criteria(results))

    content = "\n".join(md)
    with open(FINDINGS_OUTPUT, "w") as f:
        f.write(content)
    print(f"\n✓ SPIKE_FINDINGS.md written to {FINDINGS_OUTPUT}")


def _ms(value) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f} ms"


def _generate_risk_summary(results: dict) -> str:
    risks = []

    r03 = results.get("03_download_resume", {})
    resume = r03.get("resume_test", {})
    if resume.get("md5_match") is False:
        risks.append("- **HIGH**: Resume download MD5 mismatch — data corruption risk")
    if not resume.get("range_header_honored"):
        risks.append("- **HIGH**: Drive API did not honor Range headers — resume not supported")

    r06 = results.get("06_quota_stress", {})
    rl = r06.get("rapid_listing", {})
    if rl.get("first_429_at_request") and rl["first_429_at_request"] < 50:
        risks.append(f"- **MEDIUM**: Rate limit hit after only {rl['first_429_at_request']} requests — tight quota")

    bt = r06.get("backoff_test", {})
    if bt.get("backoff_phase", {}).get("recovered") is False:
        risks.append("- **HIGH**: Exponential backoff did not recover from rate limit")

    r04 = results.get("04_transcode", {})
    for tc in r04.get("transcodes", []):
        if tc.get("speed_ratio") and tc["speed_ratio"] < 0.5:
            risks.append(f"- **MEDIUM**: Transcode slower than 0.5x realtime for {tc.get('name', '?')}")

    all_errors = []
    for exp_results in results.values():
        if isinstance(exp_results, dict):
            all_errors.extend(exp_results.get("errors", []))
    if all_errors:
        risks.append(f"- **INFO**: {len(all_errors)} total error(s) across all experiments")

    if not risks:
        return "No significant risks identified."

    return "\n".join(risks)


def _generate_go_nogo(results: dict) -> str:
    blockers = []

    r01 = results.get("01_auth_list", {})
    if r01.get("crashed") or r01.get("auth", {}).get("cold_auth_error"):
        blockers.append("DWD authentication failed")

    r03 = results.get("03_download_resume", {})
    if not r03.get("downloads"):
        blockers.append("No downloads completed")
    resume = r03.get("resume_test", {})
    if resume.get("md5_match") is False:
        blockers.append("Resume download produced corrupt data (MD5 mismatch)")

    r06 = results.get("06_quota_stress", {})
    bt = r06.get("backoff_test", {})
    if bt.get("backoff_phase", {}).get("recovered") is False:
        blockers.append("Backoff recovery failed — cannot reliably handle rate limits")

    if blockers:
        lines = ["**RECOMMENDATION: NO-GO**\n", "Blockers:"]
        for b in blockers:
            lines.append(f"- {b}")
        lines.append("\nResolve blockers before proceeding to Phase 1.")
        return "\n".join(lines)

    return ("**RECOMMENDATION: GO**\n\n"
            "All critical exit criteria passed. Proceed to Phase 1 implementation.")


def _generate_exit_criteria(results: dict) -> str:
    r01 = results.get("01_auth_list", {})
    r02 = results.get("02_changes_api", {})
    r03 = results.get("03_download_resume", {})
    r06 = results.get("06_quota_stress", {})

    auth_ok = bool(r01.get("auth", {}).get("cold_auth_ms"))
    listing_ok = (r01.get("listing", {}).get("total_video_files", 0) >= 5)
    changes_ok = (r02.get("changes_list", {}).get("total_changes", -1) >= 0)
    token_persistence = bool(r02.get("token_persistence", {}).get("new_token_saved"))

    downloads = r03.get("downloads", [])
    large_dl = any(d.get("bucket") == "large" and d.get("md5_match") for d in downloads)
    any_dl = any(d.get("md5_match") for d in downloads)

    resume = r03.get("resume_test", {})
    resume_ok = resume.get("resume_worked", False)

    bt = r06.get("backoff_test", {})
    backoff_ok = bt.get("backoff_phase", {}).get("recovered", False)

    dwd_timing = bool(r01.get("auth", {}).get("cold_auth_ms"))

    criteria = [
        ("1", "DWD auth succeeds", "✓" if auth_ok else "✗", f"{r01.get('auth', {}).get('cold_auth_ms', 'N/A')} ms"),
        ("2", "files.list returns 5+ videos with metadata", "✓" if listing_ok else "✗", f"{r01.get('listing', {}).get('total_video_files', 0)} files"),
        ("3", "changes.list detects changes", "✓" if changes_ok else "✗", f"{r02.get('changes_list', {}).get('total_changes', 0)} changes"),
        ("4", "Page token persistence works", "✓" if token_persistence else "✗", f"Token: {r02.get('token_persistence', {}).get('new_token_saved', 'N/A')[:20]}..."),
        ("5", "1 GB+ download completes, MD5 matches", "✓" if large_dl else ("~" if any_dl else "✗"), "Large file tested" if large_dl else ("Smaller file OK" if any_dl else "No downloads")),
        ("6", "Resume after interruption works", "✓" if resume_ok else "✗", f"MD5 match: {resume.get('md5_match', 'N/A')}"),
        ("7", "Rate limit backoff works", "✓" if backoff_ok else "✗", f"Recovered: {backoff_ok}"),
        ("8", "DWD propagation timing documented", "✓" if dwd_timing else "✗", f"Cold auth: {r01.get('auth', {}).get('cold_auth_ms', 'N/A')} ms"),
        ("9", "Findings documented", "✓", "This document"),
    ]

    lines = [
        "| # | Criterion | Status | Evidence |",
        "|---|-----------|--------|----------|",
    ]
    for num, criterion, status, evidence in criteria:
        lines.append(f"| {num} | {criterion} | {status} | {evidence} |")

    passed = sum(1 for _, _, s, _ in criteria if s == "✓")
    total = len(criteria)
    lines.append(f"\n**{passed}/{total} criteria passed.**")

    return "\n".join(lines)


if __name__ == "__main__":
    main()

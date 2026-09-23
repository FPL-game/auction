"""Wyscout/Pappalardo adapter, via the GitHub mirror
github.com/koenvo/wyscout-soccer-match-event-dataset (branch main).
Licence chain: original data CC BY 4.0 (Pappalardo, Cintia, Rossi et al.,
Sci Data 6, 236 (2019), doi.org/10.1038/s41597-019-0247-7); this mirror is a
transformation of that same data, inheriting the licence, hosted on GitHub
because the original Figshare host is blocked in this session.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from acquisition.framework import Acquirer

BASE = "https://raw.githubusercontent.com/koenvo/wyscout-soccer-match-event-dataset/main/processed-v2/files"
INDEX_PATH = Path(__file__).resolve().parents[2] / "bronze/wyscout/2026-09-23/match_index_processed-v2.md"
LICENCE = ("Original: Pappalardo/Cintia/Rossi et al., CC BY 4.0, Sci Data 6:236 (2019), "
           "doi.org/10.1038/s41597-019-0247-7. Retrieved via GitHub mirror "
           "koenvo/wyscout-soccer-match-event-dataset (transformation of the same CC-BY-4.0 data).")

ROW_RE = re.compile(r"\|\[(\d+)\]\(files/\d+\.json\)\|([^|]*)\|([^|]*)\|([^|]*)\|")


def list_all_matches() -> list:
    """Returns [(match_id, label, date, source_competition_file), ...] for all
    matches in the mirror's own index - the same index used to validate the
    dataset's total count (1,941) earlier this project."""
    text = INDEX_PATH.read_text()
    out = []
    for m in ROW_RE.finditer(text):
        match_id, label, date, comp_file = m.groups()
        out.append((int(match_id), label.strip(), date.strip(), comp_file.strip()))
    return out


def run(acq: Acquirer, matches: list, limit: int = None):
    for i, (match_id, label, date, comp_file) in enumerate(matches):
        if limit is not None and i >= limit:
            return
        acq.fetch(
            source="wyscout", resource_type="match", resource_key=str(match_id),
            url=f"{BASE}/{match_id}.json", dest_relpath=f"matches/{match_id}.json",
            licence_tag=LICENCE, expect_json=True, min_size_bytes=1000,
        )


if __name__ == "__main__":
    matches = list_all_matches()
    print(f"Wyscout mirror index: {len(matches)} matches found")
    from collections import Counter
    by_comp = Counter(c for _, _, _, c in matches)
    for comp, n in by_comp.items():
        print(f"  {comp}: {n}")

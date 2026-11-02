"""N25d (gap critic N77 cho `images adopt`): so khớp UUID session không phân biệt hoa/thường ở CẢ HAI phía
(tên rollout và nội dung rollout), tên file vẫn so khớp chính xác; regex tên rollout được chốt theo tên THẬT.

Đo trên máy này 2026-10-30 19:3x (mọi codex_home: ~/.codex 1003 + 4 acct của codex-router 12+2+4+15 = 1036 rollout;
0 tên lệch dạng ``rollout-<stamp>-<uuid thường>.jsonl``, 0 tên mang hex hoa, 0 tên không có stamp):
  tên rollout:   rollout-2026-10-30T18-52-19-01a18ca7-55a1-7a12-b98d-c2a4436c70b5.jsonl
                 (nằm ở <acct codex_home>/sessions/2026/10/30/, cùng home với generated_images/<session>/)
  đường dẫn ảnh: "savedPath":"C:\\\\Users\\\\Admin\\\\.codex\\\\codex-router\\\\chatgpt-accounts\\\\acct_-LFRMCyD9iGu8l8m
                  \\\\generated_images\\\\01a18ca7-55a1-7a12-b98d-c2a4436c70b5\\\\exec-b6e7259d-00f6-48a5-802e-7c2a9a8520e6.png"
  (dấu ``\\\\`` là JSON-escape của một backslash; byte thật trong file là hai backslash; cùng đường dẫn còn xuất hiện
  dưới key "text" và "last_agent_message"). Probe chỉ-đọc ``find_rollout`` trên home thật: session thường/HOA đều
  tìm ra đúng rollout; sai đuôi file, tên file hoa, session khác => None; file nguồn thật có st_nlink == 1.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
for p in (SKILL, SKILL / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine.images import adopt  # noqa: E402
from images_fixtures import make_png  # noqa: E402
from test_images_n25 import live_flow  # noqa: E402
from test_images_n25b import adopt_args  # noqa: E402
from test_images_n52b import OTHER, UUID, put, real_rollout  # noqa: E402

# Tên và đường dẫn THẬT (chép nguyên từ máy, không bịa): chứng minh regex + needle bắt đúng format Codex ghi ra.
REAL_SESSION = "01a18ca7-55a1-7a12-b98d-c2a4436c70b5"
REAL_FILE = "exec-b6e7259d-00f6-48a5-802e-7c2a9a8520e6.png"
REAL_ROLLOUT_NAME = f"rollout-2026-10-30T18-52-19-{REAL_SESSION}.jsonl"
REAL_SAVED_PATH = (r"C:\Users\Admin\.codex\codex-router\chatgpt-accounts\acct_-LFRMCyD9iGu8l8m\generated_images"
                   + "\\" + REAL_SESSION + "\\" + REAL_FILE)


def saved_path_line(session: str, filename: str) -> str:
    """Một dòng rollout đúng dạng Codex ghi: JSON với ``savedPath`` tuyệt đối, backslash được JSON-escape."""
    path = REAL_SAVED_PATH.replace(REAL_SESSION, session).replace(REAL_FILE, filename)
    return json.dumps({"payload": {"savedPath": path, "failure": None}}) + "\n"


# ---------------- regex tên rollout: chốt theo tên thật ----------------

def test_rollout_name_regex_matches_real_codex_name():
    match = adopt.ROLLOUT_NAME.fullmatch(REAL_ROLLOUT_NAME)
    assert match is not None and match.group("session") == REAL_SESSION
    assert adopt.ROLLOUT_NAME.fullmatch(REAL_ROLLOUT_NAME + ".zst") is not None


def test_rollout_name_without_stamp_stays_refused():
    # Không có rollout thật nào dạng `rollout-<uuid>.jsonl` (0/1029 trên máy); giữ fail-closed, không nới regex.
    assert adopt.ROLLOUT_NAME.fullmatch(f"rollout-{REAL_SESSION}.jsonl") is None
    assert adopt.ROLLOUT_NAME.fullmatch(f"{REAL_ROLLOUT_NAME}.bak") is None


# ---------------- needle: dạng savedPath thật ----------------

def test_find_rollout_reads_real_saved_path_form(tmp_path):
    home = tmp_path / "h"
    real_rollout(home, saved_path_line(REAL_SESSION, REAL_FILE), REAL_SESSION)
    found = adopt.find_rollout(home, REAL_SESSION, REAL_FILE)
    assert found is not None and found.name == f"rollout-2026-10-30T09-00-00-{REAL_SESSION}.jsonl"


# ---------------- UUID hoa/thường ở hai phía (RED trước N25d) ----------------

def test_find_rollout_upper_case_session_arg_matches_lower_case_rollout(tmp_path):
    # Rollout thật ghi UUID chữ thường; operator gõ --source-path với UUID hoa (Windows không phân biệt).
    home = tmp_path / "h"
    real_rollout(home, saved_path_line(UUID, "exec-001.png"))
    assert adopt.find_rollout(home, UUID.upper(), "exec-001.png") is not None


def test_find_rollout_lower_case_session_arg_matches_upper_case_rollout_text(tmp_path):
    # Phía ngược lại: nội dung rollout ghi UUID hoa (giả định), tên rollout vẫn thường; session truyền vào thường.
    home = tmp_path / "h"
    real_rollout(home, saved_path_line(UUID.upper(), "exec-001.png"))
    assert adopt.find_rollout(home, UUID, "exec-001.png") is not None


def test_find_rollout_upper_case_rollout_file_name_matches(tmp_path):
    # Tên file rollout mang UUID hoa (giả định), nội dung thường, session truyền vào thường.
    home = tmp_path / "h"
    real_rollout(home, saved_path_line(UUID, "exec-001.png"), UUID.upper())
    assert adopt.find_rollout(home, UUID, "exec-001.png") is not None


# ---------------- không nới rộng: tên file và session khác vẫn bị từ chối ----------------

def test_find_rollout_file_name_case_stays_exact(tmp_path):
    # Tên file KHÔNG được so khớp mù hoa/thường: trên FS phân biệt hoa/thường đó là hai file khác nhau.
    home = tmp_path / "h"
    real_rollout(home, saved_path_line(UUID, "exec-ABC.png"))
    assert adopt.find_rollout(home, UUID, "exec-abc.png") is None
    assert adopt.find_rollout(home, UUID, "exec-ABC.png") is not None


def test_find_rollout_other_session_still_refused_after_case_fold(tmp_path):
    home = tmp_path / "h"
    real_rollout(home, saved_path_line(OTHER, "exec-001.png"))          # rollout của UUID chỉ nhắc OTHER/...
    assert adopt.find_rollout(home, UUID, "exec-001.png") is None
    assert adopt.find_rollout(home, UUID.upper(), "exec-001.png") is None


@pytest.mark.skipif(sys.platform != "win32", reason="đường dẫn hoa/thường chỉ cùng trỏ một file trên Windows")
def test_adopt_accepts_upper_case_session_in_source_path_on_windows(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "comfy.png", (2, 5, 13), (1672, 941))
    real_rollout(tmp_path / "home", saved_path_line(UUID, "exec-001.png"))
    src = put(png, tmp_path / "home" / "generated_images" / UUID / "exec-001.png")
    typed = src.parent.parent / UUID.upper() / "exec-001.png"             # cùng file, UUID gõ hoa
    code, out = adopt_args(flow, png, typed)
    assert code == 0, out

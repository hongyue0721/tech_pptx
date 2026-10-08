"""T01 非零退出码处理记录：施工AI对失败命令的退出码解释（人工核对）。"""
import subprocess

probes = [
    ("python exit(2)", ["python3", "-c", "import sys; sys.exit(2)"], 2),
    ("ls missing", ["ls", "/nonexistent_dir_xyz"], 2),
    ("python exception", ["python3", "-c", "raise RuntimeError('boom')"], 1),
]
records = []
for name, cmd, expected in probes:
    r = subprocess.run(cmd, capture_output=True, text=True)
    records.append({
        "probe": name,
        "returncode": r.returncode,
        "expected": expected,
        "match": r.returncode == expected,
        "stderr_tail": r.stderr.strip().splitlines()[-1][:80] if r.stderr else "",
    })
    print(f"{name}: 退出码={r.returncode} 预期={expected} stderr末行: {records[-1]['stderr_tail']}")

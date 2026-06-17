from pathlib import Path

targets = {
    "backend/config.py": [87, 140],
    "backend/prompt_builder.py": [211, 212, 1061, 1066],
}

out = []
for file, nums in targets.items():
    lines = Path(file).read_text(encoding="utf-8").splitlines()
    out.append(f"===== {file} =====")
    for n in nums:
        out.append(f"{n}: {repr(lines[n-1])}")

Path("six_old_prices_repr.txt").write_text("\n".join(out), encoding="utf-8")

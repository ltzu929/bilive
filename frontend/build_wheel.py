"""Replace a blrec wheel's compiled webapp with this frontend build."""

import argparse
import base64
import csv
import hashlib
import io
import zipfile
from pathlib import Path


def record_line(name: str, data: bytes) -> tuple[str, str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return name, f"sha256={digest}", str(len(data))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_wheel", type=Path)
    parser.add_argument("output_wheel", type=Path)
    parser.add_argument("version")
    parser.add_argument("--webapp", type=Path, default=Path("dist/blrec"))
    args = parser.parse_args()

    if args.base_wheel.resolve() == args.output_wheel.resolve():
        raise SystemExit("base and output wheel must differ")
    if not (args.webapp / "index.html").is_file():
        raise SystemExit(f"missing frontend build: {args.webapp}")

    files: dict[str, bytes] = {}
    with zipfile.ZipFile(args.base_wheel) as source:
        metadata_name = next(name for name in source.namelist() if name.endswith(".dist-info/METADATA"))
        old_dist_info = metadata_name.split("/", 1)[0]
        new_dist_info = f"blrec-{args.version}.dist-info"
        for name in source.namelist():
            if name.startswith("blrec/data/webapp/") or name.endswith(".dist-info/RECORD"):
                continue
            target = new_dist_info + name[len(old_dist_info):] if name.startswith(old_dist_info) else name
            data = source.read(name)
            if target == f"{new_dist_info}/METADATA":
                text = data.decode("utf-8").splitlines()
                text = [f"Version: {args.version}" if line.startswith("Version: ") else line for line in text]
                data = ("\n".join(text) + "\n").encode()
            files[target] = data

    for path in args.webapp.rglob("*"):
        if path.is_file():
            relative = path.relative_to(args.webapp).as_posix()
            files[f"blrec/data/webapp/{relative}"] = path.read_bytes()

    record_name = f"{new_dist_info}/RECORD"
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name in sorted(files):
        writer.writerow(record_line(name, files[name]))
    writer.writerow((record_name, "", ""))
    files[record_name] = output.getvalue().encode()

    temporary = args.output_wheel.with_suffix(args.output_wheel.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
        for name in sorted(files):
            target.writestr(name, files[name])
    temporary.replace(args.output_wheel)


if __name__ == "__main__":
    main()

import os
import re
import subprocess
import sys

qt_dirs = ["bin", "lib", "plugins", "qml"]
library_pattern = re.compile(r".+\.(dll|dylib|so(\.\d+)*)$")
batch_size = 100


def is_debug_variant(path):
    name = os.path.basename(path)
    if "_debug." in name:
        return True
    # MSVC packages put the debug build next to the release one: Qt6Cored.dll and Qt6Core.dll
    return name.endswith("d.dll") and os.path.exists(path[:-len("d.dll")] + ".dll")


def is_framework_binary(path):
    # <Qt>/lib/QtCore.framework/Versions/A/QtCore
    parts = path.split(os.sep)
    return len(parts) >= 4 and parts[-4].endswith(".framework") and parts[-3] == "Versions" \
        and parts[-1] == parts[-4][:-len(".framework")]


def collect_files(qt_root):
    files = []
    for qt_dir in qt_dirs:
        for dir_path, _, names in os.walk(os.path.join(qt_root, qt_dir)):
            for name in names:
                path = os.path.join(dir_path, name)
                if os.path.islink(path) or is_debug_variant(path):
                    continue
                if library_pattern.match(name) or is_framework_binary(path):
                    files.append(path)
    return sorted(files)


if __name__ == '__main__':
    qt_root = os.environ["QT_ROOT_DIR"]
    org = os.environ["SENTRY_ORG"]
    project = os.environ["SENTRY_PROJECT"]

    files = collect_files(qt_root)
    if not files:
        sys.exit(f'No Qt binaries found in {qt_root}')

    size = sum(os.path.getsize(f) for f in files)
    print(f'Uploading {len(files)} files ({size / 1024 / 1024:.1f} MB) from {qt_root} to {org}/{project}')

    for i in range(0, len(files), batch_size):
        subprocess.check_call(["sentry-cli", "debug-files", "upload", "--wait", "-o", org, "-p", project]
                              + files[i:i + batch_size])

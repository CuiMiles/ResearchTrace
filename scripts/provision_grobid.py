#!/usr/bin/env python3
"""Private rootless CPU GROBID installation (Python 3.6+, no Docker/sudo).

Run ON the remote host in the authorized private directory. Does not change
login shell, shared JDK, proxy, existing services, permissions or GPU processes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

COMMIT = "523bb8e97f357e93682dc4eaa6d22faa8b5b93de"
SOURCE_SHA = "a5f46f7082424bd232bb61e230ab235a75ce5a5aabcd5caf28000d8662faf962"
JDK_SHA = "d7f5d5cf865a2902b70ff549b97586a7d3f234e016f041ab447ea740c7d66d1c"
JDK_URL = "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jdk_x64_linux_hotspot_21.0.13_9.tar.gz"
ROOT_DEFAULT = "/home/CuiMinghao/projects/Competition/ResearchTrace-grobid-20261116"
LIBC_URL = "https://deb.debian.org/debian/pool/main/g/glibc/libc6_2.36-9+deb12u14_amd64.deb"
LIBC_SHA = "ba4f88f73dbc3ae9055f3c20f4523bfdbaf1ad13ff95e258924f77d20b4fbedf"
GRADLE_SHA = "9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download(url, target, sha):
    if target.exists() and digest(target) == sha:
        return
    op = urllib.request.build_opener(urllib.request.ProxyHandler({"https": "http://127.0.0.1:7890"}))
    temp = target.with_suffix(".partial")
    with op.open(url, timeout=60) as source, temp.open("wb") as dest:
        shutil.copyfileobj(source, dest, 1024 * 1024)
    if digest(temp) != sha:
        raise ValueError("Official archive checksum mismatch")
    temp.replace(target)


def unpack(archive, target):
    if target.exists():
        return
    temp = target.with_name(target.name + ".unpacking")
    temp.mkdir(mode=0o700, exist_ok=True)
    with tarfile.open(str(archive)) as tf:
        members = tf.getmembers()
        root = temp.resolve()
        for m in members:
            dest = (temp / m.name).resolve()
            if root not in dest.parents or m.isdev() or m.isfifo():
                raise ValueError("Unsafe archive member")
            if m.issym() or m.islnk():
                link = ((dest.parent if m.issym() else temp) / m.linkname).resolve()
                if root not in link.parents:
                    raise ValueError("Unsafe archive link")
        tf.extractall(str(temp))
    children = list(temp.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise ValueError("Unexpected archive layout")
    children[0].rename(target)
    temp.rmdir()


def environment(root):
    # Deliberately do not inherit API keys or GPU configuration.
    allowed = ("LANG", "LC_ALL", "TZ", "USER", "LOGNAME")
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    env.update({"HOME": str(Path.home()), "JAVA_HOME": str(root / "jdk"),
                "PATH": str(root / "jdk/bin") + ":/usr/bin:/bin", "CUDA_VISIBLE_DEVICES": "",
                "GRADLE_USER_HOME": str(root / "private/gradle"), "OMP_NUM_THREADS": "2",
                "OPENBLAS_NUM_THREADS": "2", "MALLOC_ARENA_MAX": "2"})
    return env


def configure(root):
    source = root / "source"
    config = source / "grobid-home/config/grobid.yaml"
    text = config.read_text()
    text = re.sub(r"(?m)^(\s*)concurrency: \d+", r"\1concurrency: 1", text)
    text = re.sub(r"(?m)^(\s*)memoryLimitMb: \d+", r"\1memoryLimitMb: 1024", text)
    text = re.sub(r"(?m)^(\s*)timeoutSec: \d+", r"\1timeoutSec: 90", text)
    text = re.sub(r"(?m)^(\s*)modelPreload: true", r"\1modelPreload: false", text)
    text = re.sub(r"(?m)^(\s*)port: 8070\s*$", r"\1port: 18070\n\1bindHost: 127.0.0.1", text)
    text = re.sub(r"(?m)^(\s*)port: 8071\s*$", r"\1port: 18069\n\1bindHost: 127.0.0.1", text)
    if re.search(r'^\s*engine:\s*[\"\']?delft', text, re.M):
        raise ValueError("GPU/deep-learning backend must remain disabled")
    config.write_text(text)
    props = source / "gradle.properties"
    original = props.read_text().split("\n# ResearchTrace private build\n")[0]
    props.write_text(original + "\n# ResearchTrace private build\n"
                     "systemProp.http.proxyHost=127.0.0.1\nsystemProp.http.proxyPort=7890\n"
                     "systemProp.https.proxyHost=127.0.0.1\nsystemProp.https.proxyPort=7890\n"
                     "org.gradle.jvmargs=-Xmx1536m -XX:ActiveProcessorCount=2\n"
                     "kotlin.compiler.execution.strategy=in-process\norg.gradle.daemon=false\n")
    wrapper = source / "gradle/wrapper/gradle-wrapper.properties"
    lines = [l for l in wrapper.read_text().splitlines() if not l.startswith("distributionSha256Sum=")]
    wrapper.write_text("\n".join(lines) + "\ndistributionSha256Sum=" + GRADLE_SHA + "\n")
    (source / "gradlew").chmod(0o700)


def compatibility(root):
    """Only the private Java/PDFalto processes use this loader, never global ld."""
    package = root / "downloads/libc6-amd64.deb"
    download(LIBC_URL, package, LIBC_SHA)
    subprocess.check_call(["dpkg-deb", "-x", str(package), str(root / "compat")])
    lib = root / "compat/lib/x86_64-linux-gnu"
    loader = lib / "ld-linux-x86-64.so.2"
    pdfalto = root / "source/grobid-home/pdfalto/lin-64/pdfalto"
    original = pdfalto.with_name("pdfalto.original")
    if not original.exists():
        pdfalto.rename(original)
    native_path = str(lib) + ":/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu"
    wrapper = "#!/bin/sh\nexec " + " ".join(shlex.quote(s) for s in [str(loader), "--library-path", native_path, str(original)]) + ' "$@"\n'
    pdfalto.write_text(wrapper)
    pdfalto.chmod(0o700)
    manifest = {"glibc": "2.36-9+deb12u14", "source_url": LIBC_URL, "package_sha256": LIBC_SHA,
                "pdfalto_original_sha256": digest(original), "pdfalto_wrapper_sha256": digest(pdfalto),
                "wapiti_original_sha256": digest(root / "source/grobid-home/lib/lin-64/libwapiti.so"),
                "scope": "explicit private loader only; system libc unchanged"}
    (root / "private/compatibility.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest))


def install_package(root):
    package = root / "source/grobid-service/build/distributions/grobid-service-0.9.1.zip"
    target = root / "source/grobid-service/build/install"
    if target.exists():
        target.rename(target.with_name("install-previous-" + str(time.time_ns() if hasattr(time, "time_ns") else int(time.time() * 1000000))))
    target.mkdir(mode=0o700)
    with zipfile.ZipFile(str(package)) as z:
        for name in z.namelist():
            if target.resolve() not in (target / name).resolve().parents:
                raise ValueError("Unsafe distribution archive path")
        z.extractall(str(target))
    extracted = target / "grobid-service-0.9.1"
    if extracted.exists():
        extracted.rename(target / "grobid-service")
    (target / "grobid-service/bin/grobid-service").chmod(0o700)
    print(json.dumps({"status": "PASS", "package_sha256": digest(package), "path": str(package)}))


def start(root, gateway):
    for port in (18069, 18070, 18072):
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                raise ValueError("Private metadata port already in use; not stopping existing process")
    token = root / "private/auth.token"
    if not token.exists():
        fd = os.open(str(token), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(36))
    env = environment(root)
    source = root / "source"
    lib = source / "grobid-home/lib/lin-64"
    env["LD_LIBRARY_PATH"] = str(lib)
    env["GROBID_SERVICE_OPTS"] = ("-Xmx1536m -XX:ActiveProcessorCount=2 "
       "--add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.io=ALL-UNNAMED "
       "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED -Djava.library.path=" + str(lib))
    command = [str(source / "grobid-service/build/install/grobid-service/bin/grobid-service"),
               "server", str(source / "grobid-home/config/grobid.yaml")]
    compat = root / "compat/lib/x86_64-linux-gnu"
    if compat.exists():
        manifest = json.loads((root / "private/compatibility.json").read_text())
        if digest(source / "grobid-home/pdfalto/lin-64/pdfalto") != manifest["pdfalto_wrapper_sha256"]:
            raise ValueError("Private PDFalto wrapper integrity failure")
        if digest(source / "grobid-home/pdfalto/lin-64/pdfalto.original") != manifest["pdfalto_original_sha256"]:
            raise ValueError("Private PDFalto binary integrity failure")
        library_path = str(compat) + ":" + str(lib) + ":" + str(root / "jdk/lib") + ":/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu"
        command = [str(compat / "ld-linux-x86-64.so.2"), "--library-path", library_path,
                   str(root / "jdk/bin/java"), "-Xmx1536m", "-XX:ActiveProcessorCount=2",
                   "--add-opens=java.base/java.lang=ALL-UNNAMED", "--add-opens=java.base/java.io=ALL-UNNAMED",
                   "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED", "-Djava.library.path=" + str(lib),
                   "-cp", str(source / "grobid-service/build/install/grobid-service/lib/*"),
                   "org.grobid.service.main.GrobidServiceApplication", "server", str(source / "grobid-home/config/grobid.yaml")]
    commands = [("grobid", command), ("gateway", [sys.executable, str(gateway), "--token-file", str(token)])]
    for name, cmd in commands:
        with (root / ("logs/" + name + ".log")).open("ab") as log:
            process = subprocess.Popen(cmd, cwd=str(source), env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        record = {"pid": process.pid, "command": cmd, "cwd": str(source), "started": time.time()}
        (root / ("private/" + name + "-process.json")).write_text(json.dumps(record, indent=2))
        print(json.dumps({"name": name, "pid": process.pid, "record": str(root / ("private/" + name + "-process.json"))}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["prepare", "compat", "build", "install", "start", "status"])
    p.add_argument("--root", default=ROOT_DEFAULT)
    p.add_argument("--gateway", help="Path to services/metadata_runtime/server.py copied into the private directory")
    args = p.parse_args()
    root = Path(args.root)
    if not root.is_absolute() or root.name != "ResearchTrace-grobid-20261116":
        raise SystemExit("Use the dedicated ResearchTrace-grobid-20261116 root")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    for directory in ("downloads", "logs", "private", "private/home", "private/gradle"):
        (root / directory).mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.action == "prepare":
        download(JDK_URL, root / "downloads/temurin21.tar.gz", JDK_SHA)
        download("https://codeload.github.com/grobidOrg/grobid/tar.gz/" + COMMIT,
                 root / "downloads/grobid-source.tar.gz", SOURCE_SHA)
        unpack(root / "downloads/temurin21.tar.gz", root / "jdk")
        unpack(root / "downloads/grobid-source.tar.gz", root / "source")
        configure(root)
        manifest = {"engine": "grobid", "version": "0.9.1", "commit": COMMIT,
                    "archive_sha256": SOURCE_SHA, "jdk": "Temurin 21.0.13+9", "jdk_archive_sha256": JDK_SHA,
                    "gradle": "9.6.1", "gradle_archive_sha256": GRADLE_SHA,
                    "runtime": "wapiti_cpu", "gpu": False, "model_api_calls": 0}
        (root / "private/installation.json").write_text(json.dumps(manifest, indent=2))
        print(json.dumps(manifest))
    elif args.action == "build":
        configure(root)
        command = [str(root / "source/gradlew"), ":grobid-service:distZip", "--no-daemon", "--max-workers=2",
                   "--console=plain", "-x", "test"]
        print("Building isolated GROBID 0.9.1; tests excluded from package build, live validation is separate", flush=True)
        code = subprocess.call(command, cwd=str(root / "source"), env=environment(root))
        if code:
            raise SystemExit(code)
        install_package(root)
    elif args.action == "install":
        install_package(root)
    elif args.action == "compat":
        compatibility(root)
    elif args.action == "start":
        if not args.gateway:
            raise SystemExit("Provide the private gateway script path")
        start(root, Path(args.gateway).resolve())
    else:
        for name in ("grobid", "gateway"):
            record = root / ("private/" + name + "-process.json")
            print(record.read_text() if record.exists() else name + ": NOT RUN")


if __name__ == "__main__":
    main()

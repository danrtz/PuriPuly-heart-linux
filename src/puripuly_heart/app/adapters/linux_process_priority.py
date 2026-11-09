from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import psutil


class LinuxProcessPriority:
    def __init__(self, pid: int | None = None) -> None:
        self.pid = os.getpid() if pid is None else pid
        self.unit: str | None = None
        self.enabled = False

    async def set_enabled(self, enabled: bool) -> None:
        if not sys.platform.startswith("linux"):
            if enabled:
                raise RuntimeError("High priority requires Linux and a systemd user session")
            return
        if not enabled and self.unit is None:
            return
        if enabled and self.enabled:
            return
        if self.unit is None:
            process = psutil.Process(self.pid)
            unit = f"puripuly-heart-{self.pid}-{int(process.create_time() * 1000)}.scope"
            await self._run(
                "busctl",
                "--user",
                "call",
                "org.freedesktop.systemd1",
                "/org/freedesktop/systemd1",
                "org.freedesktop.systemd1.Manager",
                "StartTransientUnit",
                "ssa(sv)a(sa(sv))",
                unit,
                "fail",
                "4",
                "PIDs",
                "au",
                "1",
                str(self.pid),
                "CPUWeight",
                "t",
                "10000",
                "Slice",
                "s",
                "app.slice",
                "Delegate",
                "b",
                "true",
                "0",
            )
            self.unit = unit
            await self._run("systemctl", "--user", "start", self.unit)
        weight = "10000" if enabled else "100"
        await self._run(
            "systemctl",
            "--user",
            "set-property",
            "--runtime",
            self.unit,
            f"CPUWeight={weight}",
        )
        if enabled:
            for _ in range(3):
                children = psutil.Process(self.pid).children(recursive=True)
                pids = []
                for child in children:
                    try:
                        if self.unit not in Path(f"/proc/{child.pid}/cgroup").read_text():
                            pids.append(str(child.pid))
                    except FileNotFoundError:
                        pass
                if not pids:
                    break
                await self._run(
                    "busctl",
                    "--user",
                    "call",
                    "org.freedesktop.systemd1",
                    "/org/freedesktop/systemd1",
                    "org.freedesktop.systemd1.Manager",
                    "AttachProcessesToUnit",
                    "ssau",
                    self.unit,
                    "",
                    str(len(pids)),
                    *pids,
                )
        cgroup = Path(f"/proc/{self.pid}/cgroup").read_text().strip().split("::", 1)[1]
        if not cgroup.endswith("/" + self.unit):
            raise RuntimeError("PuriPuly has not entered its priority scope")
        actual = (Path("/sys/fs/cgroup") / cgroup.lstrip("/") / "cpu.weight").read_text().strip()
        if actual != weight:
            raise RuntimeError("The systemd user session did not apply the requested CPU weight")
        if enabled:
            for child in psutil.Process(self.pid).children(recursive=True):
                try:
                    if self.unit not in Path(f"/proc/{child.pid}/cgroup").read_text():
                        raise RuntimeError("A PuriPuly worker has not entered the priority scope")
                except FileNotFoundError:
                    pass
        self.enabled = enabled

    @staticmethod
    async def _run(*args: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as exc:
            raise RuntimeError("High priority requires systemd user-session tools") from exc
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=8)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError(
                f"Priority adjustment failed: {stderr.decode(errors='replace')[:400]}"
            )

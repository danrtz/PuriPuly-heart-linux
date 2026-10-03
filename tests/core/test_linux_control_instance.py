import os
import subprocess
import sys
import uuid

import pytest

from puripuly_heart.core.control_instance import (
    InstanceAlreadyRunning,
    InstanceSecurityError,
    acquire,
    discover,
    discover_instances,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX ownership contract")


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def test_private_records_aliases_and_cross_process_exclusion(runtime):
    settings = runtime / "settings.json"
    alias = runtime / "sub" / ".." / "settings.json"
    with acquire(settings) as lease:
        lease.publish(port=12345, token="t" * 43, instance_id=str(uuid.uuid4()))
        assert discover(alias).port == 12345
        assert lease._path.stat().st_mode & 0o777 == 0o600
        assert lease._path.parent.stat().st_mode & 0o777 == 0o700
        assert "token" not in discover_instances()[0]
        with pytest.raises(InstanceAlreadyRunning):
            acquire(alias)
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; from puripuly_heart.core.control_instance import acquire, InstanceAlreadyRunning; import sys\ntry: acquire(Path(sys.argv[1]))\nexcept InstanceAlreadyRunning: sys.exit(42)",
                str(settings),
            ],
            timeout=10,
        )
        assert child.returncode == 42
    assert discover(settings) is None
    with acquire(settings):
        assert discover(settings) is None


def test_permissions_and_symlinks_fail_closed(runtime):
    settings = runtime / "settings.json"
    with acquire(settings) as lease:
        lease.publish(port=12345, token="t" * 43, instance_id=str(uuid.uuid4()))
        record = lease._path
        original = record.read_bytes()
        record.chmod(0o644)
        with pytest.raises(InstanceSecurityError):
            discover(settings)
        record.chmod(0o600)
        record.unlink()
        target = runtime / "target"
        target.write_bytes(original)
        target.chmod(0o600)
        record.symlink_to(target)
        with pytest.raises(InstanceSecurityError):
            discover(settings)
        record.unlink()
        record.write_bytes(original)
        record.chmod(0o600)


def test_crashed_owner_does_not_leave_live_endpoint(runtime):
    settings = runtime / "settings.json"
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            'import os,sys; from pathlib import Path; from puripuly_heart.core.control_instance import acquire; lease=acquire(Path(sys.argv[1])); lease.publish(port=12345,token="t"*43,instance_id="12345678-1234-4234-9234-123456789012"); os._exit(0)',
            str(settings),
        ],
        timeout=10,
    )
    assert child.returncode == 0
    assert discover(settings) is None
    assert discover_instances() == []
    with acquire(settings):
        pass

"""Backup-package ownership across a copied physical restore."""
from tests.internal_state.physical import PhysicalCluster


def test_restored_data_does_not_republish_inherited_backup_metadata(tmp_path):
    cluster = object.__new__(PhysicalCluster)
    cluster.root = tmp_path
    cluster.wal_root = tmp_path / "wal"
    cluster.counter = 1
    base = tmp_path / "base"
    base.mkdir()
    names = ("sentinel-recovery-marker", "sentinel-pitr-base-identity")
    for name in names:
        (base / name).write_text("original-proof")
    cluster.checkpoints = {"saved": {"base": base, "system_id": "1", "marker": "saved"}}
    cluster.stop_server = lambda: None
    cluster.own = lambda path: None
    verified = []
    def command(name, *args, **kwargs):
        assert name == "pg_verifybackup"
        assert all((args[-1] / file).read_text() == "original-proof" for file in names)
        verified.append(args[-1])
    cluster.command = command
    def start():
        assert verified == [cluster.primary]
        assert all(not (cluster.primary / name).exists() for name in names)
    cluster._start_server = start
    cluster.sql = lambda query: (False,)
    checkpoints = []
    cluster.checkpoint = checkpoints.append
    cluster.restore("saved")
    assert checkpoints == ["after_restore"]
    assert all((base / name).read_text() == "original-proof" for name in names)

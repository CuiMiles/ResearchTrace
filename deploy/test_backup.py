"""Real SQLite WAL and filesystem restore checks; zero model calls."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("rt_backup", Path(__file__).resolve().parents[1] / "scripts/backup.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir(mode=0o700)
        (self.data / "pdfs").mkdir(mode=0o700)
        self.pdf = self.data / "pdfs/input.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\nprivate original\n")
        self.db = sqlite3.connect(self.data / module.DATABASE)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("CREATE TABLE versions(id TEXT,path TEXT);CREATE TABLE quota(id TEXT,status TEXT);" )
        self.db.execute("INSERT INTO versions VALUES('v1',?)", (str(self.pdf),))
        self.db.executemany("INSERT INTO quota VALUES(?,?)", [("old-smoke", "ok"), ("timeout", "unknown")])
        self.db.commit()
        self.env = self.root / "private.env"
        self.env.write_text("PRIVATE_TEST_TOKEN=not-a-real-key\n")
        self.env.chmod(0o600)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_live_wal_snapshot_restore_preserves_unknown_quota_and_pdf(self):
        snapshot = module.backup(self.data, self.root / "backups", self.env)
        self.assertEqual((snapshot / "pdfs/input.pdf").read_bytes(), self.pdf.read_bytes())
        self.assertFalse((snapshot / (module.DATABASE + "-wal")).exists())
        self.assertEqual((snapshot / "runtime.env").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("PRIVATE_TEST_TOKEN", (snapshot / "backup.json").read_text())
        restored = self.root / "restored"
        module.restore(snapshot, restored)
        with sqlite3.connect(restored / module.DATABASE) as conn:
            self.assertEqual(conn.execute("SELECT id,status FROM quota ORDER BY id").fetchall(), [("old-smoke", "ok"), ("timeout", "unknown")])
            path = Path(conn.execute("SELECT path FROM versions").fetchone()[0])
            self.assertEqual(path.read_bytes(), self.pdf.read_bytes())
            self.assertEqual(path.parent.parent, restored)
        self.assertFalse((restored / "runtime.env").exists())

    def test_refuses_symlink_and_does_not_publish_partial_backup(self):
        (self.data / "escape").symlink_to(self.env)
        with self.assertRaises(ValueError):
            module.backup(self.data, self.root / "backups")
        self.assertEqual(list((self.root / "backups").glob("backup-*")), [])
        self.assertEqual(list((self.root / "backups").glob(".incomplete-*")), [])

    def test_refuses_missing_referenced_pdf(self):
        self.pdf.unlink()
        with self.assertRaises(FileNotFoundError):
            module.backup(self.data, self.root / "backups")

    def test_container_document_paths_restore_on_host(self):
        self.db.execute("UPDATE versions SET path='/app/data/pdfs/input.pdf'")
        self.db.commit()
        snapshot=module.backup(self.data,self.root/'backups')
        target=self.root/'container-restored'
        module.restore(snapshot,target)
        with sqlite3.connect(target/module.DATABASE) as conn:
            path=Path(conn.execute('SELECT path FROM versions').fetchone()[0])
            self.assertEqual(path.read_bytes(),self.pdf.read_bytes())

    def test_retention_keeps_unknown_files_and_restore_refuses_existing_destination(self):
        first = module.backup(self.data, self.root / "backups", retain=1)
        unrelated = self.root / "backups/do-not-delete"
        unrelated.write_text("operator file")
        second = module.backup(self.data, self.root / "backups", retain=1)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertTrue(unrelated.exists())
        with self.assertRaises(FileExistsError):
            module.restore(second, self.data)


if __name__ == "__main__":
    unittest.main()

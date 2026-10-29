"""Synthetic storage/prefix tests only; no Core or account execution."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_alpaca_packed import PackedRowsTests
from alpaca_fit_baseline import Journal,encoded
import alpaca_fit_continuation as continuation


class ExactPrefixStorageTests(unittest.TestCase):
    def prepared(self,root):
        source=root/'old/canonical.jsonl';source.parent.mkdir()
        old=Journal(source);old.append({'session':'2024-07-10','value':1.25})
        commit=deepcopy(old.commitment())
        tail=b'{"unsent":';source.write_bytes(source.read_bytes()+tail)
        target=root/'new/canonical.jsonl';target.parent.mkdir()
        lineage=root/'lineage';lineage.mkdir()
        return source,target,commit,lineage,tail

    def test_recovery_preserves_exact_prefix_and_unsent_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target,commit,lineage,tail=self.prepared(Path(folder));old=source.read_bytes()
            journal,recovered=continuation.copy_prefix(source,target,commit,lineage,Journal)
            self.assertEqual(source.read_bytes(),old)
            self.assertEqual(target.read_bytes(),old[:commit['bytes']]);self.assertEqual(journal.commitment(),commit)
            self.assertEqual((lineage/recovered['file']).read_bytes(),tail)
            self.assertEqual(recovered['sha256'],hashlib.sha256(tail).hexdigest())
            journal.append({'session':'2024-07-11','value':2.5})
            self.assertEqual(target.read_bytes()[:commit['bytes']],old[:commit['bytes']])

    def bad_prefix(self,remove_guard=False):
        with tempfile.TemporaryDirectory() as folder:
            source,target,commit,lineage,_=self.prepared(Path(folder));commit['sha256']='f'*64
            if remove_guard:
                original=continuation.need
                with patch.object(continuation,'need',side_effect=lambda v,r:None if r=='COMMITTED_PREFIX_HASH_OR_RECORDS' else original(v,r)):
                    return continuation.copy_prefix(source,target,commit,lineage,Journal)
            return continuation.copy_prefix(source,target,commit,lineage,Journal)

    def test_wrong_predecessor_hash_refuses_and_guard_removal_is_detected(self):
        with self.assertRaisesRegex(ValueError,'COMMITTED_PREFIX_HASH_OR_RECORDS'):self.bad_prefix()
        journal,_=self.bad_prefix(remove_guard=True)
        self.assertNotEqual(journal.commitment()['sha256'],'f'*64)

    def test_failed_flush_does_not_commit_frame_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'canonical.jsonl';journal=Journal(path);initial=journal.commitment()
            with patch('alpaca_fit_baseline.os.fsync',side_effect=OSError('synthetic fsync refusal')):
                with self.assertRaises(OSError):journal.append({'session':'synthetic'})
            self.assertEqual(journal.commitment(),initial)
            self.assertEqual(path.read_bytes(),encoded({'previous_chain_sha256':'0'*64,'session':'synthetic'}))


if __name__=='__main__':unittest.main()

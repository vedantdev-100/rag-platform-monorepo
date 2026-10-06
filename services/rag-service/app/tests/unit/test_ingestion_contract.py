import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from rag_contracts import IngestionJob
from app.workflows.policy import can_complete, matches, validate_vectors


class QueuePolicyTests(unittest.TestCase):
    def setUp(self):
        self.job = IngestionJob(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), 1, "test-v1")
        self.token = uuid.uuid4()
        self.now = datetime.now(timezone.utc)
        self.document = SimpleNamespace(id=self.job.document_id, owner_id=self.job.owner_id,
            job_id=self.job.job_id, generation=1, processing_version="test-v1", status="processing",
            processing_token=self.token, processing_lease_until=self.now + timedelta(seconds=60))

    def test_envelope_round_trip_and_no_source_bytes(self):
        encoded = self.job.to_json()
        self.assertEqual(IngestionJob.from_json(encoded), self.job)
        self.assertNotIn('content', json.loads(encoded))
        self.assertLess(len(encoded), 1024)

    def test_invalid_versions_and_shapes_rejected(self):
        for change in ({"v": 2}, {"v": True}, {"generation": True}, {"generation": 0},
                       {"owner_id": "not-a-uuid"}, {"content": "unexpected"}):
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                value = {**self.job.as_dict(), **change}
                IngestionJob.from_json(json.dumps(value))
        for raw in ('[]', '{}', 'x' * 5000):
            with self.assertRaises(ValueError):
                IngestionJob.from_json(raw)

    def test_wrong_owner_job_generation_and_version_are_fenced(self):
        for field, value in (("owner_id", uuid.uuid4()), ("job_id", uuid.uuid4()),
                             ("generation", 2), ("processing_version", "other")):
            original = getattr(self.document, field)
            setattr(self.document, field, value)
            self.assertFalse(matches(self.document, self.job))
            setattr(self.document, field, original)

    def test_only_live_processing_token_can_commit(self):
        self.assertTrue(can_complete(self.document, self.job, self.token, self.now))
        self.assertFalse(can_complete(self.document, self.job, uuid.uuid4(), self.now))
        self.assertFalse(can_complete(self.document, self.job, self.token, self.now + timedelta(seconds=60)))
        self.document.status = "ingested"
        self.assertFalse(can_complete(self.document, self.job, self.token, self.now))

    def test_vectors_reject_count_dimension_and_invalid_numbers(self):
        validate_vectors([[0.1] * 768], 1, 768)
        for vectors, count, dimension in (([], 1, 768), ([[0.1] * 767], 1, 768),
                                         ([[0.1] * 768], 1, 384), ([[float('nan')] * 768], 1, 768),
                                         ([[float('inf')] * 768], 1, 768), ([[True] * 768], 1, 768)):
            with self.assertRaises(ValueError):
                validate_vectors(vectors, count, dimension)


if __name__ == '__main__':
    unittest.main()

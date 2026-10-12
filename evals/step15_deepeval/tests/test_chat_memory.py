import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


class ChatMemoryTests(unittest.TestCase):
    def test_reviewed_empty_history_never_calls_provider(self):
        # Run the actual uploaded resolver with isolated import dependencies.
        types = ModuleType('app.rag.generation.types')
        types.GenerationError = RuntimeError
        validation = ModuleType('app.rag.retrieval.validation')
        validation.normalize_query = lambda value: value.strip()
        fixture = Path(__file__).parent / 'fixtures/reviewed_chat_memory.py'
        spec = importlib.util.spec_from_file_location('reviewed_memory', fixture)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'app.rag.generation.types': types,
                                     'app.rag.retrieval.validation': validation}):
            spec.loader.exec_module(module)
        class Provider:
            async def generate(self, *args):
                raise AssertionError('No query-resolution call expected')
        result = asyncio.run(module.standalone_question(Provider(), 'Original question', [], with_usage=True))
        self.assertEqual(result, ('Original question', None))


if __name__ == '__main__':
    unittest.main()

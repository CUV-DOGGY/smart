from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_services_do_not_import_concrete_repositories(self):
        for path in (APP_ROOT / "services").glob("*.py"):
            with self.subTest(path=path.name):
                self.assertNotIn("app.repositories", path.read_text(encoding="utf-8"))

    def test_routers_depend_on_services_not_repository_adapters(self):
        for path in (APP_ROOT / "routers").glob("*.py"):
            with self.subTest(path=path.name):
                self.assertNotIn("app.repositories", path.read_text(encoding="utf-8"))

    def test_phase_two_misspelled_and_model_factory_modules_are_gone(self):
        self.assertFalse((APP_ROOT / "contants" / "order_status.py").exists())
        self.assertFalse((APP_ROOT / "models" / "llm.py").exists())
        self.assertTrue((APP_ROOT / "constants" / "order_status.py").exists())
        self.assertTrue((APP_ROOT / "integrations" / "llm.py").exists())

    def test_langgraph_cannot_call_the_write_executor(self):
        graph_source = (APP_ROOT / "agents" / "graph.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("execute_write(", graph_source)
        self.assertIn("execute_read(", graph_source)
        self.assertIn("append_write_result", graph_source)


if __name__ == "__main__":
    unittest.main()

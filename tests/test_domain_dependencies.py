"""领域层依赖边界测试。"""

from __future__ import annotations

from pathlib import Path
import unittest


class DomainDependencyTestCase(unittest.TestCase):
    """确保 domain 层不直接依赖 infra 层。"""

    def test_domain_has_no_infra_imports(self) -> None:
        domain_dir = Path(__file__).resolve().parent.parent / "domain"
        py_files = sorted(domain_dir.rglob("*.py"))
        offending: list[str] = []
        for py_file in py_files:
            text = py_file.read_text(encoding="utf-8")
            if "from infra" in text or "import infra" in text:
                offending.append(str(py_file))
        self.assertEqual([], offending)


if __name__ == "__main__":
    unittest.main()


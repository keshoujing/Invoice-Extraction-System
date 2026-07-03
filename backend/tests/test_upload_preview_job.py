from __future__ import annotations

import unittest
from unittest.mock import call, patch

from app import main as main_module


class UploadPreviewJobTest(unittest.TestCase):
    def test_process_upload_preview_marks_failed_when_preview_falls_back(self) -> None:
        with (
            patch.object(
                main_module,
                "_get_invoice",
                return_value={"file_path": "invoice.pdf", "expense_type": ""},
            ),
            patch.object(main_module, "_prepare_supplier_on_upload", return_value=False),
            patch.object(main_module, "_mark_upload_preview_item") as mark_item,
            patch.object(main_module, "_increment_upload_preview_job") as increment_job,
        ):
            main_module._process_upload_preview_invoice("job-1", 123)

        mark_item.assert_has_calls(
            [
                call("job-1", 123, "running"),
                call("job-1", 123, "failed", "Supplier preview failed. Please confirm manually"),
            ]
        )
        increment_job.assert_called_once_with("job-1", False)


if __name__ == "__main__":
    unittest.main()

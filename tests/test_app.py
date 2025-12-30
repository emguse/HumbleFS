import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from humblefs.app import app


class HumbleFSTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.previous_root = os.environ.get("HUMBLEFS_ROOT")
        os.environ["HUMBLEFS_ROOT"] = self.temp_dir.name
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()
        if self.previous_root is None:
            os.environ.pop("HUMBLEFS_ROOT", None)
        else:
            os.environ["HUMBLEFS_ROOT"] = self.previous_root

    def test_put_get_roundtrip_default_plain(self) -> None:
        response = self.client.put("/bucket-one/path/file.txt", content=b"hello")
        self.assertEqual(response.status_code, 200)
        stored_key = response.json()["stored_key"]
        self.assertEqual(stored_key, "path/file.txt")

        stored_path = Path(self.temp_dir.name) / "bucket-one" / stored_key
        self.assertTrue(stored_path.exists())

        get_response = self.client.get("/bucket-one/path/file.txt")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.content, b"hello")

    def test_put_unique_adds_postfix(self) -> None:
        headers = {
            "x-amz-meta-hfs-mode": "unique",
            "x-amz-meta-hfs-conflict": "new",
        }
        response = self.client.put(
            "/bucket-plain/path/file.txt", headers=headers, content=b"plain"
        )
        self.assertEqual(response.status_code, 200)
        stored_key = response.json()["stored_key"]
        self.assertIn("__", stored_key)

    def test_put_conflict_fail_plain(self) -> None:
        headers = {
            "x-amz-meta-hfs-mode": "plain",
            "x-amz-meta-hfs-conflict": "fail",
        }
        first = self.client.put("/bucket-two/item.txt", headers=headers, content=b"alpha")
        self.assertEqual(first.status_code, 200)

        second = self.client.put("/bucket-two/item.txt", headers=headers, content=b"beta")
        self.assertEqual(second.status_code, 409)

    def test_list_prefix_filter(self) -> None:
        headers = {
            "x-amz-meta-hfs-mode": "plain",
            "x-amz-meta-hfs-conflict": "overwrite",
        }
        self.client.put("/bucket-three/a/one.txt", headers=headers, content=b"one")
        self.client.put("/bucket-three/b/two.txt", headers=headers, content=b"two")

        all_items = self.client.get("/bucket-three")
        self.assertEqual(all_items.status_code, 200)
        keys = {item["key"] for item in all_items.json()["objects"]}
        self.assertEqual(keys, {"a/one.txt", "b/two.txt"})

        prefix_items = self.client.get("/bucket-three", params={"prefix": "a/"})
        self.assertEqual(prefix_items.status_code, 200)
        prefix_keys = {item["key"] for item in prefix_items.json()["objects"]}
        self.assertEqual(prefix_keys, {"a/one.txt"})

    def test_delete_removes_object(self) -> None:
        headers = {
            "x-amz-meta-hfs-mode": "plain",
            "x-amz-meta-hfs-conflict": "overwrite",
        }
        self.client.put("/bucket-four/delete.txt", headers=headers, content=b"delete")

        delete_response = self.client.delete("/bucket-four/delete.txt")
        self.assertEqual(delete_response.status_code, 200)

        get_response = self.client.get("/bucket-four/delete.txt")
        self.assertEqual(get_response.status_code, 404)

    def test_invalid_metadata_header_rejected(self) -> None:
        response = self.client.put(
            "/bucket-five/item.txt",
            headers={"x-amz-meta-bad": "nope"},
            content=b"bad",
        )
        self.assertEqual(response.status_code, 400)

    def test_windows_traversal_rejected(self) -> None:
        response = self.client.put(
            "/bucket-six/safe%5C..%5Cevil.txt",
            content=b"nope",
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()

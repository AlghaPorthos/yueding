import unittest

from serve import DEFAULT_HOST, DEFAULT_PORT, resolve_address


class ResolveAddressTests(unittest.TestCase):
    def test_defaults_without_env_or_argv(self):
        self.assertEqual(resolve_address([], {}), (DEFAULT_HOST, DEFAULT_PORT))

    def test_env_overrides_defaults(self):
        environ = {"CONTRACT_READER_HOST": "0.0.0.0", "CONTRACT_READER_PORT": "9001"}
        self.assertEqual(resolve_address([], environ), ("0.0.0.0", 9001))

    def test_argv_overrides_env(self):
        environ = {"CONTRACT_READER_HOST": "0.0.0.0", "CONTRACT_READER_PORT": "9001"}
        argv = ["--host", "10.0.0.1", "--port", "9999"]
        self.assertEqual(resolve_address(argv, environ), ("10.0.0.1", 9999))

    def test_partial_mix_of_argv_and_env(self):
        self.assertEqual(
            resolve_address(["--port", "8080"], {"CONTRACT_READER_HOST": "localhost"}),
            ("localhost", 8080),
        )

    def test_invalid_argv_port_exits(self):
        with self.assertRaises(SystemExit):
            resolve_address(["--port", "not-a-port"], {})

    def test_out_of_range_env_port_rejected(self):
        with self.assertRaises(ValueError):
            resolve_address([], {"CONTRACT_READER_PORT": "70000"})


if __name__ == "__main__":
    unittest.main()

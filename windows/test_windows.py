import tempfile
import unittest
from pathlib import Path
from digup_windows import safe, read_text, cosine, command

class WindowsTests(unittest.TestCase):
    def test_exclusions(self):
        for name in ['C:/Users/me/.ssh/id_rsa', 'C:/Windows/file.txt', 'C:/files/passwords.txt', 'C:/files/key.pem']:
            self.assertFalse(safe(Path(name)))
        self.assertTrue(safe(Path('C:/Users/me/Documents/notes.txt')))

    def test_cpu_is_explicit(self):
        args = command({'server': 'server.exe', 'model': 'model.gguf', 'mode': 'CPU / system RAM'})
        self.assertEqual(args[-4:], ['--device', 'none', '--gpu-layers', '0'])

    def test_gpu_requires_device(self):
        with self.assertRaises(ValueError):
            command({'server': 'server.exe', 'model': 'model.gguf', 'mode': 'Integrated GPU'})
        args = command({'server': 'server.exe', 'model': 'model.gguf', 'mode': 'Integrated GPU', 'device': 'Vulkan1'})
        self.assertEqual(args[-4:], ['--device', 'Vulkan1', '--gpu-layers', 'all'])

    def test_vectors(self):
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1)
        self.assertEqual(cosine([1], [1, 0]), 0)
        self.assertEqual(cosine([0], [1]), 0)

    def test_text_and_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'notes.txt'
            path.write_text('Windows search example', encoding='utf-8')
            self.assertEqual(read_text(path), 'Windows search example')
            with path.open('wb') as stream:
                stream.truncate(9 * 1024 * 1024)
            self.assertEqual(read_text(path), '')

if __name__ == '__main__':
    unittest.main()

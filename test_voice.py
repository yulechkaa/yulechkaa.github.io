import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import voice


class VoicePublicationTests(unittest.TestCase):
    def run_case(self, success):
        previous = os.getcwd()
        old_out = voice.OUT
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                card = dict(date="2026-09-06", rhyme="test", verse=["line"], audio="audio/old.mp3")
                Path("data.json").write_text(json.dumps(card))
                Path("archive.json").write_text(json.dumps([card]))
                Path("audio.mp3").write_bytes(b"old audio")
                def synthesize(_):
                    if success:
                        Path(voice.OUT).write_bytes(b"x" * 2000)
                    return success
                with patch.object(voice, "read_text", return_value="line"), patch.object(voice, "try_chatterbox", side_effect=synthesize), patch.object(voice, "try_edge", return_value=False):
                    voice.main()
                updated = json.loads(Path("data.json").read_text())
                self.assertEqual(json.loads(Path("archive.json").read_text())[0]["audio"], updated["audio"])
                if success:
                    self.assertTrue(Path(updated["audio"]).exists())
                    self.assertNotIn("tmp", updated["audio"])
                else:
                    self.assertEqual(updated["audio"], "")
                self.assertEqual(Path("audio.mp3").read_bytes(), b"old audio")
            finally:
                os.chdir(previous)
                voice.OUT = old_out

    def test_failure_never_reuses_previous_audio(self):
        self.run_case(False)

    def test_success_updates_card_and_archive(self):
        self.run_case(True)


if __name__ == "__main__":
    unittest.main()

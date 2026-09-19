import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from clipforge.pipeline.render import (
    add_captions,
    compute_scene_windows,
    concat_clips,
    create_zoomed_clip,
    escape_drawtext,
    load_captions,
    mux_audio,
    probe_duration,
    render_video,
)


def _completed(stdout=b"", stderr=b""):
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestEscapeDrawtext(unittest.TestCase):
    def test_escapes_special_characters(self):
        cases = {
            "\\": "\\\\",
            "'": "''",
            '"': '\\"',
            "$": "\\$",
            "&": "\\&",
            "|": "\\|",
            ";": "\\;",
            ">": "\\>",
            "<": "\\<",
            "*": "\\*",
            "?": "\\?",
            "(": "\\(",
            ")": "\\)",
            ":": "\\:",
            "=": "\\=",
            ",": "\\,",
            "%": "%%",
            "[": "\\[",
            "]": "\\]",
        }
        for char, escaped in cases.items():
            with self.subTest(char=char):
                self.assertEqual(escape_drawtext(char), escaped)

    def test_leaves_plain_text_alone(self):
        self.assertEqual(escape_drawtext("hello world 123"), "hello world 123")

    def test_escapes_mixed_text(self):
        self.assertEqual(escape_drawtext("a: b, c"), "a\\: b\\, c")


class TestComputeSceneWindows(unittest.TestCase):
    def test_divides_evenly(self):
        windows = compute_scene_windows(9.0, 3)
        self.assertEqual(windows, [(0.0, 3.0), (3.0, 6.0), (6.0, 9.0)])

    def test_last_window_ends_exactly_at_duration(self):
        windows = compute_scene_windows(10.0, 3)
        self.assertEqual(windows[0][1], 3.33)
        self.assertEqual(windows[1][1], 6.67)
        self.assertEqual(windows[-1][1], 10.0)

    def test_single_scene(self):
        self.assertEqual(compute_scene_windows(12.34, 1), [(0.0, 12.34)])

    def test_rejects_zero_duration(self):
        with self.assertRaises(ValueError):
            compute_scene_windows(0, 3)

    def test_rejects_zero_scenes(self):
        with self.assertRaises(ValueError):
            compute_scene_windows(10.0, 0)


class TestCreateZoomedClip(unittest.TestCase):
    @patch("clipforge.pipeline.render._run_ffmpeg")
    def test_zoom_in_command(self, mock_run):
        create_zoomed_clip(Path("img.png"), 5.0, Path("clip.mp4"), effect="in")

        command = mock_run.call_args.args[0]
        self.assertEqual(command[0], "ffmpeg")
        self.assertEqual(command[1:3], ["-loop", "1"])
        self.assertEqual(command[3:5], ["-framerate", "30"])
        self.assertEqual(command[6], "img.png")
        vf = command[command.index("-vf") + 1]
        self.assertIn("scale=2160:-1", vf)
        self.assertIn("zoompan=z='zoom+0.002'", vf)
        self.assertIn("d=150", vf)
        self.assertIn("s=720x1280", vf)
        self.assertIn("fps=30", vf)
        self.assertIn("setsar=1/1,format=yuv420p", vf)
        self.assertEqual(command[command.index("-t") + 1], "5.0")
        self.assertEqual(command[command.index("-preset") + 1], "ultrafast")
        self.assertEqual(command[-1], "clip.mp4")

    @patch("clipforge.pipeline.render._run_ffmpeg")
    def test_zoom_out_command(self, mock_run):
        create_zoomed_clip(Path("img.png"), 2.0, Path("clip.mp4"), effect="out")

        vf = mock_run.call_args.args[0][mock_run.call_args.args[0].index("-vf") + 1]
        self.assertIn("if(lte(zoom,1.0),1.5,max(1.001,zoom-0.0025))", vf)
        self.assertIn("d=60", vf)

    @patch("clipforge.pipeline.render._run_ffmpeg")
    def test_random_effect_when_not_specified(self, mock_run):
        create_zoomed_clip(Path("img.png"), 1.0, Path("clip.mp4"))

        vf = mock_run.call_args.args[0][mock_run.call_args.args[0].index("-vf") + 1]
        self.assertTrue("zoom+0.002" in vf or "zoom-0.0025" in vf)


class TestConcatClips(unittest.TestCase):
    @patch("clipforge.pipeline.render._run_ffmpeg")
    def test_writes_list_file_and_runs_concat(self, mock_run):
        with tempfile.TemporaryDirectory() as tmp_dir:
            clips = [Path(tmp_dir) / f"clip_{i}.mp4" for i in range(2)]
            output = Path(tmp_dir) / "out.mp4"
            list_contents = {}

            def capture_list_file(*args, **kwargs):
                command = args[0]
                if "-f" in command:
                    list_path = Path(command[command.index("-i") + 1])
                    list_contents["text"] = list_path.read_text(encoding="utf-8")
                return _completed()

            mock_run.side_effect = capture_list_file
            concat_clips(clips, output)

            command = mock_run.call_args.args[0]
            self.assertEqual(command[command.index("-f") + 1], "concat")
            self.assertEqual(command[command.index("-safe") + 1], "0")
            self.assertEqual(command[-1], str(output))
            self.assertEqual(
                list_contents["text"],
                f"file '{clips[0]}'\nfile '{clips[1]}'\n",
            )

    def test_rejects_empty_clips(self):
        with self.assertRaises(ValueError):
            concat_clips([], Path("/tmp/out.mp4"))


class TestAddCaptions(unittest.TestCase):
    @patch("clipforge.pipeline.render._run_ffmpeg")
    def test_drawtext_chain(self, mock_run):
        captions = [((0.5, 2.0), "hello world"), ((2.0, 4.0), "next: line, ok?")]
        font_path = Path("/fonts/TitanOne-Regular.ttf")

        add_captions(Path("in.mp4"), captions, Path("out.mp4"), font_path=font_path)

        command = mock_run.call_args.args[0]
        vf = command[command.index("-vf") + 1]
        filters = vf.split("drawtext=")
        self.assertEqual(len(filters), 3)
        self.assertIn("HELLO WORLD", filters[1])
        self.assertIn(f"fontfile='{font_path}'", filters[1])
        self.assertIn("fontcolor=#FFFFFF:fontsize=35", filters[1])
        self.assertIn("x=(w-text_w)/2:y=h-text_h-(h*0.5)", filters[1])
        self.assertIn(
            "alpha='if(lt(t,0.5),0,if(lt(t,0.6),(t-0.5)/0.1,1))'", filters[1]
        )
        self.assertIn("borderw=6:bordercolor=#000000", filters[1])
        self.assertIn("enable='between(t,0.5,2.0)'", filters[1])
        self.assertIn("NEXT\\: LINE\\, OK\\?", filters[2])
        self.assertIn("enable='between(t,2.0,4.0)'", filters[2])
        self.assertEqual(command[command.index("-b:v") + 1], "2M")
        self.assertEqual(command[-1], "out.mp4")

    @patch("clipforge.pipeline.render._run_ffmpeg")
    def test_font_size_override(self, mock_run):
        add_captions(
            Path("in.mp4"),
            [((0.0, 1.0), "text")],
            Path("out.mp4"),
            font_size=50,
            vertical_offset_percent=30.0,
        )

        vf = mock_run.call_args.args[0][mock_run.call_args.args[0].index("-vf") + 1]
        self.assertIn("fontsize=50", vf)
        self.assertIn("y=h-text_h-(h*0.3)", vf)

    def test_rejects_empty_captions(self):
        with self.assertRaises(ValueError):
            add_captions(Path("in.mp4"), [], Path("out.mp4"))


class TestMuxAudio(unittest.TestCase):
    @patch("clipforge.pipeline.render._run_ffmpeg")
    def test_mux_command(self, mock_run):
        mux_audio(Path("video.mp4"), Path("voice.mp3"), Path("final.mp4"))

        command = mock_run.call_args.args[0]
        flags = lambda flag: [i for i, value in enumerate(command) if value == flag]
        self.assertEqual(command[0], "ffmpeg")
        self.assertEqual(command[flags("-i")[0] + 1], "video.mp4")
        self.assertEqual(command[flags("-i")[1] + 1], "voice.mp3")
        self.assertEqual(command[flags("-map")[0] + 1], "0:v")
        self.assertEqual(command[flags("-map")[1] + 1], "1:a")
        self.assertEqual(command[command.index("-c:v") + 1], "copy")
        self.assertEqual(command[command.index("-c:a") + 1], "aac")
        self.assertEqual(command[command.index("-b:a") + 1], "192k")
        self.assertIn("-shortest", command)
        self.assertEqual(command[-1], "final.mp4")


class TestProbeDuration(unittest.TestCase):
    @patch("clipforge.pipeline.render.subprocess.run")
    def test_parses_ffprobe_output(self, mock_run):
        mock_run.return_value = _completed(stdout=b"12.34\n")

        self.assertEqual(probe_duration(Path("audio.mp3")), 12.34)
        command = mock_run.call_args.args[0]
        self.assertEqual(command[0], "ffprobe")
        self.assertIn("format=duration", command)

    @patch("clipforge.pipeline.render.subprocess.run")
    def test_raises_on_bad_output(self, mock_run):
        mock_run.return_value = _completed(stdout=b"not-a-number\n")

        with self.assertRaises(RuntimeError):
            probe_duration(Path("audio.mp3"))


class TestLoadCaptions(unittest.TestCase):
    def test_reads_cf5_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            captions_path = Path(tmp_dir) / "captions.json"
            captions_path.write_text(
                json.dumps(
                    {
                        "text": "full text",
                        "duration": 8.5,
                        "words": [],
                        "timed_captions": [
                            {"start": 0.0, "end": 2.0, "text": "one"},
                            {"start": 2.0, "end": 8.5, "text": "two"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            timed_captions, duration = load_captions(captions_path)

            self.assertEqual(duration, 8.5)
            self.assertEqual(
                timed_captions, [((0.0, 2.0), "one"), ((2.0, 8.5), "two")]
            )


class TestRenderVideo(unittest.TestCase):
    def _captions_file(self, tmp_dir):
        captions_path = Path(tmp_dir) / "captions.json"
        captions_path.write_text(
            json.dumps(
                {
                    "text": "text",
                    "duration": 6.0,
                    "words": [],
                    "timed_captions": [{"start": 0.0, "end": 6.0, "text": "caption"}],
                }
            ),
            encoding="utf-8",
        )
        return captions_path

    @patch("clipforge.pipeline.render.shutil.which")
    @patch("clipforge.pipeline.render.subprocess.run")
    def test_full_pipeline_command_sequence(self, mock_run, mock_which):
        mock_which.return_value = "/usr/local/bin/ffmpeg"
        captured = {}

        def fake_run(command, **kwargs):
            if "-f" in command:
                list_path = Path(command[command.index("-i") + 1])
                captured["concat_list"] = list_path.read_text(encoding="utf-8")
            return _completed(stdout=b"6.0\n")

        mock_run.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmp_dir:
            images = [Path(tmp_dir) / f"scene_{i}.png" for i in range(3)]
            for image in images:
                image.touch()
            captions_path = self._captions_file(tmp_dir)
            output_path = Path(tmp_dir) / "short.mp4"

            result = render_video(images, Path("voice.mp3"), captions_path, output_path)

            self.assertEqual(result, output_path)
            commands = [call.args[0] for call in mock_run.call_args_list]
            self.assertEqual(len(commands), 7)  # ffprobe + 3 clips + concat + captions + mux
            self.assertEqual(commands[0][0], "ffprobe")
            for index in range(3):
                clip_command = commands[index + 1]
                self.assertEqual(clip_command[0], "ffmpeg")
                self.assertEqual(clip_command[clip_command.index("-t") + 1], "2.0")
            names = [
                line.replace("file '", "").rstrip("'").rsplit("/", 1)[-1]
                for line in captured["concat_list"].splitlines()
                if line
            ]
            self.assertEqual(names, [f"clip_{i:02d}.mp4" for i in range(3)])
            caption_command = commands[5]
            self.assertIn("CAPTION", caption_command[caption_command.index("-vf") + 1])
            mux_command = commands[6]
            self.assertEqual(mux_command[-1], str(output_path))
            self.assertIn("-shortest", mux_command)

    @patch("clipforge.pipeline.render.shutil.which")
    @patch("clipforge.pipeline.render.subprocess.run")
    def test_requires_ffmpeg_on_path(self, mock_run, mock_which):
        mock_which.return_value = None

        with self.assertRaises(RuntimeError) as context:
            render_video(
                [Path("scene_00.png")], Path("voice.mp3"), Path("captions.json"),
                Path("out.mp4"),
            )

        self.assertIn("ffmpeg and ffprobe", str(context.exception))
        mock_run.assert_not_called()

    @patch("clipforge.pipeline.render.shutil.which")
    def test_rejects_empty_images(self, mock_which):
        mock_which.return_value = "/usr/local/bin/ffmpeg"

        with self.assertRaises(ValueError):
            render_video([], Path("voice.mp3"), Path("captions.json"), Path("out.mp4"))


if __name__ == "__main__":
    unittest.main()
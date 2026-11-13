"""AssemblyAI against a local fake server, Whisper's readiness checks, the transcript cache."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from open_recorder import ffmpeg
from open_recorder.transcribe import AssemblyAI, TranscribeError, Whisper, load, plain_text, save
from open_recorder.transcribe import assemblyai as aai_module

from test_project import make_take


class FakeAAI(BaseHTTPRequestHandler):
    polls = 0

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("authorization") != "good":
            return self._send(401, {"error": "bad key"})
        if self.path.startswith("/transcript/"):
            FakeAAI.polls += 1
            if FakeAAI.polls < 2:
                return self._send(200, {"status": "processing"})
            return self._send(200, {"status": "completed", "language_code": "en", "words": [
                {"text": "hello", "start": 100, "end": 400}, {"text": "there", "start": 500, "end": 900}]})
        return self._send(200, {"transcripts": []})

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        if self.path == "/upload":
            return self._send(200, {"upload_url": "https://cdn/x"})
        return self._send(200, {"id": "job1"})


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(aai_module, "POLL_SECONDS", 0.05)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeAAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_key_check(server):
    assert AssemblyAI("good", server).check_key()[0]
    ok, why = AssemblyAI("bad", server).check_key()
    assert not ok and "key" in why
    assert not AssemblyAI("", server).ready()[0]


@pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg is not installed")
def test_assemblyai_transcribe(server, tmp_path):
    make_take(tmp_path, seconds=1)
    seen = []
    data = AssemblyAI("good", server).transcribe(tmp_path / "camera_20260101_120000.mp4", 1.0,
                                                 lambda f, msg: seen.append(f))
    assert data["words"] == [{"w": "hello", "s": 0.1, "e": 0.4}, {"w": "there", "s": 0.5, "e": 0.9}]
    assert seen and max(seen) <= 1


def test_whisper_not_ready_without_a_model(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    w = Whisper("small", models_dir=tmp_path / "models")
    ok, why = w.ready()
    assert not ok
    with pytest.raises(TranscribeError):
        w.transcribe(tmp_path / "x.mp4", 1, lambda *a: None)
    (tmp_path / "models" / "faster-whisper-small").mkdir(parents=True)
    (tmp_path / "models" / "faster-whisper-small" / "model.bin").write_bytes(b"x")
    assert w.model_dir() == tmp_path / "models" / "faster-whisper-small"


def test_transcript_cache(tmp_path):
    source = tmp_path / "camera.mp4"
    source.write_bytes(b"x")
    save(tmp_path / "t", source, {"words": [{"w": "hi", "s": 0, "e": 1}]})
    assert plain_text(load(tmp_path / "t", source)) == "hi"

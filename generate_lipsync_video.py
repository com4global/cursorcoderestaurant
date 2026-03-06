import argparse
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pyttsx3


ROOT = Path(__file__).resolve().parent
WAV2LIP_DIR = ROOT / "Wav2Lip"


def ensure_wav2lip_exists():
  if not WAV2LIP_DIR.exists():
    raise SystemExit(
      f"Wav2Lip repo not found at {WAV2LIP_DIR}.\n"
      "Clone it next to this script with:\n"
      "  git clone https://github.com/Rudrabha/Wav2Lip.git\n"
      "and follow its README to download the pretrained model."
    )


def synthesize_tts_to_wav(text: str, out_wav: Path):
  engine = pyttsx3.init()
  # You can tweak voice, rate, and volume here if you want
  engine.setProperty("rate", 175)   # words per minute
  engine.setProperty("volume", 1.0) # 0.0 to 1.0
  engine.save_to_file(text, str(out_wav))
  engine.runAndWait()


def run_wav2lip(face_video: Path, audio_wav: Path, out_video: Path):
  """
  Calls Wav2Lip's inference.py via subprocess.
  Assumes you have already installed Wav2Lip dependencies and downloaded the model.
  """
  ensure_wav2lip_exists()

  cmd = [
    sys.executable,
    str(WAV2LIP_DIR / "inference.py"),
    "--face", str(face_video),
    "--audio", str(audio_wav),
    "--outfile", str(out_video),
  ]

  print("Running:", " ".join(cmd))
  completed = subprocess.run(cmd)
  if completed.returncode != 0:
    raise SystemExit(f"Wav2Lip inference failed with code {completed.returncode}")


def generate_lipsynced_video(text: str, face: Path, out: Path | None = None) -> Path:
  """
  High-level helper used by both CLI and web app.

  - text: English script
  - face: path to teacher/avatar video or image
  - out: optional output video path; if None, a new one in ROOT/outputs is created
  """
  face_path = Path(face).expanduser().resolve()
  if not face_path.exists():
    raise SystemExit(f"Face/teacher video not found: {face_path}")

  outputs_dir = ROOT / "outputs"
  outputs_dir.mkdir(exist_ok=True)

  if out is not None:
    out_video = Path(out).expanduser().resolve()
  else:
    out_video = outputs_dir / f"lipsynced_{uuid.uuid4().hex[:8]}.mp4"

  with tempfile.TemporaryDirectory() as tmpdir:
    tmpdir_path = Path(tmpdir)
    audio_wav = tmpdir_path / "script_audio.wav"

    print(f"Synthesizing TTS audio to: {audio_wav}")
    synthesize_tts_to_wav(text, audio_wav)

    print(f"Running Wav2Lip with face={face_path}, audio={audio_wav}")
    run_wav2lip(face_path, audio_wav, out_video)

  print(f"Done. Output video: {out_video}")
  return out_video


def main():
  parser = argparse.ArgumentParser(
    description="Generate a lip-synced avatar video from text using local TTS + Wav2Lip."
  )
  parser.add_argument(
    "--text",
    type=str,
    required=True,
    help="English script to speak."
  )
  parser.add_argument(
    "--face",
    type=str,
    required=True,
    help="Path to your teacher/avatar video or image (e.g. assets/teacher.mp4)."
  )
  parser.add_argument(
    "--out",
    type=str,
    default=None,
    help="Output video path (default: outputs/lipsynced_<random>.mp4)."
  )

  args = parser.parse_args()

  generate_lipsynced_video(args.text, Path(args.face), Path(args.out) if args.out else None)


if __name__ == "__main__":
  main()


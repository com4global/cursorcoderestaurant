from pathlib import Path

from flask import Flask, render_template, request, send_file, redirect, url_for, flash

from generate_lipsync_video import generate_lipsynced_video, ROOT


app = Flask(__name__)
app.secret_key = "dev-secret-key"  # change if you like


@app.route("/", methods=["GET"])
def index():
  return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
  text = request.form.get("script", "").strip()
  if not text:
    flash("Please enter a script.")
    return redirect(url_for("index"))

  # Change this path to your teacher/avatar video if needed
  teacher_video = ROOT / "assets" / "teacher.mp4"

  if not teacher_video.exists():
    flash(f"Teacher video not found at {teacher_video}. Please place your video there.")
    return redirect(url_for("index"))

  try:
    output_path = generate_lipsynced_video(text, teacher_video)
  except SystemExit as e:
    flash(str(e))
    return redirect(url_for("index"))
  except Exception as e:
    flash(f"Error generating video: {e}")
    return redirect(url_for("index"))

  # Stream the file back to the browser for download/playback
  return send_file(
    output_path,
    as_attachment=True,
    download_name=output_path.name,
    mimetype="video/mp4",
  )


if __name__ == "__main__":
  # Run on http://127.0.0.1:5000
  app.run(debug=True)


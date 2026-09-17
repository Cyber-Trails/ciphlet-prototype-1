# Training a custom "Hey Ciphlet" wake-word model

**Status: not yet trained.** Ciphlet currently falls back to openWakeWord's
bundled generic pretrained models ("hey jarvis", "alexa", etc. — see
`deploy/install_voice.sh`) because no custom model exists yet. This document
is the real, verified procedure to produce one. `ciphlet/voice/providers.py`
(`OpenWakeWordProvider`) already supports loading a custom model via
`CIPHLET_WAKE_MODEL` — no Ciphlet code changes are needed once a trained
model file exists; only this training step remains.

## Why this doesn't run as part of `deploy/install_voice.sh`, on the Pi, or on a Mac dev machine

openWakeWord's real custom-training pipeline (verified directly against
`dscripka/openWakeWord`'s own `notebooks/automatic_model_training.ipynb`,
not assumed) is a GPU-class ML training job, not a lightweight script:

- ~15 additional Python packages beyond openWakeWord itself, including
  `torch`, `torch-audiomentations`, `speechbrain`, `tensorflow-cpu==2.8.1`,
  `onnx_tf`, `audiomentations` — a training-only stack, unrelated to (and
  much heavier than) the `openwakeword` *inference* package Ciphlet already
  depends on for runtime wake detection.
- Tens of GB of precomputed negative-audio feature data (e.g.
  `openwakeword_features_ACAV100M_2000_hrs_16bit.npy`, ~2,000 hours of
  precomputed features) plus AudioSet/Free Music Archive/room-impulse-
  response downloads, so the trained model has real negative examples to
  reject.
- openWakeWord's own documentation targets **~10 minutes on a free Google
  Colab T4 GPU instance** — this is the environment the upstream project
  itself is built around and tests on.

None of that belongs on the Pi (ARM, CPU-only — no GPU, and pinned wheels
like `tensorflow-cpu==2.8.1` are unlikely to have aarch64 support even if
you tried) or on the Mac used to develop Ciphlet (project rule: no Ciphlet
runtime/training workloads on the Mac; Pi behavior must come from the Pi,
and this is even further outside that — it's a one-time offline training
job, not "Ciphlet running"). Google Colab's free tier is the realistic,
correctly-scoped venue, exactly as the upstream project intends.

## Procedure (uses the real, unmodified upstream notebook)

1. Open the official notebook in Colab:
   `https://colab.research.google.com/github/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb`
   (or open the notebook's GitHub page and use its "Open in Colab" button:
   `https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb`)

2. Select a GPU runtime (Runtime → Change runtime type → T4 GPU).

3. Where the notebook sets the target phrase, use the same pattern the
   notebook itself documents for a custom phrase:
   ```python
   config["target_phrase"] = ["hey ciphlet"]
   config["model_name"] = "hey_ciphlet"
   ```
   **Pronunciation note (verify by listening, don't assume):** "Ciphlet" is
   a novel word ("SIGH-flet"), and synthetic TTS voices generating the
   positive training samples will read the literal spelling using normal
   English pronunciation rules, which may not land on "SIGH-flet" by
   default (it could come out closer to "SIF-let"). openWakeWord's own
   community already handles this for other uncommon names by respelling
   phonetically in `target_phrase` (e.g. a documented real example sets
   `target_phrase = ["hey sebastian"]` for a name, not a re-engineered
   pipeline) — `target_phrase` accepts a list, so multiple spellings can be
   included together to cover both a literal and phonetic rendering, e.g.:
   ```python
   config["target_phrase"] = ["hey ciphlet", "hey siphlet"]
   ```
   Listen to the generated synthetic samples partway through the notebook
   before committing to a full training run, and adjust the spelling(s) if
   the pronunciation is wrong.

4. Run all cells. ~10 minutes on a free Colab T4 GPU per openWakeWord's own
   documented expectation.

5. Download the resulting model from the notebook's output directory —
   `hey_ciphlet.onnx` (openWakeWord's Python inference path, which is what
   `ciphlet/voice/providers.py::OpenWakeWordProvider` uses, needs the
   `.onnx` file; a `.tflite` is also produced but not required here).

## Wiring the trained model into Ciphlet

On the Pi, in the Ciphlet repo:

```bash
mkdir -p models/wake
# copy the downloaded hey_ciphlet.onnx to models/wake/hey_ciphlet.onnx
```

Then set in `.env`:
```
CIPHLET_WAKE_MODEL=models/wake/hey_ciphlet.onnx
```

`deploy/install_voice.sh` already checks for this file and will print the
correct `CIPHLET_WAKE_MODEL` line automatically if it's present when the
script runs; if it isn't there yet, the script leaves `CIPHLET_WAKE_MODEL`
unset and Ciphlet keeps using openWakeWord's generic pretrained models
("hey jarvis" / "alexa") as the functional-test fallback described there.

No changes to `ciphlet/voice/providers.py` or `ciphlet/voice/pipeline.py`
are needed for this — `OpenWakeWordProvider(model_path=...)` already loads
whatever `.onnx` file `CIPHLET_WAKE_MODEL` points at.

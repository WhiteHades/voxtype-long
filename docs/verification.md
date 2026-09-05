# verification

Tested on 2026-09-05 with Omarchy 4.0.2 and Voxtype 1.0.0.
The model was the existing, unquantized `base.en` file in every test.

## recording limit

Omarchy's packaged configuration sets `audio.max_duration_secs = 60`.
Voxtype's supported setter accepts 5 through 3600 seconds. Zero is invalid.

Two isolated daemons captured a temporary PulseAudio null sink. The microphone,
live dictation daemon, and clipboard were not used by the test.

| elapsed time | 60-second limit | 3600-second limit |
|---|---|---|
| 58 seconds | recording | recording |
| 63 seconds | transcribing | recording |
| 66 seconds | idle | recording |

The live service was restarted only after it became idle. Its model and
recognition settings stayed unchanged. A complete one-hour recording was not
tested. At 16 kHz, one mono float32 audio buffer needs about 220 MiB per hour;
Voxtype and Whisper also need working memory. The capture buffer grows with
recording length, so this is not an unlimited-memory recording mode.

## inference measurements

A 66-second WAV repeated the upstream whisper.cpp `samples/jfk.wav` six times.
These were single runs on a busy desktop, including a separate process and
model load for each configuration. They are screening results, not a controlled
hardware benchmark or a broad accuracy evaluation.

| configuration | transcription | total wall time | peak process RSS |
|---|---:|---:|---:|
| AMD integrated Vulkan GPU, current settings | 9.90 s | 14.33 s | 171.4 MiB |
| same GPU with flash attention | 10.33 s | 15.60 s | 209.2 MiB |
| NVIDIA GTX 1650 Ti, flash attention off | 27.98 s | 34.93 s | 272.0 MiB |

Flash attention preserved the words but changed the final punctuation. Its
reported encoder buffer fell from 88.95 MB to 23.09 MB, while measured process
RSS rose. Process RSS does not include all GPU allocations. The NVIDIA run
matched the baseline transcript. Neither alternative justified changing the
installed configuration. GPU performance can vary with workload and drivers.

The helper does not change Whisper's algorithm, model, decoding, VAD, eager
processing, or output driver. Longer recordings take more time and memory.
Quality is preserved by keeping the existing transcription path; no claim is
made that a short fixture establishes accuracy for all speech.

A later latency check compared CPU and GPU with the same model and decoding
settings. The 11-second sample took 0.90 seconds to transcribe on the existing
GPU, versus 1.41 seconds on eight CPU threads. The 66-second sample took
3.52 seconds on the GPU and 5.40 seconds on eight CPU threads. These later runs
were faster than the first measurements, which shows why a busy-desktop result
is not a latency guarantee. The existing GPU and automatic four-thread setting
remain the best measured choice here.

## text after release

The installed Whisper backend transcribes after recording stops. It does not
implement Voxtype's streaming interface. The current model already stays
loaded (`whisper.on_demand_loading = false`), and GPU isolation is off.

Experimental eager processing transcribes chunks during capture, then combines
and inserts the result after release. Upstream documents possible duplicated
or missing words at chunk boundaries. It remains disabled to preserve the
existing recognition path. Live typing requires a different streaming backend
or a separate preview implementation; neither is included here. A preview
followed by the normal final pass would add processing work.

The selected output driver is `wtype`, with no pre-type delay or postprocessor.
It receives the complete transcript in one invocation. The stock one-millisecond
character delay remains enabled to avoid dropping input in slower applications.
Forcing one driver removes fallback options without speeding up the successful
path; clipboard paste changes behavior and adds its own delay.

## repeated starts

The native daemon was tested with an isolated virtual audio source playing the
same speech sample. After recording three seconds, the test stopped capture
and sent a second start while the daemon reported `transcribing`. The daemon
returned to `idle` and never started the second recording.

Voxtype 1.0.0's SIGUSR1 handler accepts starts only while idle. The helper
remembers one start request until the previous transcript finishes. It does
not capture speech during that wait. Releasing F9 or cancelling removes the
pending request. Wait for the microphone indicator before speaking.

The same isolated test passed with the helper: the queued start became a new
recording after the previous transcript finished. Thirteen integration tests
also passed, covering delayed acknowledgements, concurrent starts and stops,
queue cancellation, timeouts, and daemon exit.

## upgrade compatibility

Runtime tests used the installed Voxtype 1.0.0 package. Source review of 1.0.1
(`dda37ca`) confirmed unchanged record commands, automatic state strings,
runtime lock path, and supported duration range. It still ignores a start
during transcription. Voxtype stays package-managed; no application files or
model files were patched. Future releases still need verification.

## sources

- [Omarchy Quattro voice configuration](https://github.com/basecamp/omarchy/blob/493067741e081c3b09082da6bfd51e99ec24ef00/default/voxtype/config.toml)
- [Voxtype 1.0.0 configuration schema](https://github.com/peteonrails/voxtype/blob/v1.0.0/src/config/schema.rs)
- [Voxtype daemon timer and signal handling](https://github.com/peteonrails/voxtype/blob/v1.0.0/src/daemon.rs)
- [Voxtype capture buffer](https://github.com/peteonrails/voxtype/blob/v1.0.0/src/audio/cpal_capture.rs)
- [Whisper transcription implementation](https://github.com/peteonrails/voxtype/blob/v1.0.0/src/transcribe/whisper.rs)
- [Test audio](https://github.com/ggml-org/whisper.cpp/blob/master/samples/jfk.wav)
- [Voxtype eager processing](https://github.com/peteonrails/voxtype/blob/v1.0.0/docs/CONFIGURATION.md#eager_processing)
- [Transcriber streaming interface](https://github.com/peteonrails/voxtype/blob/v1.0.0/src/transcribe/mod.rs)
- [Voxtype 1.0.1 daemon](https://github.com/peteonrails/voxtype/blob/v1.0.1/src/daemon.rs)
- [Native wtype output](https://github.com/peteonrails/voxtype/blob/v1.0.0/src/output/wtype.rs)

# voxtype-long

`voxtype-long` keeps one requested start until voxtype is idle. Voxtype 1.0.0
silently drops `record start` while it is transcribing, which makes a quick
second dictation disappear. This helper waits until voxtype is idle, then
sends the native start command.

`configure` sets `audio.max_duration_secs` to `3600` through the official
voxtype CLI. It leaves the current model, audio device, transcription, and
output settings alone. The queued-start wait is also bounded at one hour.
Restart the voxtype service after changing the cap. Text still appears after
release; this helper does not add live transcription.

Use these commands in the compositor binding:

```text
voxtype-long start
voxtype-long stop
voxtype-long toggle
```

Hold F9 for push-to-talk. A release cancels a queued start and stops an active
recording. Toggle while voxtype is transcribing queues one start; a second
toggle cancels it. Wait for the mic indicator before speaking after a queued
press.

Install the script with a user-local symlink:

```sh
ln -s "$PWD/voxtype-long" ~/.local/bin/voxtype-long
```

The helper requires Python 3; `notify-send` is optional. It does not change
the `base.en` model or add a second transcription pass.

Run the integration tests with:

```sh
python3 -m unittest -v
```

See [verification](docs/verification.md) for capture tests and GPU measurements.

Voxtype stays package-managed. The helper uses native record commands and the
documented automatic state file. Runtime tests passed on 1.0.0; the same
contracts were checked in 1.0.1 source. Re-run checks after upgrading.

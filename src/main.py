"""CLI entry point for WASAPI Audio Recorder."""

import sys
import time
import threading
from pathlib import Path

from devices import get_loopback_devices, get_input_devices, AudioDevice
from recorder import Recorder, StreamConfig
from writer import AudioWriter


def select_device(devices: list[AudioDevice], prompt: str) -> AudioDevice | None:
    """Show device list and allow selection."""
    if not devices:
        print("  No devices available")
        return None

    for i, d in enumerate(devices, 1):
        print(f"  [{i}] {d.name}")
        print(f"       {d.channels}ch, {d.sample_rate} Hz")

    print(f"  [0] None (skip)")

    while True:
        try:
            choice = input(f"\n{prompt} [1]: ").strip()
            if choice == "":
                choice = "1"
            idx = int(choice)
            if idx == 0:
                return None
            if 1 <= idx <= len(devices):
                return devices[idx - 1]
            print("Invalid selection")
        except ValueError:
            print("Enter a number")
        except KeyboardInterrupt:
            return None


def format_duration(seconds: float) -> str:
    """Format duration as MM:SS."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"


def main() -> int:
    """Main entry point."""
    print("\n" + "=" * 50)
    print("  WASAPI Audio Recorder - v0.1.0")
    print("=" * 50)

    # Get devices
    loopback_devices = get_loopback_devices()
    input_devices = get_input_devices()

    # Select loopback
    print("\n--- Loopback Devices (System Audio) ---")
    loopback = select_device(loopback_devices, "Select loopback")

    # Select microphone
    print("\n--- Input Devices (Microphone) ---")
    mic = select_device(input_devices, "Select microphone")

    if loopback is None and mic is None:
        print("\nError: you must select at least one device")
        return 1

    # Show selection
    print("\n--- Configuration ---")
    if loopback:
        print(f"  Loopback: {loopback.name}")
    if mic:
        print(f"  Microphone: {mic.name}")

    # Ask for output folder
    default_output = Path.cwd()
    output_path = input(f"\nOutput folder [{default_output}]: ").strip()
    if not output_path:
        output_path = default_output
    else:
        output_path = Path(output_path)

    # Determine target sample rate (use highest among devices)
    target_rate = 48000
    if loopback:
        target_rate = max(target_rate, loopback.sample_rate)
    if mic:
        target_rate = max(target_rate, mic.sample_rate)

    # Create configurations
    loopback_config = None
    mic_config = None

    if loopback:
        loopback_config = StreamConfig(
            device_index=loopback.index,
            channels=loopback.channels,
            sample_rate=loopback.sample_rate,
            volume=1.0
        )

    if mic:
        mic_config = StreamConfig(
            device_index=mic.index,
            channels=mic.channels,
            sample_rate=mic.sample_rate,
            volume=1.0
        )

    # Create recorder and writer
    recorder = Recorder(
        loopback_config=loopback_config,
        mic_config=mic_config,
        target_sample_rate=target_rate
    )

    writer = AudioWriter(
        output_dir=output_path,
        sample_rate=target_rate,
        channels=2
    )

    # Start
    print("\n" + "-" * 50)
    input("Press ENTER to start recording...")

    filepath = writer.start()
    recorder.start()

    print(f"\nRecording: {filepath.name}")
    print("Press ENTER to stop...\n")

    # Stop flag
    stop_event = threading.Event()

    # Thread to write data
    def write_loop():
        while not stop_event.is_set():
            chunk = recorder.get_mixed_chunk(timeout=0.1)
            if chunk is not None:
                writer.write(chunk)

    write_thread = threading.Thread(target=write_loop, daemon=True)
    write_thread.start()

    # Thread to show time
    def display_loop():
        while not stop_event.is_set():
            duration = format_duration(writer.duration_seconds)
            print(f"\r  Duration: {duration}", end="", flush=True)
            time.sleep(0.5)

    display_thread = threading.Thread(target=display_loop, daemon=True)
    display_thread.start()

    # Wait for input to stop
    try:
        input()
    except KeyboardInterrupt:
        pass

    # Stop everything
    stop_event.set()
    print("\n\nStopping recording...")

    recorder.stop()
    write_thread.join(timeout=2.0)
    final_path = writer.stop()

    # Result
    print("\n" + "=" * 50)
    print(f"  Saved: {final_path}")
    print(f"  Duration: {format_duration(writer.duration_seconds)}")
    print("=" * 50 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""WASAPI device enumeration."""

from dataclasses import dataclass
import pyaudiowpatch as pyaudio


@dataclass
class AudioDevice:
    """Represents a WASAPI audio device."""
    index: int
    name: str
    channels: int
    sample_rate: int
    is_loopback: bool


def get_devices() -> list[AudioDevice]:
    """Return list of all available WASAPI devices."""
    devices = []
    p = pyaudio.PyAudio()

    try:
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)

            # Only devices with input channels (including loopback)
            if info.get("maxInputChannels", 0) > 0:
                devices.append(AudioDevice(
                    index=i,
                    name=info["name"],
                    channels=info["maxInputChannels"],
                    sample_rate=int(info["defaultSampleRate"]),
                    is_loopback=info.get("isLoopbackDevice", False)
                ))
    finally:
        p.terminate()

    return devices


def get_loopback_devices() -> list[AudioDevice]:
    """Return only loopback devices (system audio)."""
    return [d for d in get_devices() if d.is_loopback]


def get_input_devices() -> list[AudioDevice]:
    """Return only input devices (microphones)."""
    return [d for d in get_devices() if not d.is_loopback]


def list_devices() -> None:
    """Print all available devices."""
    devices = get_devices()

    print("\n=== Loopback Devices (System Audio) ===")
    loopback = [d for d in devices if d.is_loopback]
    if loopback:
        for d in loopback:
            print(f"  [{d.index}] {d.name}")
            print(f"       Channels: {d.channels}, Sample Rate: {d.sample_rate} Hz")
    else:
        print("  No loopback devices found")

    print("\n=== Input Devices (Microphones) ===")
    inputs = [d for d in devices if not d.is_loopback]
    if inputs:
        for d in inputs:
            print(f"  [{d.index}] {d.name}")
            print(f"       Channels: {d.channels}, Sample Rate: {d.sample_rate} Hz")
    else:
        print("  No input devices found")
    print()


if __name__ == "__main__":
    list_devices()

"""Read-only Teams call and virtual-output detection, run off the Tk thread."""
from dataclasses import dataclass, field
import re

from visuals import WindowTarget, teams_windows


@dataclass
class MeetingScene:
    windows: list[WindowTarget] = field(default_factory=list)
    virtual_audio: bool = False
    detail: str = ''

    @property
    def target(self):
        return self.windows[0] if len(self.windows) == 1 else None


def is_meeting_controls(title, buttons):
    # A Teams chat/home window can also contain a compact call bar.
    if re.match(r'^(chat|chats|activity|calendar|teams and channels|聊天|活动|日历)\s*\|', title, re.I):
        return False
    names = [name.casefold().strip() for name, _ in buttons]
    ids = {ident.casefold() for _, ident in buttons}
    leave = any('hangup' in ident or 'hang-up' in ident for ident in ids) or any(
        re.match(r'^(leave(?: call| meeting)?|hang up|离开(?:会议)?|挂断|lämna)(?:$|\s*[（(])', name) for name in names)
    mic = any('microphone' in ident or ident in ('microphone-button', 'mic-button') for ident in ids) or any(
        re.match(r'^(mic\b|microphone\b|mute\b|unmute\b|麦克风|静音|取消静音|mikrofon)', name) for name in names)
    camera = any('camera' in ident for ident in ids) or any(
        re.match(r'^(camera\b|turn .*camera|摄像头|开启摄像头|关闭摄像头|kamera)', name) for name in names)
    return bool(leave and mic and camera)


def cable_render_name(capture_name):
    prefix = 'CABLE Output ('
    if capture_name.startswith(prefix) and 'VB-Audio Virtual Cable' in capture_name:
        return capture_name.replace('CABLE Output (', 'CABLE Input (', 1)
    return None


def _meeting_buttons(automation, target):
    element = automation.ElementFromHandle(target.hwnd)
    buttons = element.FindAll(4, automation.CreatePropertyCondition(30003, 50000))
    return [(buttons.GetElement(i).CurrentName or '', buttons.GetElement(i).CurrentAutomationId or '')
            for i in range(buttons.Length)]


def _teams_process(process, meeting_pids):
    import psutil
    try:
        for _ in range(5):
            if process is None:
                return False
            if process.pid in meeting_pids or process.name().lower() in ('ms-teams.exe', 'teams.exe'):
                return True
            process = process.parent()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def _virtual_route_active(render_name, meeting_pids):
    from pycaw.utils import AudioUtilities, AudioSession
    from pycaw.api.audiopolicy import IAudioSessionControl2
    for device in AudioUtilities.GetAllDevices(data_flow=0, device_state=1):
        if device.FriendlyName != render_name:
            continue
        sessions = device.AudioSessionManager.GetSessionEnumerator()
        for i in range(sessions.GetCount()):
            session = AudioSession(sessions.GetSession(i).QueryInterface(IAudioSessionControl2))
            if session.State == 1 and _teams_process(session.Process, meeting_pids):
                return True
    return False


def detect_scene(capture_name):
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()
    try:
        candidates = teams_windows()
        if not candidates:
            return MeetingScene(detail='没有 Teams 会议 · 会议室模式')
        uia = comtypes.client.GetModule('UIAutomationCore.dll')
        automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
        windows = []
        for target in candidates:
            try:
                if is_meeting_controls(target.title, _meeting_buttons(automation, target)):
                    windows.append(target)
            except (OSError, comtypes.COMError):
                continue
        if not windows:
            return MeetingScene(detail='未确认 Teams 通话窗口 · 会议室模式')
        if len(windows) != 1:
            return MeetingScene(windows=windows, detail='找到多个会议窗口 · 请手动选择，当前仅录麦克风')
        render = cable_render_name(capture_name)
        routed = bool(render and _virtual_route_active(render, {w.pid for w in windows}))
        return MeetingScene(windows, routed, 'Teams 虚拟声卡 + 麦克风' if routed else
                            'Teams 未向所选虚拟声卡输出 · 会议室模式')
    finally:
        comtypes.CoUninitialize()

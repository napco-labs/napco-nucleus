# NAPCO Nucleus: keep the default SPEAKER endpoint UNMUTED at all times.
# PROVEN 2026-07-24: a muted speaker silences the WASAPI-loopback recording
# (call audio died the instant the speaker was muted at 19:14:38, and returned
# when unmuted at 20:00). This guard re-asserts speaker-unmuted every 3s so a
# mute can never silently kill a recording again. Speaker only; never touches mic.
$src = @'
using System;
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int RegisterControlChangeNotify(IntPtr n);
  int UnregisterControlChangeNotify(IntPtr n);
  int GetChannelCount(out int c);
  int SetMasterVolumeLevel(float l, Guid e);
  int SetMasterVolumeLevelScalar(float l, Guid e);
  int GetMasterVolumeLevel(out float l);
  int GetMasterVolumeLevelScalar(out float l);
  int SetChannelVolumeLevel(uint ch, float l, Guid e);
  int SetChannelVolumeLevelScalar(uint ch, float l, Guid e);
  int GetChannelVolumeLevel(uint ch, out float l);
  int GetChannelVolumeLevelScalar(uint ch, out float l);
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool m, Guid e);
  int GetMute(out bool m);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
  int Activate(ref Guid id, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o);
}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
  int NotImpl1();
  int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ep);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
public class NnSpk {
  static IAudioEndpointVolume Vol() {
    var en = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
    IMMDevice dev;
    Marshal.ThrowExceptionForHR(en.GetDefaultAudioEndpoint(0, 1, out dev));  // 0 = render/speaker
    Guid iid = typeof(IAudioEndpointVolume).GUID;
    object o;
    Marshal.ThrowExceptionForHR(dev.Activate(ref iid, 23, IntPtr.Zero, out o));
    return (IAudioEndpointVolume)o;
  }
  public static void Unmute() { Vol().SetMute(false, Guid.Empty); }
  public static bool IsMuted() { bool m; Vol().GetMute(out m); return m; }
}
'@
Add-Type -TypeDefinition $src -ErrorAction SilentlyContinue
$log = "E:\napco-nucleus\logs\speaker-guard.log"
"$(Get-Date -Format s) speaker-unmute-guard started" | Out-File $log -Append -Encoding utf8
while ($true) {
  try {
    if ([NnSpk]::IsMuted()) {
      [NnSpk]::Unmute()
      "$(Get-Date -Format s) speaker was MUTED -> unmuted" | Out-File $log -Append -Encoding utf8
    }
  } catch { }
  Start-Sleep -Seconds 3
}

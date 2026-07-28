param([switch]$Quiet)
# NAPCO Nucleus recording-safe audio state on MASTAN2.
#
# CRITICAL: on this machine, muting the SPEAKER endpoint SILENCES the
# WASAPI-loopback recording. A muted speaker produced ~46 minutes of silent
# recording on 2026-07-24. Therefore:
#   SPEAKER (render, flow 0)  -> UNMUTED  (must stay unmuted or we lose audio)
#   MIC     (capture, flow 1) -> MUTED    (NN has no voice; keeps the meeting
#                                          from hearing NN; does NOT affect the
#                                          speaker-loopback recording)
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
public class NnAudio {
  static IAudioEndpointVolume Vol(int flow) {
    var en = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
    IMMDevice dev;
    Marshal.ThrowExceptionForHR(en.GetDefaultAudioEndpoint(flow, 1, out dev));
    Guid iid = typeof(IAudioEndpointVolume).GUID;
    object o;
    Marshal.ThrowExceptionForHR(dev.Activate(ref iid, 23, IntPtr.Zero, out o));
    return (IAudioEndpointVolume)o;
  }
  public static void SetMute(int flow, bool m) { Marshal.ThrowExceptionForHR(Vol(flow).SetMute(m, Guid.Empty)); }
  public static bool GetMute(int flow) { bool m; Vol(flow).GetMute(out m); return m; }
}
'@
try { Add-Type -TypeDefinition $src -ErrorAction Stop } catch { }
try { [NnAudio]::SetMute(0, $false) } catch { if (-not $Quiet) { Write-Host "speaker unmute failed: $_" } }   # SPEAKER: UNMUTE
try { [NnAudio]::SetMute(1, $true) }  catch { if (-not $Quiet) { Write-Host "mic mute failed: $_" } }          # MIC: MUTE
try {
  $sp = [NnAudio]::GetMute(0); $mc = [NnAudio]::GetMute(1)
  if (-not $Quiet) { Write-Host ("speaker muted={0} (must be False)   mic muted={1} (should be True)" -f $sp, $mc) }
} catch { }

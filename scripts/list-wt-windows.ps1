# List every visible Windows Terminal window: HWND | pid | title (the focused pane's title).
# Pair with nudge-wt-pane.ps1. Read-only.
$code = @'
using System; using System.Text; using System.Runtime.InteropServices; using System.Collections.Generic;
public class W {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  public static List<string> List() { var o = new List<string>();
    EnumWindows((h,l)=>{ if(!IsWindowVisible(h)) return true; var c=new StringBuilder(256); GetClassName(h,c,256);
      if(c.ToString()!="CASCADIA_HOSTING_WINDOW_CLASS") return true; var t=new StringBuilder(512); GetWindowText(h,t,512); uint p; GetWindowThreadProcessId(h,out p);
      o.Add(h.ToInt64()+" | "+p+" | "+t.ToString()); return true;}, IntPtr.Zero); return o; } }
'@
Add-Type -TypeDefinition $code -ErrorAction Stop
[W]::List()

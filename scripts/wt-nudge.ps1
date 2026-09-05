# wt-nudge.ps1: wake an idle neuron pane in Windows Terminal by typing one prompt into it.
# Evidence: 2026-09-05 05:57-06:00Z, two relaunched grok panes at the welcome screen drained
# their inboxes within a minute of this exact method (docs/briefs/WIDGET.md, slice 5b).
#
#   list:    powershell -File scripts\wt-nudge.ps1 -List
#   dry:     powershell -File scripts\wt-nudge.ps1 -Root <thread root> -TitleMatch grok -DryRun
#   nudge:   powershell -File scripts\wt-nudge.ps1 -Root <thread root> -TitleMatch grok
#
# What it does, in order, and refuses otherwise:
#   1. finds ONE Windows Terminal window (class CASCADIA_HOSTING_WINDOW_CLASS) whose title
#      matches -TitleMatch and none of -Exclude; zero or several -> refuse.
#   2. takes the foreground with an Alt tap + AttachThreadInput + SetForegroundWindow
#      (a bare SetForegroundWindow from a background process is refused by Windows).
#   3. moves pane focus with Alt+Arrow (WT default move-focus), trying -Directions in order,
#      and VERIFIES by the window title, which is the focused pane's title: a busy grok pane
#      reads "Waiting for response..." or "Running: <tool>"; an idle one reads "grok".
#      It types only into a pane whose title matches -IdleTitle. Alt+Left from the leftmost
#      pane moves nothing, which is why the check is mandatory.
#   4. types ONE self-identifying prompt (whoami -> inbox --drain -> seated --token ->
#      inbox --wait as a background command) and Enter. Same text for every pane, so the
#      order cannot misfire. Never -p, never --resume, never a second session.
# Only on the machine that owns the panes, only for panes Convoy launched. Not for public MCP.
param(
  [switch]$List,
  [switch]$DryRun,
  [string]$Root = '',
  [string]$TitleMatch = 'grok',
  [string]$Exclude = 'convoy-wt-fable|luna',
  [string]$IdleTitle = '^grok$',
  [string[]]$Directions = @('none','%{RIGHT}','%{LEFT}'),
  [string]$Message = ''
)
$code = @'
using System; using System.Text; using System.Runtime.InteropServices; using System.Collections.Generic;
public class WtNudge {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
  public static string Title(IntPtr h){ var t=new StringBuilder(512); GetWindowText(h,t,512); return t.ToString(); }
  public static List<IntPtr> Wt(){ var o=new List<IntPtr>(); EnumWindows((h,l)=>{ if(!IsWindowVisible(h)) return true; var c=new StringBuilder(256); GetClassName(h,c,256); if(c.ToString()=="CASCADIA_HOSTING_WINDOW_CLASS") o.Add(h); return true;}, IntPtr.Zero); return o; }
  public static bool Focus(IntPtr h){ keybd_event(0x12,0,0,UIntPtr.Zero); keybd_event(0x12,0,2,UIntPtr.Zero);
    uint pid; uint tid = GetWindowThreadProcessId(h, out pid); uint me = GetCurrentThreadId();
    AttachThreadInput(me, tid, true); ShowWindow(h, 9); SetForegroundWindow(h); AttachThreadInput(me, tid, false);
    System.Threading.Thread.Sleep(400); return GetForegroundWindow()==h; } }
'@
Add-Type -TypeDefinition $code -ErrorAction Stop
Add-Type -AssemblyName System.Windows.Forms
$all = [WtNudge]::Wt()
if ($List) { $all | ForEach-Object { "{0} | {1}" -f $_.ToInt64(), [WtNudge]::Title($_) }; exit 0 }
if (-not $Root) { Write-Output "refuse: -Root <thread root> is required (the prompt names it)"; exit 4 }
$targets = @($all | Where-Object { $t=[WtNudge]::Title($_); ($t -match $TitleMatch) -and -not ($Exclude -and $t -match $Exclude) })
Write-Output ("candidates: " + (($targets | ForEach-Object { [WtNudge]::Title($_) }) -join ' || '))
if ($targets.Count -ne 1) { Write-Output "refuse: expected exactly one window matching '$TitleMatch', found $($targets.Count); nothing typed"; exit 3 }
$h = $targets[0]
if (-not $Message) {
  $Message = "You are a Convoy neuron relaunched after your pane died. Run: convoy --root $Root whoami  to learn your chair, then  convoy --root $Root inbox --drain --seat <your chair>  and act on every row, then ack with  convoy --root $Root seated --seat <your chair> --token <token from your join row in feed --since 6h>. At the end of every turn start  convoy --root $Root inbox --wait --seat <your chair>  as a background command."
}
if ($DryRun) { Write-Output ("dry-run: would focus '" + [WtNudge]::Title($h) + "', try directions " + ($Directions -join ',') + ", type only into a pane titled like '$IdleTitle'. Message: " + $Message); exit 0 }
$prev = [WtNudge]::GetForegroundWindow()
if (-not [WtNudge]::Focus($h)) { Write-Output "abort: could not take the foreground"; exit 2 }
$typed = $false
foreach ($dir in $Directions) {
  if ($dir -ne 'none') { [System.Windows.Forms.SendKeys]::SendWait($dir); Start-Sleep -Milliseconds 700 }
  $t = [WtNudge]::Title($h); Write-Output "after $dir title: $t"
  if ($t -match $IdleTitle) {
    [System.Windows.Forms.SendKeys]::SendWait($Message); Start-Sleep -Milliseconds 300; [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
    Write-Output ("nudged pane titled '$t' at " + (Get-Date).ToUniversalTime().ToString("o")); $typed = $true; break
  }
}
if (-not $typed) { Write-Output "abort: no pane matched the idle title '$IdleTitle'; nothing typed (busy panes are left alone)" }
Start-Sleep -Milliseconds 500; [WtNudge]::Focus($prev) | Out-Null
if (-not $typed) { exit 5 }

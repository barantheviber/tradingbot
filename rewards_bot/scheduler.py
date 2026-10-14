"""Daily automatic runs.

Windows: a Task Scheduler task that runs ``pythonw -m rewards_bot run
--once-per-day`` (no console window) every day at the configured time plus a
random delay, and again 15 minutes after logon. "Run as soon as possible
after a missed start" covers days the computer was off at that time;
--once-per-day makes the extra triggers no-ops once the day is done.

Other systems: prints a crontab line instead.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from .config import REPO_ROOT, Settings

TASK_NAME = "RewardsBot"


def windowless_python(executable: str) -> str:
    """pythonw.exe next to python.exe, when it exists (no console window)."""
    path = Path(executable)
    if path.name.lower() == "python.exe":
        candidate = path.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return executable


def task_xml(python_exe: str, workdir: str, start_time: str, random_delay_minutes: int,
             user_id: Optional[str] = None, today: Optional[date] = None) -> str:
    today = today or date.today()
    hour, minute = (int(p) for p in start_time.split(":"))
    user = f"<UserId>{escape(user_id)}</UserId>" if user_id else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Microsoft Rewards gunluk puan botu (python -m rewards_bot)</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{today.isoformat()}T{hour:02d}:{minute:02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <RandomDelay>PT{int(random_delay_minutes)}M</RandomDelay>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      {user}
      <Delay>PT15M</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <ExecutionTimeLimit>PT6H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python_exe)}</Command>
      <Arguments>-m rewards_bot run --once-per-day</Arguments>
      <WorkingDirectory>{escape(workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def crontab_line(python_exe: str, workdir: str, start_time: str) -> str:
    hour, minute = (int(p) for p in start_time.split(":"))
    return (f"{minute} {hour} * * * cd '{workdir}' && '{python_exe}' -m rewards_bot run "
            f"--once-per-day >/dev/null 2>&1")


def install_task(settings: Settings) -> int:
    workdir = str(REPO_ROOT)
    if sys.platform != "win32":
        print("Otomatik görev yalnızca Windows'ta kurulur. Linux/macOS için `crontab -e` ile "
              "şu satırı ekleyin:\n")
        print(crontab_line(sys.executable, workdir, settings.schedule_time))
        return 0
    user = None
    if os.environ.get("USERNAME"):
        domain = os.environ.get("USERDOMAIN")
        user = f"{domain}\\{os.environ['USERNAME']}" if domain else os.environ["USERNAME"]
    xml = task_xml(windowless_python(sys.executable), workdir, settings.schedule_time,
                   settings.schedule_random_delay_minutes, user_id=user)
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "rewards_bot_task.xml"
        xml_path.write_text(xml, encoding="utf-16")
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"],
            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Görev oluşturulamadı:\n{result.stdout}{result.stderr}")
        return 1
    print(f"Görev kuruldu: her gün {settings.schedule_time} civarında (en fazla "
          f"{settings.schedule_random_delay_minutes} dk gecikmeyle) ve oturum açtıktan "
          "15 dk sonra arka planda çalışır; gün içinde bir kez tamamlanınca tekrar çalışmaz.")
    return 0


def uninstall_task() -> int:
    if sys.platform != "win32":
        print("Windows dışında `crontab -e` ile eklediğiniz satırı silin.")
        return 0
    result = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                            capture_output=True, text=True)
    print(result.stdout or result.stderr)
    return result.returncode

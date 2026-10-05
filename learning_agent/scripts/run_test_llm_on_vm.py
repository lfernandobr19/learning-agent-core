#!/usr/bin/env python3
import paramiko
from pathlib import Path
PWD = "#Lalaloopsy5201."
ROOT = Path(__file__).resolve().parents[2]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("ravenna-vm", username="lfernando", password=PWD, timeout=15)
sftp = c.open_sftp()
sftp.put(str(ROOT / "learning_agent/scripts/test_llm_ollama.py"), "/tmp/test_llm_ollama.py")
sftp.close()
stdin, stdout, stderr = c.exec_command(
    "sudo docker cp /tmp/test_llm_ollama.py ravenna-backend:/tmp/test_llm_ollama.py && "
    "sudo docker exec ravenna-backend python3 /tmp/test_llm_ollama.py",
    timeout=300,
    get_pty=True,
)
stdin.write(PWD + "\n")
stdin.channel.shutdown_write()
print(stdout.read().decode("utf-8", errors="replace"))
c.close()

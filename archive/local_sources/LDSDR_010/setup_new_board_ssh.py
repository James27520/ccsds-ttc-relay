import os, subprocess, sys, time
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
PORT = "COM11"

if not os.path.exists(KEY):
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", KEY, "-N", "", "-C", "dsh"],
                   check=True, capture_output=True)
pub = open(KEY + ".pub", encoding="utf-8").read().strip()
print("公钥 (%d 字符): %s..." % (len(pub), pub[:50]))

sp = SerialPort(PORT, 115200)
time.sleep(0.4); sp.read()
sp.write("\r\n"); time.sleep(1.2)
b = sp.read().decode("ascii", "replace")
if "login:" in b:
    sp.write("root\r\n"); time.sleep(1.5); sp.read()
    sp.write("analog\r\n"); time.sleep(3.0); sp.read()
sp.write("stty -echo 2>/dev/null; export PS1='NB> '\r\n"); time.sleep(1.0); sp.read()


def cmd(c, wait=1.0):
    sp.write(c + "\r\n"); time.sleep(wait)
    t = sp.read().decode("ascii", "replace")
    return "\n".join(s.replace("NB>", "").strip() for s in t.splitlines()
                     if s.replace("NB>", "").strip() and s.strip() != c)


print("\n>>> 用 printf 分两段写（不加换行），最后补一个换行")
cmd("mkdir -p /root/.ssh && chmod 700 /root/.ssh && rm -f /root/.ssh/authorized_keys", 0.8)
half = len(pub) // 2
r1 = cmd("printf '%%s' '%s' > /root/.ssh/authorized_keys" % pub[:half], 0.8)
r2 = cmd("printf '%%s' '%s' >> /root/.ssh/authorized_keys" % pub[half:], 0.8)
cmd("echo >> /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys", 0.8)

print(">>> 校验：行数应为 1，字节数应为 %d" % (len(pub) + 1))
print("  " + cmd("wc -l -c /root/.ssh/authorized_keys", 0.8))
got = cmd("md5sum /root/.ssh/authorized_keys | cut -d' ' -f1", 0.8).strip()
import hashlib
want = hashlib.md5((pub + "\n").encode()).hexdigest()
print("  远端 md5 %s" % got)
print("  期望 md5 %s" % want)
print("  %s" % ("✅ 一致" if got == want else "❌ 不一致"))

print(">>> 检查 sshd 是否允许公钥登录")
print("  " + cmd("grep -iE 'PubkeyAuth|PermitRootLogin|AuthorizedKeysFile' "
                 "/etc/ssh/sshd_config 2>/dev/null | head -5", 1.0))
print("  " + cmd("ls -la /root/.ssh/", 0.8))
sp.close()

print("\n>>> 测试免密 SSH（BatchMode，失败立刻返回不挂住）")
r = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null",
                    "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                    "-o", "PreferredAuthentications=publickey",
                    "%s@%s" % (USER, BOARD), "uname -a; echo SSH_OK"],
                   capture_output=True, text=True, timeout=60)
print("  rc=%d" % r.returncode)
print("  out: %s" % r.stdout.strip()[:300])
if r.stderr.strip():
    print("  err: %s" % r.stderr.strip()[:400])

"""GNS3 operations through an explicitly configured temporary Proxmox SSH session.

Only the selected guest is addressed. No account, key, permission, VM or service
is changed. Each operation has a private guest journal for observed progress.
"""

import base64
import json
import shlex
import subprocess
import time
import uuid
import zlib

from .gns3 import GNS3SSH
from .gns3_render import native_graph
from .workshop import validate_plan


class GNS3QGA(GNS3SSH):
    def __init__(self, host, user="root", control=None, *, guest_id=110, **kwargs):
        super().__init__(host, user, control, **kwargs)
        if type(guest_id) is not int or not 100 <= guest_id <= 999999999:
            raise ValueError("Invalid GNS3 VM identifier")
        self.guest_id = guest_id

    def connection(self):
        return dict(super().connection(), transport="qga", guest_id=self.guest_id)

    def ssh_json(self, command, stdin=None, timeout=45):
        args = self.ssh_args()
        if self.batch:
            args[1:1] = ["-o", "BatchMode=yes"]
        try:
            run = subprocess.run(
                args + [command],
                # Never let background SSH status polls consume the user's terminal input.
                input=stdin if stdin is not None else "",
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "The Proxmox session did not respond; the operation may still be running."
            ) from None
        if run.returncode:
            raise RuntimeError(
                "The temporary administrative session is unavailable or the GNS3 guest agent did not respond."
            )
        try:
            return json.loads(run.stdout)
        except ValueError:
            raise RuntimeError(
                "Unrecognized guest agent response; the operation was not repeated."
            ) from None

    def guest_start(self, code, payload=None, tag=None):
        wire = (
            "import base64,zlib;exec(compile(zlib.decompress(base64.b64decode("
            + repr(base64.b64encode(zlib.compress(code.encode())).decode())
            + ')),"<nlf-qga>","exec"))'
        )
        args = ["qm", "guest", "exec", str(self.guest_id), "--synchronous", "0"]
        if payload is not None:
            args += ["--pass-stdin", "1"]
        args += ["--", "/opt/gns3/venv/bin/python", "-c", wire]
        if tag:
            args.append(tag)
        return self.ssh_json(shlex.join(args), json.dumps(payload) if payload is not None else None)

    def guest_status(self, pid):
        return self.ssh_json(
            shlex.join(["qm", "guest", "exec-status", str(self.guest_id), str(int(pid))])
        )

    def guest_read(self, code, payload=None):
        r = self.guest_start(code, payload)
        pid = r.get("pid")
        if pid is None and "exitcode" not in r:
            raise RuntimeError(
                "The guest agent did not confirm the query; it will not be repeated."
            )
        deadline = time.monotonic() + 40
        while "exitcode" not in r:
            if time.monotonic() > deadline:
                raise RuntimeError("The GNS3 query is still pending; it will not be repeated.")
            time.sleep(0.15)
            r = self.guest_status(pid)
        if r["exitcode"]:
            raise RuntimeError("Could not read the private state of this GNS3 operation.")
        return json.loads(r.get("out-data", "{}"))

    def read_journal(self, job, offset):
        code = """import json,pathlib
p=json.load(__import__('sys').stdin); f=pathlib.Path(p['job'])/'events.jsonl'
if not f.exists(): print(json.dumps({'offset':p['offset'],'events':[]}))
else:
 with f.open() as stream:
  stream.seek(p['offset']);events=[]
  while True:
   pos=stream.tell();line=stream.readline()
   if not line or not line.endswith('\\n'):stream.seek(pos);break
   events.append(json.loads(line))
  print(json.dumps({'offset':stream.tell(),'events':events}))
"""
        return self.guest_read(code, {"job": job, "offset": offset})

    def cancel_job(self, job, pid, tag):
        code = """import json,os,pathlib,signal,sys
p=json.load(sys.stdin); marker=pathlib.Path(p['job'])/'pid'
if marker.exists() and int(marker.read_text())==p['pid']:
 cmd=pathlib.Path('/proc')/str(p['pid'])/'cmdline'
 if cmd.exists() and p['tag'].encode() in cmd.read_bytes().split(b'\\0'):
  os.kill(p['pid'],signal.SIGTERM)
print(json.dumps({'cancel_requested':True}))
"""
        self.guest_read(code, {"job": job, "pid": pid, "tag": tag})

    def run(self, action, callback=None, **values):
        if "plan" in values:
            validate_plan(values["plan"])
            if values["plan"].get("backend") != "gns3":
                raise ValueError("The recipe belongs to another platform")
        if self.cancel and self.cancel.is_set():
            raise RuntimeError("Operation cancelled")
        if action == "deploy":
            values["graph"] = native_graph(values["plan"])
        tag = "nlf-qa-" + str(uuid.uuid4())
        job = "/tmp/" + tag
        payload = {"action": action, "auth_file": self.auth_file, **values}
        code = """import json,os,pathlib,sys,threading,traceback
request=json.load(sys.stdin)
job=pathlib.Path(request['job']);job.mkdir(mode=0o700)
(job/'pid').write_text(str(os.getpid()))
ns={'__name__':'nlf_guest_worker'}
exec(compile(request['source'],'<nlf-worker>','exec'),ns)
lock=threading.Lock()
def emit(kind,**values):
 with lock:
  with (job/'events.jsonl').open('a') as stream:
   stream.write(json.dumps({'event':kind,**values})+'\\n');stream.flush()
ns['emit']=emit
try:ns['gns3_main'](request['payload'])
except Exception as exc:
 emit('error',message=str(exc),status='incomplete');sys.exit(1)
"""
        started = self.guest_start(
            code, {"job": job, "source": self.worker_source(), "payload": payload}, tag
        )
        pid = started.get("pid")
        if pid is None:
            raise RuntimeError(
                "The guest agent did not confirm the process; check GNS3 before retrying."
            )
        if callback:
            callback({"event": "operation", "guest_id": self.guest_id, "pid": pid, "journal": job})
        deadline = time.monotonic() + (
            {"deploy": 3600, "verify": 1800, "stop": 600}.get(action, 120)
        )
        offset = 0
        events = []
        while True:
            status = self.guest_status(pid)
            update = self.read_journal(job, offset)
            offset = update["offset"]
            for event in update["events"]:
                events.append(event)
                if callback:
                    callback(event)
            if "exitcode" in status:
                break
            if self.cancel and self.cancel.is_set():
                self.cancel_job(job, pid, tag)
                raise RuntimeError(
                    "Operation interrupted; the project and partial record are preserved."
                )
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"The GNS3 operation is still pending (VM {self.guest_id}, PID {pid}). Do not repeat it; check its record at {job}."
                )
            time.sleep(2)
        if status["exitcode"] or not events or events[-1].get("event") == "error":
            raise RuntimeError(
                next(
                    (e["message"] for e in reversed(events) if e.get("event") == "error"),
                    "The guest agent exited without confirming the result.",
                )
            )
        return events[-1]

    def open_console(self, plan, node_name):
        """Interactive terminal relay through QGA; opens no public listening port."""
        import os
        import select
        import sys
        import termios
        import tty

        validate_plan(plan)
        if plan.get("backend") != "gns3" or node_name not in {n["name"] for n in plan["nodes"]}:
            raise ValueError("Console does not belong to the recipe")
        if not sys.stdin.isatty():
            raise RuntimeError("The interactive console requires a terminal.")
        tag = "nlf-console-" + str(uuid.uuid4())
        job = "/tmp/" + tag
        code = """import fcntl,json,os,pathlib,sys,time
import pexpect
r=json.load(sys.stdin);job=pathlib.Path(r['job']);job.mkdir(mode=0o700)
(job/'pid').write_text(str(os.getpid()));(job/'input.bin').touch();(job/'output.bin').touch()
child=None
try:
 ns={'__name__':'nlf_console'};exec(compile(r['source'],'<nlf-console>','exec'),ns)
 ns['api']=ns['GNS3API'](r['auth_file']);ns['identity'](r['plan'])
 ports=ns['current_ports'](r['plan']);node=next(n for n in r['plan']['nodes'] if n['name']==r['node'])
 child=ns['node_console'](node,ports[r['node']]);deadline=time.monotonic()+1200
 with (job/'output.bin').open('ab') as output:
  output.write(str(child.after).encode());output.flush()
  while time.monotonic()<deadline and not (job/'close').exists():
   with (job/'input.bin').open('r+b') as inputs:
    fcntl.flock(inputs,fcntl.LOCK_EX);data=inputs.read();inputs.seek(0);inputs.truncate()
   if data:child.send(data.decode('utf-8',errors='replace'))
   try:
    text=child.read_nonblocking(8192,timeout=.1);output.write(text.encode());output.flush()
   except pexpect.TIMEOUT:pass
   except pexpect.EOF:break
except Exception as exc:
 with (job/'output.bin').open('ab') as output:output.write(('\\r\\nConsole closed: '+str(exc)+'\\r\\n').encode())
finally:
 if child:child.close()
 (job/'closed').touch()
"""
        started = self.guest_start(
            code,
            {
                "source": self.worker_source(),
                "plan": plan,
                "node": node_name,
                "job": job,
                "auth_file": self.auth_file,
            },
            tag,
        )
        pid = started["pid"]
        offset = 0
        exchange = """import base64,fcntl,json,pathlib,sys
r=json.load(sys.stdin);job=pathlib.Path(r['job']);f=job/'output.bin'
if r['data'] and (job/'input.bin').exists():
 with (job/'input.bin').open('ab') as inputs:
  fcntl.flock(inputs,fcntl.LOCK_EX);inputs.write(base64.b64decode(r['data']))
if r['close'] and job.exists():(job/'close').touch()
text=b''
if f.exists():
 with f.open('rb') as output:output.seek(r['offset']);text=output.read(65536)
print(json.dumps({'data':base64.b64encode(text).decode(),'offset':r['offset']+len(text),'closed':(job/'closed').exists()}))
"""
        print(
            "Console " + node_name + " · Ctrl+] to return. The session closes after 20 minutes.",
            flush=True,
        )
        fd = sys.stdin.fileno()
        before = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                data = os.read(fd, 4096) if select.select([fd], [], [], 0.15)[0] else b""
                closing = b"\x1d" in data
                if closing:
                    data = data.split(b"\x1d")[0]
                response = self.guest_read(
                    exchange,
                    {
                        "job": job,
                        "offset": offset,
                        "data": base64.b64encode(data).decode(),
                        "close": closing,
                    },
                )
                offset = response["offset"]
                os.write(sys.stdout.fileno(), base64.b64decode(response["data"]))
                if closing or response["closed"]:
                    break
                status = self.guest_status(pid)
                if "exitcode" in status:
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, before)
            try:
                self.cancel_job(job, pid, tag)
                cleanup = "import json,pathlib,shutil,sys;r=json.load(sys.stdin);p=pathlib.Path(r['job']);shutil.rmtree(p,ignore_errors=True);print('{}')"
                self.guest_read(cleanup, {"job": job})
            finally:
                print("\nConsole closed.", flush=True)

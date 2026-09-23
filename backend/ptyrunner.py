import os
import pty
import select
import signal
import sys


class PtySession:
    def __init__(self, code, cwd):
        self.code = code
        self.cwd = str(cwd)
        self.pid = None
        self.master_fd = None
        self.stop_deadline = None
        self._exit = None

    def start(self):
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "TERM": "xterm-256color"}
        pid, master_fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(self.cwd)
                os.execve(sys.executable, [sys.executable, "-u", "-c", self.code], env)
            except BaseException:
                os._exit(127)
        self.pid = pid
        self.master_fd = master_fd

    def alive(self):
        return self.poll() is None

    def poll(self):
        if self.pid is None:
            return self._exit
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return self._exit
        if pid == 0:
            return None
        if os.WIFEXITED(status):
            self._exit = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            self._exit = -os.WTERMSIG(status)
        else:
            self._exit = None
        return self._exit

    def read(self, timeout):
        if self.master_fd is None:
            return b""
        try:
            ready, _, _ = select.select([self.master_fd], [], [], timeout)
        except (OSError, ValueError):
            return b""
        if not ready:
            return None
        try:
            return os.read(self.master_fd, 65536)
        except OSError:
            return b""

    def write(self, data):
        if self.master_fd is None or not self.alive():
            return False
        try:
            os.write(self.master_fd, data.encode("utf-8"))
            return True
        except OSError:
            return False

    def kill(self):
        if self.pid is not None and self.alive():
            try:
                os.kill(self.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def close(self):
        self.kill()
        if self.pid is not None:
            try:
                pid, status = os.waitpid(self.pid, 0)
                if os.WIFEXITED(status):
                    self._exit = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    self._exit = -os.WTERMSIG(status)
            except ChildProcessError:
                pass
            self.pid = None
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

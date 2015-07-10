#    Copyright 2015 ARM Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import sys
import subprocess
import time

from Queue import Queue, Empty
from threading import Thread
from subprocess import Popen, PIPE


class OutputPollingThread(Thread):

    def __init__(self, out, queue, name):
        super(OutputPollingThread, self).__init__()
        self.out = out
        self.queue = queue
        self.stop_signal = False
        self.name = name

    def run(self):
        for line in iter(self.out.readline, ''):
            if self.stop_signal:
                break
            self.queue.put(line)

    def set_stop(self):
        self.stop_signal = True


class CrosSdkSession(object):

    def __init__(self, cros_path):
        self.in_chroot = False if subprocess.call('which dut-control', stdout=subprocess.PIPE, shell=True) else True
        ON_POSIX = 'posix' in sys.builtin_module_names
        if self.in_chroot:
            self.cros_sdk_session = Popen(['/bin/bash'], bufsize=1, stdin=PIPE, stdout=PIPE, stderr=PIPE,
                                          cwd=cros_path, close_fds=ON_POSIX, shell=True)
        else:
            self.cros_sdk_session = Popen(['cros_sdk'], bufsize=1, stdin=PIPE, stdout=PIPE, stderr=PIPE,
                                          cwd=cros_path, close_fds=ON_POSIX, shell=True)
        self.stdout_queue = Queue()
        self.stdout_thread = OutputPollingThread(self.cros_sdk_session.stdout, self.stdout_queue, 'stdout')
        self.stdout_thread.daemon = True
        self.stdout_thread.start()
        self.stderr_queue = Queue()
        self.stderr_thread = OutputPollingThread(self.cros_sdk_session.stderr, self.stderr_queue, 'stderr')
        self.stderr_thread.daemon = True
        self.stderr_thread.start()

    def kill_session(self):
        self.stdout_thread.set_stop()
        self.stderr_thread.set_stop()
        self.send_command('echo foo >&1')  # send something into stdout to unblock it and close it properly
        self.send_command('echo foo 1>&2')  # ditto for stderr
        self.stdout_thread.join()
        self.stderr_thread.join()
        self.cros_sdk_session.kill()

    def send_command(self, cmd, flush=True):
        if not cmd.endswith('\n'):
            cmd = cmd + '\n'
        self.cros_sdk_session.stdin.write(cmd)
        if flush:
            self.cros_sdk_session.stdin.flush()

    def read_line(self, timeout_in_ms=0):
        return _read_line_from_queue(self.stdout_queue, timeout_in_ms=timeout_in_ms)

    def read_stderr_line(self, timeout_in_ms=0):
        return _read_line_from_queue(self.stderr_queue, timeout_in_ms=timeout_in_ms)

    def get_lines(self, timeout_in_ms=0, timeout_only_for_first_line=True, from_stderr=False):
        lines = []
        line = True
        while line is not None:
            if from_stderr:
                line = self.read_stderr_line(timeout_in_ms)
            else:
                line = self.read_line(timeout_in_ms)
            if line:
                lines.append(line)
                if timeout_in_ms and timeout_only_for_first_line:
                    timeout_in_ms = 0  # after a line has been read, no further delay is required
        return lines

def _read_line_from_queue(queue, timeout_in_ms=0):
    try:
        line = queue.get_nowait()
    except Empty:
        line = None
    if line is None and timeout_in_ms:
        sleep_time = timeout_in_ms / 1000.0
        time.sleep(sleep_time)
        try:
            line = queue.get_nowait()
        except Empty:
            line = None
    if line is not None:
        line = line.strip('\n')
    return line

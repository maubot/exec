# exec - A maubot plugin to execute code.
# Copyright (C) 2019 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from typing import Dict, Any, Optional, Tuple, AsyncGenerator, Type, NamedTuple
from types import TracebackType
from io import IOBase, StringIO
import contextlib
import traceback
import asyncio
import ast
import sys

from mautrix.util.manhole import asyncify

from .base import Runner, OutputType, AsyncTextOutput


class SyncTextProxy(AsyncTextOutput):
    writers: Dict[OutputType, 'ProxyWriter']

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        super().__init__(loop)
        self.writers = {}

    def close(self) -> None:
        for proxy in self.writers.values():
            proxy.close(_stp=True)
        super().close()

    def get_writer(self, output_type: OutputType) -> 'ProxyWriter':
        try:
            return self.writers[output_type]
        except KeyError:
            self.writers[output_type] = proxy = ProxyWriter(output_type, self)
            return proxy


class ProxyWriter(IOBase):
    type: OutputType
    stp: SyncTextProxy

    def __init__(self, output_type: OutputType, stp: SyncTextProxy) -> None:
        self.type = output_type
        self.stp = stp

    def write(self, data: str) -> None:
        """Write to the stdout queue"""
        self.stp.queue.put_nowait((self.type, data))

    def writable(self) -> bool:
        return True

    def close(self, _stp: bool = False) -> None:
        super().close()
        if not _stp:
            self.stp.close()


ExcInfo = NamedTuple('ExcInfo', type=Type[BaseException], exc=Exception, tb=TracebackType)


class PythonRunner(Runner):
    namespace: Dict[str, Any]
    per_run_namespace: bool

    def __init__(self, namespace: Optional[Dict[str, Any]] = None, per_run_namespace: bool = True
                 ) -> None:
        self.namespace = namespace or {}
        self.per_run_namespace = per_run_namespace

    @staticmethod
    async def _wait_task(namespace: Dict[str, Any], stdio: SyncTextProxy) -> str:
        try:
            value = await eval("__eval_async_expr()", namespace)
        finally:
            stdio.close()
        return value

    @contextlib.contextmanager
    def _redirect_io(self, output: SyncTextProxy, stdin: StringIO) -> SyncTextProxy:
        old_stdout, old_stderr, old_stdin = sys.stdout, sys.stderr, sys.stdin
        sys.stdout = output.get_writer(OutputType.STDOUT)
        sys.stderr = output.get_writer(OutputType.STDERR)
        sys.stdin = stdin
        try:
            yield output
        finally:
            sys.stdout, sys.stderr, sys.stdin = old_stdout, old_stderr, old_stdin

    @staticmethod
    def _format_exc(exception: Exception) -> str:
        if len(exception.args) == 0:
            return type(exception).__name__
        elif len(exception.args) == 1:
            return f"{type(exception).__name__}: {exception.args[0]}"
        else:
            return f"{type(exception).__name__}: {exception.args}"

    def format_exception(self, exc_info: ExcInfo) -> Tuple[Optional[str], Optional[str]]:
        if not exc_info:
            return None, None
        tb = traceback.extract_tb(exc_info.tb)

        line: traceback.FrameSummary
        for i, line in enumerate(tb):
            if line.filename == "<input>":
                line.name = "<module>"
                tb = tb[i:]
                break

        return ("Traceback (most recent call last):",
                f"{''.join(traceback.format_list(tb))}"
                f"{self._format_exc(exc_info.exc)}")

    async def run(self, code: str, stdin: str = "", loop: Optional[asyncio.AbstractEventLoop] = None
                  ) -> AsyncGenerator[Tuple[OutputType, Any], None]:
        loop = loop or asyncio.get_event_loop()
        codeobj = asyncify(compile(code, "<input>", "exec", optimize=1, flags=ast.PyCF_ONLY_AST),
                           module="<input>")
        namespace = {**self.namespace} if self.per_run_namespace else self.namespace
        exec(codeobj, namespace)
        with self._redirect_io(SyncTextProxy(loop), StringIO(stdin)) as output:
            task = asyncio.ensure_future(self._wait_task(namespace, output), loop=loop)
            async for part in output:
                yield part
            try:
                return_value = await task
            except Exception:
                yield (OutputType.EXCEPTION, ExcInfo(*sys.exc_info()))
            else:
                yield (OutputType.RETURN, return_value)

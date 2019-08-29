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
from typing import Dict, Any, Optional, AsyncGenerator
from io import IOBase, StringIO
import contextlib
import asyncio
import ast
import sys

from mautrix.util.manhole import asyncify

from .base import Runner, OutputType


class AsyncTextOutput:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    writers: Dict[OutputType, 'ProxyOutput']
    read_task: Optional[asyncio.Future]
    closed: bool

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.loop = loop or asyncio.get_event_loop()
        self.read_task = None
        self.queue = asyncio.Queue(loop=self.loop)
        self.closed = False
        self.writers = {}

    def __aiter__(self) -> 'AsyncTextOutput':
        return self

    async def __anext__(self) -> str:
        if self.closed:
            raise StopAsyncIteration
        self.read_task = asyncio.ensure_future(self.queue.get(), loop=self.loop)
        try:
            data = await self.read_task
        except asyncio.CancelledError:
            raise StopAsyncIteration
        self.queue.task_done()
        return data

    def close(self) -> None:
        self.closed = True
        for proxy in self.writers.values():
            proxy.close(_ato=True)
        if self.read_task:
            self.read_task.cancel()

    def get_writer(self, output_type: OutputType) -> 'ProxyOutput':
        try:
            return self.writers[output_type]
        except KeyError:
            self.writers[output_type] = proxy = ProxyOutput(output_type, self)
            return proxy


class ProxyOutput(IOBase):
    type: OutputType
    ato: AsyncTextOutput

    def __init__(self, output_type: OutputType, ato: AsyncTextOutput) -> None:
        self.type = output_type
        self.ato = ato

    def write(self, data: str) -> None:
        """Write to the stdout queue"""
        self.ato.queue.put_nowait((self.type, data))

    def writable(self) -> bool:
        return True

    def close(self, _ato: bool = False) -> None:
        super().close()
        if not _ato:
            self.ato.close()


class PythonRunner(Runner):
    namespace: Dict[str, Any]

    def __init__(self, namespace: Optional[Dict[str, Any]] = None) -> None:
        self.namespace = namespace or {}

    async def _run_task(self, stdio: AsyncTextOutput) -> str:
        value = await eval("__eval_async_expr()", self.namespace)
        stdio.close()
        return value

    @contextlib.contextmanager
    def _redirect_io(self, output: AsyncTextOutput, stdin: StringIO) -> AsyncTextOutput:
        old_stdout, old_stderr, old_stdin = sys.stdout, sys.stderr, sys.stdin
        sys.stdout = output.get_writer(OutputType.STDOUT)
        sys.stderr = output.get_writer(OutputType.STDERR)
        sys.stdin = stdin
        yield output
        sys.stdout, sys.stderr, sys.stdin = old_stdout, old_stderr, old_stdin

    async def run(self, code: str, stdin: str = "") -> AsyncGenerator[str, None]:
        codeobj = asyncify(compile(code, "<input>", "exec", optimize=1, flags=ast.PyCF_ONLY_AST))
        exec(codeobj, self.namespace)
        with self._redirect_io(AsyncTextOutput(), StringIO(stdin)) as output:
            task = asyncio.ensure_future(self._run_task(output))
            async for part in output:
                yield part
            return_value = await task
            yield (OutputType.RETURN, return_value)

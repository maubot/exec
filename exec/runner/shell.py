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
from typing import AsyncGenerator, Tuple, Optional, Dict, Union, Any
import asyncio

from .base import Runner, OutputType, AsyncTextOutput


class AsyncTextProxy(AsyncTextOutput):
    proxies: Dict[OutputType, 'StreamProxy']

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        super().__init__(loop)
        self.proxies = {}

    def get_proxy(self, type: OutputType, stream: asyncio.StreamReader) -> 'StreamProxy':
        try:
            return self.proxies[type]
        except KeyError:
            self.proxies[type] = proxy = StreamProxy(type, self, stream, self.loop)
            return proxy

    def close(self) -> None:
        for proxy in self.proxies.values():
            proxy.stop()
        super().close()


class StreamProxy:
    type: OutputType
    atp: AsyncTextProxy
    input: asyncio.StreamReader
    loop: asyncio.AbstractEventLoop
    proxy_task: Optional[asyncio.Future]

    def __init__(self, output_type: OutputType, atp: AsyncTextProxy, input: asyncio.StreamReader,
                 loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.type = output_type
        self.atp = atp
        self.input = input
        self.loop = loop or asyncio.get_event_loop()
        self.proxy_task = None

    def start(self) -> None:
        if self.proxy_task and not self.proxy_task.done():
            raise RuntimeError("Can't re-start running proxy")
        self.proxy_task = asyncio.ensure_future(self._proxy(), loop=self.loop)

    def stop(self) -> None:
        self.proxy_task.cancel()

    async def _proxy(self) -> None:
        while not self.input.at_eof():
            data = await self.input.readline()
            if data:
                await self.atp.queue.put((self.type, data.decode("utf-8")))


class ShellRunner(Runner):
    @staticmethod
    async def _wait_proc(proc: asyncio.subprocess.Process, output: AsyncTextProxy) -> int:
        resp = await proc.wait()
        output.close()
        return resp

    async def run(self, code: str, stdin: str = "", loop: Optional[asyncio.AbstractEventLoop] = None
                  ) -> AsyncGenerator[Tuple[OutputType, Union[str, int]], None]:
        loop = loop or asyncio.get_event_loop()
        output = AsyncTextProxy()
        proc = await asyncio.create_subprocess_shell(code, loop=loop,
                                                     stdin=asyncio.subprocess.PIPE,
                                                     stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.PIPE)
        output.get_proxy(OutputType.STDOUT, proc.stdout).start()
        output.get_proxy(OutputType.STDERR, proc.stderr).start()
        proc.stdin.write(stdin.encode("utf-8"))
        proc.stdin.write_eof()
        waiter = asyncio.ensure_future(self._wait_proc(proc, output), loop=loop)
        async for part in output:
            yield part
        yield (OutputType.RETURN, await waiter)

    def format_exception(self, exc_info: Any) -> Tuple[Optional[str], Optional[str]]:
        # The user input never returns exceptions in run()
        return None, None

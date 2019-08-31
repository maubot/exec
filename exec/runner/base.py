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
from typing import AsyncGenerator, Tuple, Optional, Any
from asyncio import AbstractEventLoop, Queue, Future, get_event_loop, ensure_future, CancelledError
from abc import ABC, abstractmethod
from enum import Enum, auto


class OutputType(Enum):
    STDOUT = auto()
    STDERR = auto()
    RETURN = auto()
    EXCEPTION = auto()


class AsyncTextOutput:
    loop: AbstractEventLoop
    queue: Queue
    read_task: Optional[Future]
    closed: bool

    def __init__(self, loop: Optional[AbstractEventLoop] = None) -> None:
        self.loop = loop or get_event_loop()
        self.read_task = None
        self.queue = Queue(loop=self.loop)
        self.closed = False

    def __aiter__(self) -> 'AsyncTextOutput':
        return self

    async def __anext__(self) -> str:
        if self.closed and self.queue.empty():
            raise StopAsyncIteration
        self.read_task = ensure_future(self.queue.get(), loop=self.loop)
        try:
            data = await self.read_task
        except CancelledError:
            raise StopAsyncIteration
        self.queue.task_done()
        return data

    def close(self) -> None:
        self.closed = True
        if self.read_task and self.queue.empty():
            self.read_task.cancel()


class Runner(ABC):
    @abstractmethod
    async def run(self, code: str, stdin: str = "", loop: Optional[AbstractEventLoop] = None
                  ) -> AsyncGenerator[Tuple[OutputType, Any], None]:
        pass

    @abstractmethod
    def format_exception(self, exc_info: Any) -> Tuple[Optional[str], Optional[str]]:
        pass

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
from typing import AsyncGenerator
from abc import ABC, abstractmethod
from enum import Enum, auto


class OutputType(Enum):
    STDOUT = auto()
    STDERR = auto()
    RETURN = auto()


class Runner(ABC):
    @abstractmethod
    async def run(self, code: str, stdin: str = "") -> AsyncGenerator[str, None]:
        pass

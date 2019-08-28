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
from typing import Type, Set, Optional, Any
from io import StringIO
from time import time

from mautrix.types import EventType, UserID
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from mautrix.util.formatter import MatrixParser, EntityString, SimpleEntity, EntityType
from maubot import Plugin, MessageEvent
from maubot.handlers import event

from .runner import PythonRunner, OutputType


class EntityParser(MatrixParser[EntityString]):
    fs = EntityString[SimpleEntity, EntityType]


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("prefix")
        helper.copy("userbot")
        helper.copy("whitelist")


class ExecBot(Plugin):
    whitelist: Set[UserID]
    userbot: bool
    prefix: str

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config

    async def start(self) -> None:
        self.on_external_config_update()

    def on_external_config_update(self) -> None:
        self.config.load_and_update()
        self.whitelist = set(self.config["whitelist"])
        self.userbot = self.config["userbot"]
        self.prefix = self.config["prefix"]

    @event.on(EventType.ROOM_MESSAGE)
    async def exec(self, evt: MessageEvent) -> None:
        if evt.sender not in self.whitelist:
            return
        elif not evt.content.body.startswith(self.prefix):
            return
        elif not evt.content.formatted_body:
            return

        command = EntityParser.parse(evt.content.formatted_body)
        entity: SimpleEntity
        code: Optional[str] = None
        lang: Optional[str] = None
        stdin: str = ""
        for entity in command.entities:
            if entity.type != EntityType.PREFORMATTED:
                continue
            current_lang = entity.extra_info["language"]
            value = command.text[entity.offset:entity.offset+entity.length]
            if not code:
                code = value
                lang = current_lang
            elif lang == "stdin":
                stdin += value
        if not code or not lang:
            return

        if lang != "python":
            await evt.respond("Only python is currently supported")
            return

        runner = PythonRunner()
        stdout = StringIO()
        stderr = StringIO()
        return_value: Any = None
        start_time = time()
        async for out_type, data in runner.run(code, stdin):
            if out_type == OutputType.STDOUT:
                stdout.write(data)
            elif out_type == OutputType.STDERR:
                stderr.write(data)
            elif out_type == OutputType.RETURN:
                return_value = data
        duration = time() - start_time

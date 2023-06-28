import logging
from datetime import datetime
from typing import Callable, Dict, List, Literal, Optional, Tuple, Union

import discord
import orjson
from openai.embeddings_utils import cosine_similarity
from pydantic import BaseModel
from redbot.core.bot import Red

from .common.utils import compile_function, num_tokens_from_string

log = logging.getLogger("red.vrt.assistant.models")

MODELS = {
    "gpt-3.5-turbo": 4096,
    "gpt-3.5-turbo-0613": 4096,
    "gpt-3.5-turbo-16k": 16384,
    "gpt-3.5-turbo-16k-0613": 16384,
    "gpt-4": 8192,
    "gpt-4-0613": 8192,
    "gpt-4-32k": 32768,
    "gpt-4-32k-0613": 32768,
    "code-davinci-002": 8001,
    "text-davinci-003": 4097,
    "text-davinci-002": 4097,
    "text-curie-001": 2049,
    "text-babbage-001": 2049,
    "text-ada-001": 2049,
}
CHAT = [
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-0613",
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo-16k-0613",
    "gpt-4",
    "gpt-4-0613",
    "gpt-4-32k",
    "gpt-4-32k-0613",
    "code-davinci-002",
]
COMPLETION = [
    "text-davinci-003",
    "text-davinci-002",
    "text-curie-001",
    "text-babbage-001",
    "text-ada-001",
]
READ_EXTENSIONS = [
    ".txt",
    ".py",
    ".json",
    ".yml",
    ".yaml",
    ".xml",
    ".html",
    ".ini",
    ".css",
    ".toml",
    ".md",
    ".ini",
    ".conf",
    ".go",
    ".cfg",
    ".java",
    ".c",
    ".php",
    ".swift",
    ".vb",
    ".xhtml",
    ".rss",
    ".css",
    ".asp",
    ".js",
    ".ts",
    ".cs",
    ".c++",
    ".cc",
    ".ps1",
    ".bat",
    ".batch",
    ".shell",
]


class Embedding(BaseModel):
    text: str
    embedding: List[float]

    class Config:
        json_loads = orjson.loads
        json_dumps = orjson.dumps


class CustomFunction(BaseModel):
    """Functions added by bot owner via string"""

    code: str
    jsonschema: dict

    class Config:
        json_loads = orjson.loads
        json_dumps = orjson.dumps

    def prep(self) -> Callable:
        return compile_function(self.jsonschema["name"], self.code)


class GuildSettings(BaseModel):
    system_prompt: str = "You are a helpful discord assistant named {botname}"
    prompt: str = "Current time: {timestamp}\nDiscord server you are chatting in: {server}"
    embeddings: Dict[str, Embedding] = {}
    top_n: int = 3
    min_relatedness: float = 0.75
    embed_method: Literal["dynamic", "static", "hybrid"] = "dynamic"
    channel_id: int = 0
    api_key: str = ""
    endswith_questionmark: bool = False
    max_retention: int = 0
    max_retention_time: int = 1800
    max_tokens: int = 4000
    min_length: int = 7
    mention: bool = False
    enabled: bool = True
    model: str = "gpt-3.5-turbo"
    timezone: str = "UTC"
    temperature: float = 0.0
    regex_blacklist: List[str] = [r"^As an AI language model,"]
    blacklist: List[int] = []  # Channel/Role/User IDs
    block_failed_regex: bool = False

    max_token_role_override: Dict[int, int] = {}
    max_retention_role_override: Dict[int, int] = {}
    model_role_overrides: Dict[int, str] = {}
    max_time_role_override: Dict[int, int] = {}

    image_tools: bool = True
    image_size: Literal["256x256", "512x512", "1024x1024"] = "1024x1024"
    use_function_calls: bool = False
    max_function_calls: int = 10  # Max calls in a row
    disabled_functions: List[str] = []

    class Config:
        json_loads = orjson.loads
        json_dumps = orjson.dumps

    def get_related_embeddings(self, query_embedding: List[float]) -> List[Tuple[str, float]]:
        if not self.top_n or not query_embedding or not self.embeddings:
            return []
        strings_and_relatedness = [
            (name, i.text, cosine_similarity(query_embedding, i.embedding))
            for name, i in self.embeddings.items()
        ]
        strings_and_relatedness = [
            i for i in strings_and_relatedness if i[2] >= self.min_relatedness
        ]
        strings_and_relatedness.sort(key=lambda x: x[2], reverse=True)
        return strings_and_relatedness[: self.top_n]

    def get_user_model(self, member: Optional[discord.Member] = None) -> str:
        if not member or not self.model_role_overrides:
            return self.model
        sorted_roles = sorted(member.roles, reverse=True)
        for role in sorted_roles:
            if role.id in self.model_role_overrides:
                return self.model_role_overrides[role.id]
        return self.model

    def get_user_max_tokens(self, member: Optional[discord.Member] = None) -> int:
        if not member or not self.max_token_role_override:
            return self.max_tokens
        sorted_roles = sorted(member.roles, reverse=True)
        for role in sorted_roles:
            if role.id in self.max_token_role_override:
                return self.max_token_role_override[role.id]
        return self.max_tokens

    def get_user_max_retention(self, member: Optional[discord.Member] = None) -> int:
        if not member or not self.max_retention_role_override:
            return self.max_retention
        sorted_roles = sorted(member.roles, reverse=True)
        for role in sorted_roles:
            if role.id in self.max_retention_role_override:
                return self.max_retention_role_override[role.id]
        return self.max_retention

    def get_user_max_time(self, member: Optional[discord.Member] = None) -> int:
        if not member or not self.max_time_role_override:
            return self.max_retention_time
        sorted_roles = sorted(member.roles, reverse=True)
        for role in sorted_roles:
            if role.id in self.max_time_role_override:
                return self.max_time_role_override[role.id]
        return self.max_retention_time


class Conversation(BaseModel):
    messages: list[dict[str, str]] = []
    last_updated: float = 0.0

    class Config:
        json_loads = orjson.loads
        json_dumps = orjson.dumps

    def token_count(self) -> int:
        return num_tokens_from_string("".join(message["content"] for message in self.messages))

    def function_count(self) -> int:
        if not self.messages:
            return 0
        return sum(i["role"] == "function" for i in self.messages)

    def user_token_count(self, message: str = "") -> int:
        if not self.messages and not message:
            return 0
        content = [m["content"] for m in self.messages]
        messages = "".join(content)
        messages += message
        if not messages:
            return 0
        return num_tokens_from_string(messages)

    def conversation_token_count(self, conf: GuildSettings, message: str = "") -> int:
        initial = conf.system_prompt + conf.prompt + (message if isinstance(message, str) else "")
        return num_tokens_from_string(initial) + self.user_token_count(message)

    def is_expired(self, conf: GuildSettings, member: Optional[discord.Member] = None):
        if not conf.get_user_max_time(member):
            return False
        return (datetime.now().timestamp() - self.last_updated) > conf.get_user_max_time(member)

    def cleanup(self, conf: GuildSettings, member: Optional[discord.Member] = None):
        clear = [
            self.is_expired(conf, member),
            not conf.get_user_max_retention(member),
        ]
        if any(clear):
            self.messages.clear()
        elif conf.max_retention:
            self.messages = self.messages[-conf.get_user_max_retention(member) :]

    def reset(self):
        self.last_updated = datetime.now().timestamp()
        self.messages.clear()

    def overwrite(self, messages: List[dict]):
        self.reset()
        for i in messages:
            if i["role"] == "system":
                continue
            self.messages.append(i)

    def update_messages(self, message: str, role: str, name: str = None) -> None:
        """Update conversation cache

        Args:
            message (str): the message
            role (str): 'system', 'user' or 'assistant'
            name (str): the name of the bot or user
        """
        message = {"role": role, "content": message}
        if name:
            message["name"] = name
        self.messages.append(message)
        self.last_updated = datetime.now().timestamp()

    def prepare_chat(
        self, user_message: str, initial_prompt: str, system_prompt: str
    ) -> List[dict]:
        prepared = []
        if system_prompt:
            prepared.append({"role": "system", "content": system_prompt})
        if initial_prompt:
            prepared.append({"role": "user", "content": initial_prompt})
        prepared.extend(self.messages)
        user_message = {"role": "user", "content": user_message}
        prepared.append(user_message)
        self.messages.append(user_message)
        self.last_updated = datetime.now().timestamp()
        return prepared


class DB(BaseModel):
    configs: dict[int, GuildSettings] = {}
    conversations: dict[str, Conversation] = {}
    persistent_conversations: bool = False
    functions: Dict[str, CustomFunction] = {}

    class Config:
        json_loads = orjson.loads
        json_dumps = orjson.dumps

    def get_conf(self, guild: Union[discord.Guild, int]) -> GuildSettings:
        gid = guild if isinstance(guild, int) else guild.id

        if gid in self.configs:
            return self.configs[gid]

        self.configs[gid] = GuildSettings()
        return self.configs[gid]

<<<<<<< HEAD
    def get_conversation(self, member: discord.Member) -> Conversation:
        try:
            key = f"{member.id}{member.guild.id}"
        except AttributeError:
            key = f"{member.id}0"
=======
    def get_conversation(
        self,
        member_id: int,
        channel_id: int,
        guild_id: int,
    ) -> Conversation:
        key = f"{member_id}-{channel_id}-{guild_id}"
>>>>>>> main
        if key in self.conversations:
            return self.conversations[key]

        self.conversations[key] = Conversation()
        return self.conversations[key]

    def prep_functions(
        self, bot: Red, conf: GuildSettings, registry: Dict[str, Dict[str, dict]]
    ) -> Tuple[List[dict], Dict[str, Callable]]:
        """Prep custom and registry functions for use with the API

        Args:
            bot (Red): Red instance
            conf (GuildSettings): current guild settings
            registry (Dict[str, Dict[str, dict]]): 3rd party cog registry dict

        Returns:
            Tuple[List[dict], Dict[str, Callable]]: List of json function schemas and a dict mapping to their callables
        """
        function_calls = []
        function_map = {}

        # Prep bot owner functions first
        for function_name, func in self.functions.items():
            if func.jsonschema["name"] in conf.disabled_functions:
                continue
            function_calls.append(func.jsonschema)
            function_map[function_name] = func.prep()

        # Next prep registry functions
        for cog_name, function_schemas in registry.items():
            cog = bot.get_cog(cog_name)
            if not cog:
                continue
            for function_name, function_schema in function_schemas.items():
                if function_name in conf.disabled_functions:
                    continue
                if function_name in function_map:
                    continue
                function_obj = getattr(cog, function_name, None)
                if function_obj is None:
                    continue
                function_calls.append(function_schema)
                function_map[function_name] = function_obj

        return function_calls, function_map


class NoAPIKey(Exception):
    """OpenAI Key no set"""


class EmbeddingEntryExists(Exception):
    """Entry name for embedding exits"""

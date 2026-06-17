from __future__ import annotations
import json
from dataclasses import dataclass

@dataclass
class Config:
    jmap_url: str
    jmap_token: str
    mx_hostname: str
    catchall_address: str
    listen_addr: str
    listen_port: int
    cache_file: str

def load_config(path: str) -> Config:
    with open(path) as f:
        d = json.load(f)
    return Config(
        jmap_url=d["jmap_url"],
        jmap_token=d["jmap_token"],
        mx_hostname=d["mx_hostname"],
        catchall_address=d["catchall_address"],
        listen_addr=d["listen_addr"],
        listen_port=int(d["listen_port"]),
        cache_file=d["cache_file"],
    )

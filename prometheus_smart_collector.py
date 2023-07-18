#!/usr/bin/env python3

# Copyright 2023 James Geboski <jgeboski@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import aiofiles
import aiofiles.os
import asyncio
import click
import json
import logging
import os
import re
from typing import Dict, List, NamedTuple, Optional, Type, TypeAlias, TypeVar

Json: TypeAlias = Dict[str, "Json"] | List["Json"] | bool | float | int | str | None
JsonDict: TypeAlias = Dict[str, Json]
JsonList: TypeAlias = List[Json]
JLT = TypeVar("JLT", bool, float, int, str)

logger = logging.getLogger(__name__)


class Attribute(NamedTuple):
    name: str
    id: Optional[int] = None

    def __hash__(self) -> int:
        if self.id is not None:
            return hash(self.id)

        return hash(self.name or self.id)

    def __str__(self) -> str:
        return self.name


class Device(NamedTuple):
    name: str
    type: str
    protocol: str

    def __str__(self) -> str:
        return self.name


def await_async(async_func):
    def wrapper(*args, **kwargs):
        asyncio.run(async_func(*args, **kwargs))

    return wrapper


def get_json_path(json_obj: Json, path: Optional[str]) -> Optional[Json]:
    if path is None:
        return json_obj

    tokens = path.split(".")
    assert len(tokens) != 0
    for token in tokens:
        if not isinstance(json_obj, dict) or token not in json_obj:
            return None

        json_obj = json_obj[token]

    return json_obj


def get_json_literal(
    json_obj: Json,
    json_type: Type[JLT],
    path: Optional[str] = None,
) -> Optional[JLT]:
    json_literal = get_json_path(json_obj, path)
    return json_literal if isinstance(json_literal, json_type) else None


def get_json_dict(json_obj: Json, path: Optional[str] = None) -> JsonDict:
    json_dict = get_json_path(json_obj, path)
    return json_dict if isinstance(json_dict, dict) else {}


def get_json_list(json_obj: Json, path: Optional[str] = None) -> JsonList:
    json_list = get_json_path(json_obj, path)
    return json_list if isinstance(json_list, list) else []


async def smartctl(*args) -> JsonDict:
    command = ["smartctl", "--json", *args]
    proc = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        logger.error("Failed to execute %s", command)
        return {}

    return json.loads(stdout.decode("utf-8"))


async def gen_devices() -> List[Device]:
    devices: List[Device] = []
    scan_results = await smartctl("--scan")
    for raw_device in get_json_list(scan_results, "devices"):
        json_device = get_json_dict(raw_device)
        missing_fields = set(Device._fields) - set(json_device)
        if missing_fields:
            logger.error("Ignoring device with missing fields: %s", raw_device)
            continue

        device = Device(
            **{field: json_device[field] for field in Device._fields}  # type: ignore
        )
        logger.debug("Found %s device %s", device.type, device.name)
        devices.append(device)

    return devices


def get_sanitized_attr_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip())
    if sanitized.startswith("_"):
        sanitized = sanitized[1:]

    if sanitized.endswith("_"):
        sanitized = sanitized[:-1]

    assert sanitized, f"Empty attribute name after sanitizing: {name}"
    return sanitized


async def gen_devices_attrs(
    devices: List[Device],
) -> Dict[Device, Dict[Attribute, int]]:
    devices_attrs: Dict[Device, Dict[Attribute, int]] = {}
    device_results = await asyncio.gather(
        *(smartctl("--all", device.name) for device in devices)
    )
    for device, raw_info in zip(devices, device_results):
        device_attrs: Dict[Attribute, int] = {}
        for json_attr in get_json_list(raw_info, "ata_smart_attributes.table"):
            attr_id = get_json_literal(json_attr, int, "id")
            name = get_json_literal(json_attr, str, "name")
            if not name or not attr_id:
                continue

            value = get_json_literal(json_attr, int, "raw.value")
            if value is None:
                logger.warning(
                    "Non-integer value for %s on %s: %s", name, device, value
                )
                continue

            if name == "Temperature_Celsius":
                value &= 0xFFFFFFFF

            attr_name = get_sanitized_attr_name(name)
            attr = Attribute(name=attr_name, id=attr_id)
            device_attrs[attr] = value

        nvme_attrs = get_json_dict(raw_info, "nvme_smart_health_information_log")
        for name, json_value in nvme_attrs.items():
            if name == "temperature_sensors":
                continue

            value = get_json_literal(json_value, int)
            if value is None:
                logger.warning(
                    "Non-integer value for %s on %s: %s", name, device, value
                )
                continue

            attr_name = get_sanitized_attr_name(name)
            attr = Attribute(name=attr_name)
            device_attrs[attr] = value

        if device_attrs:
            devices_attrs[device] = device_attrs
        else:
            logger.warning("Skipping %s without attributes", device)

    return devices_attrs


def get_labels(device: Device, attr: Attribute) -> str:
    labels: Dict[str, str] = {
        "name": attr.name,
        "device": os.path.basename(device.name),
        "device_type": device.type,
        "device_protocol": device.protocol,
    }

    if attr.id is not None:
        labels["id"] = f"{attr.id}"

    return ",".join(
        f'{name}="{value}"'
        for name, value in sorted(labels.items(), key=lambda kv: kv[0])
    )


async def write_device_attrs(
    device_attrs: Dict[Device, Dict[Attribute, int]],
    file: str,
) -> None:
    metric_count = 0
    tmp_file = f"{file}.tmp"
    await aiofiles.os.makedirs(os.path.dirname(file), exist_ok=True)
    logger.debug("Temporarily writing metrics to %s", tmp_file)
    async with aiofiles.open(tmp_file, "w") as fp:
        for device, attrs in device_attrs.items():
            for attr, value in attrs.items():
                labels = get_labels(device, attr)
                await fp.write(f"smart_attr{{{labels}}} {float(value)}{os.linesep}")
                metric_count += 1

    logger.debug("Moving %s to specified path %s", tmp_file, file)
    await aiofiles.os.replace(tmp_file, file)
    logger.info("Wrote %s metrics to %s", metric_count, file)


@click.command(
    help="Tool for writing SMART data to a file for the Promtheus node exporter.",
)
@click.option(
    "--prom-file",
    "-f",
    help="Output file path for the prom file.",
    default="/var/lib/prometheus/node-exporter/smart.prom",
)
@click.option(
    "--verbose",
    "-v",
    help="Show verbose logging messages.",
    is_flag=True,
)
@await_async
async def main(prom_file: str, verbose: bool) -> None:
    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        level=logging.DEBUG if verbose else logging.INFO,
    )
    devices = await gen_devices()
    devices_attrs = await gen_devices_attrs(devices)
    await write_device_attrs(devices_attrs, prom_file)


if __name__ == "__main__":
    main()

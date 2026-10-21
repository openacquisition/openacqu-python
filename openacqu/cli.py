"""Command-line test harness for Open Acquisition probes.

The library is the product API; this CLI exists to exercise hardware features
during bring-up and verification.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from openacqu import ProbeTemp1, ProductNumber, __version__
from openacqu.chips.mcp9600 import AdcResolution, ThermocoupleType
from openacqu.transport.base import I2CBus

_ADC_BY_BITS = {
    18: AdcResolution.BITS_18,
    16: AdcResolution.BITS_16,
    14: AdcResolution.BITS_14,
    12: AdcResolution.BITS_12,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openacqu",
        description="Test harness for Open Acquisition probes (library-first API).",
    )
    parser.add_argument("--version", action="version", version=f"openacqu {__version__}")
    parser.add_argument(
        "--check-product",
        action="store_true",
        help="require GPIO expander product number to match the selected model",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show product number, EUI-48, and MCP9600 identity")

    sub.add_parser("product", help="read 8-bit product number from the GPIO expander")

    sub.add_parser("eui48", help="read factory EUI-48 from the EEPROM")

    led = sub.add_parser("led", help="control the RGB LED")
    led_sub = led.add_subparsers(dest="led_command", required=True)
    led_set = led_sub.add_parser("set", help="set raw PWM levels (0-255), no color profile")
    led_set.add_argument("red", type=int)
    led_set.add_argument("green", type=int)
    led_set.add_argument("blue", type=int)
    led_color = led_sub.add_parser(
        "color",
        help="set CSS name or #rrggbb via LED color profile (gains + perceptual dimming)",
    )
    led_color.add_argument("name", help="CSS3 color name or #rrggbb / #rgb")
    led_color.add_argument(
        "--brightness",
        type=float,
        default=1.0,
        help="0..1 perceived brightness (CIE L* by default)",
    )
    led_sub.add_parser("colors", help="list CSS3 color names")
    led_sub.add_parser("off", help="turn LED off")
    led_sub.add_parser("get", help="read current PWM levels")

    eeprom = sub.add_parser("eeprom", help="EEPROM read/write")
    eeprom_sub = eeprom.add_subparsers(dest="eeprom_command", required=True)
    ee_read = eeprom_sub.add_parser("read", help="read bytes from EEPROM")
    ee_read.add_argument("offset", type=lambda s: int(s, 0))
    ee_read.add_argument("length", type=int)
    ee_write = eeprom_sub.add_parser("write", help="write hex bytes to EEPROM")
    ee_write.add_argument("offset", type=lambda s: int(s, 0))
    ee_write.add_argument(
        "data",
        help="hex bytes, e.g. deadbeef or de:ad:be:ef",
    )

    temp = sub.add_parser("temp", help="MCP9600 thermocouple commands")
    temp_sub = temp.add_subparsers(dest="temp_command", required=True)

    temp_read = temp_sub.add_parser("read", help="read hot-junction temperature")
    temp_read.add_argument(
        "--no-wait",
        action="store_true",
        help="do not wait for TH_UPDATE before reading",
    )
    temp_read.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="seconds to wait for a conversion (default: 1.0)",
    )
    temp_sub.add_parser("cold", help="read cold-junction (ambient) temperature")
    temp_sub.add_parser("status", help="show ready / open-circuit status flags")

    temp_type = temp_sub.add_parser("type", help="get or set thermocouple type")
    temp_type.add_argument(
        "value",
        nargs="?",
        choices=[t.name for t in ThermocoupleType],
        help="thermocouple type letter (K, J, T, ...)",
    )

    temp_filter = temp_sub.add_parser("filter", help="get or set digital filter 0..7")
    temp_filter.add_argument("value", nargs="?", type=int)

    temp_res = temp_sub.add_parser("resolution", help="get or set ADC resolution")
    temp_res.add_argument(
        "bits",
        nargs="?",
        type=int,
        choices=sorted(_ADC_BY_BITS),
        help="18, 16, 14, or 12",
    )

    temp_sub.add_parser("identify", help="read MCP9600 device ID and revision")

    return parser


def _open_probe(args: argparse.Namespace, bus: I2CBus | None) -> ProbeTemp1:
    return ProbeTemp1(bus, check_product=args.check_product)


def _parse_hex_bytes(text: str) -> bytes:
    cleaned = text.replace(":", "").replace(" ", "").replace("-", "")
    if len(cleaned) % 2:
        raise ValueError("hex data must contain an even number of digits")
    return bytes.fromhex(cleaned)


def _run(args: argparse.Namespace, bus: I2CBus | None) -> int:
    probe = _open_probe(args, bus)
    try:
        return _dispatch(args, probe)
    finally:
        probe.close()


def _dispatch(args: argparse.Namespace, probe: ProbeTemp1) -> int:
    cmd = args.command

    if cmd == "info":
        tc = probe.thermocouple
        device_id, revision = tc.read_device_id_revision()
        product = probe.product_number
        try:
            product_name = ProductNumber(product).name
        except ValueError:
            product_name = "unknown"
        print(f"product:     0x{product:02X} ({product_name})")
        print(f"eui48:       {probe.eeprom.eui48_str}")
        print(f"mcp9600 id:  0x{device_id:02X}")
        print(f"mcp9600 rev: {tc.revision_str} (0x{revision:02X})")
        print(f"tc type:     {tc.thermocouple_type.name}")
        print(f"filter:      {tc.filter_coefficient}")
        print(f"adc:         {tc.adc_resolution.name}")
        print(f"ready:       {tc.temperature_ready}")
        print(f"open/range:  {tc.open_circuit}")
        return 0

    if cmd == "product":
        print(f"0x{probe.product_number:02X}")
        return 0

    if cmd == "eui48":
        print(probe.eeprom.eui48_str)
        return 0

    if cmd == "led":
        if args.led_command == "set":
            probe.led.set_rgb(args.red, args.green, args.blue)
            print(f"{args.red} {args.green} {args.blue}")
            return 0
        if args.led_command == "color":
            pwm = probe.led.set_color(args.name, brightness=args.brightness)
            print(f"{args.name} -> {pwm[0]} {pwm[1]} {pwm[2]}")
            return 0
        if args.led_command == "colors":
            from openacqu.colors import named_colors

            print("\n".join(named_colors()))
            return 0
        if args.led_command == "off":
            probe.led.off()
            print("off")
            return 0
        if args.led_command == "get":
            r, g, b = probe.led.get_pwm()
            print(f"{r} {g} {b}")
            return 0

    if cmd == "eeprom":
        if args.eeprom_command == "read":
            data = probe.eeprom.read(args.offset, args.length)
            print(data.hex(" "))
            return 0
        if args.eeprom_command == "write":
            payload = _parse_hex_bytes(args.data)
            probe.eeprom.write(args.offset, payload)
            print(f"wrote {len(payload)} byte(s) at 0x{args.offset:02X}")
            return 0

    if cmd == "temp":
        tc = probe.thermocouple
        if args.temp_command == "read":
            value = tc.read_hot_junction_c(wait=not args.no_wait, timeout_s=args.timeout)
            print(f"{value:.4f}")
            return 0
        if args.temp_command == "cold":
            print(f"{tc.cold_junction_c:.4f}")
            return 0
        if args.temp_command == "status":
            print(f"ready={tc.temperature_ready} open_circuit={tc.open_circuit} status=0x{tc.status:02X}")
            return 0
        if args.temp_command == "type":
            if args.value is None:
                print(tc.thermocouple_type.name)
            else:
                tc.thermocouple_type = ThermocoupleType[args.value]
                print(tc.thermocouple_type.name)
            return 0
        if args.temp_command == "filter":
            if args.value is None:
                print(tc.filter_coefficient)
            else:
                tc.filter_coefficient = args.value
                print(tc.filter_coefficient)
            return 0
        if args.temp_command == "resolution":
            if args.bits is None:
                bits = {v: k for k, v in _ADC_BY_BITS.items()}[tc.adc_resolution]
                print(bits)
            else:
                tc.adc_resolution = _ADC_BY_BITS[args.bits]
                print(args.bits)
            return 0
        if args.temp_command == "identify":
            device_id, revision = tc.identify()
            print(f"0x{device_id:02X} 0x{revision:02X} ({tc.revision_str})")
            return 0

    raise AssertionError(f"unhandled command: {args.command}")


def main(argv: Sequence[str] | None = None, *, bus: I2CBus | None = None) -> int:
    """CLI entry point. Pass ``bus`` in tests to avoid opening USB hardware."""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return _run(args, bus)
    except BrokenPipeError:
        return 0
    except (ValueError, TypeError, TimeoutError, LookupError, NotImplementedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

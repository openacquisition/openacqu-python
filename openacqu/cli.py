"""Command-line test harness for Open Acquisition probes.

The library is the product API; this CLI exists to exercise hardware features
during bring-up and verification.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections.abc import Sequence
from typing import Any

from openacqu import Probe, ProbePh1, ProbeTemp1, ProductNumber, __version__
from openacqu.chips.eeprom_24aa025e48 import (
    DEFAULT_ADDRESS as EEPROM_ADDRESS,
)
from openacqu.chips.eeprom_24aa025e48 import (
    USER_MEMORY_SIZE,
)
from openacqu.chips.lp5817 import DEFAULT_ADDRESS as LED_ADDRESS
from openacqu.chips.lmp91200 import PgaGain, VcmLevel, VocmSelect
from openacqu.chips.mcp9600 import AdcResolution, ThermocoupleType
from openacqu.colors import indicator_pwm, indicator_sequence
from openacqu.transport.base import I2CBus
from openacqu.transport.mcp2221 import MCP2221Bus, open_mcp2221_bus

_ADC_BY_BITS = {
    18: AdcResolution.BITS_18,
    16: AdcResolution.BITS_16,
    14: AdcResolution.BITS_14,
    12: AdcResolution.BITS_12,
}

_VCM_BY_NAME = {
    "7/8": VcmLevel.VREF_7_8,
    "3/4": VcmLevel.VREF_3_4,
    "5/8": VcmLevel.VREF_5_8,
    "1/2": VcmLevel.VREF_1_2,
    "3/8": VcmLevel.VREF_3_8,
    "1/4": VcmLevel.VREF_1_4,
    "1/8": VcmLevel.VREF_1_8,
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
    parser.add_argument(
        "--keepalive",
        nargs="?",
        const=1.0,
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "enable MCP2221A HID keep-alive while the command runs "
            "(optional interval, default 1.0s); helps keep USBCFG high"
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    usb = sub.add_parser(
        "usb",
        help="MCP2221A USB diagnostics (USBCFG / suspend bring-up)",
    )
    usb.add_argument(
        "--hold",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="keep the USB handle open this many seconds (for scoping USBCFG)",
    )
    usb_sub = usb.add_subparsers(dest="usb_command", required=False)
    usbcfg = usb_sub.add_parser(
        "usbcfg",
        help="read or flash the USBCFG level used while USB is configured",
    )
    usbcfg.add_argument(
        "level",
        nargs="?",
        choices=("high", "low"),
        help=(
            "flash this active level (pin level while USB is configured). "
            "Omit to read the level stored in flash"
        ),
    )

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
    led_cycle = led_sub.add_parser(
        "cycle",
        help="cycle indicator colors, starting and ending with the LED off",
    )
    led_cycle.add_argument(
        "--dwell",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="seconds to hold the off states and each color (default: 1)",
    )
    led_cycle.add_argument(
        "--start",
        default=None,
        help=(
            "indicator color to show first (red, yellow, green, "
            "blue, magenta, white). The cycle still visits every color once"
        ),
    )
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
    ee_stress = eeprom_sub.add_parser(
        "stress",
        help="erase, write random data, verify, then erase and verify the user EEPROM",
    )
    ee_stress.add_argument(
        "--yes",
        action="store_true",
        help="proceed with the erase after the warning, without an interactive prompt",
    )
    ee_stress.add_argument(
        "--seed",
        type=int,
        default=None,
        help="seed for the random payload (a seed is printed either way)",
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

    ph = sub.add_parser(
        "ph",
        help="pH probe AFE / SC18IS606 commands (config only; ADC not wired yet)",
    )
    ph_sub = ph.add_subparsers(dest="ph_command", required=True)
    ph_sub.add_parser("info", help="show bridge address, SPI config, and AFE cache")
    ph_sub.add_parser("bridge", help="show SC18IS606 address and cached SPI config byte")
    ph_cfg = ph_sub.add_parser(
        "configure",
        help="write LMP91200 pH defaults (PGA 5, VCM 1/2 VREF, VOCM, diag off)",
    )
    ph_cfg.add_argument(
        "--verify",
        action="store_true",
        help="double-clock and verify shift-register echo",
    )
    ph_sub.add_parser("config", help="show cached LMP91200 configuration word")
    ph_pga = ph_sub.add_parser("pga", help="get or set PGA gain (5 or 10 V/V)")
    ph_pga.add_argument("value", nargs="?", type=int, choices=[5, 10])
    ph_vcm = ph_sub.add_parser("vcm", help="get or set VCM as fraction of VREF")
    ph_vcm.add_argument("value", nargs="?", choices=sorted(_VCM_BY_NAME))
    ph_vocm = ph_sub.add_parser("vocm", help="get or set VOUT reference (vocm|gnd)")
    ph_vocm.add_argument("value", nargs="?", choices=["vocm", "gnd"])
    ph_diag = ph_sub.add_parser("diag", help="get or set diagnostic enable (on|off)")
    ph_diag.add_argument("value", nargs="?", choices=["on", "off"])
    ph_write = ph_sub.add_parser("write", help="write raw 16-bit AFE config word")
    ph_write.add_argument("word", type=lambda s: int(s, 0), help="e.g. 0x0000 or 0x0800")
    ph_write.add_argument("--verify", action="store_true")

    return parser


def _keepalive_arg(args: argparse.Namespace) -> bool | float:
    if args.keepalive is None:
        return False
    return args.keepalive


_EEPROM_STRESS_WARNING = (
    "warning: the 24AA025E48 user EEPROM (0x00-0x7F, 128 bytes) will be erased. "
    "The factory EUI-48 at 0xFA-0xFF is not modified."
)


def _confirm_eeprom_stress(args: argparse.Namespace) -> bool:
    """Print the erase warning and require an explicit yes before continuing."""
    print(_EEPROM_STRESS_WARNING)
    if args.yes:
        return True
    if not sys.stdin.isatty():
        print(
            "error: refusing to erase the EEPROM without --yes",
            file=sys.stderr,
        )
        return False
    answer = input("Type yes to continue: ")
    if answer.strip() != "yes":
        print("aborted")
        return False
    return True


def _open_probe(args: argparse.Namespace, bus: I2CBus | None) -> Probe:
    keepalive = _keepalive_arg(args)
    if args.command == "ph":
        return ProbePh1(
            bus,
            check_product=args.check_product,
            keepalive=keepalive,
        )
    # Core peripherals must not wait on the thermocouple converter. That part
    # can be absent or at another address while the LED or EEPROM is exercised.
    ready_address = {"eeprom": EEPROM_ADDRESS, "led": LED_ADDRESS}.get(args.command)
    if bus is None and ready_address is not None:
        interval = keepalive if isinstance(keepalive, float) else None
        bus = open_mcp2221_bus(
            keepalive_s=interval,
            ready_address=ready_address,
        )
        keepalive = False
    return ProbeTemp1(
        bus,
        check_product=args.check_product,
        keepalive=keepalive,
    )


def _parse_hex_bytes(text: str) -> bytes:
    cleaned = text.replace(":", "").replace(" ", "").replace("-", "")
    if len(cleaned) % 2:
        raise ValueError("hex data must contain an even number of digits")
    return bytes.fromhex(cleaned)


def _print_usb_status(status: dict[str, Any]) -> None:
    for key in (
        "vid",
        "pid",
        "handle_open",
        "keepalive_active",
        "keepalive_interval_s",
        "usbcfg_note",
    ):
        if key in status:
            print(f"{key}: {status[key]}")
    if "flash" in status:
        print("flash:")
        print(json.dumps(status["flash"], indent=2, default=str))
    if "flash_error" in status:
        print(f"flash_error: {status['flash_error']}")
    if "device" in status:
        print("device:")
        print(status["device"])
    if "device_error" in status:
        print(f"device_error: {status['device_error']}")


def _run_usb(args: argparse.Namespace, bus: I2CBus | None) -> int:
    owned = False
    keepalive = _keepalive_arg(args)
    if bus is None:
        interval = keepalive if keepalive is not False else None
        if interval is True:
            interval = 1.0
        bus = open_mcp2221_bus(keepalive_s=interval if interval else None)
        owned = True
    elif keepalive and isinstance(bus, MCP2221Bus):
        bus.start_keepalive(float(keepalive) if keepalive is not True else 1.0)

    try:
        if getattr(args, "usb_command", None) == "usbcfg":
            return _run_usb_usbcfg(args, bus)
        status_fn = getattr(bus, "usb_status", None)
        if not callable(status_fn):
            raise TypeError("injected bus does not support usb_status()")
        _print_usb_status(status_fn())
        if args.hold > 0:
            print(f"holding USB handle open for {args.hold:g}s (scope USBCFG)...", flush=True)
            time.sleep(args.hold)
            print("hold complete")
        return 0
    finally:
        if owned:
            close = getattr(bus, "close", None)
            if callable(close):
                close()


def _run_usb_usbcfg(args: argparse.Namespace, bus: I2CBus) -> int:
    if not isinstance(bus, MCP2221Bus):
        raise TypeError("USBCFG flash requires an MCP2221 bus")
    if args.level is None:
        level = bus.usbcfg_active_level()
        print(f"active: {level}")
        print(f"USBCFGINST: {0 if level == 'high' else 1}")
        return 0
    level = bus.flash_usbcfg_active_level(args.level)
    print(f"active: {level}")
    print(f"USBCFGINST: {0 if level == 'high' else 1}")
    print("re-enumerate the MCP2221A before this level is used")
    return 0


def _run(args: argparse.Namespace, bus: I2CBus | None) -> int:
    if args.command == "usb":
        return _run_usb(args, bus)
    if args.command == "eeprom" and args.eeprom_command == "stress":
        if not _confirm_eeprom_stress(args):
            return 1
    probe = _open_probe(args, bus)
    try:
        return _dispatch(args, probe)
    finally:
        probe.close()


def _run_led_cycle(args: argparse.Namespace, probe: Probe) -> int:
    """Hold off, each indicator color, and off again for ``--dwell`` seconds."""
    if args.dwell <= 0:
        raise ValueError("dwell must be > 0")
    sequence = indicator_sequence(args.start)
    probe.led.off()
    print("off", flush=True)
    time.sleep(args.dwell)
    for name, color in sequence:
        pwm = indicator_pwm(name)
        probe.led.set_pwm(*pwm)
        print(f"{name} {color} -> {pwm[0]} {pwm[1]} {pwm[2]}", flush=True)
        time.sleep(args.dwell)
    probe.led.off()
    print("off", flush=True)
    time.sleep(args.dwell)
    return 0


def _dispatch(args: argparse.Namespace, probe: Probe) -> int:
    cmd = args.command

    if cmd == "info":
        product = probe.product_number
        try:
            product_name = ProductNumber(product).name
        except ValueError:
            product_name = "unknown"
        print(f"product:     0x{product:02X} ({product_name})")
        print(f"eui48:       {probe.eeprom.eui48_str}")
        if isinstance(probe, ProbeTemp1):
            tc = probe.thermocouple
            device_id, revision = tc.read_device_id_revision()
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
        if args.led_command == "cycle":
            return _run_led_cycle(args, probe)
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
        if args.eeprom_command == "stress":
            seed = args.seed if args.seed is not None else random.randrange(2**32)
            pattern = bytes(random.Random(seed).getrandbits(8) for _ in range(USER_MEMORY_SIZE))
            eui = probe.eeprom.eui48_str
            print(f"seed:  {seed}")
            print(f"eui48: {eui}")
            probe.eeprom.stress_user(pattern)
            print(f"passed: {USER_MEMORY_SIZE} random bytes verified, user area erased")
            print(f"eui48 unchanged: {probe.eeprom.eui48_str}")
            return 0

    if cmd == "temp":
        if not isinstance(probe, ProbeTemp1):
            raise TypeError("temp commands require ProbeTemp1")
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

    if cmd == "ph":
        if not isinstance(probe, ProbePh1):
            raise TypeError("ph commands require ProbePh1")
        return _dispatch_ph(args, probe)

    raise AssertionError(f"unhandled command: {args.command}")


def _print_afe_config(afe) -> None:
    print(f"config:  0x{afe.config:04X}")
    print(f"mode:    {afe.meas_mode.name}")
    print(f"pga:     {5 if afe.pga is PgaGain.GAIN_5 else 10} V/V")
    vcm_name = next(
        (name for name, level in _VCM_BY_NAME.items() if level is afe.vcm),
        f"0b{int(afe.vcm):03b}",
    )
    print(f"vcm:     {vcm_name} VREF")
    print(f"vocm:    {afe.vocm.name.lower()}")
    print(f"diag:    {'on' if afe.diag_en else 'off'}")


def _dispatch_ph(args: argparse.Namespace, probe: ProbePh1) -> int:
    afe = probe.afe
    bridge = probe.bridge
    cmd = args.ph_command

    if cmd == "info":
        print(f"product:       0x{probe.product_number:02X}")
        print(f"bridge:        0x{bridge.address:02X}")
        print(f"spi_config:    0x{bridge.config_byte:02X}")
        _print_afe_config(afe)
        print("adc:           not configured (choose MCP2221A ADC or I2C ADC)")
        return 0

    if cmd == "bridge":
        print(f"0x{bridge.address:02X} config=0x{bridge.config_byte:02X}")
        return 0

    if cmd == "configure":
        afe.configure_ph(verify=args.verify)
        _print_afe_config(afe)
        return 0

    if cmd == "config":
        _print_afe_config(afe)
        return 0

    if cmd == "pga":
        if args.value is None:
            print(5 if afe.pga is PgaGain.GAIN_5 else 10)
        else:
            afe.pga = PgaGain.GAIN_10 if args.value == 10 else PgaGain.GAIN_5
            print(args.value)
        return 0

    if cmd == "vcm":
        if args.value is None:
            name = next(
                (n for n, level in _VCM_BY_NAME.items() if level is afe.vcm),
                str(int(afe.vcm)),
            )
            print(name)
        else:
            afe.vcm = _VCM_BY_NAME[args.value]
            print(args.value)
        return 0

    if cmd == "vocm":
        if args.value is None:
            print(afe.vocm.name.lower())
        else:
            afe.vocm = VocmSelect.GND if args.value == "gnd" else VocmSelect.VOCM
            print(afe.vocm.name.lower())
        return 0

    if cmd == "diag":
        if args.value is None:
            print("on" if afe.diag_en else "off")
        else:
            afe.diag_en = args.value == "on"
            print("on" if afe.diag_en else "off")
        return 0

    if cmd == "write":
        afe.write_config(args.word, verify=args.verify)
        print(f"0x{afe.config:04X}")
        return 0

    raise AssertionError(f"unhandled ph command: {cmd}")


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

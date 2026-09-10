#!/usr/bin/env python3
# @brief	    Manage a Waveshare Modbus RTU Analog Input 8CH module
# @author		Helge Klug
# @copyright	Copyright (c) 2026 Helge Klug
# @file			modbus-waveshare-ai.py
# @details		Provides Modbus RTU commands for address, channel, UART, and input value management.

"""Manage a Waveshare Modbus RTU Analog Input 8CH module via a local RS485 adapter."""

from __future__ import annotations

import argparse
import sys
import time


# Holding register containing the device Modbus address.
REGISTER_DEVICE_ADDRESS = 0x4000
# Holding register containing the device software version.
REGISTER_SOFTWARE_VERSION = 0x8000
# First holding register containing analog input channel modes.
REGISTER_CHANNEL_MODE_START = 0x1000
# First input register containing analog input values.
REGISTER_INPUT_START = 0x0000
# Holding register containing UART parity and baudrate settings.
REGISTER_UART_PARAMETER = 0x2000
# Register count for single-register Modbus requests.
REGISTER_COUNT_ONE = 0x0001
# Modbus function code for reading holding registers.
FUNCTION_READ_HOLDING = 0x03
# Modbus function code for reading input registers.
FUNCTION_READ_INPUT = 0x04
# Modbus function code for writing one holding register.
FUNCTION_WRITE_SINGLE = 0x06
# Modbus function code for writing multiple holding registers.
FUNCTION_WRITE_MULTIPLE = 0x10

# Human-readable labels for analog input channel mode codes.
CHANNEL_MODE_LABELS = {
	0: "voltage mode 0-5V, B model 0-10V",
	1: "voltage mode 1-5V, B model 2-10V",
	2: "current mode 0-20mA",
	3: "current mode 4-20mA",
	4: "raw 4096-scale code",
}

# Mapping from device UART baudrate codes to baudrate values.
UART_BAUDRATE_BY_CODE = {
	0: 4800,
	1: 9600,
	2: 19200,
	3: 38400,
	4: 57600,
	5: 115200,
	6: 128000,
	7: 256000,
}
# Mapping from device UART baudrate values to baudrate codes.
UART_BAUDRATE_CODE_BY_VALUE = {baudrate: code for code, baudrate in UART_BAUDRATE_BY_CODE.items()}
# Mapping from parity names to device UART parity codes.
UART_PARITY_BY_NAME = {"none": 0, "even": 1, "odd": 2}
# Mapping from device UART parity codes to parity names.
UART_PARITY_NAME_BY_CODE = {code: name for name, code in UART_PARITY_BY_NAME.items()}
# Mapping from parity names to PySerial parity constants.
SERIAL_PARITY_BY_NAME = {"none": "N", "even": "E", "odd": "O"}


# @brief	Exception raised for invalid or unexpected Modbus communication.
class ModbusError(RuntimeError):
	pass


# @brief	Argparse formatter with fixed wide help output.
class WideHelpFormatter(argparse.RawTextHelpFormatter):
	# @brief	Initialize the wide command-line help formatter.
	# @param	args Positional arguments forwarded to the base formatter.
	# @param	kwargs Keyword arguments forwarded to the base formatter.
	# @return	None.
	def __init__(self, *args, **kwargs):
		super().__init__(*args, max_help_position=24, width=100, **kwargs)

# @brief	Parse and validate a Modbus node address.
# @param	value Node address text.
# @return	Valid node address in the range 1 to 255.
def parseNode(value: str) -> int:
	try:
		node = int(value, 0)
	except ValueError as exc:
		raise argparse.ArgumentTypeError(f"invalid node number: {value!r}") from exc
	if not 1 <= node <= 255:
		raise argparse.ArgumentTypeError("node number must be in range 1..255")
	return node


# @brief	Parse and validate a serial baudrate.
# @param	value Baudrate text, optionally prefixed with ``baudrate=``.
# @return	Positive baudrate value.
def parseBaudrate(value: str) -> int:
	if value.startswith("baudrate="):
		value = value.split("=", 1)[1]
	try:
		baudrate = int(value, 0)
	except ValueError as exc:
		raise argparse.ArgumentTypeError(f"invalid baudrate: {value!r}") from exc
	if baudrate <= 0:
		raise argparse.ArgumentTypeError("baudrate must be greater than 0")
	return baudrate


# @brief	Parse a baudrate supported by the device UART.
# @param	value Device UART baudrate text.
# @return	Supported device UART baudrate.
def parseUartBaudrate(value: str) -> int:
	baudrate = parseBaudrate(value)
	if baudrate not in UART_BAUDRATE_CODE_BY_VALUE:
		supported = ", ".join(str(item) for item in UART_BAUDRATE_CODE_BY_VALUE)
		raise argparse.ArgumentTypeError(f"unsupported device baudrate {baudrate}; supported: {supported}")
	return baudrate


# @brief	Parse a device UART parity setting.
# @param	value Parity setting text.
# @return	Normalized parity name.
def parseUartParity(value: str) -> str:
	parity = value.lower()
	if parity not in UART_PARITY_BY_NAME:
		supported = ", ".join(UART_PARITY_BY_NAME)
		raise argparse.ArgumentTypeError(f"unsupported parity {value!r}; supported: {supported}")
	return parity


# @brief	Parse and validate an analog input channel mode.
# @param	value Channel mode text.
# @return	Channel mode in the range 0 to 4.
def parseChannelMode(value: str) -> int:
	try:
		mode = int(value, 0)
	except ValueError as exc:
		raise argparse.ArgumentTypeError(f"invalid channel mode: {value!r}") from exc
	if not 0 <= mode <= 4:
		raise argparse.ArgumentTypeError("channel mode must be in range 0..4")
	return mode


# @brief	Parse a channel and mode assignment.
# @param	value Assignment text in ``CHANNEL=MODE`` format.
# @return	Tuple containing the channel number and mode.
def parseChannelAssignment(value: str) -> tuple[int, int]:
	if "=" not in value:
		raise argparse.ArgumentTypeError("channel assignment must use CHANNEL=MODE, for example 1=3")
	channelText, modeText = value.split("=", 1)
	try:
		channel = int(channelText, 0)
	except ValueError as exc:
		raise argparse.ArgumentTypeError(f"invalid channel number: {channelText!r}") from exc
	if not 1 <= channel <= 8:
		raise argparse.ArgumentTypeError("channel number must be in range 1..8")
	return channel, parseChannelMode(modeText)


# @brief	Parse and validate an analog input channel number.
# @param	value Channel number text.
# @return	Channel number in the range 1 to 8.
def parseChannel(value: str) -> int:
	try:
		channel = int(value, 0)
	except ValueError as exc:
		raise argparse.ArgumentTypeError(f"invalid channel number: {value!r}") from exc
	if not 1 <= channel <= 8:
		raise argparse.ArgumentTypeError("channel number must be in range 1..8")
	return channel


# @brief	Calculate the Modbus RTU CRC-16 checksum.
# @param	data Payload bytes to checksum.
# @return	Unsigned 16-bit CRC value.
def crc16Modbus(data: bytes) -> int:
	crc = 0xFFFF
	for byte in data:
		crc ^= byte
		for _ in range(8):
			if crc & 0x0001:
				crc = (crc >> 1) ^ 0xA001
			else:
				crc >>= 1
	return crc & 0xFFFF


# @brief	Append a Modbus RTU CRC to a payload.
# @param	payload Modbus RTU payload without CRC.
# @return	Complete Modbus RTU frame with CRC.
def frame(payload: bytes) -> bytes:
	crc = crc16Modbus(payload)
	return payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


# @brief	Verify the CRC of a Modbus RTU response.
# @param	response Complete Modbus RTU response frame.
# @return	None.
def verifyCrc(response: bytes) -> None:
	if len(response) < 5:
		raise ModbusError(f"response too short: {response.hex(' ')}")
	expected = crc16Modbus(response[:-2])
	actual = response[-2] | (response[-1] << 8)
	if actual != expected:
		raise ModbusError(
			f"CRC mismatch in response {response.hex(' ')}: expected {expected:04x}, got {actual:04x}"
		)


# @brief	Read and validate an exact-length Modbus RTU response.
# @param	port Open serial port.
# @param	length Expected response length in bytes.
# @return	Validated response frame.
def readExact(port, length: int) -> bytes:
	response = port.read(length)
	if len(response) != length:
		raise ModbusError(f"timeout waiting for {length} bytes, got {len(response)}: {response.hex(' ')}")
	verifyCrc(response)
	if response[1] & 0x80:
		raise ModbusError(f"modbus exception {response[2]:#04x}: {response.hex(' ')}")
	return response


# @brief	Read consecutive Modbus registers.
# @param	port Open serial port.
# @param	node Modbus node address.
# @param	function_code Modbus read function code.
# @param	start_address First register address.
# @param	count Number of registers to read.
# @return	Register values in request order.
def readRegisters(port, node: int, functionCode: int, startAddress: int, count: int) -> list[int]:
	request = frame(
		bytes(
			(
				node,
				functionCode,
				(startAddress >> 8) & 0xFF,
				startAddress & 0xFF,
				(count >> 8) & 0xFF,
				count & 0xFF,
			)
		)
	)
	port.reset_input_buffer()
	port.write(request)
	port.flush()
	response = readExact(port, 5 + count * 2)
	if response[0] != node or response[1] != functionCode or response[2] != count * 2:
		raise ModbusError(f"unexpected read response: {response.hex(' ')}")
	return [(response[index] << 8) | response[index + 1] for index in range(3, 3 + count * 2, 2)]


# @brief	Read the device address register.
# @param	port Open serial port.
# @param	node Modbus node address.
# @return	Address stored in the device register.
def readDeviceAddress(port, node: int) -> int:
	return readRegisters(port, node, FUNCTION_READ_HOLDING, REGISTER_DEVICE_ADDRESS, REGISTER_COUNT_ONE)[0]


# @brief	Read and split the UART parameter register.
# @param	port Open serial port.
# @param	node Modbus node address.
# @return	Tuple of register value, parity code, and baudrate code.
def readUartParameter(port, node: int) -> tuple[int, int, int]:
	value = readRegisters(port, node, FUNCTION_READ_HOLDING, REGISTER_UART_PARAMETER, REGISTER_COUNT_ONE)[0]
	return value, (value >> 8) & 0xFF, value & 0xFF


# @brief	Read all analog input channel modes.
# @param	port Open serial port.
# @param	node Modbus node address.
# @return	Eight channel mode values.
def readChannelModes(port, node: int) -> list[int]:
	return readRegisters(port, node, FUNCTION_READ_HOLDING, REGISTER_CHANNEL_MODE_START, 8)


# @brief	Verify that an AI-8CH-compatible register map responds.
# @param	port Open serial port.
# @param	node Modbus node address.
# @return	None.
def probeAiDevice(port, node: int) -> None:
	deviceAddress = readDeviceAddress(port, node)
	if deviceAddress != node:
		raise ModbusError(f"device answered on node {node}, but register 0x4000 contains {deviceAddress}")

	softwareVersion = readRegisters(port, node, FUNCTION_READ_HOLDING, REGISTER_SOFTWARE_VERSION, 1)[0]
	channelModes = readChannelModes(port, node)
	if any(mode > 4 for mode in channelModes):
		modes = ", ".join(str(mode) for mode in channelModes)
		raise ModbusError(f"AI channel mode register check failed: expected values 0..4, got [{modes}]")

	inputValues = readRegisters(port, node, FUNCTION_READ_INPUT, REGISTER_INPUT_START, 8)
	versionText = f"V{softwareVersion / 100:.2f}"
	modesText = ", ".join(str(mode) for mode in channelModes)
	inputsText = ", ".join(str(value) for value in inputValues)
	print(f"ai check ok: Waveshare AI-8CH register map answered on node {node}")
	print(f"software version: {versionText} ({softwareVersion})")
	print(f"channel modes: [{modesText}]")
	print(f"input values: [{inputsText}]")


# @brief	Print one analog input channel mode.
# @param	channel Channel number.
# @param	mode Channel mode value.
# @return	None.
def printChannelMode(channel: int, mode: int) -> None:
	registerAddress = REGISTER_CHANNEL_MODE_START + channel - 1
	label = CHANNEL_MODE_LABELS.get(mode, "unknown mode")
	print(f"channel {channel}: register 0x{registerAddress:04X}, value 0x{mode:04X} --> mode {mode} = {label}")


# @brief	Read and print selected channel modes.
# @param	port Open serial port.
# @param	node Modbus node address.
# @param	channels Channel numbers to print.
# @return	None.
def printChannelModes(port, node: int, channels: list[int]) -> None:
	modes = readChannelModes(port, node)
	for channel in channels:
		printChannelMode(channel, modes[channel - 1])


# @brief	Format a module-scaled analog input register value.
# @param	mode Channel mode value.
# @param	value Raw input register value.
# @return	Measurement formatted with its unit or raw-code label.
def formatInputValue(mode: int, value: int) -> str:
	if mode in (0, 1):
		return f"{value / 1000:.3f} V"
	if mode == 2:
		return f"{value / 1000:.3f} mA"
	if mode == 3:
		return f"{value / 1000:.3f} mA"
	if mode == 4:
		return f"{value} (raw 4096-scale code)"
	return f"{value} (unknown channel mode {mode})"


# @brief	Read and print selected analog input values.
# @param	port Open serial port.
# @param	node Modbus node address.
# @param	channels Channel numbers to print.
# @param	value_only Whether to print only formatted measurements.
# @param	raw_value_only Whether to print only raw hexadecimal values.
# @return	None.
def printInputValues(port, node: int, channels: list[int], valueOnly: bool, rawValueOnly: bool) -> None:
	modes = readChannelModes(port, node)
	values = readRegisters(port, node, FUNCTION_READ_INPUT, REGISTER_INPUT_START, 8)
	for channel in channels:
		value = values[channel - 1]
		registerAddress = REGISTER_INPUT_START + channel - 1
		measurement = formatInputValue(modes[channel - 1], value)
		if rawValueOnly:
			print(f"0x{value:04X}")
		elif valueOnly:
			print(measurement)
		else:
			print(f"channel {channel}: register 0x{registerAddress:04X}, value 0x{value:04X} --> {measurement}")


# @brief	Format the decoded UART parameter register.
# @param	value Complete UART parameter register value.
# @param	parity_code UART parity code.
# @param	baudrate_code UART baudrate code.
# @return	Human-readable UART parameter description.
def formatUartParameter(value: int, parityCode: int, baudrateCode: int) -> str:
	parity = UART_PARITY_NAME_BY_CODE.get(parityCode, f"unknown({parityCode})")
	baudrate = UART_BAUDRATE_BY_CODE.get(baudrateCode, f"unknown({baudrateCode})")
	return f"register 0x{REGISTER_UART_PARAMETER:04X}, value 0x{value:04X} --> parity {parityCode} = {parity}, baudrate {baudrateCode} = {baudrate}"


# @brief	Read and print the device UART parameter.
# @param	port Open serial port.
# @param	node Modbus node address.
# @return	None.
def printUartParameter(port, node: int) -> None:
	value, parityCode, baudrateCode = readUartParameter(port, node)
	print(formatUartParameter(value, parityCode, baudrateCode))


# @brief	Write one Modbus holding register.
# @param	port Open serial port.
# @param	node Modbus node address.
# @param	register_address Register address to write.
# @param	value Register value to write.
# @return	None.
def writeRegister(port, node: int, registerAddress: int, value: int) -> None:
	request = frame(
		bytes(
			(
				node,
				FUNCTION_WRITE_SINGLE,
				(registerAddress >> 8) & 0xFF,
				registerAddress & 0xFF,
				(value >> 8) & 0xFF,
				value & 0xFF,
			)
		)
	)
	port.reset_input_buffer()
	port.write(request)
	port.flush()
	response = readExact(port, 8)
	if response != request:
		raise ModbusError(f"unexpected write response: {response.hex(' ')}; request was {request.hex(' ')}")


# @brief	Write consecutive Modbus holding registers.
# @param	port Open serial port.
# @param	node Modbus node address.
# @param	start_address First register address to write.
# @param	values Register values to write in order.
# @return	None.
def writeRegisters(port, node: int, startAddress: int, values: list[int]) -> None:
	count = len(values)
	if not values:
		raise ValueError("at least one register value is required")
	payload = bytes(
		(
			node,
			FUNCTION_WRITE_MULTIPLE,
			(startAddress >> 8) & 0xFF,
			startAddress & 0xFF,
			(count >> 8) & 0xFF,
			count & 0xFF,
			count * 2,
		)
	) + b"".join(value.to_bytes(2, "big") for value in values)
	request = frame(payload)
	expectedResponse = frame(payload[:6])
	port.reset_input_buffer()
	port.write(request)
	port.flush()
	response = readExact(port, 8)
	if response != expectedResponse:
		raise ModbusError(f"unexpected write response: {response.hex(' ')}; expected {expectedResponse.hex(' ')}")


# @brief	Write a new device address.
# @param	port Open serial port.
# @param	request_node Address used for the write request.
# @param	new_node New device address to store.
# @return	None.
def writeDeviceAddress(port, requestNode: int, newNode: int) -> None:
	writeRegister(port, requestNode, REGISTER_DEVICE_ADDRESS, newNode)


# @brief	Write the UART parity and baudrate parameter.
# @param	port Open serial port.
# @param	node Modbus node address.
# @param	parityCode UART parity code.
# @param	baudrateCode UART baudrate code.
# @return	Combined UART parameter register value.
def writeUartParameter(port, node: int, parityCode: int, baudrateCode: int) -> int:
	value = (parityCode << 8) | baudrateCode
	writeRegister(port, node, REGISTER_UART_PARAMETER, value)
	return value


# @brief	Write selected analog input channel modes.
# @param	port Open serial port.
# @param	node Modbus node address.
# @param	channel_modes Channel-number and mode pairs to write.
# @return	None.
def writeChannelModes(port, node: int, channelModes: list[tuple[int, int]]) -> None:
	for channel, mode in channelModes:
		register_address = REGISTER_CHANNEL_MODE_START + channel - 1
		writeRegister(port, node, register_address, mode)
		label = CHANNEL_MODE_LABELS.get(mode, "unknown mode")
		print(f"changed channel {channel}: register 0x{register_address:04X}, value 0x{mode:04X} --> mode {mode} = {label}")


# @brief	Set all eight channel modes with one Modbus write.
# @param	port Open serial port.
# @param	node Modbus node address.
# @param	mode Channel mode to apply.
# @return	None.
def writeAllChannelModes(port, node: int, mode: int) -> None:
	writeRegisters(port, node, REGISTER_CHANNEL_MODE_START, [mode] * 8)
	for channel in range(1, 9):
		printChannelMode(channel, mode)


# @brief	Verify stored analog input channel modes.
# @param	port Open serial port.
# @param	node Modbus node address.
# @param	expected_modes Expected channel-number and mode pairs.
# @return	None.
def verifyChannelModes(port, node: int, expectedModes: list[tuple[int, int]]) -> None:
	modes = readChannelModes(port, node)
	for channel, expectedMode in expectedModes:
		actualMode = modes[channel - 1]
		if actualMode != expectedMode:
			raise ModbusError(
				f"channel {channel} verification failed: expected mode {expectedMode}, got {actualMode}"
			)
		register_address = REGISTER_CHANNEL_MODE_START + channel - 1
		label = CHANNEL_MODE_LABELS.get(actualMode, "unknown mode")
		print(
			f"verification ok: channel {channel}: register 0x{register_address:04X}, value 0x{actualMode:04X} --> mode {actualMode} = {label}"
		)


# @brief	Build the command-line argument parser.
# @param	None.
# @return	Configured argument parser.
def buildParser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Manage a Waveshare Modbus RTU Analog Input 8CH module via a local RS485 adapter.",
		formatter_class=WideHelpFormatter,
	)
	parser.add_argument("usbDevice", nargs="?", help="serial RS485 device, for example /dev/ttyUSB0 or COM4")
	parser.add_argument("node", nargs="?", type=parseNode, help="Modbus node number, 1..255")
	parser.add_argument("newNode", nargs="?", type=parseNode, help=argparse.SUPPRESS)

	connectionGroup = parser.add_argument_group("connection options")
	addressGroup = parser.add_argument_group("address options")
	channelGroup = parser.add_argument_group("channel options")
	uartGroup = parser.add_argument_group("device uart options")
	miscGroup = parser.add_argument_group("misc options")

	addressGroup.add_argument("--change-address", dest="changeAddress", type=parseNode, help="new Modbus node number, 1..255")
	channelGroup.add_argument(
		"--set-channel",
		dest="setChannel",
		action="append",
		default=[],
		type=parseChannelAssignment,
		metavar="CHANNEL=MODE",
		help=(
			"set one channel mode, repeatable; channel 1..8\n"
			"mode values:\n"
			"  0  voltage mode 0-5V, B model 0-10V\n"
			"  1  voltage mode 1-5V, B model 2-10V\n"
			"  2  current mode 0-20mA\n"
			"  3  current mode 4-20mA\n"
			"  4  raw 4096-scale code"
		),
	)
	channelGroup.add_argument(
		"--set-all-channels",
		dest="setAllChannels",
		type=parseChannelMode,
		help="set all 8 channel modes to MODE in one Modbus write; values are listed above",
	)
	channelGroup.add_argument(
		"--get-channel",
		dest="getChannel",
		type=parseChannel,
		metavar="CHANNEL",
		help="read one channel mode and show register, mode value, and label",
	)
	channelGroup.add_argument(
		"--get-all-channels",
		dest="getAllChannels",
		action="store_true",
		help="read all channel modes and show register, mode value, and label",
	)
	channelGroup.add_argument(
		"--get-value",
		dest="getValue",
		type=parseChannel,
		metavar="CHANNEL",
		help="read one analog input value and show its register and measurement",
	)
	channelGroup.add_argument(
		"--get-all-values",
		dest="getAllValues",
		action="store_true",
		help="read all 8 analog input values and show their registers and measurements",
	)
	channelGroup.add_argument(
		"--value-only",
		dest="valueOnly",
		action="store_true",
		help="with --get-value or --get-all-values, print only each formatted measurement",
	)
	channelGroup.add_argument(
		"--raw-value-only",
		dest="rawValueOnly",
		action="store_true",
		help="with --get-value or --get-all-values, print only each raw register value in hex",
	)
	uartGroup.add_argument(
		"--get-uart",
		dest="getUart",
		action="store_true",
		help=(
			"read device UART register 0x2000\n"
			"baudrate values: 4800, 9600, 19200, 38400, 57600, 115200, 128000, 256000\n"
			"parity values: none, even, odd"
		),
	)
	uartGroup.add_argument(
		"--set-uart",
		dest="setUart",
		nargs=2,
		metavar=("BAUDRATE", "PARITY"),
		help="set device UART baudrate and parity in register 0x2000, for example: --set-uart 19200 none",
	)
	uartGroup.add_argument(
		"--set-uart-baudrate",
		dest="setUartBaudrate",
		type=parseUartBaudrate,
		metavar="BAUDRATE",
		help="set device UART baudrate in register 0x2000",
	)
	uartGroup.add_argument(
		"--set-uart-parity",
		dest="setUartParity",
		type=parseUartParity,
		metavar="PARITY",
		help="set device UART parity in register 0x2000; values: none, even, odd",
	)
	connectionGroup.add_argument("--baudrate", type=parseBaudrate, default=9600, help="serial baudrate, default: 9600")
	connectionGroup.add_argument(
		"--parity",
		type=parseUartParity,
		default="none",
		help="serial interface parity, default: none; values: none, even, odd",
	)
	connectionGroup.add_argument("--timeout", type=float, default=1.0, help="serial timeout in seconds, default: 1.0")
	miscGroup.add_argument(
		"--broadcast-write",
		dest="broadcastWrite",
		action="store_true",
		help="write with Modbus broadcast address 0, as shown in the Waveshare examples",
	)
	miscGroup.add_argument("--skip-verify", dest="skipVerify", action="store_true", help="do not read back the new address after writing")
	miscGroup.add_argument("--self-test", dest="selfTest", action="store_true", help=argparse.SUPPRESS)
	return parser


# @brief	Run CRC and command-line parsing self-tests.
# @param	None.
# @return	None.
def runSelfTest() -> None:
	examples = {
		"000640000001": "5c1b",
		"000640000002": "1c1a",
		"010400000008": "f1cc",
		"010610000003": "cd0b",
		"000620000001": "421b",
	}
	for payloadHex, crcHex in examples.items():
		if frame(bytes.fromhex(payloadHex)).hex() != payloadHex + crcHex:
			raise ModbusError(f"CRC self-test failed for {payloadHex}")

	parser = buildParser()
	optionExamples = [
		["COM5", "1"],
		["COM5", "1", "--get-uart"],
		["COM5", "1", "--get-channel", "1"],
		["COM5", "1", "--get-all-channels"],
		["COM5", "1", "--get-value", "1"],
		["COM5", "1", "--get-value", "1", "--value-only"],
		["COM5", "1", "--get-value", "1", "--raw-value-only"],
		["COM5", "1", "--get-all-values"],
		["COM5", "1", "--set-channel", "1=3"],
		["COM5", "1", "--set-all-channels", "3"],
		["COM5", "1", "--set-uart", "19200", "none"],
		["COM5", "1", "--set-uart-baudrate", "19200"],
		["COM5", "1", "--set-uart-parity", "none"],
		["COM5", "1", "--change-address", "2", "--baudrate", "9600", "--parity", "none"],
	]
	for optionExample in optionExamples:
		parser.parse_args(optionExample)


# @brief	Run the command-line application.
# @param	None.
# @return	Process exit status.
def main() -> int:
	parser = buildParser()
	args = parser.parse_args()
	if args.selfTest:
		runSelfTest()
		print("self-test ok: crc examples and cli options passed")
		return 0

	if args.changeAddress is not None and args.newNode is not None and args.changeAddress != args.newNode:
		parser.error("use either --change-address or positional new_node, not both with different values")

	newNode = args.changeAddress if args.changeAddress is not None else args.newNode
	channelModes = list(args.setChannel)
	if args.setAllChannels is not None:
		channelModes = [(channel, args.setAllChannels) for channel in range(1, 9)] + channelModes
	getChannels = []
	if args.getAllChannels:
		getChannels.extend(range(1, 9))
	elif args.getChannel is not None:
		getChannels.append(args.getChannel)
	getValues = []
	if args.getAllValues:
		getValues.extend(range(1, 9))
	elif args.getValue is not None:
		getValues.append(args.getValue)
	if args.valueOnly and args.rawValueOnly:
		parser.error("use either --value-only or --raw-value-only, not both")
	if (args.valueOnly or args.rawValueOnly) and not getValues:
		parser.error("--value-only and --raw-value-only require --get-value or --get-all-values")
	if args.setUart is not None and (args.setUartBaudrate is not None or args.setUartParity is not None):
		parser.error("use either --set-uart or --set-uart-baudrate/--set-uart-parity, not both")
	setUartBaudrate = args.setUartBaudrate
	setUartParity = args.setUartParity
	if args.setUart is not None:
		setUartBaudrate = parseUartBaudrate(args.setUart[0])
		setUartParity = parseUartParity(args.setUart[1])
	changeUart = setUartBaudrate is not None or setUartParity is not None

	node = args.node

	if args.usbDevice is None or node is None:
		parser.error("the following arguments are required: usb_device, node")

	try:
		import serial
	except ImportError:
		print("pyserial is missing. Install it with: python3 -m pip install -r requirements.txt", file=sys.stderr)
		return 2

	writeNode = 0 if args.broadcastWrite else node

	try:
		with serial.Serial(
			args.usbDevice,
			baudrate=args.baudrate,
			bytesize=serial.EIGHTBITS,
			parity=SERIAL_PARITY_BY_NAME[args.parity],
			stopbits=serial.STOPBITS_ONE,
			timeout=args.timeout,
			write_timeout=args.timeout,
		) as port:
			if args.getUart:
				before = readDeviceAddress(port, node)
				if before != node:
					raise ModbusError(f"device answered on node {node}, but register 0x4000 contains {before}")
				printUartParameter(port, node)
				if newNode is None and not channelModes and not changeUart:
					return 0

			if getChannels:
				before = readDeviceAddress(port, node)
				if before != node:
					raise ModbusError(f"device answered on node {node}, but register 0x4000 contains {before}")
				printChannelModes(port, node, getChannels)
				if newNode is None and not channelModes and not changeUart and not getValues:
					return 0

			if getValues:
				before = readDeviceAddress(port, node)
				if before != node:
					raise ModbusError(f"device answered on node {node}, but register 0x4000 contains {before}")
				printInputValues(port, node, getValues, args.valueOnly, args.rawValueOnly)
				if newNode is None and not channelModes and not changeUart:
					return 0

			if newNode is None and not channelModes and not changeUart:
				probeAiDevice(port, node)
				print(f"test ok: device answered on node {node} on {args.usbDevice} at {args.baudrate} baud")
				return 0

			before = readDeviceAddress(port, node)
			if before != node:
				raise ModbusError(f"device answered on node {node}, but register 0x4000 contains {before}")

			if channelModes:
				if args.setAllChannels is not None:
					writeAllChannelModes(port, node, args.setAllChannels)
				if args.setChannel:
					writeChannelModes(port, node, args.setChannel)
				if not args.skipVerify:
					verifyChannelModes(port, node, channelModes)

			if changeUart:
				_, currentParityCode, currentBaudrateCode = readUartParameter(port, node)
				parityCode = currentParityCode
				baudrateCode = currentBaudrateCode
				if setUartParity is not None:
					parityCode = UART_PARITY_BY_NAME[setUartParity]
				if setUartBaudrate is not None:
					baudrateCode = UART_BAUDRATE_CODE_BY_VALUE[setUartBaudrate]
				value = writeUartParameter(port, node, parityCode, baudrateCode)
				print(f"changed uart: register 0x{REGISTER_UART_PARAMETER:04X}, value 0x{value:04X}")
				if not args.skipVerify:
					time.sleep(0.2)
					value, readParityCode, readBaudrateCode = readUartParameter(port, node)
					if readParityCode != parityCode or readBaudrateCode != baudrateCode:
						raise ModbusError("UART verification failed: read back different register value")
					print(f"verification ok: {formatUartParameter(value, readParityCode, readBaudrateCode)}")

			if newNode is None:
				return 0

			writeDeviceAddress(port, writeNode, newNode)
			print(f"changed Modbus node {node} -> {newNode} on {args.usbDevice} at {args.baudrate} baud")
			time.sleep(0.2)

			if not args.skipVerify:
				after = readDeviceAddress(port, newNode)
				if after != newNode:
					raise ModbusError(f"verification failed: register 0x4000 contains {after}")
				print(f"verification ok: device answered on new node {newNode}")

		return 0
	except (OSError, serial.SerialException, ModbusError) as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())

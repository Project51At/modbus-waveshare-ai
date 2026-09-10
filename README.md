# Waveshare Modbus AI 8CH Management Tool

This local tool manages a Waveshare Modbus RTU Analog Input 8CH module through a local RS485 adapter.

## Official Documentation

[Waveshare Modbus RTU Analog Input 8CH documentation](https://www.waveshare.com/wiki/Modbus_RTU_Analog_Input_8CH)

## Installation

```bash
cd _CodeAssistant/modbus-ai
python3 -m pip install -r requirements.txt
```

## Self-test

```bash
./modbus-waveshare-ai.sh --self-test
```

The self-test verifies the Modbus CRC examples from the Waveshare documentation and CLI option parsing. It does not communicate with a physical device.

## Help

```bash
./modbus-waveshare-ai.sh --help
```

`--help` displays options, mode values, UART codes, and examples.

## Usage

Test a device at an address and verify its AI-8CH registers:

```bash
./modbus-waveshare-ai.sh <usb-device> <node-number> [--baudrate 9600] [--parity none]
```

Change the address:

```bash
./modbus-waveshare-ai.sh <usb-device> <current-node-number> --change-address <new-node-number> [--baudrate 9600] [--parity none]
```

Configure channel modes:

```bash
./modbus-waveshare-ai.sh <usb-device> <node-number> --get-channel <channel>
./modbus-waveshare-ai.sh <usb-device> <node-number> --get-all-channels
./modbus-waveshare-ai.sh <usb-device> <node-number> --get-value <channel>
./modbus-waveshare-ai.sh <usb-device> <node-number> --get-all-values
./modbus-waveshare-ai.sh <usb-device> <node-number> --set-channel <channel>=<mode> [--set-channel <channel>=<mode>]
./modbus-waveshare-ai.sh <usb-device> <node-number> --set-all-channels <mode>
```

`--set-all-channels` writes the eight channel mode registers `0x1000..0x1007` together in one Modbus `0x10` request.

`--get-value` and `--get-all-values` display the hexadecimal register value and the measurement already scaled by the module in V or mA. Mode `4` displays the raw 4096-scale ADC code. `--value-only` displays only the formatted measurement; `--raw-value-only` displays only the hexadecimal register value.

Read or change the device UART configuration:

```bash
./modbus-waveshare-ai.sh <usb-device> <node-number> --get-uart
./modbus-waveshare-ai.sh <usb-device> <node-number> --set-uart <baudrate> <none|even|odd>
./modbus-waveshare-ai.sh <usb-device> <node-number> --set-uart-baudrate <baudrate>
./modbus-waveshare-ai.sh <usb-device> <node-number> --set-uart-parity <none|even|odd>
```

Examples:

```bash
./modbus-waveshare-ai.sh COM5 1
./modbus-waveshare-ai.sh /dev/ttyUSB0 1 --change-address 12
./modbus-waveshare-ai.sh /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AB0M0DZE-if00-port0 1 --change-address 12 --baudrate 9600
./modbus-waveshare-ai.sh COM5 1 --change-address 12 --baudrate 9600
./modbus-waveshare-ai.sh COM5 1 --get-channel 1
./modbus-waveshare-ai.sh COM5 1 --get-all-channels
./modbus-waveshare-ai.sh COM5 1 --get-value 1
./modbus-waveshare-ai.sh COM5 1 --get-value 1 --value-only
./modbus-waveshare-ai.sh COM5 1 --get-value 1 --raw-value-only
./modbus-waveshare-ai.sh COM5 1 --get-all-values
./modbus-waveshare-ai.sh COM5 1 --set-channel 1=3
./modbus-waveshare-ai.sh COM5 1 --set-channel 1=3 --set-channel 2=3
./modbus-waveshare-ai.sh COM5 1 --set-all-channels 0
./modbus-waveshare-ai.sh COM5 1 --get-uart
./modbus-waveshare-ai.sh COM5 1 --set-uart 19200 none
./modbus-waveshare-ai.sh COM5 1 --set-uart-baudrate 19200
./modbus-waveshare-ai.sh COM5 1 --set-uart-parity none
python3 modbus-waveshare-ai.py /dev/ttyUSB0 1 --change-address 12
```

On Windows, use a port such as `COM4` instead of `/dev/ttyUSB0`.

The script first reads register `0x4000` at the current address, writes the new address to register `0x4000` with Modbus function `0x06`, and then reads the new address back for verification.

Without `--change-address`, the script does not change the device address. It verifies that a Waveshare AI-8CH-compatible register map responds: device address `0x4000`, software version `0x8000`, channel modes `0x1000..0x1007`, and eight analog values using function `0x04`. The protocol does not expose a unique product ID register.

Channel mode values:

```text
0  voltage mode 0-5V, B model 0-10V
1  voltage mode 1-5V, B model 2-10V
2  current mode 0-20mA
3  current mode 4-20mA
4  raw 4096-scale code
```

The module jumpers must match the selected mode: open jumper for voltage and closed jumper for current.

UART baudrate values for device register `0x2000`:

```text
4800, 9600, 19200, 38400, 57600, 115200, 128000, 256000
```

UART parity values for device register `0x2000`:

```text
none, even, odd
```

`--baudrate` is the current PC-side connection baudrate. `--set-uart-baudrate` instead changes the baudrate used to reach the device afterward.

`--parity` is the current PC-side serial parity setting. The default is `none`. `--set-uart-parity` instead changes the parity used to reach the device afterward.

`--timeout` sets the serial read and write timeout in seconds. The default is `1.0`.

`--set-uart <baudrate> <parity>` sets the device baudrate and parity together in register `0x2000`.

`--skip-verify` disables the read-back verification after writing channel modes, UART settings, or the device address.

If the module accepts address changes only with the broadcast address, use:

```bash
./modbus-waveshare-ai.sh /dev/ttyUSB0 1 --change-address 12 --baudrate 9600 --broadcast-write
```

Important: With `--broadcast-write`, only this one Waveshare module should be connected to the RS485 bus. Otherwise, multiple devices could be changed at once.


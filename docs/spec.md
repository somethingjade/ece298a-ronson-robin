## Specification

| Parameter | Value |
|:---:|:---:|
| Tiles | 1x1 |
| Interface | SPI |
| SPI mode | 1 (CPOL = 0, CPHA = 1) |
| Bit order | MSB first |
| Byte order | Big-endian |
| Clock frequency | 50 MHz |
| Max SCK frequency | 10 MHz |

## Message format
Each command consists of a 16-bit MOSI frame:
| Bits 15:14 | Bits 13:6 | Bits 5:0 |
|:---:|:---:|:---:|
| Command<br>`00`: `WRITE_DATA`<br>`01`: `WRITE_CONTROL`<br>`10`: `READ_DATA`<br>`11`: `READ_STATUS` | Payload for write<br>Don't care for reads | Padding to maintain byte alignment |

The MISO frame overlaps with the MOSI frame. The least significant byte is the response:
| Bits 15:8 | Bits 7:0 |
|:---:|:---:|
| Padding | Response |


## Registers

### Status register
Reset value: `0x00`
| Bit 7 | Bit 6 | Bits 5:0 |
|:---:|:---:|:---:|
| r | r | r |
| `error` | `busy` | `counter` |

`error`: error status
- `0`: no error
- `1`: error

`busy`: busy status
- `0`: not busy (current FSM state is `IDLE`)
- `1`: busy (current FSM state is not `IDLE`)

`counter`: value of 6-bit round counter

### Control register
Reset value: `0x00`
| Bits 7:4 | Bits 3:1 | Bit 0 |
|:---:|:---:|:---:|
| w | w | w |
| `read_byte` | `breakpoint` | `reset` |

`read_byte`: selects which byte is read by `READ_DATA` command
- Valid range: `[0, 10]` (`0x0` to `0xA`)
- If `read_byte` is outside of the valid range, byte 0 will be read by `READ_DATA`, but reading will not trigger an application of the `PI_b` permutation \[1\] (see [design doc](./spongent_core_design.md) for more details)

`breakpoint`: selects an FSM state to pause execution at
- Valid values:
    - `000`: `IDLE`
    - `001`: `ABSORB`
    - `010`: `LFSR`
    - `011`: `SBOX`
    - `100`: `PLAYER`
- Refer to [design doc](./spongent_core_design.md) for details

`reset`: software reset
- `0`: do not reset
- `1`: reset SPONGENT-88 core

## References
\[1\] A. Bogdanov, M. Knezevic, G. Leander, D. Toz, K. Varici, I. Verbauwhede, "SPONGENT: A Lightweight Hash Function," in CHES 2011, 2011, pp. 312-325, doi: https://doi.org/10.1007/978-3-642-23951-9_21.

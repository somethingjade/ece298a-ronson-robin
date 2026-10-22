# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, FallingEdge


async def send_command(dut, command):
    RISE = 0b00000010
    FALL = 0b00000001
    LOW_CYCLES = 4
    HIGH_CYCLES = 4

    ret = 0
    await FallingEdge(dut.clk)
    for i in range(16):
        bit = (((command << i) & 0x8000) >> 12)
        await ClockCycles(dut.clk, LOW_CYCLES)
        dut.uio_in.value = (bit | RISE) & 0xFF
        await ClockCycles(dut.clk, 1)
        dut.uio_in.value = (bit | 0b00000000) & 0xFF
        await ClockCycles(dut.clk, HIGH_CYCLES)
        dut.uio_in.value = (bit | FALL) & 0xFF
        await ClockCycles(dut.clk, 1)
        dut.uio_in.value = (bit | 0b00000000) & 0xFF
        ret = (ret << 1) | (int(dut.uio_out.value) >> 2 & 0x01)

    return (ret >> 6) & 0xFF

@cocotb.test()
async def test_project(dut):
    dut._log.info("Start")

    # Set the clock period to 10 us (100 KHz)
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1

    dut._log.info("Test project behavior")

    # Set the input values you want to test
    # dut.ui_in.value = 20
    # dut.uio_in.value = 30
    
    READY = 0b00000000
    BUSY = 0b00000001

    ABSORB_OK = 0b00000000
    ABSORB_ERR = 0b11111111

    # Wait for one clock cycle to see the output values
    await ClockCycles(dut.clk, 1)

    dut._log.info("")
    dut._log.info(">>> Test: Status read (ready)")
    received = await send_command(dut, 0b1100000111000000)
    assert received == READY
    dut._log.info(">>> PASSED: Status read (ready)")

    dut._log.info("")
    dut._log.info(">>> Test: Absorb")
    received = await send_command(dut, 0b0011001111000000)
    assert received == ABSORB_OK
    # assert dut.user_project.spongent.state.value == 0x67
    dut._log.info(">>> PASSED: Absorb")

    dut._log.info("")
    dut._log.info(">>> Test: Status read (busy)")
    received = await send_command(dut, 0b1100000111000000)
    assert received == BUSY
    dut._log.info(">>> PASSED: Status read (busy)")


    dut._log.info("")
    dut._log.info(">>> Test: Write while busy")
    received = await send_command(dut, 0b0001100110000000)
    assert received == ABSORB_ERR
    dut._log.info(">>> PASSED: Write while busy")


    # The following assersion is just an example of how to check the output values.
    # Change it to match the actual expected output of your module:
    # assert dut.uo_out.value == 50

    # Keep testing the module by changing the input values, waiting for
    # one or more clock cycles, and asserting the expected output values.

        
